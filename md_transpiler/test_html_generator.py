import pytest
from lexer import TEXT, PUNCT, ParagraphToken, HeaderToken
from html_generator import (
    parse_block,
    _split_by_delimiter,
    generate_paragraph,
    generate_header,
    BOLD, ITALIC, LINK, BRACES, LATEX_INLINE, NOFORMAT
)


class TestSemanticTokens:
    """Test that semantic tokens format correctly."""

    def test_bold_formatting(self):
        """BOLD token formats to <strong>."""
        bold = BOLD([TEXT("text")])
        assert bold.get_formatted() == "<strong>text</strong>"

    def test_italic_formatting(self):
        """ITALIC token formats to <em>."""
        italic = ITALIC([TEXT("text")])
        assert italic.get_formatted() == "<em>text</em>"

    def test_link_formatting(self):
        """LINK token formats to <a href>."""
        link = LINK([TEXT("text")])
        html = link.get_formatted()
        assert "<a href=" in html
        assert "text" in html
        assert "</a>" in html

    def test_braces_formatting(self):
        """BRACES token formats to <code>."""
        braces = BRACES([TEXT("code()")])
        assert braces.get_formatted() == "<code>code()</code>"

    def test_latex_inline_formatting(self):
        """LATEX_INLINE token formats to <span class=math>."""
        latex = LATEX_INLINE([TEXT("x^2")])
        html = latex.get_formatted()
        assert "<span class=" in html
        assert "x^2" in html
        assert "</span>" in html

    def test_noformat_formatting(self):
        """NOFORMAT token just returns text."""
        noformat = NOFORMAT([TEXT("plain text")])
        assert noformat.get_formatted() == "plain text"


class TestSplitByDelimiter:
    """Test the delimiter parser."""

    def test_simple_text_no_delimiters(self):
        """Text without delimiters stays as NOFORMAT."""
        tokens = [TEXT("Hello world")]
        result = _split_by_delimiter(tokens)
        assert len(result) == 1
        assert isinstance(result[0], NOFORMAT)
        assert result[0].inner_string == "Hello world"

    def test_bold_detection(self):
        """Double asterisks create BOLD token."""
        tokens = [PUNCT("*"), PUNCT("*"), TEXT("bold"), PUNCT("*"), PUNCT("*")]
        result = _split_by_delimiter(tokens)
        assert any(isinstance(tk, BOLD) for tk in result)

    def test_italic_detection(self):
        """Single asterisks create ITALIC token."""
        tokens = [PUNCT("*"), TEXT("italic"), PUNCT("*")]
        result = _split_by_delimiter(tokens)
        assert any(isinstance(tk, ITALIC) for tk in result)

    def test_link_detection(self):
        """Brackets create LINK token."""
        tokens = [PUNCT("["), TEXT("link"), PUNCT("]")]
        result = _split_by_delimiter(tokens)
        assert any(isinstance(tk, LINK) for tk in result)

    def test_code_detection(self):
        """Braces create BRACES/CODE token."""
        tokens = [PUNCT("{"), TEXT("code()"), PUNCT("}")]
        result = _split_by_delimiter(tokens)
        assert any(isinstance(tk, BRACES) for tk in result)

    def test_latex_detection(self):
        """Dollar signs create LATEX_INLINE token."""
        tokens = [PUNCT("$"), TEXT("x^2"), PUNCT("$")]
        result = _split_by_delimiter(tokens)
        assert any(isinstance(tk, LATEX_INLINE) for tk in result)

    def test_mixed_formatting(self):
        """Multiple formats in one block."""
        tokens = [
            TEXT("Text with "),
            PUNCT("*"), PUNCT("*"), TEXT("bold"), PUNCT("*"), PUNCT("*"),
            TEXT(" and "),
            PUNCT("*"), TEXT("italic"), PUNCT("*")
        ]
        result = _split_by_delimiter(tokens)
        has_bold = any(isinstance(tk, BOLD) for tk in result)
        has_italic = any(isinstance(tk, ITALIC) for tk in result)
        assert has_bold and has_italic


class TestParseBlock:
    """Test the complete block parsing."""

    def test_simple_text(self):
        """Parse text without formatting."""
        tokens = [TEXT("Hello world")]
        result = parse_block(tokens)
        assert "Hello world" in result

    def test_with_bold(self):
        """Parse text with bold."""
        tokens = [TEXT("See "), PUNCT("*"), PUNCT("*"), TEXT("bold"), PUNCT("*"), PUNCT("*")]
        result = parse_block(tokens)
        assert "See" in result
        assert "<strong>bold</strong>" in result

    def test_with_italic(self):
        """Parse text with italic."""
        tokens = [TEXT("See "), PUNCT("*"), TEXT("italic"), PUNCT("*")]
        result = parse_block(tokens)
        assert "See" in result
        assert "<em>italic</em>" in result

    def test_with_code(self):
        """Parse text with code."""
        tokens = [TEXT("Use "), PUNCT("{"), TEXT("func()"), PUNCT("}")]
        result = parse_block(tokens)
        assert "Use" in result
        assert "<code>func()</code>" in result

    def test_with_latex(self):
        """Parse text with LaTeX."""
        tokens = [TEXT("Equation: "), PUNCT("$"), TEXT("x^2"), PUNCT("$")]
        result = parse_block(tokens)
        assert "Equation:" in result
        assert "<span class=" in result
        assert "x^2" in result


class TestGenerateParagraph:
    """Test paragraph HTML generation."""

    def test_simple_paragraph(self):
        """Generate HTML for simple paragraph."""
        pt = ParagraphToken()
        pt.inner_tokens = [TEXT("Hello world")]
        html = generate_paragraph(pt)
        assert html.startswith("<p>")
        assert html.endswith("</p>")
        assert "Hello world" in html

    def test_paragraph_with_bold(self):
        """Generate HTML for paragraph with bold."""
        pt = ParagraphToken()
        pt.inner_tokens = [TEXT("This is "), PUNCT("*"), PUNCT("*"), TEXT("bold"), PUNCT("*"), PUNCT("*")]
        html = generate_paragraph(pt)
        assert html.startswith("<p>")
        assert html.endswith("</p>")
        assert "<strong>bold</strong>" in html


class TestGenerateHeader:
    """Test header HTML generation."""

    def test_h1_header(self):
        """Generate H1 header."""
        ht = HeaderToken()
        ht.header_depth = 1
        ht.inner_tokens = [TEXT("My Heading")]
        html = generate_header(ht)
        assert html.startswith("<h1>")
        assert html.endswith("</h1>")
        assert "My Heading" in html

    def test_h3_header(self):
        """Generate H3 header."""
        ht = HeaderToken()
        ht.header_depth = 3
        ht.inner_tokens = [TEXT("Subsection")]
        html = generate_header(ht)
        assert "<h3>" in html
        assert "</h3>" in html
        assert "Subsection" in html

    def test_header_with_code(self):
        """Generate header with code."""
        ht = HeaderToken()
        ht.header_depth = 2
        ht.inner_tokens = [TEXT("Using "), PUNCT("{"), TEXT("function()"), PUNCT("}")]
        html = generate_header(ht)
        assert "<h2>" in html
        assert "</h2>" in html
        assert "<code>function()</code>" in html


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
