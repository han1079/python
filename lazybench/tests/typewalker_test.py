from typing import Optional, Union

import pytest

from lazybench.core.typewalker import TypeTree, prompt_for_type
from lazybench.app.ux.prompter import Prompter, CannedPrompter

_TYPE = dict[
    Union[
        Optional[
            tuple[
                frozenset[Union[float, tuple[Union[str, int]], Optional[int]]],
                int,
            ]
        ],
        str | None,
    ],
    str | None,
]




def test_full_transcript_replay_up_to_dictval(restore_prompter):
    canned = CannedPrompter(
        text=[
            '1',         # ['dict'] nelem
            '2',         # [DictKey]['tuple'] nelem
            '1',         # [DictKey]['tuple']['frozenset'] nelem, round 1
            '2.3',       # frozenset round1 el1: float value
            '1',         # [DictKey]['tuple'] int slot (round 1)
            '3',         # [DictKey]['tuple']['frozenset'] nelem, round 2
            '1',         # frozenset round2 el1: int value
            '2',         # nested tuple (frozenset round2 el3) nelem
            'fdff',      # nested tuple el1: str value
            '1',         # nested tuple el2: int value
            '4',         # [DictKey]['tuple'] int slot (round 2)
            'demo_val',  # [DictVal]: str value
        ],
        confirm=[
            True,   # [DictKey] optional: tuple/str -> proceed
            True,   # frozenset round1 el1: proceed
            True,   # frozenset round2 el1: proceed
            False,  # frozenset round2 el2: done (element -> None)
            True,   # frozenset round2 el3: proceed
            True,   # [DictVal] optional: proceed
        ],
        select=[
            'tuple',  # [DictKey]: tuple
            'float',  # frozenset round1 el1
            'int',    # frozenset round2 el1
            'tuple',  # frozenset round2 el3
            'str',    # nested tuple el1
            'int',    # nested tuple el2
            'str',    # [DictVal] -- live session got `None` here instead
        ],
    )
    Prompter.set(canned)

    result = prompt_for_type(_TYPE)

    assert canned.remaining() == {'text': 0, 'confirm': 0, 'select': 0}
    assert len(result) == 1
    ((key, val),) = result.items()
    assert val == 'demo_val'


def test_select_returning_none_crashes_handle_union(restore_prompter):
    class NoneSelectPrompter(CannedPrompter):
        """Mimics the live glitch: select() returns None regardless of the
        choices it was handed."""

        def select(self, prompt: str, choices):
            self.prompt_calls.append(('select', prompt))
            return None

    Prompter.set(NoneSelectPrompter(confirm=[True]))

    with pytest.raises(Exception, match="expected Callable"):
        TypeTree(str | None).prompt_cb()
