import pytest
from lexer import lex, TT, Token


def types(src):
    """Return just the token types for a source string."""
    return [t.type for t in lex(src)]


def values(src):
    """Return just the token values (excluding EOF)."""
    return [t.value for t in lex(src) if t.type != TT.EOF]


# ── Primitive tokens ────────────────────────────────────────────────────────

def test_lbrace():
    assert types("{")[0] == TT.LBRACE

def test_rbrace():
    assert types("}")[0] == TT.RBRACE

def test_colon():
    assert types(":")[0] == TT.COLON

def test_comma():
    assert types(",")[0] == TT.COMMA

def test_semicolon():
    assert types(";")[0] == TT.SEMICOLON

def test_unquoted_string():
    toks = lex("button")
    assert toks[0].type == TT.STRING
    assert toks[0].value == "button"

def test_quoted_string_double():
    toks = lex('"hello world"')
    assert toks[0].type == TT.STRING
    assert toks[0].value == "hello world"

def test_quoted_string_single():
    toks = lex("'hello world'")
    assert toks[0].type == TT.STRING
    assert toks[0].value == "hello world"

def test_whitespace_ignored():
    assert types("  button  ") == [TT.STRING, TT.EOF]


# ── Grid cells ───────────────────────────────────────────────────────────────

def test_grid_cell_simple():
    toks = lex("<[button_a]>")
    assert toks[0].type == TT.GRID_CELL
    assert toks[0].value == "button_a"

def test_grid_cell_whitespace_trimmed():
    toks = lex("<[  self  ]>")
    assert toks[0].type == TT.GRID_CELL
    assert toks[0].value == "self"

def test_grid_cell_empty():
    toks = lex("<[]>")
    assert toks[0].type == TT.GRID_SEP  # empty <[]> counts as separator

def test_grid_cell_layers():
    toks = lex("<[a::b::c]>")
    assert toks[0].type == TT.GRID_CELL
    assert toks[0].value == "a::b::c"

def test_grid_row_two_cells():
    toks = [t for t in lex("<[button_a]> <[button_b]>") if t.type != TT.EOF]
    assert toks[0].type == TT.GRID_CELL
    assert toks[0].value == "button_a"
    assert toks[1].type == TT.GRID_CELL
    assert toks[1].value == "button_b"


# ── Grid separators ──────────────────────────────────────────────────────────

def test_grid_sep_equals():
    toks = lex("<[=]>")
    assert toks[0].type == TT.GRID_SEP

def test_grid_sep_dash():
    toks = lex("<[-]>")
    assert toks[0].type == TT.GRID_SEP

def test_grid_sep_long_equals():
    toks = lex("<[==========]>")
    assert toks[0].type == TT.GRID_SEP

def test_grid_sep_mixed():
    toks = lex("<[---------==]>")
    assert toks[0].type == TT.GRID_SEP

def test_grid_sep_bare():
    toks = lex("<=========>")
    assert toks[0].type == TT.GRID_SEP

def test_grid_sep_bare_dash():
    toks = lex("<------->")
    assert toks[0].type == TT.GRID_SEP


# ── Config key: value ────────────────────────────────────────────────────────

def test_simple_key_value():
    toks = [t for t in lex("app: button") if t.type != TT.EOF]
    assert toks[0] == Token(TT.STRING, "app")
    assert toks[1] == Token(TT.COLON, ":")
    assert toks[2] == Token(TT.STRING, "button")

def test_key_value_with_semicolon():
    toks = [t for t in lex("app: button;") if t.type != TT.EOF]
    assert toks[-1].type == TT.SEMICOLON

def test_flat_dict():
    src = '{ app: button, label: "Left" }'
    tt = types(src)
    assert tt[0] == TT.LBRACE
    assert TT.COMMA in tt
    assert tt[-2] == TT.RBRACE

def test_nested_dict():
    src = 'content: { app: button, label: "foo" }'
    toks = [t for t in lex(src) if t.type != TT.EOF]
    assert toks[0] == Token(TT.STRING, "content")
    assert toks[1] == Token(TT.COLON, ":")
    assert toks[2] == Token(TT.LBRACE, "{")
    assert toks[-1] == Token(TT.RBRACE, "}")


# ── Full tile body ───────────────────────────────────────────────────────────

def test_tile_body_with_layout_and_config():
    src = """
<[button_a]> <[button_b]>
<[=]>
button_a: { content: { app: button, label: "Left" } }
button_b: { content: { app: button, label: "Right" } }
"""
    toks = [t for t in lex(src) if t.type != TT.EOF]
    grid_cells = [t for t in toks if t.type == TT.GRID_CELL]
    grid_seps  = [t for t in toks if t.type == TT.GRID_SEP]
    assert len(grid_cells) == 2
    assert grid_cells[0].value == "button_a"
    assert grid_cells[1].value == "button_b"
    assert len(grid_seps) == 1


def test_tile_body_multirow():
    src = """
<[btn_a]> <[btn_b]> <[btn_c]>
<[-]>
<[btn_d]> <[btn_e]>
<[=]>
btn_a: { content: { app: button, label: "A" } }
"""
    toks = [t for t in lex(src) if t.type != TT.EOF]
    grid_cells = [t for t in toks if t.type == TT.GRID_CELL]
    grid_seps  = [t for t in toks if t.type == TT.GRID_SEP]
    assert len(grid_cells) == 5
    assert len(grid_seps) == 2   # one row sep + one layout/config sep


# ── Garbage tolerance ────────────────────────────────────────────────────────

def test_mangled_separator_still_grid_sep():
    toks = lex("<[-----------------------==]>")
    assert toks[0].type == TT.GRID_SEP

def test_junk_lines_dont_crash():
    src = "ffwefaeunc\n<[single_button]>"
    toks = [t for t in lex(src) if t.type != TT.EOF]
    cells = [t for t in toks if t.type == TT.GRID_CELL]
    assert len(cells) == 1
    assert cells[0].value == "single_button"
