import inspect
from typing import Optional, Union

import pytest
from lazybench.core.invokable import Invokable
from lazybench.core.violations import RuleViolation
from lazybench.app.ux.prompter import CannedPrompter, Prompter

@pytest.fixture
def restore_prompter():
    prior = Prompter._instance
    yield
    Prompter._instance = prior

def resolved(n: Invokable) -> dict:
    """Named params by .value, *args/**kwargs buckets under their own
    param names — mirrors inspect.BoundArguments.arguments."""
    out = {}
    for p in n.params:
        if p.param_kind == inspect.Parameter.VAR_POSITIONAL:
            out[p.name] = n.bound_args
        elif p.param_kind == inspect.Parameter.VAR_KEYWORD:
            out[p.name] = n.bound_kwargs
        else:
            out[p.name] = p.value
    return out

def kitchen_sink(a:int , b, /, c: int, d=4, *args, e, f:int =6, **kwargs):
    return (a, b, c, d, args, e, f, kwargs)

def var_pos_and_kw(*varpos, d=5, e, f, **kwargs):
    return (varpos, d, e, f, kwargs)

def test_var_pos_as_only_positional_case():
    n = Invokable(var_pos_and_kw)
    n.bind(1,2,3,4,5, d=44, e=55, h=100)
    assert resolved(n) == {
    'd': 44, 'e': 55, 'f': inspect.Parameter.empty,
    'varpos': (1,2,3,4,5), 'kwargs': {'h': 100}
    }
