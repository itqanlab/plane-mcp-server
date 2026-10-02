"""Rich text as an agent reads it: plain, short, and with its line structure kept.

A work item body is HTML. An agent reading it to pick, triage or verify a ticket needs the
words, not the markup, and usually only the first part. Raw HTML is several times the size
of the text it carries, so every read of it is paid for twice.
"""

from __future__ import annotations

import html
import re

DEFAULT_BODY_CHARS = 1500

# Elements whose boundaries are line boundaries. Turning them into newlines keeps headings,
# list items and paragraphs on their own lines, which is what makes a §-structured ticket
# readable as text. Every other tag becomes a space.
_BLOCK = r"(?:p|div|li|ul|ol|h[1-6]|tr|blockquote|pre|table)"
_BREAK = re.compile(rf"<br\s*/?>|</?{_BLOCK}(?:\s[^>]*)?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_SPACES = re.compile(r"[^\S\n]+")
_BLANKS = re.compile(r"\n\s*\n+")


def plain_text(rich: str | None) -> str:
    """HTML as plain text: tags stripped, entities unescaped, block elements on their own lines.

    Tags are stripped before entities are unescaped, so an escaped `&lt;code&gt;` in the body
    survives as the text `<code>` instead of being mistaken for markup.
    """
    text = _TAG.sub(" ", _BREAK.sub("\n", rich or ""))
    text = _SPACES.sub(" ", html.unescape(text).replace("\xa0", " "))
    lines = (line.strip() for line in text.split("\n"))
    return _BLANKS.sub("\n", "\n".join(lines)).strip()


def truncate(text: str, chars: int) -> tuple[str, bool]:
    """`text` cut to `chars` characters (0 means no cap), and whether anything was cut."""
    if chars and chars > 0 and len(text) > chars:
        return text[:chars], True
    return text, False
