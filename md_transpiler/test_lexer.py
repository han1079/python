import pytest
from lexer import _make_blocks, HeaderToken, ParagraphToken, _delete_trailing_zeros, BlockTokenType


def read_test_file(filename):
    """Read a test markdown file and convert to string list."""
    raw = bytearray(8192)
    with open(filename, 'rb') as f:
        f.readinto(raw)
    raw = _delete_trailing_zeros(raw)
    return raw


def test_basic_structure():
    """Test that test_basic.md parses into expected block structure."""
    raw = read_test_file('test_basic.md')
    tokens = _make_blocks(raw)

    # Expected sequence with leading newlines
    expected_types = [
        BlockTokenType.LEADING_NEWLINE,  # Leading newlines from file start
        BlockTokenType.PARAGRAPH,  # "Bunch of Test Text..."
        BlockTokenType.HEADING,     # # Top Level Heading
        BlockTokenType.PARAGRAPH,   # This is a simple paragraph.
        BlockTokenType.HEADING,     # ## Second Level Heading
        BlockTokenType.PARAGRAPH,   # Another paragraph here... (spans 3 lines)
        BlockTokenType.HEADING,     # ### Third Level Heading
        BlockTokenType.PARAGRAPH,   # Short paragraph.
        BlockTokenType.PARAGRAPH,   # Multiple blank lines above.
        BlockTokenType.PARAGRAPH,   # Lots of blank lines above this one.
        BlockTokenType.HEADING,     # # Back to Top Level
        BlockTokenType.PARAGRAPH,   # Single line paragraph.
        BlockTokenType.HEADING,     # ## Another Second Level
        BlockTokenType.PARAGRAPH,   # Paragraph one.
        BlockTokenType.PARAGRAPH,   # Paragraph two.
        BlockTokenType.PARAGRAPH,   # Paragraph three with... (spans 3 lines)
        BlockTokenType.HEADING,     # ### Nested Under Second
        BlockTokenType.PARAGRAPH,   # Final paragraph.
        BlockTokenType.HEADING,     # #### Fourth Level
        BlockTokenType.PARAGRAPH,   # Very nested paragraph.
        BlockTokenType.HEADING,     # # Final Top Level
        BlockTokenType.PARAGRAPH,   # Closing paragraph.
    ]

    assert len(tokens) == len(expected_types), f"Expected {len(expected_types)} tokens, got {len(tokens)}"

    for i, (token, expected_type) in enumerate(zip(tokens, expected_types)):
        assert token.token_type == expected_type, f"Token {i}: expected {expected_type}, got {token.token_type}"


def test_header_depth():
    """Test that header depths are correctly parsed."""
    raw = read_test_file('test_basic.md')
    tokens = _make_blocks(raw)
    tokens = [t for t in tokens if t.token_type == BlockTokenType.HEADING]

    expected_depths = [1, 2, 3, 1, 2, 3, 4, 1]

    assert len(tokens) == len(expected_depths), f"Expected {len(expected_depths)} headers, got {len(tokens)}"

    for i, (token, expected_depth) in enumerate(zip(tokens, expected_depths)):
        assert isinstance(token, HeaderToken), f"Token {i} should be HeaderToken"
        assert token.header_depth == expected_depth, f"Header {i}: expected depth {expected_depth}, got {token.header_depth}"


def test_paragraph_multiline():
    """Test that multi-line paragraphs are correctly parsed as single blocks."""
    raw = read_test_file('test_basic.md')
    tokens = _make_blocks(raw)
    paragraphs = [t for t in tokens if t.token_type == BlockTokenType.PARAGRAPH]

    # "Another paragraph here." + "This paragraph spans..." + "And even more lines."
    # should be ONE token with content spanning 3 lines
    multi_line_para = paragraphs[2]  # Third paragraph
    assert 'Another paragraph here.' in multi_line_para.raw_text
    assert 'This paragraph spans multiple lines.' in multi_line_para.raw_text
    assert 'And even more lines.' in multi_line_para.raw_text


def test_header_text_clean():
    """Test that header text doesn't include leading/trailing whitespace or newlines."""
    raw = read_test_file('test_basic.md')
    tokens = _make_blocks(raw)
    headers = [t for t in tokens if t.token_type == BlockTokenType.HEADING]

    first_header = headers[0]
    # Should not have leading/trailing spaces or newlines
    assert first_header.raw_text.strip() == first_header.raw_text, "Header text should be stripped"
    assert '\n' not in first_header.raw_text, "Header text should not contain newlines"


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
