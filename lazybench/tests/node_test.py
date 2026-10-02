import pytest

from lazybench.core.violations import RuleViolation
from lazybench.core.tree import TreeNav, TreeNodeHandle, DeadReference
from lazybench.core.node import DAGNode, DAGDict
from lazybench.core.violations import *
from lazybench.tests.conftest import root_node
from lazybench.app.ux.prompter import Prompter, InquirerPrompter

iqp = InquirerPrompter()
Prompter.set(iqp)

NAME_CASES = {'none': None, 'set': 'n'}
DEPENDENCY_CASES = {
    'none': None,
    'empty_tuple': (),
    'root_str': 'root',
    'root_str_tuple': ('root',),
    'root_node': lambda root: root,
    'root_node_tuple': lambda root: (root,),
}


@pytest.mark.parametrize('name_key', NAME_CASES.keys())
@pytest.mark.parametrize('dependencies_key', DEPENDENCY_CASES.keys())
def test_dagnode_init(root_node, restore_prompter, dependencies_key, name_key):
    """Every (name, dependencies) combo DAGNode.__init__ accepts. The one hard
    invariant, regardless of which combo: a rejected combo must fail loudly
    via RuleViolation (a recognized domain error), never leak a bare
    TypeError/NameError/etc from the implementation. Successful combos get
    spot-checked for basic name/unique_path consistency.
    """
    name = NAME_CASES[name_key]
    resources = DEPENDENCY_CASES[dependencies_key]
    if callable(resources):
        resources = resources(root_node)

    try:
        node = DAGNode(name=name, resources=resources)
    except RuleViolation:
        return
    except Exception as e:
        pytest.fail(f'non-RuleViolation leak: {type(e).__name__}: {e}')

    assert node.dagnode_name == name
    if root_node.install(node):
        assert node.dagnode_path in root_node._dependents
        assert node.is_active

        assert root_node.uninstall(node) == True
        assert root_node._dependents == DAGDict()
        assert not node.is_active
        assert root_node.dagnode_path not in node._dependencies.keys()
    else:
        assert root_node.uninstall(node) == False

def assert_node_dead(node):
    assert node._trying_to_be_active is False, f'{node.dagnode_name}._trying_to_be_active is True'
    assert node.is_active is False, f'{node.dagnode_name}.is_active is True'
    assert node.is_alive is False, f'{node.dagnode_name}.is_alive is True'

def assert_node_alive_not_active(node):
    assert node.is_active is False, f'{node.dagnode_name}.is_active is True'
    assert node.is_alive is True, f'{node.dagnode_name}.is_alive is False'

def assert_node_alive_and_active(node):
    assert node.is_active is True, f'{node.dagnode_name}.is_active is False'
    assert node.is_alive is True, f'{node.dagnode_name}.is_alive is False'

def install_and_assert_consistent(child, parent):
    assert child.dagnode_children == []
    pre_install = set(parent.dagnode_children)
    assert parent.install(child) is True, f'install() refused: {child.dagnode_name} onto {parent.dagnode_name}'
    post_install = set(parent.dagnode_children)
    assert pre_install.symmetric_difference(post_install) == set([child]) 
    assert pre_install.issubset(post_install)

    assert child.dagnode_path == parent.get_child_path(child)
    assert child.dagnode_path == parent.get_child_path(child.dagnode_name)

    assert child.dagnode_path == parent.dagnode_path + (child.dagnode_name,), (
        f'unique_path mismatch: {child.dagnode_path} != '
        f'{parent.dagnode_path + (child.dagnode_name,)}'
    )

    # Forward index: child knows parent
    assert parent.dagnode_path in child._dependencies.keys()
    assert child._dependencies[parent.dagnode_path] is parent

    # Backward index: parent knows child, exactly once
    assert child.dagnode_path in parent._dependents
    assert child in parent.dagnode_children
    assert parent._dependents[child.dagnode_path] is child
    assert sum(1 for v in parent._dependents.values() if v is child) == 1

    # Every dependency child actually holds is symmetric on the other end too
    for dep in child._dependencies.values():
        assert dep._dependents.get(child.dagnode_path) is child

    assert len(child.dependency_alive_states) > 0, 'vacuous dependency_alive_states after install'
    assert all(state is True for state in child.dependency_alive_states)
    assert len(child.dependency_active_states) > 0, 'vacuous dependency_active_states after install'
    assert all(state is True for state in child.dependency_active_states)
    assert_node_alive_and_active(child)

    return child

