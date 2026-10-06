"""Source texts for the excerpt check: fetch a URL as plain text, normalize, find excerpts.

An excerpt "appears" in a source if, after normalizing both (HTML entities, Unicode quotes,
dashes and spaces, case, whitespace), it is a substring of the source text. An excerpt with an
ellipsis passes if each part (3+ words) appears, in order.
"""

from __future__ import annotations

import html
import io
import logging
import re
import unicodedata
from html.parser import HTMLParser

from apps.api.config import load_scoring
from apps.api.sources._http import SourceError, request

SKIP_TAGS = {"script", "style", "noscript", "head", "svg"}
BLOCK_TAGS = {"p", "div", "br", "tr", "li", "h1", "h2", "h3", "h4", "h5", "h6", "td", "th", "table"}

# Look-alike characters → ASCII, written as escapes so the source stays readable.
_QUOTES = str.maketrans(
    {
        **dict.fromkeys(["\u2018", "\u2019", "\u201a", "\u201b", "\u2032"], "'"),
        **dict.fromkeys(["\u201c", "\u201d", "\u201e", "\u2033"], '"'),
        **dict.fromkeys(["\u2010", "\u2011", "\u2013", "\u2014", "\u2212"], "-"),
        **dict.fromkeys(["\u00a0", "\u2009", "\u202f"], " "),
        "\u2026": "...",
    }
)


class _TextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in SKIP_TAGS:
            self._skip += 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in SKIP_TAGS and self._skip:
            self._skip -= 1
        elif tag in BLOCK_TAGS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def html_to_text(markup: str) -> str:
    parser = _TextParser()
    parser.feed(markup)
    parser.close()
    text = "".join(parser.parts).replace("\u00a0", " ")
    return re.sub(r"[ \t\r\f\v]+", " ", re.sub(r"\n\s*\n+", "\n\n", text)).strip()


def pdf_to_text(data: bytes) -> str:
    from pypdf import PdfReader

    logging.getLogger("pypdf").setLevel(logging.ERROR)  # font-encoding warnings are noise here

    reader = PdfReader(io.BytesIO(data))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(_QUOTES)
    text = re.sub(r"\s+", " ", text).casefold()
    # Table layouts split "$ 11,743" and "45 %"; join them so excerpts written naturally match.
    text = re.sub(r"\$ (?=\d)", "$", text)
    text = re.sub(r"(?<=\d) %", "%", text)
    text = re.sub(r"\( ", "(", text)
    return re.sub(r" \)", ")", text).strip()


def cap_words(excerpt: str, max_words: int) -> tuple[str, bool]:
    words = excerpt.split()
    if len(words) <= max_words:
        return excerpt.strip(), False
    return " ".join(words[:max_words]), True


def excerpt_in(excerpt: str, source_text: str) -> bool:
    haystack = normalize(source_text)
    needle = normalize(excerpt).strip(" .\"'")
    if not needle:
        return False
    if needle in haystack:
        return True
    parts = [p.strip(" .\"'") for p in re.split(r"\.\.\.|\[\.\.\.\]", needle)]
    parts = [p for p in parts if p]
    if len(parts) < 2 or any(len(p.split()) < 3 for p in parts):
        return False
    pos = 0
    for part in parts:
        found = haystack.find(part, pos)
        if found < 0:
            return False
        pos = found + len(part)
    return True


async def fetch_text(url: str) -> str:
    """The URL's content as plain text (HTML, PDF, JSON or text). Raises SourceError."""
    max_chars = int(load_scoring().research.get("source_text_max_chars", 3_000_000))
    resp = await request("web", url, timeout_s=90.0, retries=1)
    ctype = resp.headers.get("content-type", "").lower()
    if "pdf" in ctype or url.lower().endswith(".pdf"):
        try:
            text = pdf_to_text(resp.content)
        except Exception as e:  # malformed PDFs shouldn't crash a run
            raise SourceError("web", f"couldn't read PDF: {type(e).__name__}") from e
    elif (
        "html" in ctype
        or "xml" in ctype
        or resp.text.lstrip()[:15].lower().startswith(("<!doctype", "<html", "<?xml"))
    ):
        text = html_to_text(resp.text)
    else:
        text = resp.text
    return text[:max_chars]
