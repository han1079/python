import enum
import dataclasses
from dataclasses import field

class BlockTokenType(enum.Enum):
    HEADING = 'HEADING'
    PARAGRAPH = 'PARAGRAPH'
    LEADING_NEWLINE = 'LEADING_NEWLINE'

@dataclasses.dataclass
class BlockToken:
    token_type: BlockTokenType = field(default=BlockTokenType.PARAGRAPH)
    raw_block: list =  field(default_factory=list) 
    raw_text: str = field(default='')
    inner_tokens: list =  field(default_factory=list) 

    def add_raw(self, tk):
        self.raw_block.append(tk)
        self.raw_text += tk

@dataclasses.dataclass
class LeadingNLBlock(BlockToken):
    token_type: BlockTokenType = field(default=BlockTokenType.LEADING_NEWLINE)

@dataclasses.dataclass
class HeaderToken(BlockToken):
    header_depth: int = field(default=0)
    token_type: BlockTokenType = field(default=BlockTokenType.HEADING)

@dataclasses.dataclass
class ParagraphToken(BlockToken):
    token_type: BlockTokenType = field(default=BlockTokenType.PARAGRAPH)

def handle_header(raw, idx):
    tk = HeaderToken()
    assert(raw[idx] == '#')
    
    while idx < len(raw):
        tk.raw_block.append(raw[idx])
        if raw[idx] == '\n':
            # Scan for newlines until it hits a valid target. 
            # Strip all newlines and return the new index.
            i = 1

            while raw[idx + i] == '\n':
                i += 1
            idx += i
            break

        if raw[idx] == '#':
            tk.header_depth += 1
            idx += 1
            continue 
        
        tk.raw_text += raw[idx]
        idx += 1

    # Strip leading whitespace
    while tk.raw_text[0] == ' ':
        tk.raw_text = tk.raw_text[1:]

    return tk, idx


def _skip_over_newlines(raw, idx):
    while raw[idx] == '\n' and raw[idx + 1] == '\n':
        idx += 1

    return idx + 1

def handle_paragraph(raw, idx):
    tk = ParagraphToken()
    assert(raw[idx] != '\n')
    while idx < len(raw):
        tk.add_raw(raw[idx])

        # Check for newline as paragraph end
        if raw[idx] == '\n' and idx + 1 == len(raw):
            return tk, idx + 1

        if raw[idx] == '\n' and raw[idx + 1] == '\n':
            idx = _skip_over_newlines(raw, idx)
            return tk, idx
        else:
            idx += 1

    return tk, idx

    
def handle_leading_newline(raw, idx):
    tk = LeadingNLBlock()
    assert(raw[idx] == '\n')

    while idx < len(raw):
        # The first time the "latest" index is
        # not a newline - we're in business
        # return with the latest idx
        if raw[idx] != '\n':
            break
        tk.add_raw(raw[idx])

        idx += 1

    return tk, idx


def _delete_trailing_zeros(raw):
    less_raw = bytearray([])
    zeros_done = False
    for i in reversed(raw):
        if i == 0 and not zeros_done:
            continue
        else:
            zeros_done = True
        less_raw.append(i)
    less_raw = [chr(i) for i in reversed(less_raw)]
    return less_raw

def _delete_line_continuations(raw):
    result = []
    idx = 0
    while idx < len(raw):
        # Hanging backslash not great. Just suppress and don't 
        # even add it to the filtered bytestream
        if raw[idx] == '\\' and idx+1 == len(raw):
            idx += 1 
            continue

        # Backslash and newline should cancel out for line 
        # continuation
        if raw[idx] == '\\' and raw[idx+1] == '\n':
            idx += 2
            continue

        # Add everything else - including backslashes
        result.append(raw[idx])
        idx += 1

    return result

def _make_blocks(raw):
    bltokens = []
    idx = 0
    while idx < len(raw):
        if raw[idx] == '#':
            tk, idx = handle_header(raw, idx)
            bltokens.append(tk)
        elif raw[idx] == '\n':
            tk, idx = handle_leading_newline(raw, idx)
            bltokens.append(tk)
        else:
            tk, idx = handle_paragraph(raw, idx)
            bltokens.append(tk)

    return bltokens


@dataclasses.dataclass
class InlineToken:
    content: str

@dataclasses.dataclass 
class TEXT(InlineToken):
    content: str = field(default='')

@dataclasses.dataclass 
class PUNCT(InlineToken):
    content: str = field(default='')

PUNCTUATIONS =           ('[', ']', 
                          '(', ')', 
                          '{', '}',
                          '*', '`',
                          ';', ':',
                          ',', '.',
                          '$', '#',
                          '@', '%',
                          '/', '?',
                          '|', '-',
                          '_', '"', '\\')

def _handle_inline_text(raw, idx):
    emit = '' 
    while idx < len(raw):
        #if raw[idx] == '\\':
        #    # This way, we literally skip over detecting punctuations
        #    idx += 1
        #    emit += raw[idx]
        #    idx += 1
        #    continue

        if raw[idx] in PUNCTUATIONS:
            tk = TEXT(emit)
            return tk, idx

        emit += raw[idx]
        idx += 1


    tk = TEXT(emit)
    return tk, idx


def _make_inline_tokens(block):
    raw = block.raw_block
    idx = 0
    while idx < len(raw):
        if raw[idx] == '#' and isinstance(block, HeaderToken):
            idx += 1
            continue
        else:
            block.inner_tokens.append(PUNCT(raw[idx]))
            idx += 1
            continue
         
        tk, idx = _handle_inline_text(raw, idx)
        block.inner_tokens.append(tk)

if __name__ == '__main__':
    BUFLEN=8192
    # DELIBERATE JANK: ByteArray Parsing with known size buffer.
    raw = bytearray(BUFLEN)
    with open('test_inline.md', 'rb') as f:
        f.readinto(raw)

    raw = _delete_trailing_zeros(raw)
    raw = _delete_line_continuations(raw)

    blocks = _make_blocks(raw)

    for block in blocks:
        _make_inline_tokens(block)
        print(block.inner_tokens)
    
