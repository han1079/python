"""Tile UI skeleton — prompt_toolkit 3.x.

Model
-----
Node tree = layout tree (every Node implements __pt_container__).
Zones per tile:  gutter (parent-owned, resize) | border (tile-owned, block focus) | content (control-owned, text).
Mode is DERIVED from focus:  block  <=> focus on tile.sink ;  text  <=> focus on tile's BufferControl.
Mouse never bubbles: every zone is a UIControl with its own mouse_handler.
Keys bubble: block bindings live on containers, gated by has_focus(sink); editor bindings live in the BufferControl.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from enum import IntEnum

from prompt_toolkit.application import Application, get_app
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.data_structures import Point
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import (
    ConditionalContainer, DynamicContainer, Float, FloatContainer,
    HSplit, Layout, VSplit, Window,
)
from prompt_toolkit.layout.controls import (
    BufferControl, FormattedTextControl, UIContent, UIControl,
)
from prompt_toolkit.layout.dimension import Dimension as D
from prompt_toolkit.mouse_events import MouseEvent, MouseEventType as M


# ─────────────────────────────── glyphs ────────────────────────────────

class W(IntEnum):
    NONE = 0
    LIGHT = 1
    DOUBLE = 2


# (up, down, left, right) -> glyph.  Fill to taste; Unicode lacks many mixed combos
# (e.g. up LIGHT + down DOUBLE), so lookups fall back by promoting to the max weight.
GLYPH: dict[tuple[W, W, W, W], str] = {
    (W.LIGHT, W.LIGHT, W.NONE, W.NONE): "│", (W.DOUBLE, W.DOUBLE, W.NONE, W.NONE): "║",
    (W.NONE, W.NONE, W.LIGHT, W.LIGHT): "─", (W.NONE, W.NONE, W.DOUBLE, W.DOUBLE): "═",
    (W.NONE, W.LIGHT, W.NONE, W.LIGHT): "┌", (W.NONE, W.DOUBLE, W.NONE, W.DOUBLE): "╔",
    (W.NONE, W.LIGHT, W.LIGHT, W.NONE): "┐", (W.NONE, W.DOUBLE, W.DOUBLE, W.NONE): "╗",
    (W.LIGHT, W.NONE, W.NONE, W.LIGHT): "└", (W.DOUBLE, W.NONE, W.NONE, W.DOUBLE): "╚",
    (W.LIGHT, W.NONE, W.LIGHT, W.NONE): "┘", (W.DOUBLE, W.NONE, W.DOUBLE, W.NONE): "╝",
    (W.LIGHT, W.LIGHT, W.NONE, W.DOUBLE): "╞", (W.LIGHT, W.LIGHT, W.DOUBLE, W.NONE): "╡",
    (W.DOUBLE, W.DOUBLE, W.NONE, W.LIGHT): "╟", (W.DOUBLE, W.DOUBLE, W.LIGHT, W.NONE): "╢",
    # ... tees / crosses: ├┤┬┴┼ ╠╣╦╩╬ ╤╧╥╨ ╪╫
}
ROUND = {"┌": "╭", "┐": "╮", "└": "╰", "┘": "╯"}  # light only — no double arcs exist


def glyph(up: W, down: W, left: W, right: W, rounded: bool = False) -> str:
    key = (up, down, left, right)
    g = GLYPH.get(key)
    if g is None:  # promote mixed weights until a glyph exists
        m = max(key)
        g = GLYPH.get(tuple(m if w else W.NONE for w in key), " ")
    return ROUND.get(g, g) if rounded else g


# ───────────────────────────── shared state ─────────────────────────────

@dataclass
class UIState:
    cursor: "Node | None" = None        # current block (node ref; level = depth)
    hover: "Zone | None" = None         # exactly one lit zone
    drag: "Gutter | None" = None        # active resize, owns the capture layer
    freeze_reflow: bool = False         # width drag in progress → clip, don't rewrap


STATE = UIState()


def invalidate() -> None:
    get_app().invalidate()


def in_text_mode(tile: "Tile") -> bool:
    return get_app().layout.has_focus(tile.content_window)


# ───────────────────────────── zone base ────────────────────────────────

class Zone(UIControl):
    """Hit zone. Subclasses override on_click / on_drag; hover is handled here."""

    def is_focusable(self) -> bool:
        return False

    def mouse_handler(self, e: MouseEvent):
        if e.event_type == M.MOUSE_MOVE and STATE.drag is None:
            if STATE.hover is not self:
                STATE.hover = self
                invalidate()
            return None
        if e.event_type == M.MOUSE_UP:
            return self.on_click(e)
        if e.event_type == M.MOUSE_DOWN:
            return self.on_press(e)
        return NotImplemented

    def on_press(self, e: MouseEvent):
        return None

    def on_click(self, e: MouseEvent):
        return None

    def style(self) -> str:
        s = "class:zone"
        if STATE.hover is self:
            s += " class:zone.hover"
        return s


# ───────────────────────────── tree nodes ───────────────────────────────

class Node:
    parent: "Group | None" = None
    children: list["Node"]
    last_index: int = 0

    def __init__(self) -> None:
        self.children = []

    @property
    def depth(self) -> int:
        return 0 if self.parent is None else self.parent.depth + 1

    def is_active(self) -> bool:
        """Cursor is on this node."""
        return STATE.cursor is self

    def contains_cursor(self) -> bool:
        n = STATE.cursor
        while n is not None:
            if n is self:
                return True
            n = n.parent
        return False

    def edge_weight(self) -> W:
        return W.DOUBLE if self.is_active() else W.LIGHT

    def __pt_container__(self):
        raise NotImplementedError


class Tile(Node):
    """Leaf: border zones + content. Owns a zero-height focus sink for block mode."""

    def __init__(self, content: Window, rounded: bool = True) -> None:
        super().__init__()
        self.content_window = content
        self.rounded = rounded
        self.sink = Window(FormattedTextControl("", focusable=True), height=D.exact(0))
        self.dim = D(weight=1)  # parent mutates this on resize

    def focus_block(self) -> None:
        STATE.cursor = self
        get_app().layout.focus(self.sink)

    def __pt_container__(self):
        col = lambda side: Window(BorderControl(self, side), width=1,
                                  style=lambda: self._border_style())
        row = lambda side: Window(BorderRowControl(self, side), height=1,
                                  style=lambda: self._border_style())
        return HSplit([
            self.sink,
            row("top"),
            VSplit([col("left"), self.content_window, col("right")]),
            row("bottom"),
        ], width=lambda: self.dim)

    def _border_style(self) -> str:
        s = "class:tile.border"
        if self.is_active():
            s += " class:tile.border.text" if in_text_mode(self) else " class:tile.border.block"
        return s


class BorderControl(Zone):
    """Vertical border column. Click → block focus on its tile."""

    def __init__(self, tile: Tile, side: str) -> None:
        self.tile, self.side = tile, side

    def create_content(self, width: int, height: int) -> UIContent:
        w = self.tile.edge_weight()
        ch = glyph(w, w, W.NONE, W.NONE)
        return UIContent(get_line=lambda i: [(self.style(), ch)], line_count=height)

    def on_click(self, e: MouseEvent):
        self.tile.focus_block()
        return None


class BorderRowControl(BorderControl):
    """Horizontal border row incl. corners. Fragment handlers allow sub-zones per row."""

    def create_content(self, width: int, height: int) -> UIContent:
        w = self.tile.edge_weight()
        top = self.side == "top"
        l = glyph(W.NONE if top else w, w if top else W.NONE, W.NONE, w, self.tile.rounded)
        r = glyph(W.NONE if top else w, w if top else W.NONE, w, W.NONE, self.tile.rounded)
        mid = glyph(W.NONE, W.NONE, w, w)
        line = [(self.style(), l + mid * max(width - 2, 0) + r)]
        return UIContent(get_line=lambda i: line, line_count=1)


class EditControl(BufferControl):
    """Content zone. Jupyter semantics:
    block mode: click → focus block; click on already-active block (or double-click) → enter text at point.
    text mode:  click in own cell → cursor; click in another cell → that cell's block mode.
    """

    DOUBLE_CLICK_S = 0.35

    def __init__(self, tile: "CellTile", **kw) -> None:
        super().__init__(buffer=tile.buffer, focus_on_click=False, **kw)
        self.tile = tile
        self._last_up = 0.0

    def mouse_handler(self, e: MouseEvent):
        if e.event_type == M.SCROLL_UP or e.event_type == M.SCROLL_DOWN:
            return self.tile.pane.on_wheel(self.tile, e) if self.tile.pane else NotImplemented
        if in_text_mode(self.tile):
            return super().mouse_handler(e)            # stock cursor placement / selection
        if e.event_type != M.MOUSE_UP:
            return None
        now, dbl = time.monotonic(), False
        dbl, self._last_up = now - self._last_up < self.DOUBLE_CLICK_S, now
        if self.tile.is_active() or dbl:
            self.tile.edit(at=e.position)
        else:
            self.tile.focus_block()
        return None


class CellTile(Tile):
    """In[n]/Out[n] cell."""

    def __init__(self, text: str = "", pane: "ScrollPane | None" = None) -> None:
        self.buffer = Buffer(multiline=True, document=None)
        self.buffer.text = text
        self.pane = pane
        self.control = EditControl(self)
        win = Window(self.control, wrap_lines=Condition(lambda: not STATE.freeze_reflow),
                     always_hide_cursor=Condition(lambda: not in_text_mode(self)))
        super().__init__(win)

    def edit(self, at: Point | None = None) -> None:
        STATE.cursor = self
        get_app().layout.focus(self.content_window)
        if at is not None:
            doc = self.buffer.document
            self.buffer.cursor_position = doc.translate_row_col_to_index(at.y, at.x)
            # NOTE: at is in content coords; with wrap on, map via the Window's render_info


# ─────────────────────────────── groups ─────────────────────────────────

class Group(Node):
    axis: str  # "x" (VSplit) | "y" (HSplit)

    def __init__(self, children: list[Node]) -> None:
        super().__init__()
        self.children = children
        for c in children:
            c.parent = self
        self.dim = D(weight=1)

    def index_of(self, child: Node) -> int:
        return next(i for i, c in enumerate(self.children) if c is child)


class Stack(Group):
    """Vertical stack, not resizable → no gutters."""
    axis = "y"

    def __pt_container__(self):
        return HSplit(self.children)


class Row(Group):
    """Horizontal, resizable → parent-owned gutters between children."""
    axis = "x"

    def __pt_container__(self):
        parts: list = []
        for i, c in enumerate(self.children):
            if i:
                parts.append(Window(Gutter(self, i - 1), width=1))
            parts.append(c)
        return VSplit(parts)


class Gutter(Zone):
    """Between children[i] and children[i+1] of a Row. Drag transfers width between them."""

    def __init__(self, row: Row, i: int) -> None:
        self.row, self.i = row, i
        self._x0 = 0

    def create_content(self, width: int, height: int) -> UIContent:
        s = self.style() + (" class:gutter.drag" if STATE.drag is self else "")
        return UIContent(get_line=lambda i: [(s, " ")], line_count=height)

    def on_press(self, e: MouseEvent):
        STATE.drag, STATE.freeze_reflow = self, True
        self._x0 = None  # captured layer reports absolute x
        invalidate()
        return None

    def drag_to(self, abs_x: int) -> None:
        """Called by DragCapture with screen-space x."""
        if self._x0 is None:
            self._x0 = abs_x
            return
        dx, self._x0 = abs_x - self._x0, abs_x
        a, b = self.row.children[self.i], self.row.children[self.i + 1]
        # Convert dx to weight transfer; or switch both to D.exact(...) while dragging.
        a.dim, b.dim = _transfer(a.dim, b.dim, dx)
        invalidate()

    def release(self) -> None:
        STATE.drag, STATE.freeze_reflow = None, False
        invalidate()  # single reflow at the new width


def _transfer(a: D, b: D, dx: int) -> tuple[D, D]:
    """Move dx columns of preference from b to a, clamped by min/max."""
    ...


class DragCapture(UIControl):
    """Full-screen transparent float shown only while dragging.
    Mouse events don't follow the gutter once the pointer leaves its 1-col window;
    this layer owns the MouseHandlers grid during a drag (poor man's pointer capture).
    """

    def create_content(self, width: int, height: int) -> UIContent:
        return UIContent(get_line=lambda i: [], line_count=height)

    def mouse_handler(self, e: MouseEvent):
        g = STATE.drag
        if g is None:
            return NotImplemented
        if e.event_type == M.MOUSE_MOVE:
            g.drag_to(e.position.x)
        elif e.event_type == M.MOUSE_UP:
            g.release()
        return None


def capture_float() -> Float:
    # NOTE: verify Float(transparent=...) in your pt version; without it the float erases content.
    return Float(
        ConditionalContainer(Window(DragCapture()), filter=Condition(lambda: STATE.drag is not None)),
        left=0, right=0, top=0, bottom=0, transparent=True,
    )


# ───────────────────────────── navigation ───────────────────────────────

class Navigator:
    """Structural (keyboard) movement. Level = depth of STATE.cursor; never crosses levels implicitly."""

    def move(self, axis: str, step: int) -> None:
        cur = STATE.cursor
        if cur is None:
            return
        level, node = cur.depth, cur
        while node.parent is not None:
            p = node.parent
            p.last_index = p.index_of(node)
            i = p.last_index + step
            if p.axis == axis and 0 <= i < len(p.children):
                target = p.children[i]
                while target.depth < level and target.children:   # descend back to level
                    target = target.children[target.last_index]
                self._land(target)                                  # unbalanced tree: clamps here
                return
            node = p
        # at edge: saturate

    def enter(self) -> None:
        cur = STATE.cursor
        if isinstance(cur, CellTile):
            cur.edit()
        elif cur is not None and cur.children:
            self._land(cur.children[cur.last_index])

    def leave(self) -> None:
        cur = STATE.cursor
        if isinstance(cur, Tile) and in_text_mode(cur):
            cur.focus_block()
        elif cur is not None and cur.parent is not None:
            cur.parent.last_index = cur.parent.index_of(cur)
            self._land(cur.parent)

    def _land(self, node: Node) -> None:
        if isinstance(node, Tile):
            node.focus_block()
        else:
            STATE.cursor = node            # group-level cursor: focus stays on some sink
        invalidate()


# ───────────────────────────── scroll pane ──────────────────────────────

class ScrollPane:
    """Virtualized vertical list of CellTiles. Real Windows in the real layout:
    pt keeps mouse translation + cursor placement; we own only the outer offset.
    Outer scroll = (top, offset): first visible cell + lines clipped from its top.
    """

    def __init__(self, cells: list[CellTile]) -> None:
        self.cells = cells
        for c in cells:
            c.pane = self
        self.top, self.offset = 0, 0
        self.stack = Stack(cells)

    def __pt_container__(self):
        return DynamicContainer(self._visible)

    def _visible(self):
        # Pick cells[top:k] until viewport filled; set clipped top cell's vertical_scroll.
        height = get_app().output.get_size().rows  # or the pane's allotted height
        head = self.cells[self.top]
        head.content_window.vertical_scroll = self.offset
        shown, used = [], -self.offset
        for c in self.cells[self.top:]:
            shown.append(c)
            used += self._cell_height(c)
            if used >= height:
                break
        return HSplit(shown)

    def _cell_height(self, c: CellTile) -> int:
        """Rendered height incl. borders. Cache per (cell, width); invalid on edit / width change."""
        ...

    # mouse: saturate inside cell, then hop
    def on_wheel(self, cell: CellTile, e: MouseEvent):
        down = e.event_type == M.SCROLL_DOWN
        if self._inner_can_scroll(cell, down):
            return NotImplemented      # let the cell's Window scroll itself
        self.hop(+1 if down else -1)
        return None

    def _inner_can_scroll(self, cell: CellTile, down: bool) -> bool:
        ...

    def hop(self, step: int) -> None:
        self.top = max(0, min(len(self.cells) - 1, self.top + step))
        self.offset = 0
        invalidate()

    def follow_cursor(self) -> None:
        """Keyboard: keep active cell (and its text cursor in text mode) in view."""
        ...


# ───────────────────────────── key bindings ─────────────────────────────

def block_mode_bindings(nav: Navigator) -> KeyBindings:
    kb = KeyBindings()
    block = Condition(lambda: isinstance(STATE.cursor, Tile) and not in_text_mode(STATE.cursor)
                      or (STATE.cursor is not None and not isinstance(STATE.cursor, Tile)))

    @kb.add("h", filter=block)
    @kb.add("left", filter=block)
    def _(e): nav.move("x", -1)

    @kb.add("l", filter=block)
    @kb.add("right", filter=block)
    def _(e): nav.move("x", +1)

    @kb.add("k", filter=block)
    @kb.add("up", filter=block)
    def _(e): nav.move("y", -1)

    @kb.add("j", filter=block)
    @kb.add("down", filter=block)
    def _(e): nav.move("y", +1)

    @kb.add("enter", filter=block)
    def _(e): nav.enter()

    @kb.add("escape", eager=True)  # text → block, block → parent; eager: don't wait for Meta-x
    def _(e): nav.leave()

    return kb


# ─────────────────────────────── assembly ───────────────────────────────

def make_app(root: Node) -> Application:
    nav = Navigator()
    body = FloatContainer(content=HSplit([root]), floats=[capture_float()])
    return Application(
        layout=Layout(body),
        key_bindings=block_mode_bindings(nav),
        mouse_support=True,
        full_screen=True,
    )
