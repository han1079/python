import inspect
from typing import Optional, Union

import pytest
from lazybench.core.invokable import Invokable
from lazybench.core.violations import RuleViolation
from lazybench.app.ux.prompter import CannedPrompter, Prompter
from lazybench.tests.conftest import strings_in_exception


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


def simple(a, b, c):
    return (a, b, c)


def test_positional_then_keyword_collide_same_round():
    n = Invokable(simple)
    with pytest.raises(Exception) as e:
        n.bind(1, 2, 3, a=99)
    strings_in_exception(e, 'already filled with')

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

def test_kitchen_sink_across_multiple_bind_calls():
    n = Invokable(kitchen_sink)

    n.bind(1, 2, 3, 40, 50, 60, e=7, g=8, h=9)
    assert resolved(n) == {
        'a': 1, 'b': 2, 'c': 3, 'd': 40,
        'args': (50, 60), 'e': 7, 'f': inspect.Parameter.empty,
        'kwargs': {'g': 8, 'h': 9},
    }

    assert n.currently_unbound == {}

    # d was bound positionally last round; keyword override wins since
    # this round has no positional write on d to collide with.
    n.bind(d=88)
    assert resolved(n)['d'] == 88

    # Only 3 positional inputs -> no overflow -> bound_args clears to ()
    # rather than keeping the previous round's (50, 60).
    n.bind(2, 3, 4, 77, 88, 99)
    assert resolved(n) == {
        'a': 2, 'b': 3, 'c': 4, 'd': 77,
        'args': (88, 99), 'e': 7, 'f': inspect.Parameter.empty,
        'kwargs': {'g': 8, 'h': 9},
    }

    # Collide with positional arg only
    with pytest.raises(Exception) as e:
        n.bind(3, b=4)
    strings_in_exception(e, 'Cannot fill keyword')

    # Verify that nothing has changed (cached values applied at the end)
    assert resolved(n) == {
        'a': 2, 'b': 3, 'c': 4, 'd': 77,
        'args': (88, 99), 'e': 7, 'f': inspect.Parameter.empty,
        'kwargs': {'g': 8, 'h': 9},
    }

def test_currently_unbound_lists_required_params_missing_default_or_value():
    # d and f are absent: they have real defaults (4, 6), so get_value(False)
    # resolves them without needing a bind. args/kwargs are excluded by kind.
    n = Invokable(kitchen_sink)
    assert n.currently_unbound == {
        'a': int, 'b': inspect.Parameter.empty,
        'c': int, 'e': inspect.Parameter.empty,
    }

def test_currently_unbound_narrows_as_params_are_bound():
    n = Invokable(kitchen_sink)
    n.bind(1, 2)
    assert n.currently_unbound == {'c': int, 'e': inspect.Parameter.empty}

    n.bind(c=3, e=7)
    assert n.currently_unbound == {}


class TstBound:
    def tst_method(self, a: int = 4, *args, **kwargs):
        self.name = "asdf"
        return self.name, a

tstbound = TstBound()

def test_signature():
    n = Invokable(kitchen_sink)

    n.bind(1, 2, 3, 40, 50, 60, e=7, g=8, h=9)
    assert resolved(n) == {
        'a': 1, 'b': 2, 'c': 3, 'd': 40,
        'args': (50, 60), 'e': 7, 'f': inspect.Parameter.empty,
        'kwargs': {'g': 8, 'h': 9},
    }

    assert n.signature == 'kitchen_sink(a: int, b, c: int, d, *args, e, f: int, **kwargs)', print(n.signature)

    assert n.qualsignature == 'kitchen_sink(a: int, b, c: int, d, *args, e, f: int, **kwargs)', print(n.qualsignature)

    t = Invokable(tstbound.tst_method)
    assert t.signature == 'tst_method(a: int, *args, **kwargs)'
    assert t.qualsignature == 'TstBound.tst_method(a: int, *args, **kwargs)'

    t2 = Invokable(TstBound.tst_method)
    assert t2.signature == 'tst_method(self, a: int, *args, **kwargs)'
    assert t2.qualsignature == 'TstBound.tst_method(self, a: int, *args, **kwargs)'


def var_kw_named_kwargs(a, **kwargs):
    return (a, kwargs)


def test_keyword_matching_varkw_name_goes_to_overflow():
    """A keyword literally named the same as the **kwargs parameter itself
    is not an addressable target -- it's just another unmatched name and
    lands in the overflow bucket, same as real Python: def f(**kwargs);
    f(kwargs=5) -> kwargs == {'kwargs': 5}."""
    n = Invokable(var_kw_named_kwargs)
    n.bind(1, kwargs=5)
    assert resolved(n) == {'a': 1, 'kwargs': {'kwargs': 5}}


def kwonly_no_varpos(*, a, **kwargs):
    return (a, kwargs)


def test_positional_arg_with_no_slots_and_no_varpos_raises():
    """Zero positional-capable slots AND no *args -- the first positional
    arg has nowhere to go and must raise immediately."""
    n = Invokable(kwonly_no_varpos)
    with pytest.raises(RuleViolation) as e:
        n.bind(1)

    strings_in_exception(e, '[Not in Node]', 'VARPOS')

def test_kwarg_with_no_slots_and_no_varkw_raises():
    n = Invokable(simple)
    with pytest.raises(RuleViolation) as e:
        n.bind(2, k=3)

    strings_in_exception(e, '[Not in Node]', 'No VARKW')

def with_default(a, b=42):
    return (a, b)


