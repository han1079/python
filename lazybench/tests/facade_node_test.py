import functools

import pytest

from lazybench.core.callable import CallableNode
from lazybench.core.facade import FacadeNode
from lazybench.core.node import DAGNode
from lazybench.core.violations import ValidityViolation, UniquenessViolation
from lazybench.tests.conftest import root_node
from lazybench.app.ux.prompter import Prompter, InquirerPrompter

Prompter.set(InquirerPrompter())

EMPTY_INSTALL_FAILS = {'wrap': frozenset([]), 'install': frozenset([])}
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

#def test_ipc_bulk(root_node):
#    ipc = default_ipc_factory()
#    f = FacadeNode(ipc)
#    root_node.install(f)
#    f.expose_all()
#    assert all(not n.startswith('_') for n in f._exposed.keys())
#    assert isinstance(f.poll, CallableNode)
#    with pytest.raises(AttributeError, match='not exposed by FacadeNode'):
#        x = f._pubsub
#
#    # expose_name/hide_name: newest-wins, works on names expose_all skipped
#    private_vars = f._exploded_obj.instance_vars - f._exploded_obj.public_instance_vars
#    private_name = next(iter(private_vars))
#    assert private_name not in dir(f)
#
#    assert f.expose_name(private_name) is True
#    assert private_name in dir(f)
#    assert getattr(f, private_name) == getattr(ipc, private_name)
#
#    assert f.hide_name(private_name) is True
#    assert private_name not in dir(f)
#    with pytest.raises(AttributeError, match='not exposed by FacadeNode'):
#        getattr(f, private_name)
#
#    # hide_all: bulk reset, then a surgical expose_name proves newest-wins
#    # survives a full clear -- no leftover memory blocking or requiring a
#    # fresh expose_all to work again.
#    cleared = f.hide_all()
#    assert 'poll' in cleared
#    assert 'my_node_name' in cleared
#    assert dict(f._exposed) == {}
#    assert 'poll' not in dir(f)
#    with pytest.raises(AttributeError, match='not exposed by FacadeNode'):
#        f.poll
#
#    assert f.expose_name('poll') is True
#    assert isinstance(f.poll, CallableNode)
#    # only the surgically re-exposed name is back -- hide_all didn't leave
#    # anything else half-restored, and expose_name didn't resurrect the rest
#    assert dict(f._exposed) == {'poll': f._exposed['poll']}
#    assert 'my_node_name' not in dir(f)
#    with pytest.raises(AttributeError, match='not exposed by FacadeNode'):
#        f.my_node_name
#
#    # newest wins the other direction too: a fresh expose_all after the
#    # surgical single-name state fully restores the rest, no memory of the
#    # intervening hide_all/expose_name detour
#    f.expose_all()
#    assert isinstance(f.publish_to_topic, CallableNode)
#    assert 'my_node_name' in dir(f)
#
#    f.kill_node()
#    assert not f.poll.is_alive
#    
#    with pytest.raises(KeyError):
#        root_node._dependents[('root',)]
#
#    with pytest.raises(ValidityViolation, match='not alive'):
#        f.poll()
#
#    with pytest.raises(ValidityViolation, match='not alive'):
#        f.publish_to_topic()


def test_callable_node_dispatch(root_node):
    foo = Foo(1)
    cn = CallableNode(foo.do_thing, resources='root')
    root_node.install(cn)
    assert cn(0) == 5          # execute_raw: explicit args
    assert cn() == 15          # execute_bound: falls back to the default


def test_callable_node_rejects_non_callable():
    with pytest.raises(ValidityViolation, match='not callable'):
        CallableNode(None)
    with pytest.raises(ValidityViolation, match='not callable'):
        CallableNode(42)


def test_callable_node_unreachable_once_killed(root_node):
    cn = CallableNode(lambda: 5, name='piece', resources='root')
    root_node.install(cn)
    assert cn() == 5

    root_node.uninstall(cn)
    assert not cn.is_alive
    with pytest.raises(ValidityViolation, match='not alive'):
        cn()


def test_walk_and_attach_names_by_attribute_not_by_fn_name(root_node):
    class Foo:
        def real_method(self):
            return 'real'

        alias_method = real_method   # same __name__, different attribute name

    f = FacadeNode(Foo())
    assert f.dagnode_name == 'Foo'
    root_node.install(f)
    names = {n.dagnode_name for n in f._dependents.values()}
    assert names == {'real_method', 'alias_method'}
    assert f._failed_embeds == {'wrap': frozenset([]), 'install': frozenset([])}


