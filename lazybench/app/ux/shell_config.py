import importlib.machinery
import importlib.util
import os
import sys

# Import token unconditionally grabs the wrong module
_stdlib_dir = os.path.dirname(os.__file__)
_spec = importlib.machinery.PathFinder.find_spec('token', [_stdlib_dir])
_real_token = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_real_token)
sys.modules['token'] = _real_token

from prompt_toolkit import Application
import prompt_toolkit
import io
import contextlib
import subprocess
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion as PTCompletion
from prompt_toolkit.document import Document
from prompt_toolkit.history import History
from prompt_toolkit.layout import Float, FloatContainer, Layout, HSplit, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.menus import CompletionsMenu
from prompt_toolkit.layout.processors import AppendAutoSuggestion
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.filters import Condition, has_focus
from prompt_toolkit.key_binding import ConditionalKeyBindings, KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.bindings.auto_suggest import load_auto_suggest_bindings
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.mouse_events import MouseEventType
from prompt_toolkit.widgets import HorizontalLine, VerticalLine
from prompt_toolkit.application.current import get_app
from pygments.lexers.python import PythonLexer
from IPython.core.completer import provisionalcompleter
from IPython.terminal import interactiveshell


class FocusableTextControl(FormattedTextControl):
    """FormattedTextControl always returns NotImplemented from its own
    mouse_handler unless a fragment carries its own per-fragment handler --
    it has no built-in click-to-focus the way BufferControl does. Mirror
    BufferControl's own pattern (get_app().layout.current_control = self on
    MOUSE_UP) so clicking anywhere on this control's Window focuses it."""

    def mouse_handler(self, mouse_event):
        if mouse_event.event_type == MouseEventType.MOUSE_UP:
            get_app().layout.focus(self)
            return None
        return super().mouse_handler(mouse_event)


class LogTextControl(FocusableTextControl):
    """FormattedTextControl has no real cursor, so Window's built-in wheel
    handler (which nudges vertical_scroll directly) is useless here --
    Window._scroll() unconditionally re-centers the viewport on
    cursor_position every frame (containers.py:1766, no focus check), so
    any manual vertical_scroll change is overwritten on the very next
    render. Drive cursor_position ourselves instead: unpin_log.scroll_line
    *is* our fake cursor row, moved one line per wheel tick; render_log()
    plants [SetCursorPosition] there and Window's normal cursor-follow
    logic does the scrolling for us."""

    def mouse_handler(self, mouse_event):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            scroll_log_up()
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            scroll_log_down()
            return None
        return super().mouse_handler(mouse_event)


class HistoryScrollBufferControl(BufferControl):
    """Scroll wheel over the input pane pages through command history
    instead of scrolling the (1-2 line) viewport -- intercept SCROLL_UP/
    SCROLL_DOWN before they fall through to Window's default
    viewport-scroll behavior."""

    def mouse_handler(self, mouse_event):
        if mouse_event.event_type == MouseEventType.SCROLL_UP:
            self.buffer.history_backward()
            return None
        if mouse_event.event_type == MouseEventType.SCROLL_DOWN:
            self.buffer.history_forward()
            return None
        return super().mouse_handler(mouse_event)

class FakeChild:
    def __init__(self, idx):
        self.name = f'child_{idx}'
        self.parent = 'root'

class FakeRoot:
    def __init__(self):
        self.name = 'root'
        self.child = [FakeChild(1), FakeChild(2)]
ns = {}
ns['root'] = FakeRoot()

class ShellCompleter(Completer):
    """Adapts IPCompleter.completions() (start/end offsets into the whole
    buffer text, IPython's own Completion type) to prompt_toolkit's
    Completer protocol (start_position relative to the cursor, its own
    Completion type)."""

    def get_completions(self, document, complete_event):
        # provisionalcompleter() is the documented, 
        # required wrapper (completer.py:302-331).
        offset = document.cursor_position
        with provisionalcompleter():
            for c in shell.Completer.completions(document.text, offset):
                yield PTCompletion(
                    text=c.text,
                    start_position=c.start - offset,
                    display_meta=c.type or '',
                )

class IPythonHistory(History):
    def load_history_strings(self):
        tail = shell.history_manager.get_tail(1000, include_latest=True)
        return [text for _session, _line, text in reversed(list(tail)) if text.strip()]

    def store_string(self, string: str) -> None:
        pass

kb = KeyBindings()
@kb.add('c-c')
def _(event): event.app.exit()

# focus_next/focus_previous just walk find_all_windows() in flat traversal
# order -- no notion of the layout's actual 2D geometry. Hand-roll a small
# state machine instead: c-left/c-right cross the outer VSplit (sidebar vs
# the log+input column), c-up/c-down cross the inner HSplit (log vs input
# within that column). last_right_pane remembers which of the two you were
# in last, so c-right back out of the sidebar returns you to the same row
# instead of always landing on log.
def pane_state(): pass
pane_state.last_right = None  # set to log_control on first use (below)

