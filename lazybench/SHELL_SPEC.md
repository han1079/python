# lazybench shell — design spec

Status: design only. Nothing in this doc is implemented yet; `app/ux/shell_config.py`
as it currently stands predates this redesign. Parking this file at the top of
`lazybench/` for now — expected to move when the shell is broken out into its
own package.

## Goals / constraints

- **Maximal portability.** `pip install <shell-pkg>`; a single file does
  `import <shell-pkg> as shell; shell.run()`; `python my_file.py` pops up the
  TUI with no setup. No compiled extensions, no platform assumptions (X11,
  specific terminal emulator, tmux) baked into the hard path.
- **Minimal dependency footprint.** Every dependency questioned against this
  goal explicitly (see Dependencies section) — nothing gets pulled in because
  a nicer library happened to exist.
- **Minimal keybinding surface.** Pane navigation, `Enter`, `Ctrl+Enter`, `V`
  are the only "new" gestures a user has to learn. Everything else reuses
  normal navigation.
- **Terminal ergonomics, not Jupyter ergonomics.** Exactly one execution
  authority exists in the whole system (the Shell pane). This is what avoids
  Jupyter's classic out-of-order-execution confusion — cells/history can
  never desync from actual execution order because there's only one order.

## Layout

```
VSplit[
  Sidebar,
  HSplit[
    TopBar,
    DynamicContainer(-> LogEntry's current display-mode window),
    DynamicContainer(-> Shell's current sub-mode window: executor | editor | prompter),
    BottomBar,
  ],
]
```

- **Sidebar** — Namespace tree (DAGNode/TreeNav-backed) + directly-accessible
  variables. File-navigator style: `Enter` expands in place, `Ctrl+Enter`
  actually moves `TreeNav` (see Sidebar section).
- **TopBar** — LogEntry's 3 display-mode picker (history / log / blend).
- **LogEntry** — the transcript + notebook-cell region.
- **Shell** — the command-entry pane; swaps between executor / text-editor /
  prompter sub-modes.
- **BottomBar** — vim-motion on/off toggle + live editing-mode indicator.

Both `DynamicContainer` slots use the same prompt_toolkit primitive
(`layout.containers.DynamicContainer(get_container)`, re-invoked every
render) — one mechanism, reused twice, not two different things.

## Minimal prompt_toolkit subset to build on

Out of the full API surface, only these matter for this design:

- `Container` — universal layout interface (`write_to_screen`,
  `preferred_width/height`, `reset`). `HSplit`/`VSplit`/`FloatContainer`
  implement it; `AnyContainer` also accepts anything with
  `__pt_container__() -> Container`.
- `Window` — a `Container` that renders exactly one `UIControl`. Owns sizing
  (`width`/`height` accept int, `Dimension`, or a zero-arg callable
  re-resolved every render — this is what makes drag-resize mechanical),
  scrolling, wrap, `get_line_prefix`.
- `UIControl` — the "what," deliberately split from `Window`'s "where/how
  big." Two methods matter: `create_content()`, `mouse_handler()`.
  `FormattedTextControl` (static/computed fragments) and `BufferControl`
  (backed by a `Buffer`) are the two flavors in play.
- `Buffer`/`BufferControl`/`Lexer` — pure text-editing model, zero rendering
  awareness. Only the Shell pane and notebook cells touch this; reuse
  wholesale, never reimplement.
- `Layout`/`Application` — exactly one of each, owned by `Coordinator`.
  `Layout.focus(x)` accepts a `Container`, `Window`, `UIControl`, buffer
  name, **or a bare `Buffer`** — reuse this instead of hand-rolling focus
  tracking wherever a real `Buffer` already exists (cell focus, Prompter's
  text sub-mode).
- `Float`/`FloatContainer` — not part of the `Pane` hierarchy. Positioning
  descriptor + two-pass (base then floats) draw surface; only used for the
  completion popup.
- `ScrollablePane` — wraps one content `Container` (an `HSplit` of many
  sub-windows) as a single continuous scrollable region, with
  `keep_focused_window_visible`/`keep_cursor_visible`. This is what makes
  "hold up drifts across cell/output boundaries" work — see Notebook-cell
  model.

## Class model

### `Coordinator` (one instance)

Owns everything that spans more than one pane:

- `layout: Layout`, `application: Application`
- focus routing: current focus, `last_right` (which right-column pane to
  return to from the sidebar)
- drag-resize state: dragging flag, active separator/pane, size holder(s)
- `scrollable_pane: ScrollablePane` wrapping the interleaved LogEntry/cell
  region
- `_injected_names: set[str]` — exactly which shell-namespace keys
  Coordinator injected last, so a namespace "swap" can remove precisely
  those without touching IPython/runtime-owned keys