def uninstall_and_assert_consistent(child, parent):
    child_upath_cache = child.dagnode_path
    assert parent.uninstall(child) is True, (
        f'uninstall() was a no-op for {child.dagnode_name} on {parent.dagnode_name}'
    )

    assert_node_dead(child)

    assert dict(child._dependencies) == {}, (
        f'child.dependencies not cleared: {dict(child._dependencies)}'
    )
    assert child_upath_cache not in parent._dependents
    assert child.dagnode_path is None
    assert not any(v is child for v in parent._dependents.values())

def test_install_lifecycle(root_node):
    node = DAGNode()
    node._set_name('a')
    install_and_assert_consistent(node, root_node)
    uninstall_and_assert_consistent(node, root_node)


def test_double_install_raises(root_node):
    node = DAGNode()
    node._set_name('a')
    install_and_assert_consistent(node, root_node)

    nodeb = DAGNode()
    nodeb._set_name('a')
    with pytest.raises(RuleViolation, match = 'Existing lib'):
        root_node.install(nodeb)

    nodeb._set_name('b')
    install_and_assert_consistent(nodeb, root_node)
    uninstall_and_assert_consistent(nodeb, root_node)

def test_install_and_graft_raises(root_node):
    node = DAGNode()
    node._set_name('a')
    install_and_assert_consistent(node, root_node)

    with pytest.raises(UniquenessViolation, match='new parent illegal'):
        node.graft_install()

    uninstall_and_assert_consistent(node, root_node)

def test_unbound_node_cant_install(root_node):
    node = DAGNode()
    node._set_name('a')

    node_nest = DAGNode()
    node_nest._set_name('aa')

    with pytest.raises(ValidityViolation, match='a is not alive'):
        node.install(node_nest)




def _named_fluent(name):
    node = DAGNode()
    node._set_name(name)
    return node

NODE_NAME_STRATEGIES = {'ctor': lambda name: DAGNode(name=name), 'fluent': _named_fluent}


@pytest.mark.parametrize('node_strategy', NODE_NAME_STRATEGIES.keys())
@pytest.mark.parametrize('nest_strategy', NODE_NAME_STRATEGIES.keys())
def test_cascade_install(root_node, node_strategy, nest_strategy):
    node = NODE_NAME_STRATEGIES[node_strategy]('a')
    node_nest = NODE_NAME_STRATEGIES[nest_strategy]('aa')

    install_and_assert_consistent(node, root_node)
    install_and_assert_consistent(node_nest, node)
    uninstall_and_assert_consistent(node_nest, node)
    assert_node_alive_and_active(node)
    assert_node_dead(node_nest)
    uninstall_and_assert_consistent(node, root_node)

    install_and_assert_consistent(node, root_node)
    install_and_assert_consistent(node_nest, node)
    uninstall_and_assert_consistent(node, root_node)
    assert_node_dead(node_nest)


@pytest.mark.parametrize('node_strategy', NODE_NAME_STRATEGIES.keys())
@pytest.mark.parametrize('nest_strategy', NODE_NAME_STRATEGIES.keys())
def test_cascade_deactivate(root_node, node_strategy, nest_strategy):
    node = NODE_NAME_STRATEGIES[node_strategy]('a')
    node_nest = NODE_NAME_STRATEGIES[nest_strategy]('aa')

    install_and_assert_consistent(node, root_node)
    install_and_assert_consistent(node_nest, node)
    node.deactivate_node()
    assert not node._trying_to_be_active
    assert_node_alive_not_active(node)
    assert node_nest._trying_to_be_active
    assert_node_alive_not_active(node_nest)

    node.set_trying_to_be_active()
    assert_node_alive_and_active(node)
    assert_node_alive_and_active(node_nest)
    uninstall_and_assert_consistent(node, root_node)

