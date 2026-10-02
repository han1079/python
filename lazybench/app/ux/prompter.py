import dataclasses
import enum
import logging
from typing import Optional, Protocol, Union
from InquirerPy import inquirer
from InquirerPy.utils import color_print
from InquirerPy.base.control import Choice
from InquirerPy.validator import EmptyInputValidator

_YES_NO_MENU = ['No', 'Yes']            # index 0 = False, index 1 = True
_Y_N_MENU = ['N', 'Y']
_ON_OFF_MENU = ['Off', 'On']
_TRUE_FALSE_MENU = ['False', 'True']
_T_F_MENU = ['F', 'T']
_CONTINUE_MENU = ['No/Done', 'Yes/Proceed']

_ALL_MENUS = [
    _YES_NO_MENU, _Y_N_MENU, _ON_OFF_MENU,
    _TRUE_FALSE_MENU, _T_F_MENU, _CONTINUE_MENU,
]

_ALL_FALSES = list(set(
    e for menu in _ALL_MENUS
    for e in [menu[False], menu[False].upper(), menu[False].lower()]
))
_ALL_TRUES = list(set(
    e for menu in _ALL_MENUS
    for e in [menu[True], menu[True].upper(), menu[True].lower()]
))


class ConfirmType(enum.Enum):
    """Which confirm-mode the concrete Prompter should render:
      DEFAULT — native yes/no dialog
      TEXT    — free-text input parsed against ConfirmMatch vocab
      *_MENU  — select-from-choices variants (Yes/No, On/Off, T/F, ...)"""
    DEFAULT = None
    TEXT = [_ALL_TRUES, _ALL_FALSES]
    CONTINUE = _CONTINUE_MENU
    YES_NO = _YES_NO_MENU
    Y_N = _Y_N_MENU
    ON_OFF = _ON_OFF_MENU
    TRUE_FALSE = _TRUE_FALSE_MENU
    T_F = _T_F_MENU

class OperatorCancelled(Exception):
    """Raised by a Prompter when the operator cancels an input flow. Bubbles
    up through prompt_for so the caller can abort the enclosing menu step."""

@dataclasses.dataclass(frozen=True)
class ConfirmMatch:
    """String vocab a text-confirm should accept as True/False."""
    TRUE_STR = _ALL_TRUES
    FALSE_STR = _ALL_FALSES
class _PrompterMeta(type):
    def __getattr__(cls, name):
        return getattr(cls.get(), name)

class Prompter(metaclass = _PrompterMeta):
    _instance: Optional['PrompterBase'] = None

    @classmethod
    def get(cls) -> 'PrompterBase':
        if cls._instance is None:
            raise RuntimeError("No Prompter Initialized")
        return cls._instance

    @classmethod
    def set(cls, prompter: 'PrompterBase') -> None:
        cls._instance = prompter

class PrompterBase(Protocol):
    def text(
        self, prompt: str, result_cast: type, default: str = '',
    ) -> object: ...

    def confirm(
        self, prompt: str,
        confirm_type: ConfirmType = ConfirmType.DEFAULT,
        default: bool = True,
    ) -> bool: ...

    def select(self, prompt: str, choices: list) -> object: ...

    def log(self, prompt: object) -> None: ...

class CannedPrompter:
    """Pre-programmed Prompter. Answers are popped in submission order."""

    def __init__(self, text=(), confirm=(), select=()):
        self._text = list(text)
        self._confirm = list(confirm)
        self._select = list(select)
        self.log_calls: list[object] = []
        # (method_name, prompt) trace for debugging exhaustion errors.
        self.prompt_calls: list[tuple[str, str]] = []

    # ── Prompter Protocol methods ──────────────────────────────────────────
    def add_text(self, text: str):
        self._text.append(text)

    def add_confirm(self, confirm: bool):
        self._confirm.append(confirm)

    def add_select(self, select: int):
        self._select.append(select)

    def text(self, prompt: str, result_cast: type, default: str = ''):
        self.prompt_calls.append(('text', prompt))
        if not self._text:
            raise IndexError(
                f'CannedPrompter: text queue exhausted at prompt {prompt!r}',
            )
        raw = self._text.pop(0)
        # Empty raw + explicit default → mirror InquirerPrompter behavior.
        if raw == '' and default is not None:
            return default
        if result_cast is bool:
            if isinstance(raw, bool):
                return raw
            return str(raw).lower() in ('true', '1', 'y', 'yes')
        # Already-casted values pass through untouched.
        if isinstance(raw, result_cast):
            return raw
        return result_cast(raw)

    def confirm(
        self, prompt: str,
        confirm_type: ConfirmType = ConfirmType.DEFAULT,
        default: bool = True,
    ) -> bool:
        self.prompt_calls.append(('confirm', prompt))
        if not self._confirm:
            raise IndexError(
                f'CannedPrompter: confirm queue exhausted at prompt {prompt!r}',
            )
        return bool(self._confirm.pop(0))

    def select(self, prompt: str, choices: list):
        self.prompt_calls.append(('select', prompt))
        if not self._select:
            raise IndexError(
                f'CannedPrompter: select queue exhausted at prompt {prompt!r} '
                f'(choices were {choices!r})',
            )
        return choices[self._select.pop(0)]

    def log(self, prompt: object) -> None:
        self.log_calls.append(prompt)

    # ── Debug helpers ──────────────────────────────────────────────────────

    def remaining(self) -> dict:
        """How many answers are unused per queue. Useful in test asserts."""
        return {
            'text': len(self._text),
            'confirm': len(self._confirm),
            'select': len(self._select),
        }



