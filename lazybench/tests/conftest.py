import itertools

import pytest
from lazybench.app.ux.prompter import Prompter, InquirerPrompter

iqp = InquirerPrompter()
Prompter.set(iqp)

from lazybench.core.node import DAGNode, RootNode
from lazybench.core.tree import TreeNav
@pytest.fixture
def restore_prompter():
    prior = Prompter._instance
    yield
    Prompter._instance = prior

def construct_matrix(cls, **param_options):
    """Cartesian product every combo of `param_options` (param name -> list
    of candidate values), constructing `cls(**combo)` for each. Never raises
    -- each combo's outcome (the built instance, or whatever exception it
    raised) is captured, so one broken combo can't hide the rest of the
    matrix. Returns a list of (combo_dict, outcome) pairs.
    """
    names = list(param_options.keys())
    results = []
    for values in itertools.product(*param_options.values()):
        _values = []
        for v in values:
            if callable(v):
                _values.append(v())
            else:
                _values.append(v)
        combo = dict(zip(names, _values))
        try:
            outcome = cls(**combo)
        except Exception as e:
            outcome = e
        results.append((combo, outcome))
    return results


def strings_in_exception(exc, *strings):
    """Assert every string in `strings` appears in str(exc.value) -- for
    checking `pytest.raises(...) as exc` results without falling into
    regex/match pitfalls (unescaped literals, order-dependent .*)."""
    msg = str(exc.value)
    Prompter.log(f'[EXC Scan]: {msg}')
    for s in strings:
        assert s in msg


@pytest.fixture
def root_node():
    root = None
    try:
        root = RootNode()
        tree = TreeNav()
        yield root
    finally:
        if root is not None:
            try:
                root.kill_node()
                RootNode._singleton = None
                TreeNav._singleton = None
            except Exception as e:
                Prompter.log(f'Root Node Destroy raised: {e}')
                RootNode._singleton = None
                TreeNav._singleton = None
        else:
            RootNode._singleton = None
            TreeNav._singleton = None

