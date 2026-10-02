import pytest
from lazybench.core.core import make_subclass
from lazybench.core.node import Registry, DAGNode
from lazybench.core.tree import TreeNodeHandle, TreeNav, DeadReference
from lazybench.core.violations import *
import weakref

from lazybench.tests.node_test import assert_node_dead
from lazybench.tests.node_test import assert_node_alive_not_active

def assert_registry_dead(node):
    assert_node_dead(node)
    assert not node.values()
    assert not node.keys()
    assert not node.nodes()

def test_registry_key_uniquness(root_node):
    a = Registry('a')
    root_node.install(a)
    for i in range(100):
        a.install(DAGNode(str(i)))

    with pytest.raises(RuleViolation, match='already bound elsewhere'):
        a.install(DAGNode('66'))

def test_registry_deactivate_reactivate(root_node):
    node_list = []
    a = Registry('a')
    root_node.install(a)

    for i in range(100):
        name = str(i)
        d = DAGNode(name)
        node_list.append(d)
        a.install(d)

    assert len(a.nodes()) == 100
    a.deactivate_node()
    assert all(not n.is_active for n in a.values())
    a.set_trying_to_be_active()
    assert all(n.is_active for n in a.values())

def test_registry_garbage_collection(root_node):
    node_list = []
    a = Registry('a')
    root_node.install(a)

    for i in range(100):
        name = str(i)
        d = DAGNode(name)
        node_list.append(d)
        a.install(d)

    node_refs = [weakref.ref(n) for n in node_list]
    assert len(node_refs) == len(a.nodes())

    # Kill node. Local list still holds references
    # Check "dead node-ness" using those references
    # Kill the list - a list of weakrefs should all go to None
    a.kill_node()
    assert_registry_dead(a)
    [assert_node_dead(n) for n in node_list]
    [assert_node_dead(n()) for n in node_refs]
    node_list = []
    d = None
    assert all([n() is None for n in node_refs])

def test_registry_garbage_collection_using_tree(root_node):
    assert TreeNav.cwd().dagnode_name == 'root'
    node_list = []
    a = Registry('a')
    root_node.install(a)

    for i in range(100):
        name = str(i)
        d = DAGNode(name)
        node_list.append(d)
        a.install(d)

    TreeNav.down('a')
    assert TreeNav.cwd().dagnode_name == 'a'
    node_refs = TreeNav.cwd()._children
    assert len(node_refs) == len(a.nodes())

    # Kill node. Local list still holds references
    # Check "dead node-ness" using those references
    # Kill the list - a list of weakrefs should all go to None
    a.kill_node()
    assert_registry_dead(a)
    [assert_node_dead(n) for n in node_list]
    for n in node_refs.values():
        with pytest.raises(DeadReference, match="is not alive"):
            n.dagnode_name

    node_list = []
    d = None
    for n in node_refs.values():
        with pytest.raises(DeadReference, match="garbage collected"):
            n.dagnode_name


def test_registry_nodes_with_unique_alias(root_node):
    AliasNode = make_subclass(DAGNode, 
                              attr_name='alias',
                              default_factory=set,
                              class_name='AliasNode')
    a = Registry('a')
    root_node.install(a)

    def block_duplicate_alias(node, to_add):
        return all([to_add.alias.intersection(n.alias) == set() for n in node.values()])

    for i in range(100):
        name = str(i)
        d = AliasNode(name)
        assert hasattr(d, 'alias')
        d.alias.add(str(i))
        a.install(d, block_duplicate_alias)

    collide = AliasNode(str(100))
    collide.alias.add(str(66))

    with pytest.raises(ValidityViolation, match='filter rule'):
        a.install(collide, block_duplicate_alias)

    collide.alias.remove(str(66))
    collide.alias = collide.alias.union({str(100), str(101)})
    a.install(collide, block_duplicate_alias)

    attempted_alias = str(98)
    assert attempted_alias in set().union(*[x.alias for x in a.values()])


