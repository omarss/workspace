"""Format-aware chunking.

Chunks are the unit of context we hand to Claude during generation. The
rules are intentionally simple:

* Markdown → split on ATX headings (H1/H2/H3), preserve the heading path
  so the LLM sees the section trail. Sections larger than the token budget
  are windowed with overlap.
* HTML     → strip tags, collapse whitespace, then window.
* Anything else (txt/rst/adoc/json/yaml/sgml/xml) → window by tokens
  directly; headings are not extracted.

Token counting uses tiktoken's `cl100k_base`. It's not Anthropic's tokenizer
but it's close enough to budget prompt sizes — we're sizing context, not
billing. Same choice made by most RAG pipelines built before Anthropic
shipped public token counts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from html.parser import HTMLParser

import tiktoken

MARKDOWN_EXTS = {".md", ".markdown", ".mdown", ".mkd"}
HTML_EXTS = {".html", ".htm", ".xhtml"}
# AsciiDoc / reST / SGML / JSON / YAML are all readable as plain text;
# we don't do format-specific parsing — just window.
PLAIN_EXTS = {
    ".txt",
    ".text",
    ".rst",
    ".adoc",
    ".asciidoc",
    ".json",
    ".yaml",
    ".yml",
    ".sgml",
    ".xml",
    ".log",
    ".vtt",
    ".srt",
}

TEXT_EXTS = MARKDOWN_EXTS | HTML_EXTS | PLAIN_EXTS


@dataclass
class Chunk:
    idx: int
    heading_path: str | None
    text: str
    token_count: int


@lru_cache(maxsize=1)
def _enc() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    return len(_enc().encode(text))


# ---------------------------------------------------------------------------
# HTML → text
# ---------------------------------------------------------------------------

_SKIP_TAGS = {"script", "style", "svg", "noscript"}


class _HtmlStripper(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._out.append(data)

    def text(self) -> str:
        raw = "".join(self._out)
        raw = re.sub(r"[ \t\f\v]+", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html: str) -> str:
    p = _HtmlStripper()
    try:
        p.feed(html)
        p.close()
    except Exception:
        # Malformed upstream HTML shouldn't kill the whole ingest run.
        pass
    return p.text()


# ---------------------------------------------------------------------------
# Chunking primitives
# ---------------------------------------------------------------------------


def _window_tokens(
    text: str,
    *,
    heading_path: str | None,
    start_idx: int,
    max_tokens: int,
    overlap: int,
) -> list[Chunk]:
    """Split `text` into token windows. Returns chunks numbered from `start_idx`.

    The overlap lets a section boundary sit *inside* two chunks instead of
    between them — important so the LLM never sees a sentence cut in half
    mid-answer."""
    enc = _enc()
    toks = enc.encode(text)
    if len(toks) <= max_tokens:
        return [
            Chunk(
                idx=start_idx,
                heading_path=heading_path,
                text=text,
                token_count=len(toks),
            )
        ]

    chunks: list[Chunk] = []
    stride = max(1, max_tokens - overlap)
    idx = start_idx
    start = 0
    while start < len(toks):
        end = min(start + max_tokens, len(toks))
        piece = enc.decode(toks[start:end])
        chunks.append(
            Chunk(
                idx=idx,
                heading_path=heading_path,
                text=piece,
                token_count=end - start,
            )
        )
        idx += 1
        if end == len(toks):
            break
        start += stride
    return chunks


_H_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$", re.MULTILINE)


def chunk_markdown(text: str, *, max_tokens: int, overlap: int) -> list[Chunk]:
    """Heading-anchored chunking. Sections inherit the full `H1 > H2 > H3` trail."""
    # Build a list of (heading_stack, body) pairs in document order.
    lines = text.splitlines()
    sections: list[tuple[list[str], list[str]]] = []
    stack: list[tuple[int, str]] = []  # (level, title)
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append(([t for _, t in stack], list(buf)))
        buf.clear()

    for line in lines:
        m = _H_RE.match(line)
        if m:
            flush()
            level = len(m.group(1))
            title = m.group(2).strip()
            # Pop same- or deeper-level headings so the stack always
            # reflects the current path from the root.
            while stack and stack[-1][0] >= level:
                stack.pop()
            stack.append((level, title))
        else:
            buf.append(line)
    flush()

    if not sections:
        # No headings at all — fall back to flat token windowing.
        return _window_tokens(
            text,
            heading_path=None,
            start_idx=0,
            max_tokens=max_tokens,
            overlap=overlap,
        )

    out: list[Chunk] = []
    next_idx = 0
    for path, lines_ in sections:
        body = "\n".join(lines_).strip()
        if not body:
            continue
        heading_path = " > ".join(path) if path else None
        pieces = _window_tokens(
            body,
            heading_path=heading_path,
            start_idx=next_idx,
            max_tokens=max_tokens,
            overlap=overlap,
        )
        out.extend(pieces)
        next_idx += len(pieces)
    return out


def chunk_file(text: str, ext: str, *, max_tokens: int, overlap: int) -> list[Chunk]:
    """Dispatch by extension. Unknown extensions fall back to plain windowing."""
    ext = ext.lower()
    if ext in MARKDOWN_EXTS:
        return chunk_markdown(text, max_tokens=max_tokens, overlap=overlap)
    if ext in HTML_EXTS:
        return _window_tokens(
            html_to_text(text),
            heading_path=None,
            start_idx=0,
            max_tokens=max_tokens,
            overlap=overlap,
        )
    return _window_tokens(
        text,
        heading_path=None,
        start_idx=0,
        max_tokens=max_tokens,
        overlap=overlap,
    )