def test_facade_is_handle_only_before_load_tree(root_node):
    f = FacadeNode(Foo(1))
    assert dict(f._dependents) == {}
    assert dict(f._exposed) == {}
    with pytest.raises(AttributeError):
        f.do_thing


def test_facade_load_tree_requires_install_first(root_node):
    f = FacadeNode(Foo(1))
    f._on_successful_install()
    assert not f.is_alive
    assert all(k in f.failed_to_wrap['install'] for k in f._dependents.keys())


def test_facade_explode_and_expose(root_node):
    foo = Foo(1)
    f = FacadeNode(foo)
    root_node.install(f)
    f.expose_all()

    assert f._exposed == {'do_thing', 'x', 'y'}
    assert 'do_thing' in dir(f)
    assert '_hidden' not in dir(f)
    assert f.do_thing() == 15
    assert f.do_thing(0) == 5

def test_facade_reserved_attr_collision_stays_installed_but_unexposed(root_node):
    foo = Foo(1)
    f = FacadeNode(foo)
    root_node.install(f)
    f.expose_all()

    # still a real child -- still torn down with the facade...
    assert any(dep._name == '_name' for dep in f._dependents.values())
    assert '_name' not in f._exposed
    # ...but the facade's own real attribute wins on read, not Foo.name.
    assert f._name == 'Foo'


def test_facade_load_tree_idempotent(root_node):
    foo = Foo(1)
    f = FacadeNode(foo)
    root_node.install(f)
    f.expose_all()
    with pytest.raises(UniquenessViolation, match='bypass and double-install'):
        f._on_successful_install()


def test_reserved_attr_names_not_shared_across_subclasses(root_node):
    """RootNode.get (a classmethod unrelated to FacadeNode) must not leak
    into FacadeNode's own reserved-name check just because both classes
    inherit DAGNode._reserved_attr_names without redeclaring it."""
    class Bar:
        def get(self):
            return 'mine'

    f = FacadeNode(Bar())
    root_node.install(f)
    f.expose_all()
    assert f._failed_embeds == EMPTY_INSTALL_FAILS

    assert f.get() == 'mine'


def test_facade_kill_cascades_to_exposed_children(root_node):
    foo = Foo(1)
    f = FacadeNode(foo)
    root_node.install(f)
    f.expose_all()

    piece = f.do_thing
    assert piece.is_alive
    assert piece() == 15

    f.kill_node()
    assert not piece.is_alive
    with pytest.raises(ValidityViolation, match="do_thing is not alive .*never installed, or killed.*"):
        piece()

    with pytest.raises(AttributeError, match="'do_thing' not exposed by FacadeNode"):
        f.do_thing()


def test_facade_sets_holder_node_for_violation_context(root_node):
    foo = Foo(1)
    f = FacadeNode(foo)
    assert foo._holder_node._ref() is f


def test_facade_skip_private_false_is_reachable(root_node):
    class Foo:
        def public(self):
            return 'pub'

        def _priv(self):
            return 'priv'

    f = FacadeNode(Foo())
    root_node.install(f)
    f.expose_all(expose_private=True)

    assert f._priv() == 'priv'
    assert '_priv' in dir(f)


def test_walk_and_attach_does_not_trigger_cached_property(root_node):
    class Foo:
        def __init__(self):
            self.computed = 0

        @functools.cached_property
        def expensive(self):
            self.computed += 1
            return 42

    f = FacadeNode(Foo())
    root_node.install(f)
    f.expose_all()
    Prompter.log(f._exposed)

    assert f.computed == 0
    assert not any(n._name == 'expensive' for n in f._dependents)


def test_skips_reserved_names(root_node):
    class Collide:
        def __init__(self, y):
            self.x = 5
            self.y = y

        def install(self, extra: int = 10):
            return self.x + extra

        def _name(self):
            """Collides with DAGNode._name -- must be skipped loudly, not lost silently."""
            return 'gotcha'

        def is_alive(self):
            return 'nope'

        def safe(self):
            return 'safe'

    f = FacadeNode(Collide(3))
    root_node.install(f)
    f.expose_all()

    assert f._exposed == {'safe', 'x', 'y'}