- pending-prompt bridging state (see Prompter section)

### `PaneMixin` (thin — essentially just a dataclass)

Across the three original pane species there is **zero field overlap** —
LogPane's state shares nothing with SidebarPane's, which shares nothing with
Shell's. So the common base only needs a `coordinator` back-reference (and
maybe a `window` reference). Not literally inert, though: there's one shared
*behavior* — "if `coordinator` is mid-drag on my border, defer this
`mouse_handler` call to it" — so it's a small dataclass plus at least one
shared method, not zero methods.

Mixed via multiple inheritance with whatever prompt_toolkit control type each
pane actually needs, e.g. `class LogPane(PaneMixin, FormattedTextControl)` —
prompt_toolkit dispatches by calling methods on the control object directly,
so something has to really be a `UIControl`/`BufferControl` subclass; a
wrapper-owns-a-control shape would add indirection with no current consumer.
Concrete panes need their own hand-written `__init__` regardless (chaining
into `FormattedTextControl.__init__`/`BufferControl.__init__`'s own real
state), so `@dataclass`'s main convenience mostly doesn't apply once mixed in.

### Per-species state

**LogPane**
- `entries: list[LogEntry]` where `LogEntry = {kind: 'command'|'output', text, execution_count}`
  (replaces the old flat `__log_text` string — required for display modes)
- `pinned`, `scroll_line`, `scroll_col`, `col_trimmed`, `line_count`
- `capturing`, `capture_anchor` (V-mode selection)
- `display_mode: Literal['history', 'log', 'blend']`

**SidebarPane**
- `cursor_path: tuple[str, ...]` — where the interaction cursor sits (not a
  flat sibling index; rows now span multiple depths at once)
