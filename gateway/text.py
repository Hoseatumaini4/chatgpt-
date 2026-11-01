"""Turn model output into cheap, safe SMS text.

SMS is billed per segment: 160 characters in the basic GSM alphabet, but only
70 as soon as one character falls outside it (emoji, curly quotes, long dashes).
So we strip markdown, flatten typography to ASCII, and cap the length.
"""
from __future__ import annotations

import re
import unicodedata

_REPLACEMENTS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"',
    "–": "-", "—": "-", "−": "-",
    "…": "...", " ": " ", "•": "-", "·": "-",
    "→": "->", "←": "<-", "×": "x",
}

_MD_PATTERNS = [
    (re.compile(r"```.*?```", re.S), lambda m: m.group(0).strip("`")),
    (re.compile(r"`([^`]*)`"), r"\1"),
    (re.compile(r"\*\*(.+?)\*\*", re.S), r"\1"),
    (re.compile(r"__(.+?)__", re.S), r"\1"),
    (re.compile(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)"), r"\1"),
    (re.compile(r"^\s{0,3}#{1,6}\s*", re.M), ""),
    (re.compile(r"^\s*[*+]\s+", re.M), "- "),
    (re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)"), r"\1 \2"),
]


def to_sms_text(text: str, max_chars: int = 459) -> str:
    """Clean `text` for SMS and cut it to at most `max_chars` characters."""
    out = text or ""
    for pattern, repl in _MD_PATTERNS:
        out = pattern.sub(repl, out)
    for src, dst in _REPLACEMENTS.items():
        out = out.replace(src, dst)
    out = unicodedata.normalize("NFKD", out)
    out = "".join(ch for ch in out if not unicodedata.combining(ch))
    out = out.encode("ascii", "ignore").decode("ascii")
    out = re.sub(r"[ \t]+", " ", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return _truncate(out, max_chars)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    budget = limit - 3
    cut = text[:budget]
    # prefer ending on a sentence, but only if that keeps most of the content
    end = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if end >= int(budget * 0.6):
        return cut[: end + 1]
    space = cut.rfind(" ")
    if space >= int(budget * 0.6):
        cut = cut[:space]
    return cut.rstrip(" ,;:-") + "..."


def segments(text: str) -> int:
    """How many SMS segments `text` will cost (ASCII only, so 160 / 153)."""
    n = len(text)
    if n == 0:
        return 0
    return 1 if n <= 160 else -(-n // 153)
