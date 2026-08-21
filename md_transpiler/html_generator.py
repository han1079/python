import enum
import dataclasses
from dataclasses import field
from lexer import BlockTokenType, HeaderToken, ParagraphToken
from lexer import TEXT, PUNCT, InlineToken
import subprocess
import json

def render_with_katex(latex_str, display_mode=False):
    mode = "true" if display_mode else "false"
    cmd = f'''
    const katex = require('katex');
    console.log(katex.renderToString({json.dumps(latex_str)},
    {{ displayMode: {mode} }}));
    '''
    result = subprocess.run(['node', '-e', cmd], 
                            capture_output=True, text=True)

    if result.returncode != 0:
        print(result.stderr)
        return f"<span class='error'>LaTeX rendering failed</span>"
    return result.stdout.strip()

@dataclasses.dataclass
class SemanticToken:
    tokens: list[InlineToken] = field(default_factory=list)

    @property
    def inner_string(self):
        return "".join(tk.content for tk in self.tokens)

    def get_formatted(self):
        return self.inner_string

@dataclasses.dataclass
class NOFORMAT(SemanticToken):
    tokens: list[InlineToken] = field(default_factory=list)

    def get_formatted(self):
        return self.inner_string

@dataclasses.dataclass
class BOLD(SemanticToken):
    tokens: list[InlineToken] = field(default_factory=list)

    def get_formatted(self):
        return f'<strong>{self.inner_string}</strong>'

@dataclasses.dataclass 
class ITALIC(SemanticToken):
    tokens: list[InlineToken] = field(default_factory=list)

    def get_formatted(self):
        return f'<em>{self.inner_string}</em>'

@dataclasses.dataclass 
class LINK(SemanticToken):
    tokens: list[InlineToken] = field(default_factory=list)

    def get_formatted(self):
        return f'<a href="url">{self.inner_string}</a>'

# Putting this as code for now, will need to reuse later for 
# LaTeX parsing.
@dataclasses.dataclass 
class BRACES(SemanticToken):
    tokens: list[InlineToken] = field(default_factory=list)

    def get_formatted(self):
        return f'<code>{self.inner_string}</code>'
    
@dataclasses.dataclass 
class LATEX_INLINE(SemanticToken):
    tokens: list[InlineToken] = field(default_factory=list)

    def get_formatted(self):
        latex_string = f'{self.inner_string}'
        return render_with_katex(latex_string)

@dataclasses.dataclass 
class LATEX_BLOCK(SemanticToken):
    tokens: list[InlineToken] = field(default_factory=list)

    def get_formatted(self):
        latex_string = f'{self.inner_string}'
        return f'<div class="math-block">{render_with_katex(latex_string, True)}</div>'
def _match_right_closure(tokens, idx, right_closure):
    steps = len(right_closure)
    
    idx += steps
    while idx < len(tokens):
        window = tokens[idx:idx+steps]
        windowstr = "".join(w.content for w in window)
        
        
        if windowstr == right_closure:
            return idx

        if len(windowstr) < steps:
            raise Exception(f"Reached end of tokens, but no right closure.")
        idx += 1
    return idx


def _handle_left_closure(tokens, idx):
    init_idx = idx
    left_closure = tokens[init_idx].content

    def list_get(tokens, idx):
        try:
            return tokens[idx].content
        except IndexError:
            return None

    if left_closure == "[": 
        idx = _match_right_closure(tokens, init_idx, "]")
        return LINK(tokens[init_idx+1:idx]), idx+1
    if left_closure == "{":
        idx = _match_right_closure(tokens, init_idx, "}")
        return BRACES(tokens[init_idx+1:idx]), idx+1

    if left_closure == "*" and list_get(tokens, init_idx+1) == "*":
        idx = _match_right_closure(tokens, init_idx, "**")
        return BOLD(tokens[init_idx+2:idx]), idx+2

    if left_closure == "*" and list_get(tokens, init_idx+1) != "*":
        idx = _match_right_closure(tokens, init_idx, "*")
        return ITALIC(tokens[init_idx+1:idx]), idx+1

    if left_closure == "$" and list_get(tokens, init_idx+1) == "$":
        idx = _match_right_closure(tokens, init_idx, "$$")
        return LATEX_BLOCK(tokens[init_idx+2:idx]), idx+2

    if left_closure == "$" and list_get(tokens, init_idx+1) != "$":
        idx = _match_right_closure(tokens, init_idx, "$")
        return LATEX_INLINE(tokens[init_idx+1:idx]), idx+1

def _split_by_delimiter(tokens: list):
    split_text = []
    semtk = NOFORMAT()
    idx = 0

    while idx < len(tokens):
        if isinstance(tokens[idx], TEXT):
            semtk.tokens.append(tokens[idx])
        elif isinstance(tokens[idx], PUNCT):
            if tokens[idx].content in ("[", "{", "*", "$"):
                if semtk != NOFORMAT():
                    split_text.append(semtk)
                    semtk = NOFORMAT()
                tok, idx = _handle_left_closure(tokens, idx)
                split_text.append(tok)
                continue
            else:
                semtk.tokens.append(tokens[idx])
        else:
            raise TypeError(f"Not an appropriate type.")

        idx += 1
    
    if semtk != NOFORMAT():
        split_text.append(semtk)

    return split_text

def parse_block(tokens: list):
    split_text = _split_by_delimiter(tokens)
    raw_text = "".join(tk.get_formatted() for tk in split_text)
    
    return raw_text

def generate_paragraph(pt: ParagraphToken):
    
    return f"<p>{parse_block(pt.inner_tokens)}</p>"

def generate_header(ht: HeaderToken):
    
    return f"<h{ht.header_depth}>{parse_block(ht.inner_tokens)}</h{ht.header_depth}>"
