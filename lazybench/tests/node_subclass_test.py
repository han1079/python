import pytest
from lazybench.core.core import make_subclass
from lazybench.core.node import Registry, DAGNode
from lazybench.core.violations import *
from typing import Callable
import weakref

from lazybench.tests.node_test import assert_node_dead
from lazybench.tests.node_test import assert_node_alive_not_active

AliasNode = make_subclass(DAGNode, 
                          attr_name='alias',
                          default_factory=set,
                          class_name='AliasNode')

def is_unique_after_subclass(cls):
    assert cls('a') is not cls('b')
    assert cls('a') != cls('b')

def subclass_name_matches(cls, name):
    a = cls('a')
    assert type(a).__name__ == name

def test_unique_after_subclass():
    is_unique_after_subclass(AliasNode)

def test_subclass_name_matches():
    subclass_name_matches(AliasNode, 'AliasNode')

def test_nested_subclass():
    TaggedAliasNode = make_subclass(AliasNode,
                                  attr_name='tags',
                                  default_factory=tuple,
                                  class_name='TaggedAliasNode')
    is_unique_after_subclass(TaggedAliasNode)
    subclass_name_matches(TaggedAliasNode, 'TaggedAliasNode')

    # Use Invokable to grab all the parameters from the __init__ functions of 
    # each of these subclasses. The KWARGS should be completely unaffected.
    from lazybench.core.invokable import Invokable
    tagged_init_names = [p.name for p in Invokable(TaggedAliasNode.__init__).params]
    alias_init_names = [p.name for p in Invokable(AliasNode.__init__).params]
    base_init_names = [p.name for p in Invokable(DAGNode.__init__).params]
    assert set(alias_init_names).intersection(tagged_init_names) == set(alias_init_names)
    assert set(alias_init_names).intersection(base_init_names) == set(alias_init_names)
    assert set(base_init_names).intersection(tagged_init_names) == set(base_init_names)

    t = TaggedAliasNode('t', alias=set(['t', 'tea']), tags=('asdf', 'jkl;'))
    assert 'asdf' in t.tags and 'asdf' not in t.alias
    assert 'jkl;' in t.tags and 'jkl;' not in t.alias
    assert 't' in t.alias and 't' not in t.tags
    assert 'tea' in t.alias and 'tea' not in t.tags

def test_collided_attr_new(root_node):
    with pytest.raises(AttributeError, match='Cannot override existing attribute'):
        InstallNameCollideNode = make_subclass(DAGNode,
                                               attr_name='install',
                                               default_factory=None,
                                               class_name='InstallNameCollideNode')

    OtherAliasNode = make_subclass(DAGNode, 
                              attr_name='otheralias',
                              default_factory=set,
                              class_name='OtherAliasNode')

    with pytest.raises(AttributeError, match='Cannot override existing attribute'):
        AliasNewAttr = make_subclass(OtherAliasNode,
                                       attr_name='otheralias',
                                       default_factory=tuple,
                                       class_name='AliasIdempotentNewAttr')

    class Foo:
        pass

    with pytest.raises(AttributeError, match='has no _reserved_attr_names'):
        FooEy = make_subclass(Foo,
                                       attr_name='attr_name',
                                       default_factory=tuple,
                                       class_name='FooEy')


