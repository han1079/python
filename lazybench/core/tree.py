"""
Walks dagnodes in a directory fashion.

The tree variant 
"""
import weakref
from typing import Optional

from lazybench.core.node import DAGNode, RootNode
from lazybench.app.ux.prompter import Prompter


class DeadReference(Exception):
    """Raised when WeakTree's target is garbage collected."""


class TreeNodeHandle:
    """Transparent, weak stand-in for one gathered DAGNode.

    If you have x = CallNode() and y = WeakNodeHandle(x), this allows 
    y() to be called just like x(), as opposed to y()().
    """
    __slots__ = ('_ref', '_path')
    _current_node: Optional['TreeNodeHandle'] = None

    def __init__(self, node: DAGNode):
        try:
            self._ref = weakref.ref(node)
            self._path = node.dagnode_path
        except TypeError:
            self._ref = None
            self._path = None

    @property
    def _children(self) -> dict[str, DAGNode]:
        node = self._ref()
        return {node.dagnode_name: TreeNodeHandle(node) for node in node.dagnode_children} 

    def _resolve(self) -> DAGNode:
        node = self._ref()
        if node is None:
            raise DeadReference(f'{self._path} has been garbage collected')
        if not node.is_alive:
            raise DeadReference(f'{self._path} is not alive')
        return node

    def __call__(self, *args, **kwargs):
        return self._resolve()(*args, **kwargs)

    def __getattr__(self, name: str):
        excs = []
        try:
            return getattr(self._resolve(), name)
        except AttributeError as e:
            excs.append(e)
            pass

        try:
            return self._children[name]
        except KeyError as e:
            excs.append(e)
            pass

        raise ExceptionGroup(f'At path: {self._path}. Attempted to get {name}. Got following exceptions:', excs)

    def __dir__(self):
        return sorted(set(self._children.keys()) | set(super().__dir__()))

    def __repr__(self):
        node = self._ref()
        alive = node is not None and node.is_alive
        active = node is not None and node.is_active
        return f'<TreeNodeHandle {self._path} alive={alive}, active={active}>'


class ResourceView:
    """Dependency-side counterpart to TreeNodeHandle's _children: name-keyed
    access to a node's _dependencies (things it uses but doesn't own),
    resolving to a TreeNodeHandle rather than a held reference. Distinguishes
    dependents (children, accessed as attributes via Registry/FacadeNode's
    own __getattr__) from dependencies (resources a node calls on, accessed
    via this namespace instead)."""
    __slots__ = ('_instance',)

    def __init__(self, owner: DAGNode):
        self._instance = owner

    def get_owner_instance(self):
        return TreeNodeHandle(self._instance)

    def __getattr__(self, name: str) -> TreeNodeHandle:
        """Resources recurse backward up the tree and return a handle.

        Think of a resource_view as a "order reversed" tree navigation.

        On installation, each node gets a single dependency by default.
        This is the PARENT node.

        The parent then "passes its dependencies" to the child node, which 
        is how most of the dependency flow works.

        However, if a child needs ACCESS to a specific dependency - it is 
        very bad practice to "hand the object" to the child. This messes 
        with DAG teardown, since it's impossible to know which child holds 
        which node.

        Therefore, if a node NEEDS to access other objects ACROSS the DAG, we 
        create a level of indirection.

        Invoke NodeClass(name="my_node", dependencies={node_1, node_2, ...}). These
        are added to the dependency graph, as usual, but unlike the PARENT node, 
        which can be accessed via walking the tree via node.unique_path[:-1], these
        nodes are MOSTLY hidden. They can THEORETICALLY be accessed via self._dependencies[path_to_node], 
        but that access pattern is deliberately difficult so it's hard to hold a strong reference 
        that doesn't get auto-cleaned by kill_node.

        Instead, we expose this class ResourceView as a property node.resources. Specifically, this 
        class searches out ALL of the nodes that AREN'T in the direct tree path, and does so recursively.

        This reverse search SPECIFICALLY skips the "parent node" since 
        node.resources IS the parent node.
        """
        for dep in self._instance._dependencies.values():
            if dep.dagnode_name != name: continue
            if dep.dagnode_path == self._instance.dagnode_path[:-1]:
                raise AttributeError(f'Cannot access own parent as a resource. Use get_owner_instance explicitly.')
            else:
                return TreeNodeHandle(dep)
        raise AttributeError(
            f'{name!r} not a dependency of {self._instance.dagnode_name!r}. '
            f'Available: {[d.dagnode_name for d in self._instance._dependencies.values()]}'
        )

    def __dir__(self):
        return sorted(d.dagnode_name for d in self._instance._dependencies.values())