@kb.add('c-left')
def _(event):
    cc = get_app().layout.current_control
    if cc in (log_control, input_control):
        pane_state.last_right = cc
        get_app().layout.focus(sidebar_control)

@kb.add('c-right')
def _(event):
    if get_app().layout.current_control is sidebar_control:
        get_app().layout.focus(pane_state.last_right or log_control)

@kb.add('c-down')
def _(event):
    if get_app().layout.current_control is log_control:
        pane_state.last_right = input_control
        get_app().layout.focus(input_control)

@kb.add('c-up')
def _(event):
    if get_app().layout.current_control is input_control:
        pane_state.last_right = log_control
        get_app().layout.focus(log_control)

@kb.add('tab')
def _(event):
    buf = event.current_buffer
    if buf.complete_state:
        buf.complete_next()
    else:
        buf.start_completion(select_first=False)

@kb.add('enter')
def _(event):
    buf = event.current_buffer
    status, indent = shell.input_transformer_manager.check_complete(buf.text)
    if status == 'incomplete':
        buf.insert_text('\n' + ' ' * (indent or 0))
    else:
        buf.validate_and_handle()

# Only active while the log pane has focus (see the has_focus(log_control)
# wrap at Application construction) -- otherwise up/down would steal the
# input buffer's own history navigation.
focus_kb = KeyBindings()

@focus_kb.add('up')
def _(event):
    scroll_log_up()

@focus_kb.add('down')
def _(event):
    scroll_log_down()

# Vim's own "V" mnemonic (visual LINE mode) -- first V drops an anchor at
# the current line, up/down (above) extend the range, second V commits it
# to the system clipboard (via xclip -- see xclip_copy) and clears the
# anchor.
@focus_kb.add('V')
def _(event):
    toggle_capture()

capturing = Condition(lambda: toggle_capture.active)

# Only meaningful once V has dropped an anchor -- trims the moving end of
# the range to a column within its line instead of the whole line. See
# move_log_cursor()'s docstring for how the untouched (untrimmed) default
# is chosen.
@focus_kb.add('left', filter=capturing)
def _(event):
    move_log_cursor(-1)

@focus_kb.add('right', filter=capturing)
def _(event):
    move_log_cursor(1)

__log_text = ''

def unpin_log() -> None:
    unpin_log.pinned = False

unpin_log.pinned = True
unpin_log.scroll_line = 0  # fake cursor row -- see LogTextControl docstring
unpin_log.line_count = 1
unpin_log.scroll_col = 0
unpin_log.col_trimmed = False  # has move_log_cursor() set an explicit column?

def scroll_log_up() -> None:
    unpin_log()
    unpin_log.scroll_line = max(0, unpin_log.scroll_line - 1)
    unpin_log.col_trimmed = False  # new line -- any prior column trim is stale

def scroll_log_down() -> None:
    unpin_log.scroll_line = min(unpin_log.line_count - 1, unpin_log.scroll_line + 1)
    if unpin_log.scroll_line >= unpin_log.line_count - 1:
        unpin_log.pinned = True
    unpin_log.col_trimmed = False

def move_log_cursor(delta: int) -> None:
    # The anchor (see toggle_capture) never trims -- it always contributes
    # a whole line to whichever side of the range it ends up on. The
    # moving point (this function) is the only one Left/Right can trim,
    # and only when explicitly used: untouched, its default column is
    # "whole line" too, chosen by which topological role it's currently
    # playing -- end-of-line if it's below-or-equal to the anchor (the
    # range extends downward, so this line is the range's END and an
    # untrimmed end means "through the end of the line"), else
    # start-of-line (0). Matches _capture_bounds()'s own s_line/e_line
    # assignment exactly, so the first Left/Right press narrows from
    # wherever the whole-line highlight was already showing, not from 0.
    lines = __log_text.split('\n')
    line_idx = max(0, min(unpin_log.scroll_line, len(lines) - 1))
    line = lines[line_idx]
    if unpin_log.col_trimmed:
        col = unpin_log.scroll_col
    else:
        col = len(line) if toggle_capture.anchor <= line_idx else 0
    unpin_log.scroll_col = max(0, min(len(line), col + delta))
    unpin_log.col_trimmed = True

