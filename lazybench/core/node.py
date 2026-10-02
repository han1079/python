# Core scaffolding for a Node Object 
# TODO: Create recursive typechecker for registry

import inspect
from typing import Union, Optional, Callable, TypeVar
from lazybench.core.core import MetaNode
from lazybench.core.violations import *
from lazybench.app.ux.prompter import Prompter

# Forward decl
class RootNode: pass

K = TypeVar('K')
V = TypeVar('V')

class DedupedDict(dict[K, V], metaclass=MetaNode):
    _reserved_attr_names = set()
    def __init__(self, *args, **kwargs):
        self.update(*args, **kwargs)

    def _bootstrap_node(self):
        """Metaclass reserved method. This runs after __init__
        on all classes inheriting Identity. That way, any dict-based namespacing 
        can raise on naming collisions.
        """
        for cls in type(self).__mro__:
            self._reserved_attr_names.update(cls.__dict__.keys())

        self._reserved_attr_names.update(self.__dict__.keys())

    def _check_unique(self, key: K, value: V) -> None:
        if key in self:
            if self[key] == value:
                return                               
            raise UniquenessViolation[self](f'key {key!r} already bound elsewhere')
        if value in self.values():
            raise UniquenessViolation[self](f'value {value!r} already under another key')

    def __setitem__(self, key: K, value: V) -> None:
        self._check_unique(key, value)
        super().__setitem__(key, value)

    def update(self, *args, **kwargs) -> None:
        """Dict inits first like normal. Then we overwrite - but with
        the updated __setitem__. Should freak out on duplicates
        """
        for k, v in dict(*args, **kwargs).items():       
            self[k] = v

    def setdefault(self, key: K, default: V = None) -> V:
        if key not in self:
            self[key] = default
        return self[key]

class DAGDict(DedupedDict[Union[str, tuple], 'DAGNode']):
    def __init__(self, *args, **kwargs):
        super().__init__(self, *args, **kwargs)
    def _check_type(self, key: Union[str, tuple], value: 'DAGNode') -> None:
        """DAG Dict can be keyed either be name (str) or unique path (tuple[str])

            Frequently, just name is sufficient, but for DAG navigation, unique path
            is desired for unambiguous ID.
        """
        if not isinstance(value, DAGNode):
            raise TypeCheckViolation[self](f'{value!r} is not a DAGNode')

        if not (isinstance(key, tuple) or isinstance(key, str)):
            raise TypeCheckViolation[self](f'Key {key} is not valid.')

    def _reaches(self, n, value: 'DAGNode', seen):
        if n is value:
            return True
        if id(n) in seen:
            return False
        seen.add(id(n))
        return any(self._reaches(d, value, seen) for d in n._dependencies.values())

    def _check_acyclic(self, value: 'DAGNode') -> None:
        """Recursively checks for 'cycles back to current node'"""
        seen: set[int] = set()


        if any(self._reaches(d, value, seen) for d in value._dependencies.values()):
            raise ValidityViolation[self](f'Inserting {value} creates a cycle.')

    def __setitem__(self, key: Union[str, tuple], value: 'DAGNode') -> None:
        self._check_type(key, value)
        self._check_acyclic(value)
        super().__setitem__(key, value)             # → DedupedDict._check_unique → dict set

    def __getattr__(self, name):
        if name in self._reserved_attr_names:
            return super().__getattribute__(name)

        # Ignore any underscore keys
        if name.startswith('_'):
            return None

        if result := self.get(name):
            return result
        else:
            raise AttributeError(f"No such attribute {name}")

    def overwrite(self, key: Union[str, tuple], value: 'DAGNode') -> None:
        """Sanctioned del-then-set (DedupedDict blocks direct re-bind). All
        checks still fire on the set half."""
        if key in self:
            del self[key]
        self[key] =value