#class VirtualRegistry:
#    __slots__ = ('namespace', 'nodepaths', 'dependents')
#    def __init__(self, name, nodes: Optional[frozenset['DAGNode'], 'DAGNode']]):
#        self.nodepaths = set()
#        self._update_node_paths(nodes)
#        self.namespace = name
#        self.dependents = dict()
#
#    def _update_node_paths(self, nodes:Union[tuple[str], frozenset['DAGNode'], 'DAGNode']):
#        if nodes is None:
#            return 
#        if isinstance(nodes, (tuple, set, frozenset)):
#            assert(all(isinstance(n, DAGNode) for n in nodes))
#            self.nodepaths.add(node.dagnode_path)
#        else:
#            assert(isinstance(nodes, DAGNode))
#            self.nodepaths.add(nodes.dagnode_path)
#
#    @property
#    def virtual_nodes(self):
#        return [TreeNodeHandle(RootNode.find_node(path)) for path in self.nodepaths]
#
#    @property
#    def is_alive(self):
#        return all([v().is_alive for v in self.virtual_nodes])
#
#    @property
#    def is_active(self):
#        return all([v().is_active for v in self.virtual_nodes])
#
#    def _get_virtual_node(self, name):
#        for path in self.nodepaths:
#            if name == path[-1]:
#                return TreeNodeHandle(RootNode.find_node(path))
#
#        return None
#
#    def __getattr__(self, name):
#        node = self._get_virtual_node(name)
#        if node is None:
#            raise AttributeError(f'No such attribute {name}')
#
#    def __dir__(self):
#        return sorted(set([p[-1] for p in self.nodepaths]) | set(super().__dir__()))
#
#    def install(self, node: DAGNode, 
#                filter_function: Callable = lambda a,b: True,
#                default_activate=True):
#        result = filter_function(self, node)
#        if not result:
#            raise ValidityViolation[self](f'Failed install due to filter rule')
#
#        if not self.is_alive:
#            raise ValidityViolation[self](f'{self.namespace} is not alive. Cannot install other nodes.')
#        
#        for vnode in self.virtual_nodes:
#            vnode = vnode()
#            if vnode is None:
#                raise DeadReference(f"Dead ref {vnode.dagnode_name} during install of {node.dagnode_name}")
#
#            try:
#                node._dependencies[vnode.unique_path] = vnode
#            except ValidityViolation:
#                Prompter.log(f"[{type(node).__name__}]: Cannot act as parent node. Creates Cycle")
#                node._proposed_dependencies = tuple([x for x in node._proposed_dependencies if x != vnode])
#                node._unique_path = None
#                return False
#            except RuleViolation as e:
#                node._unique_path = None
#                raise RuleViolation(f"Raised {e}: {node.dagnode_name}. Attempted {vnode._unique_path}. Existing lib is {node._dependencies}")

        

        


class TreeNav:
    _singleton: Optional[TreeNodeHandle] = None
    def __init__(self, node: Optional[DAGNode] = None):
        if node is None:
            type(self)._singleton = TreeNodeHandle(RootNode.get())
        else:
            type(self)._singleton = TreeNodeHandle(node)

    @classmethod
    def set(cls, node):
        cls._singleton = TreeNodeHandle(node)

    @classmethod
    def _get_treenode_from_path(cls, path):
        found_node = RootNode.find_node(path)
        return TreeNodeHandle(found_node)

    @classmethod
    def cwd(cls) -> TreeNodeHandle:
        return cls._singleton

    @classmethod
    def ls(cls):
        return set(list(cls._singleton._children.keys()))

    @classmethod
    def up(cls):
        parent_path = cls._singleton._path[:-1]
        cls._singleton = cls._get_treenode_from_path(parent_path)
        return cls._singleton

    @classmethod
    def down(cls, name: str):
        current = cls._singleton
        newnode = current._children.get(name, None)
        if newnode is None:
            raise AttributeError(f'No children node of name {name} under {cls._singleton.dagnode_name}')
        else:
            cls._singleton = newnode 
            return cls._singleton