def _capture_bounds(lines):
    """(start_line, start_col, end_line, end_col) for the active capture,
    or None if not capturing. See move_log_cursor()'s docstring for why
    the untrimmed defaults are chosen the way they are."""
    if not toggle_capture.active:
        return None
    anchor_line = max(0, min(toggle_capture.anchor, len(lines) - 1))
    cur_line = max(0, min(unpin_log.scroll_line, len(lines) - 1))
    if anchor_line <= cur_line:
        s_line, e_line = anchor_line, cur_line
        s_col = 0
        e_col = unpin_log.scroll_col if unpin_log.col_trimmed else len(lines[cur_line])
    else:
        s_line, e_line = cur_line, anchor_line
        s_col = unpin_log.scroll_col if unpin_log.col_trimmed else 0
        e_col = len(lines[anchor_line])
    return s_line, s_col, e_line, e_col

def toggle_capture() -> None:
    if toggle_capture.active:
        lines = __log_text.split('\n')
        s_line, s_col, e_line, e_col = _capture_bounds(lines)
        selected = [
            lines[i][s_col if i == s_line else 0:e_col if i == e_line else len(lines[i])]
            for i in range(s_line, e_line + 1)
        ]
        xclip_copy('\n'.join(selected))
        toggle_capture.active = False
    else:
        toggle_capture.active = True
        toggle_capture.anchor = unpin_log.scroll_line
    unpin_log.col_trimmed = False

toggle_capture.active = False
toggle_capture.anchor = 0

def xclip_copy(text: str) -> None:
    # Bypasses tmux/terminal escape-sequence relaying entirely -- talks to
    # the X11 clipboard selection directly via a subprocess. Requires a
    # local X/Wayland session; the OSC 52 route (the tmux/terminal-relay
    # alternative) didn't work here because tmux's terminal-features never
    # granted this client the clipboard feature, so `set-clipboard
    # external` had nothing to relay.
    subprocess.run(
        ['xclip', '-selection', 'clipboard'],
        input=text.encode(), check=True,
    )

def append_log(text: str) -> None:
    global __log_text
    __log_text += text
    unpin_log.line_count = __log_text.count('\n') + 1
    unpin_log.pinned = True  # new output -- snap back to the tail
    unpin_log.scroll_line = unpin_log.line_count - 1
    unpin_log.col_trimmed = False

def _style_range(fragments, lo, hi):
    """Apply an extra 'reverse' style to characters in [lo, hi) of the
    flattened fragment text, splitting fragments at the boundary as
    needed. lo >= hi is a no-op (empty range)."""
    out = []
    pos = 0
    for style, text in fragments:
        start, end = pos, pos + len(text)
        pos = end
        if lo >= hi or end <= lo or start >= hi:
            out.append((style, text))
            continue
        seg_lo, seg_hi = max(lo, start) - start, min(hi, end) - start
        if seg_lo > 0:
            out.append((style, text[:seg_lo]))
        out.append((f'{style} reverse', text[seg_lo:seg_hi]))
        if seg_hi < len(text):
            out.append((style, text[seg_hi:]))
    return out

def _insert_cursor_marker(fragments, col):
    """Insert a zero-width [SetCursorPosition] fragment at character
    offset `col` of the flattened fragment text, splitting a fragment if
    col lands inside one. col at or past the end appends it last.

    A wholly empty line renders zero fragments, so the marker would be
    the line's ONLY content -- prompt_toolkit's row/col -> screen lookup
    only registers a position while actually iterating a real character
    (containers.py copy_line, ~line 2075: `current_rowcol_to_yx[lineno,
    col] = ...` happens INSIDE the per-character loop, once per
    character) -- so registered columns only ever go up to len(text) - 1,
    NEVER len(text) itself. A marker sitting at col == len(text) -- true
    for a wholly empty line (len 0) but ALSO for the ordinary "end of a
    non-empty line" position, e.g. a fresh single-line V capture, whose
    highlighted range runs to the line's own length -- always misses
    that lookup. cursor_pos_to_screen_pos's own fallback for a missed
    lookup ("Normally this should never happen. It is a bug, if it
    happens.") silently snaps the terminal cursor to absolute screen
    (0, 0) instead of raising -- which happens to be the sidebar's
    top-left corner, so it *looks* like focus jumped there when it never
    actually moved. A trailing real placeholder character, appended
    whenever col lands at or past the line's total length, always gives
    the lookup something to register against."""
    total_len = sum(len(text) for _, text in fragments)
    out = []
    inserted = False
    remaining = col
    for style, text in fragments:
        if not inserted and remaining <= len(text):
            out.append((style, text[:remaining]))
            out.append(('[SetCursorPosition]', ''))
            if text[remaining:]:
                out.append((style, text[remaining:]))
            inserted = True
        else:
            out.append((style, text))
            remaining -= len(text)
    if not inserted:
        out.append(('[SetCursorPosition]', ''))
    if col >= total_len:
        out.append(('', ' '))
    return out