PROMPT = 25
logging.addLevelName(PROMPT, 'PROMPT')

def default_confirm(message: str, default: bool) -> bool:
    return inquirer.confirm(message=message, default=default).execute()


def menu_confirm(
    message: str, default: bool, choices=None,
) -> bool:
    """Select-from-choices confirm. `choices` = [false_label, true_label]."""
    choices = list(choices or ConfirmType.YES_NO.value)
    default_sel = choices[default]

    # Reorder so the default lands on top of the select list.
    displayed_choices = (
        [choices[1], choices[0]] if default else list(choices)
    )

    if 'CANCEL' not in choices:
        choices.append('CANCEL')
        displayed_choices.append('CANCEL')

    result = inquirer.select(
        message=message, choices=displayed_choices, default=default_sel,
    ).execute()

    if result == choices[True]:
        return True
    if result == choices[False]:
        return False
    raise OperatorCancelled('Cancelled Menu Confirm')


def text_confirm(message: str, default: bool = False) -> bool:
    """Free-text confirm — accepts any variant in the True/False vocabulary."""
    default_str = 'Yes' if default else 'No'
    raw = inquirer.text(
        message=f'{message} (Yes/No)?', default=default_str,
    ).execute()

    if raw in ConfirmMatch.TRUE_STR:
        return True
    if raw in ConfirmMatch.FALSE_STR:
        return False
    raise OperatorCancelled('Not a valid input. Ignoring.')


class InquirerPrompter:
    """Concrete implementation of the `Prompter` Protocol using InquirerPy."""
    _singleton: 'Optional[InquirerPrompter]' = None

    def __init__(self, logger_name: str = 'lazybench.prompter'):
        # Stable public name, deliberately not __name__ -- SessionLogger
        # depends on this exact name to always-on-capture Prompter.log
        # regardless of level (it forces this logger's level to DEBUG so
        # root's default level can't silently no-op the .info() call below).
        self._logger = logging.getLogger(logger_name)

    def _confirm_fn(self, confirm_type: ConfirmType):
        if confirm_type == ConfirmType.DEFAULT:
            return default_confirm
        if confirm_type == ConfirmType.TEXT:
            return text_confirm

        def wrapped(message: str, default: bool):
            return menu_confirm(message, default, confirm_type.value)
        return wrapped

    @classmethod
    def get_prompter(cls):
        return Prompter.get()

    # ── Prompter Protocol methods ──────────────────────────────────────────

    def text(
        self, prompt: str, result_cast: type, default: str = '',
    ) -> object:
        try:
            raw = inquirer.text(
                message=(
                    f'{prompt} '
                    f'({getattr(result_cast, "__name__", str(result_cast))})'
                ),
                default='' if default is None else str(default),
            ).execute()
        except KeyboardInterrupt:
            raise OperatorCancelled('Cancelled Text Input')

        if not raw and default is not None:
            return default
        if result_cast is bool:
            return raw.lower() in ('true', '1', 'y', 'yes')
        return result_cast(raw)

    def confirm(
        self, prompt: str,
        confirm_type: ConfirmType = ConfirmType.DEFAULT,
        default: bool = True,
    ) -> bool:
        try:
            return self._confirm_fn(confirm_type)(message=prompt, default=default)
        except KeyboardInterrupt:
            raise OperatorCancelled('Cancelled Y/N Prompt')

    def select(self, prompt: str, choices: Union[list, dict]) -> object:
        # Fuzzy search — type-ahead filter for long lists; arrow keys for short.
        if 'CANCEL' not in choices:
            if isinstance(choices, list):
                choices.append('CANCEL')
            elif isinstance(choices, dict):
                choices['CANCEL'] = 'CANCEL'

        if isinstance(choices, list):
            choices = [Choice(value=c) for c in choices]
        elif isinstance(choices, dict):
            choices = [Choice(value=v, name=k) for k,v in choices.items()]

        try:
            result = inquirer.fuzzy(
                message=prompt, choices=choices,
            ).execute()
        except KeyboardInterrupt:
            raise OperatorCancelled('Cancelled Menu Prompt')

        if result == 'CANCEL':
            raise OperatorCancelled('Cancelled Input')
        return result

    def log(self, prompt: object) -> None:
        if isinstance(prompt, str):
            message = prompt
        elif isinstance(prompt, list):
            message = '\n'.join(str(p) for p in prompt)
        else:
            message = str(prompt)
        self._logger.log(PROMPT, message)
