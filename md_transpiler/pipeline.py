"""
Full markdown → HTML pipeline.
"""

from lexer import (
    _delete_trailing_zeros,
    _delete_line_continuations,
    _make_blocks,
    _make_inline_tokens,
    BlockTokenType
)
from html_generator import generate_paragraph, generate_header


def generate_html_document(blocks):
    """
    Walk through blocks and generate HTML.
    """
    html_parts = []

    for block in blocks:
        # Skip leading newlines (they're just whitespace)
        if block.token_type == BlockTokenType.LEADING_NEWLINE:
            continue

        # Tokenize inline content
        _make_inline_tokens(block)

        # Generate HTML based on block type
        if block.token_type == BlockTokenType.HEADING:
            html_parts.append(generate_header(block))
        elif block.token_type == BlockTokenType.PARAGRAPH:
            html_parts.append(generate_paragraph(block))

    return "\n".join(html_parts)

def create_full_html(content_html, title="Document"):
      return f"""<!DOCTYPE html>
  <html lang="en">
  <head>
      <meta charset="UTF-8">
      <meta name="viewport" content="width=device-width, initial-scale=1.0">
      <title>{title}</title>
      <link rel="stylesheet"
  href="https://cdn.jsdelivr.net/npm/katex@0.18.4/dist/katex.min.css">
      <link rel="preconnect" href="https://fonts.googleapis.com">
      <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
      <link href="https://fonts.googleapis.com/css2?family=CMU+Serif&1&display=swap" rel="stylesheet">
      <style>
          body {{
              font-family: 'Lora', 'Latin Modern Roman', 'Times New Roman', serif;
              max-width: 8.5in;
              margin: 1in auto;
              padding: 0;
              line-height: 1.1;
              color: #333;
              text-align: justify;
              font-size: 1.1em;
          }}
          h1, h2, h3, h4, h5, h6 {{
              font-weight: bold;
              margin-top: 1.5em;
              margin-bottom: 0.4em;
              text-align: left;
          }}
          h1 {{ font-size: 1.5em; }}
          h2 {{ font-size: 1.3em; }}
          h3 {{ font-size: 1.1em; }}
          p {{
              line-height: 1.1;
              margin-top: 0;
          }}
          .katex {{
              font-size: 1em;
              line-height: 1.1;
          }}
          .math-block {{
              display: block;
              text-align: center;
              margin: 1em 0;
              text-indent: 0;
          }}
      </style>
  </head>
  <body>
  {content_html}
  </body>
  </html>"""



def transpile_file(filepath):
    """
    Read markdown file and transpile to HTML.
    """
    # Read file
    raw = bytearray(8192)
    with open(filepath, 'rb') as f:
        f.readinto(raw)

    # Clean up
    raw = _delete_trailing_zeros(raw)
    raw = _delete_line_continuations(raw)

    # Tokenize blocks
    blocks = _make_blocks(raw)

    # Generate HTML
    content_html = generate_html_document(blocks)
    full_html = create_full_html(content_html, title=filepath)

    return full_html


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <markdown_file> [output_file]")
        print("Example: python pipeline.py test_basic.md output.html")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Transpiling {input_file}...")
    html = transpile_file(input_file)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(html)
        print(f"✓ Written to {output_file}")
    else:
        print("\n" + "=" * 60)
        print(html)
        print("=" * 60)
