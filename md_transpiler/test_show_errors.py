"""
Test runner that demonstrates actual errors in html_generator.py
Run this to see what breaks and where.
"""

import traceback
from lexer import TEXT, PUNCT, ParagraphToken, HeaderToken
from html_generator import (
    parse_block,
    _split_by_delimiter,
    generate_paragraph,
    generate_header,
    BOLD, ITALIC, LINK, BRACES, LATEX_INLINE, NOFORMAT
)


def test_parse_block_simple():
    """Show what happens with simple text."""
    print("\n=== Test: parse_block with simple text ===")
    try:
        tokens = [TEXT("Hello world")]
        result = parse_block(tokens)
        print(f"✓ Success: {result}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_parse_block_with_bold():
    """Show what happens with bold formatting."""
    print("\n=== Test: parse_block with bold ===")
    try:
        tokens = [TEXT("Hello "), PUNCT("*"), PUNCT("*"), TEXT("bold"), PUNCT("*"), PUNCT("*")]
        result = parse_block(tokens)
        print(f"✓ Success: {result}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_parse_block_with_italic():
    """Show what happens with italic formatting."""
    print("\n=== Test: parse_block with italic ===")
    try:
        tokens = [TEXT("Hello "), PUNCT("*"), TEXT("italic"), PUNCT("*")]
        result = parse_block(tokens)
        print(f"✓ Success: {result}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_split_by_delimiter_simple():
    """Show what happens when splitting by delimiters."""
    print("\n=== Test: _split_by_delimiter simple ===")
    try:
        tokens = [TEXT("Hello"), PUNCT("*"), TEXT("bold"), PUNCT("*")]
        result = _split_by_delimiter(tokens)
        print(f"✓ Success: {len(result)} semantic tokens")
        for i, tk in enumerate(result):
            print(f"   [{i}] {type(tk).__name__}: {tk.inner_string}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_split_by_delimiter_with_link():
    """Show what happens with link syntax."""
    print("\n=== Test: _split_by_delimiter with link ===")
    try:
        tokens = [TEXT("See "), PUNCT("["), TEXT("link"), PUNCT("]")]
        result = _split_by_delimiter(tokens)
        print(f"✓ Success: {len(result)} semantic tokens")
        for i, tk in enumerate(result):
            print(f"   [{i}] {type(tk).__name__}: {tk.inner_string}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_split_by_delimiter_with_latex():
    """Show what happens with LaTeX."""
    print("\n=== Test: _split_by_delimiter with LaTeX ===")
    try:
        tokens = [TEXT("Equation: "), PUNCT("$"), TEXT("x^2"), PUNCT("$")]
        result = _split_by_delimiter(tokens)
        print(f"✓ Success: {len(result)} semantic tokens")
        for i, tk in enumerate(result):
            print(f"   [{i}] {type(tk).__name__}: {tk.inner_string}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_generate_paragraph_simple():
    """Show what happens generating a paragraph."""
    print("\n=== Test: generate_paragraph simple ===")
    try:
        pt = ParagraphToken()
        pt.inner_tokens = [TEXT("Hello world")]
        result = generate_paragraph(pt)
        print(f"✓ Success: {result}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_generate_paragraph_with_formatting():
    """Show what happens with formatted paragraph."""
    print("\n=== Test: generate_paragraph with formatting ===")
    try:
        pt = ParagraphToken()
        pt.inner_tokens = [TEXT("This is "), PUNCT("*"), PUNCT("*"), TEXT("bold"), PUNCT("*"), PUNCT("*"), TEXT(" text")]
        result = generate_paragraph(pt)
        print(f"✓ Success: {result}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_generate_header():
    """Show what happens generating a header."""
    print("\n=== Test: generate_header ===")
    try:
        ht = HeaderToken()
        ht.header_depth = 2
        ht.inner_tokens = [TEXT("My Section")]
        result = generate_header(ht)
        print(f"✓ Success: {result}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_generate_header_with_code():
    """Show what happens with code in header."""
    print("\n=== Test: generate_header with code ===")
    try:
        ht = HeaderToken()
        ht.header_depth = 1
        ht.inner_tokens = [TEXT("Using "), PUNCT("{"), TEXT("code()"), PUNCT("}")]
        result = generate_header(ht)
        print(f"✓ Success: {result}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


def test_mismatched_delimiters():
    """Show what happens with unclosed delimiters."""
    print("\n=== Test: mismatched delimiters ===")
    try:
        tokens = [TEXT("Unclosed "), PUNCT("$"), TEXT("math")]
        result = parse_block(tokens)
        print(f"✓ Success: {result}")
    except Exception as e:
        tb = traceback.extract_tb(e.__traceback__)
        line_info = tb[-1]
        print(f"✗ Error: {type(e).__name__}: {e}")
        print(f"  at {line_info.filename}:{line_info.lineno} in {line_info.name}")


if __name__ == '__main__':
    print("Running error demonstration tests...")
    print("=" * 60)

    test_parse_block_simple()
    test_parse_block_with_bold()
    test_parse_block_with_italic()
    test_split_by_delimiter_simple()
    test_split_by_delimiter_with_link()
    test_split_by_delimiter_with_latex()
    test_generate_paragraph_simple()
    test_generate_paragraph_with_formatting()
    test_generate_header()
    test_generate_header_with_code()
    test_mismatched_delimiters()

    print("\n" + "=" * 60)
    print("Done. Check errors above.")
