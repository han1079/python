"""facade — wrap an arbitrary object as a DAGNode-shaped, 1-depth fanout tree.
"""
from typing import Optional, Union, Callable
import dataclasses
from dataclasses import field
import functools
import weakref

from lazybench.core.callable import CallableNode
from lazybench.core.violations import RuleViolation
from lazybench.core.node import DAGDict, DAGNode
from lazybench.core.violations import ValidityViolation, UniquenessViolation
from lazybench.app.ux.prompter import Prompter

@dataclasses.dataclass
class ExplodedObject:
    instance_vars: frozenset[str] = field(default_factory=frozenset) # cached_property goes here
    class_vars: frozenset[str] = field(default_factory=frozenset)
    properties: frozenset[str] = field(default_factory=frozenset)
    methods: frozenset[str] = field(default=frozenset)

    @property
    def public_instance_vars(self):
        return frozenset([v for v in self.instance_vars if not v.startswith('_')])
    @property
    def public_class_vars(self):
        return frozenset([v for v in self.class_vars if not v.startswith('_')])
    @property
    def public_properties(self):
        return frozenset([v for v in self.properties if not v.startswith('_')])
    @property
    def public_methods(self):
        return frozenset([v for v in self.methods if not v.startswith('_')])
    @property 
    def all_publics(self):
        return self.public_instance_vars.union(
                self.public_methods.union(
                    self.public_properties.union(
                        self.public_class_vars
                        )
                    )
                )
    @property 
    def all_attrs(self):
        return self.instance_vars.union(
                self.methods.union(
                    self.properties.union(
                        self.class_vars
                        )
                    )
                )

def _class_check(obj: object, name: str, check: type) -> bool:
    for cls in type(obj).__mro__:
        if isinstance(cls.__dict__.get(name), check):
            return True
    return False

def walk_object(obj: object) -> ExplodedObject:
    _instvar = []
    _classvar = []
    _properties = []
    _methods = []
    for name in dir(obj):
        if name.startswith('__'): continue
        if _class_check(obj, name, property): _properties.append(name); continue
        if _class_check(obj, name, functools.cached_property): _instvar.append(name); continue
        if name in obj.__dict__.keys(): _instvar.append(name); continue
        if _class_check(obj, name, Callable): _methods.append(name); continue
        for cls in type(obj).__mro__:
            if name in cls.__dict__:
                _classvar.append(name)
                continue

    return ExplodedObject(instance_vars=frozenset(_instvar),
                          class_vars=frozenset(_classvar),
                          properties=frozenset(_properties),
                          methods=frozenset(_methods))

class _DeferredNodePathGetter:
    __slots__ = ('_ref',)
    def __init__(self, node):
        self._ref = weakref.ref(node)

    @property
    def dagnode_path(self):
        node = self._ref()
        return node.dagnode_path if node is not None else None

class FacadeNode(DAGNode):
    """A DAGNode that looks like `instance` via attribute passthrough, except
    every exposed member is a real, installed CallableNode child -- so
    killing the facade kills every exposed piece
    """

    # Fresh per-class set -- see CallableNode's identical declaration for why
    # this can't be inherited as-is from DAGNode.
    _reserved_attr_names: set = set()

    def __init__(self, instance: object, name: Optional[str] = None,
                 resources: Optional[Union[str, frozenset['DAGNode'], 'DAGNode']] = None):
        self._instance = None
        self._exploded_obj = None
        self._exposed = set()
        self._failed_embeds = None

        self._embed_object(instance)

        instance._holder_node = _DeferredNodePathGetter(self)
        super().__init__(name=name or type(instance).__name__, resources=resources)

    def expose_name(self, name: str) -> bool:
        """Expose a single name, newest-wins: safe to call in any order
        relative to hide_name/expose_all, no memory of prior calls beyond
        whatever's currently in `_exposed`."""
        if not self.is_alive:
            return False
        if name in self._reserved_attr_names:
            Prompter.log(f'{self._name}: cannot expose {name!r}, it shadows a reserved attr')
            return False

        self._exposed.add(name)
        return True

    def hide_name(self, name: str) -> bool:
        """Newest-wins counterpart to expose_name -- pure removal, no
        tracking, an expose_name call after this simply wins again."""
        return self._exposed.pop(name, None) is not None

    def hide_all(self) -> frozenset[str]:
        """Bulk counterpart to hide_name -- clears every currently exposed
        name regardless of how it got there (expose_all sweep or individual
        expose_name calls). No tracking beyond current dict state, so a
        subsequent expose_name/expose_all simply wins again, same as after
        hide_name. Returns the names that were cleared."""
        cleared = frozenset(self._exposed)
        self._exposed.clear()
        return cleared

    def expose_all(self, expose_private: bool = False):
        if not self.is_alive:
            return False
        if expose_private:
            attrs = set(self._exploded_obj.all_attrs)
        else:
            attrs = set(self._exploded_obj.all_publics)

        self._exposed = attrs - set(self._reserved_attr_names)

    def _embed_object(self, obj: object):
        self._instance = obj
        self._exploded_obj = walk_object(obj)

    def _on_successful_install(self):
        if self._failed_embeds is not None:
            raise UniquenessViolation[self](f'Somehow attempting to bypass and double-install')
        failed_to_wrap = []
        failed_to_install = []
        for m in self._exploded_obj.methods:
            try:
                n = CallableNode(getattr(self._instance,m), name=m) 
            except RuleViolation as e:
                failed_to_wrap.append(m)
                Prompter.log(f'{m} node creation refused for reason: {e}')
                continue
            except Exception as exc:
                raise Exception(exc)

            try:
                self.install(n)
            except RuleViolation as e:
                failed_to_install.append(n)
                Prompter.log(f'{n.dagnode_name} was refused for {e}')
                continue
            except Exception as exc:
                raise Exception(exc)

        self._failed_embeds = {'wrap': frozenset(failed_to_wrap), 'install': frozenset(failed_to_install)}

    @property
    def dagnode_children(self):
        pre_filter = super().dagnode_children
        post_filter = []
        for node in pre_filter:
            if self._exposed is not None and node.dagnode_name in self._exposed:
                post_filter.append(node)

        return post_filter

    def kill_node(self):
        super().kill_node()
        self._exposed.clear()
        # Check the wrapped instance directly, not `hasattr(self, 'stop')` --
        # that went through __getattr__'s _exposed/get_child_path machinery,
        # which (a) made cleanup depend on 'stop' happening to be in the
        # config's expose list, and (b) raised TypeError instead of
        # AttributeError once _unique_path was already None from the
        # super().kill_node() above, since get_child_path does
        # `self._unique_path + (name,)` unconditionally.
        if hasattr(self._instance, 'stop'):
            self._instance.stop()

    def __getattr__(self, name: str) -> object:
        if name in self._reserved_attr_names:
            return super().__getattribute__(name)

        exposed = self.__dict__.get('_exposed')
        if exposed is not None and name in exposed:
            try:
                return self._dependents[self.get_child_path(name)]
            except KeyError as e:
                pass

            try:
                return getattr(self._instance, name)
            except AttributeError as e:
                pass

        raise AttributeError(f'{name!r} not exposed by {type(self).__name__} {self._name!r}. Exposed names: {self._exposed}')

    def __dir__(self) -> list[str]:
        return sorted(set(super().__dir__()) | set(self._exposed))