class DAGNode(metaclass=MetaNode):
    #_reserved_attr_names = set()
    __hash__ = object.__hash__
    __eq__ = object.__eq__

    def __init__(self, name: Optional[str] = None,
                 resources: Optional[tuple['DAGNode', ...]] = None):
        self._name = None
        self._unique_path = None
        self._proposed_dependencies: Optional[frozenset[DAGNode]] = None
        self._dependencies = DAGDict()
        self._dependents = DAGDict()
        self._always_leaf = False

        excs = []
        try:
            self._set_name(name)
        except RuleViolation as e:
            excs.append(e)

        try:
            self._set_dependencies(resources)
        except RuleViolation as e:
            excs.append(e)

        if excs:
            Prompter.log(f'Initial staging ran into the following problems:')
            for e in excs:
                Prompter.log(e)

        # Flag for activeness outside of validity / dependency checks
        self._trying_to_be_active = False

    def _bootstrap_node(self):
        """Metaclass reserved method. This runs after __init__
        on all classes inheriting Identity. That way, any dict-based namespacing
        can raise on naming collisions.
        """
        for cls in type(self).__mro__:
            self._reserved_attr_names.update(cls.__dict__.keys())

        self._reserved_attr_names.update(self.__dict__.keys())

    def _on_successful_install(self):
        raise NotImplementedError(f'No Post Install Run')

    # ----- Public, read-only identity accessors -----
    @property
    def dagnode_name(self) -> Optional[str]:
        return self._name

    @property
    def dagnode_path(self) -> Optional[tuple[str, ...]]:
        return self._unique_path

    @property
    def dagnode_children(self) -> Optional[str]:
        return [node for node in self._dependents.values() if self.dagnode_path == node.dagnode_path[:-1]]

    @property
    def resources(self) -> 'ResourceView':
        """Name-keyed access to this node's dependencies (things it uses but
        doesn't own), each resolving to a TreeNodeHandle rather than a held
        reference -- e.g. self.resources.ipc_node. Distinct from dependents
        (children this node owns, accessed as plain attributes via
        Registry/FacadeNode's own __getattr__). Uncached on purpose: always
        reflects the current _dependencies, so it can't go stale."""
        from lazybench.core.tree import ResourceView
        return ResourceView(self)

    # ----- Public, alive-gated setters (fluent build) -----

    def set_dagnode_name(self, name: str) -> 'DAGNode':
        if self.is_alive:
            raise ValidityViolation[self](f'{self.dagnode_name} already installed; cannot rename.')
        self._set_name(name)
        return self

    def set_resources(self, *nodes: 'DAGNode') -> 'DAGNode':
        if self.is_alive:
            raise ValidityViolation[self](f'{self.dagnode_name} already installed; cannot stage new resources.')
        self._set_dependencies(frozenset(nodes))
        return self

    def get_child_path(self, child: Union['DAGNode', str]):
        if isinstance(child, DAGNode):
            return self._unique_path + (child.dagnode_name,)
        elif isinstance(child, str):
            return self._unique_path + (child,)
        else:
            raise TypeError(f'{child} is {type(child)}. Must be either DAGNode or str')


    def graft_install(self, node: Optional['DAGNode'] = None):
        if node is None:
            node = RootNode.get()
        node.install(self)

    def _set_name(self, name: Optional[str] = None) -> bool:
        if name is None:
            return False

        self._name = name
        return True

    def _set_dependencies(self, dependencies: Optional[Union[str, frozenset['DAGNode', ...], 'DAGNode']] = None) -> bool:
        if dependencies is None or dependencies in (frozenset(), set(), ()):
            return False

        if isinstance(self._proposed_dependencies, frozenset):
            tp = self._proposed_dependencies
        else:
            assert self._proposed_dependencies is None
            tp = frozenset()

        if dependencies in ('root', ('root',), RootNode.get(), (RootNode.get(),)):
            self._proposed_dependencies = tp.union([RootNode.get()])
        elif isinstance(dependencies, DAGNode):
            self._proposed_dependencies = tp.union([dependencies])
        elif isinstance(dependencies, frozenset) and all(isinstance(d, DAGNode) for d in dependencies):
            self._proposed_dependencies = tp.union(dependencies)
        else:
            raise RuleViolation(f'Invalid choices of dependencies to stage {dependencies}')
        return True

    def _set_parent_node_as(self, node: 'DAGNode'):
        if self._name is None:
            return False

        if self._unique_path is not None:
            raise UniquenessViolation[self](f'{self._unique_path} is already set. Setting new parent illegal.')

        self._set_dependencies(node)
        self._unique_path = node._unique_path + (self._name, )

        return True

    def install(self, node: 'DAGNode', default_activate=True, **kwargs):
        if not self.is_alive:
            raise ValidityViolation[self](f'{self._name} is not alive. Cannot install other nodes.')
        if not node._set_parent_node_as(self):
            return False

        try:
            node._dependencies[self._unique_path] = self
        except ValidityViolation:
            Prompter.log(f"[{type(node).__name__}]: Cannot act as parent node. Creates Cycle")
            node._proposed_dependencies = tuple([x for x in node._proposed_dependencies if x != self])
            node._unique_path = None
            return False
        except RuleViolation as e:
            node._unique_path = None
            raise RuleViolation(f"Raised {e}: {node._name}. Attempted {self._unique_path}. Existing lib is {node._dependencies}")

        try:
            self._dependents[node._unique_path] = node
        except ValidityViolation:
            Prompter.log(f'Failed to install as dependent. Undoing installation.')
            return False
        except RuleViolation as e:
            node._unique_path = None
            raise RuleViolation(f"Raised {e}: {self._name}. Attempted {node._unique_path}. Existing lib is {self._dependents}")

        hit_nodes = []
        try:
            for n in node._proposed_dependencies:
                if not isinstance(n, DAGNode):
                    raise TypeCheckViolation[self](f'{n} is not a DAGNode. Cannot be a dependency')

                if n._always_leaf: 
                    raise ValidityViolation[node](f'{n._name} is a permanent leaf. Cannot be a dependency')

                # Cyclic dependencies should raise here.
                node._dependencies[n._unique_path] = n
                n._dependents[node._unique_path] = node
                hit_nodes.append(n)
        except ValidityViolation:
            for n in hit_nodes:
                try:
                    del n._dependents[node._unique_path]
                except KeyError:
                    Prompter.log(f"Never set node as dependent for {n}")

                try:
                    del node._dependencies[n._unique_path]
                except KeyError:
                    Prompter.log(f"Never set {node} dependency {n}")

            return False

        if node.is_alive:
            try:
                node._on_successful_install()
            except NotImplementedError:
                Prompter.log(f'{node.dagnode_name} is base class. Has no post install callback')
            except Exception as e:
                raise Exception(e)

        if default_activate:
            node.set_trying_to_be_active()

        return True

    def uninstall(self, node: 'DAGNode'):
        if node not in self._dependents.values():
            return False

        node.kill_node()
        return True
    # ----- Aliveness Indicators / Setters -----

    @property
    def dependency_alive_states(self):
        return [d.is_alive for d in self._dependencies.values()]

    @property
    def dependency_active_states(self):
        return [d.is_active for d in self._dependencies.values()]

    @property
    def is_alive(self):
        """Pure structural fact: am I still linked into a non-killed graph.
        Only kill_node's edge removal can ever flip this -- deactivating a
        node has no effect on it."""
        return len(self.dependency_alive_states) > 0 and all(state is True for state in self.dependency_alive_states)

    @property
    def is_active(self):
        """Operational fact: am I, and everything I depend on, currently
        running. Freely toggled by activate_node/deactivate_node with zero
        effect on the graph structure -- unlike is_alive."""
        return (self._trying_to_be_active
                and len(self.dependency_active_states) > 0
                and all(state is True for state in self.dependency_active_states))

    # ----- Node Lifecycle -----

    def set_trying_to_be_active(self):
        """Subclasses should override this to start resources (threads, etc)"""
        if not self.is_alive:
            raise ValidityViolation(f'{self.dagnode_name} is not alive.')
        else:
            self._trying_to_be_active = True
            return True
        return False

    def propagate_activation(self):
        if self.is_active:
            successful_activations = []
            for dep in self._dependents.values():
                dep.set_trying_to_be_active()
                activated = dep.propagate_activation()
                successful_activations.append(activated)
            return all(successful_activations)
        else:
            return False

    def deactivate_node(self):
        """Subclasses should override this to stop resources (threads, etc)"""
        self._trying_to_be_active = False

    def kill_node(self):
        self.deactivate_node()

        exceptions = []

        for dep in list(self._dependents.values()):
            try:
                dep.kill_node()
            except Exception as e:
                exceptions.append(f'Popping dependents got exc {e}. Dependent is: {dep._name}. Used pop')


        all_deps = list(self._dependencies.values())
        for dep in all_deps:
            e = dep._dependents.pop(self._unique_path, None)
            if e is None:
                exceptions.append(f'Popping {self._name} from {dep._name} got None. It was already gone.')

        self._dependencies.clear()
        self._unique_path = None
        self._proposed_dependencies = None

        if exceptions:
            raise Exception(f'{self._name} kill_node ran into exceptions: {exceptions}')

    def __dir__(self):
        return sorted(set(super().__dir__()) | set({child.dagnode_name for child in self.dagnode_children}))

