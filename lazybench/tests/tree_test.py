from lazybench.core.node import DAGNode, Registry
from lazybench.core.facade import FacadeNode
from lazybench.core.tree import TreeNodeHandle, TreeNav, DeadReference
from lazybench.tests.node_test import install_and_assert_consistent, uninstall_and_assert_consistent

import pytest

def test_node_finder(root_node):
    LAYERS = 3
    PER_LAYER = 5
    name_maker = lambda layer, idx: "".join([str(idx+1) for i in range(1,layer+2)])
    parents = [root_node]
    total = 0
    for layer in range(LAYERS):
        for idx in range(PER_LAYER):
            for p in parents:
                node = DAGNode()
                name = name_maker(layer, idx)
                node._set_name(name)
                install_and_assert_consistent(node, p)
                total += 1
        parents_lumped = [p.dagnode_children for p in parents]
        parents = [a for p in parents_lumped for a in p]

            
    found_node = root_node.find_node(('root', "1","22","555"))
    assert found_node._unique_path == ('root', "1","22","555")

def assert_tree_children_consistent(node, parent):
    if isinstance(node, str):
        k = node
    elif isinstance(node, DAGNode):
        k = node.dagnode_name
    elif isinstance(node, TreeNodeHandle):
        k = node.dagnode_name

    assert TreeNav.cwd().dagnode_name == 'root'
    root = TreeNav.cwd()._ref()
    TreeNav(parent)
    assert TreeNav.cwd().dagnode_name == parent.dagnode_name

    if isinstance(TreeNav.cwd()._ref(), Registry):
        assert k in TreeNav.cwd().nodes()

    if isinstance(TreeNav.cwd()._ref(), FacadeNode):
        assert k not in [c for c in TreeNav.cwd()._children]
        assert k not in [c.dagnode_name for c in TreeNav.cwd().dagnode_children]
        assert k in [c.dagnode_name for c in TreeNav.cwd()._dependents.values()]
    else:
        assert k in [c for c in TreeNav.cwd()._children]
        assert k in [c.dagnode_name for c in TreeNav.cwd().dagnode_children]
        assert k in [c.dagnode_name for c in TreeNav.cwd()._dependents.values()]

    assert k in dir(TreeNav.cwd())
    TreeNav(root)
    assert TreeNav.cwd().dagnode_name == 'root'


def test_tree_nav_root_idempotent(root_node):
    node = DAGNode()
    node._set_name('a')
    install_and_assert_consistent(node, root_node)
    TreeNav.down('a')
    assert TreeNav.cwd().dagnode_name == 'a'
    TreeNav.up()
    assert TreeNav.cwd().dagnode_name == 'root'
    TreeNav.up()
    assert TreeNav.cwd().dagnode_name == 'root'

class Foo:
    def __init__(self, y):
        self.x = 5
        self.y = y

    def do_thing(self, extra: int = 10):
        return self.x + extra

    def _name(self):
        """Designed to collide with reserved"""
        return 'gotcha'

    def _hidden(self):
        """Just normal hidden"""
        return 'nope'

def test_dagnode_children_filters_exposed(root_node):
    f = FacadeNode(Foo(1))
    assert isinstance(f._instance, Foo)
    root_node.install(f)
    starting_dependents = f._dependents
    assert starting_dependents != []

    assert f.dagnode_children == []
    assert f._dependents == starting_dependents
    f.expose_name("_hidden")
    assert f.dagnode_children == [f._dependents[f.get_child_path('_hidden')]]
    assert f._dependents == starting_dependents
    f.hide_all()
    assert f.dagnode_children == []
    assert f._dependents == starting_dependents


