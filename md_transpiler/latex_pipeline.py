"""
Full LaTeX (.tex) -> HTML pipeline.

Uses Pandoc as the LaTeX parser/compiler backend (subprocess), then
post-processes the resulting math spans through the existing KaTeX
subprocess renderer, and wraps the result in the same HTML template
used by the markdown pipeline.
"""

import subprocess
import sys
from bs4 import BeautifulSoup

from html_generator import render_with_katex_batch
from pipeline import create_full_html


def run_pandoc(filepath):
    """
    Convert a .tex file to HTML via Pandoc, preserving raw LaTeX math
    (via --mathjax) instead of letting Pandoc flatten it to HTML/Unicode.
    """
    result = subprocess.run(
        ['pandoc', '-f', 'latex', '-t', 'html5', '--mathjax', filepath],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Pandoc failed:\n{result.stderr}")
    return result.stdout


def replace_math_spans(html):
    """
    Walk the Pandoc HTML output, replacing math spans with KaTeX-rendered
    HTML in place. All equations are rendered in a single batched call to
    avoid spawning one Node process per equation.
    """
    soup = BeautifulSoup(html, 'html.parser')
    spans = soup.find_all('span', class_='math')

    requests = []
    for span in spans:
        is_display = 'display' in span.get('class', [])
        tex = span.get_text().strip()
        if is_display:
            tex = tex.removeprefix('\\[').removesuffix('\\]')
        else:
            tex = tex.removeprefix('\\(').removesuffix('\\)')
        requests.append({'latex': tex, 'displayMode': is_display})

    rendered = render_with_katex_batch(requests)

    for span, rendered_html in zip(spans, rendered):
        is_display = 'display' in span.get('class', [])
        if is_display:
            rendered_html = f'<div class="math-block">{rendered_html}</div>'
        fragment = BeautifulSoup(rendered_html, 'html.parser')

        parent = span.parent
        only_child = is_display and parent.name == 'p' and len(parent.contents) == 1
        if only_child:
            parent.replace_with(fragment)
        else:
            span.replace_with(fragment)

    return str(soup)


def transpile_latex_file(filepath):
    """
    Read a .tex file and transpile it to a full HTML document.
    """
    pandoc_html = run_pandoc(filepath)
    content_html = replace_math_spans(pandoc_html)
    return create_full_html(content_html, title=filepath)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python latex_pipeline.py <tex_file> [output_file]")
        print("Example: python latex_pipeline.py pset_23_abbott.tex output.html")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"Transpiling {input_file}...")
    html = transpile_latex_file(input_file)

    if output_file:
        with open(output_file, 'w') as f:
            f.write(html)
        print(f"Written to {output_file}")
    else:
        print("\n" + "=" * 60)
        print(html)
        print("=" * 60)
