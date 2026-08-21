from dataclasses import dataclass
from enum import Enum, auto
from typing import Any


class TT(Enum):
    LBRACE    = auto()
    RBRACE    = auto()
    COLON     = auto()
    COMMA     = auto()
    SEMICOLON = auto()
    STRING    = auto()   # quoted or unquoted word
    GRID_CELL = auto()   # <[name]> contents
    GRID_SEP  = auto()   # <[-]>, <[=]>, <=====>, etc.
    NEWLINE   = auto()
    EOF       = auto()


@dataclass
class Token:
    type: TT
    value: str


def lex(src: str) -> list[Token]:
    """Tokenize a tile block body."""
    tokens = []
    i = 0
    n = len(src)

    while i < n:
        c = src[i]

        if c in " \t\r":
            i += 1
            continue

        if c == "\n":
            tokens.append(Token(TT.NEWLINE, "\n"))
            i += 1
            continue

        if c == "{":
            tokens.append(Token(TT.LBRACE, "{"))
            i += 1
            continue

        if c == "}":
            tokens.append(Token(TT.RBRACE, "}"))
            i += 1
            continue

        if c == ":":
            tokens.append(Token(TT.COLON, ":"))
            i += 1
            continue

        if c == ",":
            tokens.append(Token(TT.COMMA, ","))
            i += 1
            continue

        if c == ";":
            tokens.append(Token(TT.SEMICOLON, ";"))
            i += 1
            continue

        if c == '"' or c == "'":
            quote = c
            i += 1
            start = i
            while i < n and src[i] != quote:
                i += 1
            tokens.append(Token(TT.STRING, src[start:i]))
            i += 1  # closing quote
            continue

        if c == "<":
            # Could be <[...> grid cell or <====> grid separator
            rest = src[i:]
            if rest.startswith("<["):
                end = rest.find("]>")
                if end != -1:
                    inner = rest[2:end].strip()
                    # Separator if inner is all = or - characters
                    if inner == "" or all(ch in "=-" for ch in inner):
                        tokens.append(Token(TT.GRID_SEP, inner))
                    else:
                        tokens.append(Token(TT.GRID_CELL, inner))
                    i += end + 2
                    continue
            # bare <=====>, <----> style separators
            j = i + 1
            while j < n and src[j] in "=-":
                j += 1
            if j > i + 1 and j < n and src[j] == ">":
                tokens.append(Token(TT.GRID_SEP, src[i+1:j]))
                i = j + 1
                continue

        # unquoted word / identifier
        start = i
        while i < n and src[i] not in " \t\r\n{}:,;<>\"'":
            i += 1
        if i > start:
            tokens.append(Token(TT.STRING, src[start:i]))
            continue

        # unknown character — skip
        i += 1

    tokens.append(Token(TT.EOF, ""))
    return tokens
