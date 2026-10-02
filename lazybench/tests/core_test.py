import pytest
from lazybench.tests.conftest import strings_in_exception
from lazybench.app.ux.prompter import Prompter, InquirerPrompter

# ============= Node Metaclass Tests ===============================
from lazybench.core.core import MetaNode

def test_metanode_guard_no_init():
    # Every Node NEEDS an init - even if you just args, kwargs it. 
    # This way we ensure that the bootstrap process is guaranteed to 
    # run at EVERY inheritance level
    with pytest.raises(AttributeError, match='__init__ function'):
        class NodeNoBootstrapNoInit(metaclass=MetaNode): pass

def test_metanode_guard_no_bootstrap():

    class NodeNoBootstrapWithInit(metaclass=MetaNode): 
        def __init__(self):
            return

    with pytest.raises(AttributeError, match='NodeNoBootstrapWithInit may not be a valid DAGNode'):
        n = NodeNoBootstrapWithInit()

    # Run into the attribute guard - NOT the init guard.
    class InheritedInit(NodeNoBootstrapWithInit): pass

    with pytest.raises(AttributeError, match='InheritedInit may not be a valid DAGNode'):
        n = InheritedInit()

def get_all_public(instance):
    if isinstance(instance, type):
        return {k: v for k, v in instance.__dict__.items() if not k.startswith('_')}
    else:
        class_params = {k: v for k, v in type(instance).__dict__.items() if not k.startswith('_')}
        inst_params = {k: v for k, v in instance.__dict__.items() if not k.startswith('_')}
        class_params.update(inst_params)
        return class_params

class BaseBoot(metaclass=MetaNode): 
    def __init__(self):
        self.x = 0
        self.y = 0
        self.counter = 0

    def foo(self):
        pass

    def bar(self):
        pass
    def _bootstrap_node(self):
        self.counter += 1
        self.params = {}
        self.params.update(get_all_public(self))
        class_walk = type(self).mro()
        for cls in class_walk:
            self.params.update(get_all_public(cls))
            
class InheritedBoot(BaseBoot): pass

class ExtendedBoot(InheritedBoot):
    def __init__(self):
        self.z = 3
        super().__init__()
    def new_method(self):
        self.z = self.y + self.x
    def _bootstrap_node(self):
        super()._bootstrap_node()

class LazyCounter(InheritedBoot): 
    def __init__(self):
        self.q = 2
        self.counter = 0
    def newer_method(self):
        self.z = 4
    def _bootstrap_node(self):
        super()._bootstrap_node()
        self.newer_method()

class BrokenCounter(InheritedBoot):
    def __init__(self):
        pass

def test_metanode_bootstrap():
    b = BaseBoot()
    assert b.x == 0
    assert b.y == 0
    assert all(x in b.params for x in ('counter', 'x', 'y', 'params', 'foo', 'bar'))
    assert b._bootstrapped_meta == True

    b = InheritedBoot()
    assert b.x == 0
    assert b.y == 0
    assert all(x in b.params for x in ('counter', 'x', 'y', 'params', 'foo', 'bar'))
    assert b._bootstrapped_meta == True

    b = ExtendedBoot()
    assert b.x == 0
    assert b.y == 0
    assert b.z == 3
    assert all(x in b.params for x in ('x', 'y', 'z', 'params', 'foo', 'bar', 'counter', 'new_method'))
    assert b.counter == 1
    assert b._bootstrapped_meta == True

    lazy = LazyCounter()
    assert lazy.q == 2
    assert all(x in lazy.params for x in ('q', 'params', 'foo', 'bar', 'counter', 'newer_method'))
    assert lazy.counter == 1
    assert lazy._bootstrapped_meta == True

def test_broken_metanode():
    with pytest.raises(AttributeError, match='BrokenCounter may not be a valid DAGNode'):
        broken = BrokenCounter()