def test_tree_nav(root_node):
    def scope():
        node = DAGNode()
        node._set_name('a')
        install_and_assert_consistent(node, root_node)
        assert_tree_children_consistent(node, root_node)

        node_nest = DAGNode()
        node_nest._set_name('aa')
        install_and_assert_consistent(node_nest, node)
        assert_tree_children_consistent(node_nest, node)

        fnode = FacadeNode(Foo(1))
        install_and_assert_consistent(fnode, node)
        fnode.expose_name("_hidden")
        assert_tree_children_consistent(fnode, node)

        TreeNav.set(node)
        assert isinstance(TreeNav._singleton, TreeNodeHandle)
        assert TreeNav.cwd().dagnode_name == 'a'
        assert TreeNav.cwd()._ref() == node

        TreeNav.up()
        assert TreeNav.cwd().dagnode_name == 'root'
        assert TreeNav.ls() == set({'a'})
        TreeNav.down('a')
        assert TreeNav.cwd().dagnode_name == 'a'
        assert TreeNav.cwd()._ref() == node
        TreeNav.down('aa')
        assert TreeNav.cwd().dagnode_name == 'aa'
        assert TreeNav.cwd()._ref() == node_nest
        TreeNav.up()
        assert TreeNav.cwd().dagnode_name == 'a'
        assert TreeNav.cwd()._ref() == node
        TreeNav.down('Foo')
        assert TreeNav.cwd().dagnode_name == 'Foo'
        assert TreeNav.cwd()._ref() == fnode
        assert '_hidden' in TreeNav.ls()
        assert '_name' not in TreeNav.ls()
        TreeNav.down('_hidden')
        assert TreeNav.cwd().dagnode_name == '_hidden'

        TreeNav.set(node)
        uninstall_and_assert_consistent(fnode, node)
        assert 'Foo' not in TreeNav.ls()
        uninstall_and_assert_consistent(node, root_node)
        assert 'alive=False' in TreeNav.cwd().__repr__()
        with pytest.raises(DeadReference, match="not alive"):
            a = TreeNav.cwd().dagnode_name


    scope()
    
    with pytest.raises(DeadReference, match="garbage collected"):
        a = TreeNav.cwd().dagnode_name

def test_dagnode_children_ignores_name_collision_from_extra_dependency(root_node):
    """Two unrelated nodes both named 'a' in different branches. A node whose
    real parent is one of them, but which also carries an *extra* dependency
    on the other, must not show up as the wrong one's child just because the
    names collide."""
    top = DAGNode(); top._set_name('top')
    install_and_assert_consistent(top, root_node)
    top_a = DAGNode(); top_a._set_name('a')
    install_and_assert_consistent(top_a, top)

    side = DAGNode(); side._set_name('side')
    install_and_assert_consistent(side, root_node)
    side_a = DAGNode(); side_a._set_name('a')
    install_and_assert_consistent(side_a, side)

    assert top_a.dagnode_name == side_a.dagnode_name == 'a'

    leaf = DAGNode(resources=top_a)
    leaf._set_name('leaf')
    install_and_assert_consistent(leaf, side_a)

    assert top_a in leaf._dependencies.values()          # extra dep, not install-parent
    assert leaf not in top_a.dagnode_children, (
        "leaf's real parent is side_a; an extra dependency on top_a "
        "(which merely shares side_a's name) must not count as a child"
    )
    assert leaf in side_a.dagnode_children


def test_tree_nav_reflects_installs_and_kills_after_construction(root_node):
    """TreeNav.set() must not snapshot children at the moment it's called --
    ls()/dir()/_children need to reflect whatever's currently installed,
    checked both by adding and by removing after the handle already exists."""
    node = DAGNode(); node._set_name('a')
    install_and_assert_consistent(node, root_node)
    TreeNav.set(node)
    assert TreeNav.ls() == set()

    child = DAGNode(); child._set_name('b')
    install_and_assert_consistent(child, node)
    assert TreeNav.ls() == {'b'}
    assert 'b' in dir(TreeNav.cwd())
    TreeNav.down('b')
    assert TreeNav.cwd().dagnode_name == 'b'
    TreeNav.up()
    assert TreeNav.cwd().dagnode_name == 'a'

    uninstall_and_assert_consistent(child, node)
    assert TreeNav.ls() == set()
    assert 'b' not in dir(TreeNav.cwd())