def render_log():
    # cursor_position defaults to (0, 0) whenever no [SetCursorPosition]
    # fragment is present, and Window._scroll() unconditionally re-centers
    # the viewport on it every frame -- so the marker's position IS the
    # scroll target, always. unpin_log.scroll_line/scroll_col track it
    # explicitly instead of leaving it implicitly pinned at (0, 0).
    lines = __log_text.split('\n')
    cur_line = max(0, min(unpin_log.scroll_line, len(lines) - 1))

    sel = _capture_bounds(lines)
    if sel is not None:
        s_line, s_col, e_line, e_col = sel
        cur_col = e_col if cur_line == e_line else s_col
    else:
        cur_col = unpin_log.scroll_col if unpin_log.col_trimmed else 0

    fragments = []
    for i, line in enumerate(lines):
        line_fragments = prompt_toolkit.formatted_text.to_formatted_text(
            prompt_toolkit.formatted_text.ANSI(line))
        if sel is not None and s_line <= i <= e_line:
            lo = s_col if i == s_line else 0
            hi = e_col if i == e_line else len(line)
            line_fragments = _style_range(line_fragments, lo, hi)
        if i == cur_line:
            line_fragments = _insert_cursor_marker(line_fragments, cur_col)
        fragments.extend(line_fragments)
        if i != len(lines) - 1:
            fragments.append(('', '\n'))
    return fragments

def on_command(buf):
    text = buf.text
    buf_out = io.StringIO()
    try:
        if text.strip() == 'exit':
            get_app().exit()
            return
        with contextlib.redirect_stdout(buf_out):
            # store_history defaults to False (checked directly against
            # source -- interactiveshell.py:3133) -- without this, nothing
            # typed here ever reaches history_manager's db (IPythonHistory
            # would only ever show history from OTHER real ipython
            # sessions) and execution_count never advances (get_input_prompt
            # would show "In [1]:" forever).
            result = shell.run_cell(text, store_history=True)
        append_log(f'>>> {text}\n{buf_out.getvalue()}\n')
    except Exception as e:
        append_log(f'>>> {text}\nERROR: {e}\n')
    return False

def render_sidebar():
    breadcrumb = 'root'
    lines = [('class:breadcrumb', f'{breadcrumb}\n')]
    for child in ns['root'].child:
        lines.append(('', f' {child.name}\n'))
    return lines

def get_input_prompt(lineno, wrap_count):
    primary = f'In [{shell.execution_count}]: '
    if lineno == 0:
        return [('class:prompt', primary)]
    # Right-align '...: ' under the primary prompt, same width, matching
    # real IPython's own continuation-line look.
    pad = max(0, len(primary) - len('...: '))
    return [('class:prompt', ' ' * pad + '...: ')]

input_buffer = Buffer(
    multiline=True, accept_handler=on_command,
    completer=ShellCompleter(), complete_while_typing=False,
    history=IPythonHistory(), auto_suggest=AutoSuggestFromHistory(),
)

input_control = HistoryScrollBufferControl(
    buffer=input_buffer, focus_on_click=True,
    lexer=PygmentsLexer(PythonLexer),
    # BufferControl doesn't render buffer.suggestion on its own --
    # AppendAutoSuggestion is the processor that actually appends
    # it as a class:auto-suggestion fragment (layout/processors.py
    # ~574). That style class itself needs no setup on our end:
    # Application always merges default_ui_style() in regardless
    # of what `style=` it's given (application.py
    # _create_merged_style), and default_ui_style already maps
    # class:auto-suggestion to a dim grey -- same reason the
    # PygmentsLexer above needs no explicit style either
    # (default_pygments_style() is merged in the same way).
    input_processors=[AppendAutoSuggestion()],
)

input_window = FloatContainer(
    Window(
        input_control,
        wrap_lines=True, height=2, get_line_prefix=get_input_prompt,
    ),
    [
        Float(
            xcursor=True, ycursor=True, transparent=True,
            content=CompletionsMenu(max_height=8, scroll_offset=1),
        ),
    ],
)

log_control = LogTextControl(render_log, focusable=True)
sidebar_control = FocusableTextControl(render_sidebar, focusable=True)

body = VSplit([
    Window(sidebar_control, width=24),
    VerticalLine(),
    HSplit([
        Window(log_control, wrap_lines=True),
        HorizontalLine(),
        input_window,
        ]),
    ])

app = Application(
    layout=Layout(body, focused_element=input_buffer),
    key_bindings=merge_key_bindings([
        load_key_bindings(), load_auto_suggest_bindings(), kb,
        ConditionalKeyBindings(focus_kb, has_focus(log_control)),
    ]),
    full_screen=True, mouse_support=True,
)

ns['panes'] = body
ns['app'] = app
shell = interactiveshell.InteractiveShell.instance(user_ns=ns)

if __name__ == "__main__":
    app.run()