@pytest.mark.parametrize('node_strategy', NODE_NAME_STRATEGIES.keys())
@pytest.mark.parametrize('nest_strategy', NODE_NAME_STRATEGIES.keys())
@pytest.mark.parametrize('nest_2_strategy', NODE_NAME_STRATEGIES.keys())
def test_propagated_activation(root_node, node_strategy, nest_strategy, nest_2_strategy):
    node = NODE_NAME_STRATEGIES[node_strategy]('a')
    node_nest = NODE_NAME_STRATEGIES[nest_strategy]('aa')
    node_nest_2 = NODE_NAME_STRATEGIES[nest_2_strategy]('aaa')

    install_and_assert_consistent(node, root_node)
    install_and_assert_consistent(node_nest, node)
    install_and_assert_consistent(node_nest_2, node_nest)
    node.deactivate_node()
    node_nest_2.deactivate_node()

    assert not node._trying_to_be_active
    assert_node_alive_not_active(node)
    assert node_nest._trying_to_be_active
    assert_node_alive_not_active(node_nest)
    assert not node_nest_2._trying_to_be_active
    assert_node_alive_not_active(node_nest_2)

    node.set_trying_to_be_active()
    assert_node_alive_and_active(node)
    assert_node_alive_and_active(node_nest)
    assert not node_nest_2._trying_to_be_active
    assert_node_alive_not_active(node_nest_2)

    node.propagate_activation()
    assert_node_alive_and_active(node)
    assert_node_alive_and_active(node_nest)
    assert_node_alive_and_active(node_nest_2)

    uninstall_and_assert_consistent(node, root_node)


# ── dependency staging (`_set_dependencies`) ──

def test_set_dependencies_accumulates(root_node):
    dep1 = _named_fluent('dep1')
    dep2 = _named_fluent('dep2')
    install_and_assert_consistent(dep1, root_node)
    install_and_assert_consistent(dep2, root_node)

    node = _named_fluent('a')
    assert node._set_dependencies(dep1) is True
    assert node._proposed_dependencies == frozenset({dep1})
    assert node._set_dependencies(frozenset({dep2})) is True
    assert node._proposed_dependencies == frozenset({dep1, dep2})


def test_dependency_value_collision_rejected(root_node):
    """Same dependency object can't occupy two different keys in `_dependencies`."""
    dep = _named_fluent('dep')
    install_and_assert_consistent(dep, root_node)

    node = _named_fluent('a')
    install_and_assert_consistent(node, root_node)
    node._dependencies[dep.dagnode_path] = dep
    with pytest.raises(UniquenessViolation, match='already under another key'):
        node._dependencies[('bogus', 'key')] = dep


def test_set_dependencies_realized_on_install(root_node):
    extra = _named_fluent('extra')
    install_and_assert_consistent(extra, root_node)

    node = _named_fluent('a')
    node._set_dependencies(extra)
    install_and_assert_consistent(node, root_node)

    assert extra.dagnode_path in node._dependencies
    assert node._dependencies[extra.dagnode_path] is extra
    assert node.dagnode_path in extra._dependents
    assert extra._dependents[node.dagnode_path] is node


def test_set_dependencies_idempotent_with_future_parent(root_node):
    """Staging the node's eventual parent explicitly is redundant with what
    install() wires automatically -- must not raise or double-count."""
    node = _named_fluent('a')
    node._set_dependencies(root_node)
    install_and_assert_consistent(node, root_node)

    assert len(node._dependencies) == 1
    assert node._dependencies[root_node.dagnode_path] is root_node


def test_set_dependencies_invalid_shape_raises_rule_violation():
    """Unrecognized shapes must fail loudly via RuleViolation, never leak a
    bare TypeError -- same invariant test_dagnode_init holds the constructor to."""
    node = _named_fluent('a')
    with pytest.raises(RuleViolation, match='Invalid choices'):
        node._set_dependencies(123)
    with pytest.raises(RuleViolation, match='Invalid choices'):
        node._set_dependencies(frozenset({123}))


def test_dependency_key_collision_rejected(root_node):
    """Two distinct dependency objects can't occupy the same `_dependencies` slot."""
    dep_a = _named_fluent('dep')
    install_and_assert_consistent(dep_a, root_node)

    dep_b = _named_fluent('dep')
    dep_b._unique_path = dep_a.dagnode_path  # force a colliding path

    node = _named_fluent('a')
    install_and_assert_consistent(node, root_node)
    node._dependencies[dep_a.dagnode_path] = dep_a
    with pytest.raises(UniquenessViolation, match='already bound elsewhere'):
        node._dependencies[dep_b.dagnode_path] = dep_b


# ── public, alive-gated setters (fluent build) ──

ALIVE_GATED_SETTERS = {
    'set_resources': lambda node, root: node.set_resources(root),
    'set_dagnode_name': lambda node, root: node.set_dagnode_name('renamed'),
}


@pytest.mark.parametrize('setter_key', ALIVE_GATED_SETTERS.keys())
def test_setter_raises_once_alive(root_node, setter_key):
    """Every alive-gated fluent setter must refuse once a node is installed."""
    node = _named_fluent('a')
    install_and_assert_consistent(node, root_node)
    with pytest.raises(ValidityViolation):
        ALIVE_GATED_SETTERS[setter_key](node, root_node)