- `expanded_paths: set[tuple[str, ...]]` — which nodes are disclosed
- item kinds when rendering: `header` (plaintext, e.g. "Namespace") /
  `dagnode` (real tree children). No `mode-option` kind — display-mode
  picking moved to TopBar (superseding the earlier "sidebar as dual
  selector" idea).

**Shell**
- `buffer: Buffer`
- `history` — `prompt_toolkit.history.FileHistory`, not IPython's history manager
- `completer` — user's own `jedi`-backed `Completer`, not IPython's
- own execution state: a persistent `dict` namespace + `execution_count` int
  (replaces `IPython.terminal.interactiveshell.InteractiveShell` — see
  Dependencies)
- `mode: Literal['executor', 'editor', 'prompter']`

**Cell** (notebook region, distinct from LogPane — see below)
- `buffer: Buffer`
- `last_run_text: str | None` — dirty indicator is `buffer.text != last_run_text`,
  no separate flag needed

## Navigation model

- `TreeNav` (existing, unchanged) is the *only* thing that swaps the shell
  namespace / moves "cwd." Invoked exclusively by `Ctrl+Enter`.
- Plain `Enter` in the Sidebar only mutates local `expanded_paths`/
  `cursor_path` — never touches `TreeNav`, never touches the shell namespace.
- Namespace swap: `TreeNav.down(name)`/`.up()` return a `TreeNodeHandle`;
  `TreeNodeHandle._children` already gives `{name: TreeNodeHandle}` for the
  new position. Coordinator diffs against `_injected_names`, removes the old
  set, injects the new one — a true swap, never a merge.
- Auto-collapse: on cursor move, collapse any `expanded_paths` entry that
  isn't an ancestor of the new `cursor_path` (standard accordion pattern).
  This is what keeps an unbounded "local variables" subtree from taking over
  the screen, without a separate mechanism.
- Cross-block scroll continuity ("hold up drifts across a cell/output
  boundary") is owned by the `ScrollablePane`, not by any individual pane's
  cursor state. `Ctrl+Up` to jump to the previous block: move focus to that
  block's window/buffer and let `keep_focused_window_visible` do the
  scrolling — no manual offset math.
- Rejected: live "hold Ctrl → highlight all options green" preview.
  Confirmed against this prompt_toolkit's input layer — no key-hold/release
  events exist, only discrete completed keystrokes (no Kitty-protocol
  support here). If the discoverability goal still matters, use a static
  per-row marker or an explicit discrete preview-toggle key instead.

## Notebook-cell model

Two distinct structures, not one — don't subdivide `LogPane` into chunks:

1. **LogPane/transcript** — stays append-only, unchanged in kind (just
   tagged `entries` now instead of a flat string, per display modes above).
2. **CellPane** — `cells: list[Cell]`, freely editable in place, no
   execution state of its own beyond `last_run_text`.

Cells are never independent execution contexts. `Ctrl+Enter`(or the agreed
"send to shell" gesture) on a focused cell copies `cell.buffer.text` into
Shell's *existing* execution path — the same one manual typing uses — then
sets `cell.last_run_text`. This is the whole mechanism that avoids Jupyter's
out-of-order confusion: there is exactly one execution authority/history in
the system; a cell is only ever a saved draft that writes into it on demand.

- Cell focus reuses `Layout.focus(cell.buffer)` directly — no custom
  cursor-index needed, unlike Sidebar (cells are real focusable `Buffer`s).
- Rendering: `Window(BufferControl(buffer=cell.buffer))` per cell, stacked in
  an `HSplit`, the whole thing wrapped in the `ScrollablePane`. `Enter`
  inside a cell always inserts a newline (no `check_complete`-style
  statement-completeness detection — a cell is a persistent multi-line
  block, not a REPL line).
- Focus indicator: `Window(style=lambda: 'class:cell-focused' if <has focus>
  else 'class:cell')` — a plain conditional-style callable, no bespoke
  mechanism needed.
- Extraction to a real file falls out for free: `'\n\n'.join(c.buffer.text
  for c in cells)`, since cell content is always real `Buffer.text`.

## LogPane display modes

Solves the "where does print spam go" problem without a separate filter UI —
just a render-time filter over `entries`:

- **history** — command/cell-source entries only.
- **log** — output entries only.
- **blend** — interleaved, current/default look (matches today's `>>> cmd\noutput`).

Toggle lives in **TopBar**, reached by normal pane navigation + `Enter` (not
in the Sidebar — see Navigation model).

## Shell sub-modes

Same `DynamicContainer` mechanism as LogPane's display modes.

- **executor** — current behavior: `Enter` checks statement completeness
  (via stdlib `codeop.compile_command`, replacing IPython's
  `input_transformer_manager.check_complete`) and either inserts a newline or
  executes.
- **editor** — `Enter` always inserts a newline. For editing a full function
  body without execution semantics fighting the cursor.
- **prompter** — Shell temporarily becomes the rolled-own Prompter UI. Fired
  when `Prompter.text()/confirm()/select()` is called from synchronous DAG
  code elsewhere in the system.

### Prompter (replaces InquirerPy)

InquirerPy is dropped entirely — confirmed via source that `fuzzy`/`list`/
`number` prompts each construct their own `prompt_toolkit.Application`
(`self._application = Application(...)`) and block until it exits. That's
structurally incompatible with one continuous app with no modal takeovers.

- `text` sub-mode: a `Buffer`+`BufferControl`, "answer once, then close" —
  same shape as Shell's own executor buffer.
- `select`/`confirm` sub-mode: the selectable-row-list primitive (see below)
  + a query `Buffer` for fuzzyfind, re-filtered on every keystroke via
  `pfzy.fuzzy_match`/`fzy_scorer` — the actual matching library InquirerPy
  itself depends on, used directly instead of through InquirerPy's UI shell.
- Sync/async bridge: DAG code calling `Prompter.text()` etc. runs on a
  background thread; the call blocks that thread on a `threading.Event`/
  `concurrent.futures.Future` that Coordinator resolves from the main
  asyncio loop once the user answers via Shell's prompter sub-mode. This is
  the one piece of real, non-reused design work — everything else here is
  composition of existing pieces.

## Vim motions

Not built from scratch. prompt_toolkit already ships a complete Vi emulation
layer (`key_binding/bindings/vi.py`, ~2233 lines: navigation, insert,
visual/visual-line/visual-block, delete/yank/change with real text objects),
already loaded by `load_key_bindings()` (already called in the current
`shell_config.py`), gated by `Application.editing_mode`.

- BottomBar's toggle just flips `Application.editing_mode` between `EMACS`
  and `VI`.
- BottomBar's render reads `get_app().vi_state.input_mode` live every frame
  for a real `-- INSERT --`/`-- VISUAL --`-style indicator — same
  "read live app state in a render callable" pattern as `render_log`/
  `get_input_prompt`.
- Constraint: `editing_mode` is Application-wide, not per-buffer — affects
  Shell and every notebook cell at once, not selectively.

## Toolbars (TopBar / BottomBar)

Reached via the same hand-rolled cross-pane focus state machine already in
`shell_config.py` (explicitly not prompt_toolkit's generic
`focus_next`/`focus_previous`, which has no notion of the layout's real
geometry) — toolbars are just two more stops in that state machine.
Internally, each toolbar is the same selectable-row-list primitive, laid out
horizontally instead of vertically.

## Cross-cutting primitive: the selectable-row-list

Worth building once, generically — it's independently justified by four
different features:

- Sidebar rows (tree navigation)
- TopBar (display-mode picker)
- BottomBar (vim-mode toggle)
- Prompter's `select`/`confirm` sub-mode

Shape: an ordered list of items, a highlighted index, arrow-keys move it,
`Enter` activates the highlighted item's own callback. Orientation
(vertical/horizontal) and item source (tree children, fixed options, prompt
choices) vary; the mechanism doesn't.

## Drag-to-resize (pane borders)

- `mouse_support=True` (already set) already enables xterm any-event/drag
  tracking (modes 1000+1003+SGR) — nothing to turn on.
- `Window.width`/`height` accepting a zero-arg callable, re-resolved every
  render, is what makes live resize mechanical.
- No mouse "capture" exists in prompt_toolkit — every event (including a
  mid-drag `MOUSE_MOVE`) is independently routed by current (x, y) against a
  freshly-rendered handler grid. A naive 1-column separator `mouse_handler`
  will drop fast drags the instant the cursor crosses into a neighboring
  pane's cells.
- Needed: a custom separator control (stock `VerticalLine`/`HorizontalLine`
  have no `mouse_handler` at all) + a Coordinator-held drag flag + size
  holder; the adjacent panes' own `mouse_handler`s must check "is a drag
  active" first and defer to Coordinator before their normal click/scroll
  logic; clamp to min/max size; clear the flag on `MOUSE_UP`.

## Clipboard (V-mode copy)

Current `xclip_copy` shells out to the `xclip` binary — X11-only, and
fundamentally cannot solve "SSH'd into a remote machine, want the local
clipboard": it writes to whatever clipboard mechanism exists on the machine
the process is running on, which over SSH is the remote box, never the
user's actual local machine.

- **Primary mechanism: OSC 52** — `\x1b]52;c;<base64 of text>\x07`, written
  via `get_app().output.write_raw(...)` (the same method prompt_toolkit's own
  `enable_mouse_support()` uses to send raw escape codes without corrupting
  the app's rendering). Zero pip dependencies; works over plain SSH because
  it rides the existing terminal data stream and is interpreted by the
  user's actual local terminal emulator.
- **tmux**: must detect `$TMUX` and wrap in tmux's DCS passthrough envelope —
  `\x1bPtmux;` + the inner OSC52 sequence with its own ESC byte doubled +
  `\x1b\\` to close — otherwise tmux consumes the raw sequence before the
  outer terminal ever sees it. (Likely the real root cause of a previously
  documented "OSC52 didn't work" attempt, independent of tmux's
  `terminal-features`/`set-clipboard` setting, which also needs to be
  correct.)
- **Fallback chain**: OSC52 first → `pyperclip` if installed (covers rare
  non-OSC52 terminals or genuinely local-only sessions) → no-op with a
  one-time warning.

## Dependencies

Scoped to the shell/TUI package specifically — `sqlalchemy`, `pyvisa`,
`pyusb`, `PyYAML` etc. belong to the separate DAG-engine/hardware-scanning
side of `lazybench`, not this package (ties back to keeping the shell
genuinely separable for the portability goal).

- **Hard**: `prompt_toolkit` — confirmed via `importlib.metadata` to have
  exactly one dependency itself (`wcwidth`).
- **Optional, zero transitive cost**: `pygments` (syntax highlighting),
  `pfzy` (fuzzy matching — confirmed zero required runtime deps).
- **Optional, small**: `pyperclip` (clipboard fallback), `jedi` (autocomplete
  — wrapped directly, not via IPython).
- **Explicitly dropped**:
  - `InquirerPy` — wrong architecture (own `Application` per prompt).
  - `IPython`'s `InteractiveShell` — confirmed via `importlib.metadata` to
    pull in 7 more packages (`decorator`, `ipython-pygments-lexers`, `jedi`,
    `matplotlib-inline`, `pexpect`, `stack_data`, `traitlets`), several with
    further transitive depth (`jedi`→`parso`, `stack_data`→`executing`/
    `asttokens`/`pure_eval`). Replaced by stdlib `exec()` + `codeop.
    compile_command` + a persistent `dict` namespace + `prompt_toolkit.
    history.FileHistory`.
  - `coloredlogs` — replaceable with a small hand-rolled ANSI formatter;
    lower priority than the above.

## Open / deferred

- Exact `Completer` shape for wrapping `jedi` into prompt_toolkit's
  `Completer` protocol — not designed yet.
- Whether `SidebarPane` needs the `_insert_cursor_marker`-style
  scroll-to-highlighted-row trick (only relevant if a single node's children
  can overflow the sidebar's height) — not resolved.
- "Local variables" collapsible in the Sidebar — floated as a maybe, not committed.
- The selectable-row-list widget's exact API — agreed it should be built
  once, generically; not yet designed in detail.
- Full keybinding table (which physical keys map to expand / jump / drag /
  vim-toggle / etc.) — implied throughout but not yet written down in one place.
