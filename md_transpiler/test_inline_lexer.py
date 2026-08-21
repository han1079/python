import pytest
from lexer import TEXT, PUNCT, _make_inline_tokens, _delete_trailing_zeros, _delete_line_continuations, _make_blocks


def read_test_file(filename):
    """Read a test markdown file and convert to string list."""
    raw = bytearray(8192)
    with open(filename, 'rb') as f:
        f.readinto(raw)
    raw = _delete_trailing_zeros(raw)
    raw = _delete_line_continuations(raw)
    return raw


def test_simple_text():
    """Test plain text without punctuation."""
    blocks = _make_blocks("Simple text")
    block = blocks[0]
    _make_inline_tokens(block)
    tokens = block.inner_tokens

    assert len(tokens) == 1
    assert isinstance(tokens[0], TEXT)
    assert tokens[0].content == "Simple text"


def test_text_with_punct():
    """Test text with punctuation."""
    blocks = _make_blocks("Hello, world")
    block = blocks[0]
    _make_inline_tokens(block)
    tokens = block.inner_tokens

    # Expected: [TEXT("Hello"), PUNCT(","), TEXT(" world")]
    assert len(tokens) == 3
    assert isinstance(tokens[0], TEXT)
    assert tokens[0].content == "Hello"
    assert isinstance(tokens[1], PUNCT)
    assert tokens[1].content == ","
    assert isinstance(tokens[2], TEXT)
    assert tokens[2].content == " world"


def test_multiple_punct():
    """Test multiple punctuation marks."""
    blocks = _make_blocks("a**b")
    block = blocks[0]
    _make_inline_tokens(block)
    tokens = block.inner_tokens

    # Expected: [TEXT("a"), PUNCT("*"), PUNCT("*"), TEXT("b")]
    assert len(tokens) == 4
    assert isinstance(tokens[0], TEXT)
    assert isinstance(tokens[1], PUNCT)
    assert tokens[1].content == "*"
    assert isinstance(tokens[2], PUNCT)
    assert tokens[2].content == "*"


def test_escaped_punct():
    """Test escaped punctuation (should be treated as literal)."""
    blocks = _make_blocks(r"text \* more")
    block = blocks[0]
    _make_inline_tokens(block)
    tokens = block.inner_tokens

    # Expected: [TEXT("text "), TEXT("*"), TEXT(" more")]
    # The backslash should be consumed, leaving just the asterisk in text
    punct_found = any(isinstance(t, PUNCT) and t.content == "*" for t in tokens)
    assert not punct_found, "Escaped asterisk should not be PUNCT token"


def test_brackets():
    """Test bracket punctuation."""
    blocks = _make_blocks("[link](url)")
    block = blocks[0]
    _make_inline_tokens(block)
    tokens = block.inner_tokens

    # Expected: [PUNCT("["), TEXT("link"), PUNCT("]"), PUNCT("("), TEXT("url"), PUNCT(")")]
    assert len(tokens) == 6
    assert isinstance(tokens[0], PUNCT) and tokens[0].content == "["
    assert isinstance(tokens[1], TEXT)
    assert isinstance(tokens[2], PUNCT) and tokens[2].content == "]"


def test_inline_code():
    """Test backticks for inline code."""
    blocks = _make_blocks("Use `code` here")
    block = blocks[0]
    _make_inline_tokens(block)
    tokens = block.inner_tokens

    # Expected: [TEXT("Use "), PUNCT("`"), TEXT("code"), PUNCT("`"), TEXT(" here")]
    backtick_count = sum(1 for t in tokens if isinstance(t, PUNCT) and t.content == "`")
    assert backtick_count == 2


def test_inline_latex():
    """Test dollar signs for inline LaTeX."""
    blocks = _make_blocks("Math: $x^2$ here")
    block = blocks[0]
    _make_inline_tokens(block)
    tokens = block.inner_tokens

    # Expected: [TEXT("Math: "), PUNCT("$"), TEXT("x^2"), PUNCT("$"), TEXT(" here")]
    dollar_count = sum(1 for t in tokens if isinstance(t, PUNCT) and t.content == "$")
    assert dollar_count == 2


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