def test_populated_falls_back_to_default_until_bound():
    n = Invokable(with_default)
    b_param = next(p for p in n.params if p.name == 'b')

    # unbound -> populated reports the default
    assert b_param.populated == ('b', inspect.Parameter.empty, 42,
                                  inspect.Parameter.POSITIONAL_OR_KEYWORD)

    n.bind(1, 99)

    # bound -> populated reports the bound value, not the default
    assert b_param.populated == ('b', inspect.Parameter.empty, 99,
                                  inspect.Parameter.POSITIONAL_OR_KEYWORD)


def test_bind_noop_leaves_state_untouched():
    n = Invokable(kitchen_sink)
    n.bind(1, 2, 3, 40, 50, 60, e=7, g=8, h=9)
    before = resolved(n)

    n.bind()  # zero args, zero kwargs
    assert resolved(n) == before

# ===== Runner Tests =====

def test_basic_executor():
    n = Invokable(simple) 
    n.bind(1,2,3)

    assert resolved(n) == {
            'a': 1, 'b': 2, 'c': 3
            }
    result = n.execute_raw(1,2,3)
    assert result == (1,2,3)

    result = n.execute_bound()
    assert result == (1,2,3)

    result = n.execute_raw(3,4,5)
    assert result == (3,4,5)

    n.bind(2,3,4)
    result = n.execute_bound()
    assert result == (2,3,4)

def test_partial_executor(restore_prompter):
    canned = CannedPrompter(
            text=['2']
            )
    
    Prompter.set(canned)

    n = Invokable(simple)
    n.bind(1, c=3)

    assert resolved(n) == {
            'a': 1,
            'b': inspect.Parameter.empty,
            'c': 3
            }

    result = n.execute_bound()
    assert result == (1, '2', 3)


def torture(a: int, b, /, c: str, *, d: float, e: list[int],
            f: dict[str, int], g: Optional[int], h: Union[str, int]):
    return (a, b, c, d, e, f, g, h)


def test_torture_executor_fills_every_unbound_kind_via_prompter(restore_prompter):
    """a and c are bound; everything else -- a bare/untyped positional-only,
    a plain float, a list, a dict, a declined Optional, and a Union -- gets
    filled by execute_bound() -> get_value() -> prompt_for_type() across a
    single CannedPrompter queue set."""
    canned = CannedPrompter(
        text=[
            'bee_val',  # b: no annotation -> TypeTree treats it as str
            '3.14',     # d: float
            '2',        # e: list[int] nelem
            '7',        # e: elem 1
            '8',        # e: elem 2
            '1',        # f: dict[str, int] nelem
            'fk',       # f: key
            '9',        # f: val
            'aitch',    # h: Union[str, int] value, once 'str' is picked
        ],
        confirm=[
            False,  # g: Optional[int] -- decline, g stays None
        ],
        select=[
            'str',  # h: Union[str, int] -- pick the str branch
        ],
    )
    Prompter.set(canned)

    n = Invokable(torture)
    n.bind(1, c='ccc')

    result = n.execute_bound()

    assert canned.remaining() == {'text': 0, 'confirm': 0, 'select': 0}
    assert result == (1, 'bee_val', 'ccc', 3.14, [7, 8], {'fk': 9}, None, 'aitch')


def test_execute_bound_rejects_var_positional(restore_prompter):
    """*args has no single type to prompt for -- execute_bound() must raise
    the moment it reaches a VAR_POSITIONAL param, not silently drop it.
    Empty CannedPrompter queues: if the code tried to prompt instead, this
    would surface as an IndexError, not the TypeError we assert on."""
    canned_arg = CannedPrompter(
            text=[
                'e_var',
                ]
            )
    Prompter.set(canned_arg)
    n = Invokable(kitchen_sink)
    n.bind(1, 2, 3, h="h_var")  # a, b, c bound; d has a default; *args left untouched
    result = n.execute_bound()

    assert result == (1,2,3,4, (), 'e_var', 6, {'h': 'h_var'})

#def kitchen_sink(a:int , b, /, c: int, d=4, *args, e, f:int =6, **kwargs):
#    return (a, b, c, d, args, e, f, kwargs)

def test_execute_bound_passes_through_bound_wildcards(restore_prompter):
    """Unbound *args/**kwargs have no type to prompt for and must raise (see
    test_execute_bound_rejects_var_positional/keyword above) -- but once the
    operator has actually bound overflow values into them, execute_bound()
    should pass those straight through rather than refusing to run."""
    Prompter.set(CannedPrompter())

    n = Invokable(kitchen_sink)
    # a=1, b=2, c=3, d=40 fill the named slots; 50, 60 overflow into *args;
    # e=7 fills the keyword-only slot; f is left to its default (6); g, h
    # overflow into **kwargs.
    n.bind(1, 2, 3, 40, 50, 60, e=7, g=8, h=9)

    result = n.execute_bound()

    assert result == (1, 2, 3, 40, (50, 60), 7, 6, {'g': 8, 'h': 9})

#def kwonly_no_varpos(*, a, **kwargs):
#    return (a, kwargs)

def test_execute_bound_rejects_var_keyword(restore_prompter):
    """Same guarantee for **kwargs, via a signature with no *args to hit
    first (kwonly_no_varpos: `def kwonly_no_varpos(*, a, **kwargs)`)."""
    Prompter.set(CannedPrompter())

    n = Invokable(kwonly_no_varpos)

    with pytest.raises(RuleViolation) as e:
        n.bind(1)
    strings_in_exception(e, 'No VARPOS and only')