class Registry(DAGNode):
    _reserved_attr_names: set = set()
    def __init__(self, name: Optional[str] = None,
                 resources: Optional[Union[str, frozenset['DAGNode'], 'DAGNode']] = None):
        super().__init__(name=name, resources=resources)

    def values(self):
        return self._dependents.values()

    def items(self):
        return self._dependents.items()

    def keys(self):
        return self._dependents.keys()

    def nodes(self):
        return [n.dagnode_name for n in self.values()]

    def install(self, node: DAGNode, 
                filter_function: Callable = lambda a,b : True,
                default_activate=True,
                **kwargs):
        result = filter_function(self, node)
        if not result:
            raise ValidityViolation[self](f'Failed install due to filter rule')
        return super().install(node, default_activate)


    def __getitem__(self, key: Union[str, tuple[str]]):
        if key in self._reserved_attr_names:
            return None
        # Ideally, we recursively typecheck here
        if isinstance(key, tuple):
            try:
                return self._dependents[key]
            except KeyError as k:
                raise KeyError(f'No such node with path {key} in {self.dagnode_name} dependents.')

        if isinstance(key, str):
            for k,v in self._dependents.items():
                if v.dagnode_name == key:
                    return self._dependents[k]

            raise KeyError(f'No such node named {key} in {self.dagnode_name} dependents.')

        raise KeyError(f'{key} is not a valid key')

    def get(self, key: Union[str, tuple[str]], default=None):
        try:
            return self[key]
        except KeyError:
            return default

    def __getattr__(self, name: str) -> object:
        if name in self._reserved_attr_names:
            return super().__getattribute__(name)

        if not isinstance(name, str):
            raise TypeCheckViolation[self](f'{name} is of type {type(name).__name__}.'
                                        + 'Must be string for attr access.')

        return self[name]


class RootNode(Registry):
    _singleton: Optional[DAGNode] = None
    def __init__(self):
        super().__init__(name='root', resources=())
        self._trying_to_be_active = True
        self._unique_path = ('root',)
        type(self)._singleton = self

    # Override and hardcode as permanently true
    @property
    def dependency_alive_states(self):
        return [True]

    @property
    def dependency_active_states(self):
        return [True]

    @classmethod
    def get(cls) -> DAGNode:
        return cls._singleton

    def _on_successful_install(self):
        return True

    @classmethod
    def find_node(cls, unique_path):
        if len(unique_path) == 0:
            return cls._singleton

        if unique_path == ('root',):
            return cls._singleton

        next_node = None
        current_node = cls._singleton
        pathlen = len(unique_path)
        for i in range(1, pathlen+1):
            search_path = unique_path[0:i]
            if search_path == ('root',):
                continue
            next_node = current_node._dependents.get(search_path, None)
            if next_node is None:
                return None
            else:
                current_node = next_node
                next_node = None

        return current_node

