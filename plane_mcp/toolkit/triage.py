"""Pre-pick facts about a ticket that Plane alone can answer.

A scheduler about to claim a ticket wants to know, cheaply, whether it is stale, vague or
still waiting on a decision. These are the Plane-side checks from the plane-ship skill's
board.py `triage --stale`, kept here so the skill and the MCP read tickets the same way.

Every hit is a CANDIDATE for a human-sized look, never a verdict: "no migration needed"
matches the schema keyword "migration" too.

Repo-side checks (commits on the trunk naming the ticket, PRs, cited paths missing on the
trunk) are not here. They need the caller's git checkout, which an MCP server running in
its own directory, or on another host, cannot see. The paths below are handed back so the
caller can run those checks itself.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from plane_mcp.toolkit.pql_fallback import as_datetime

# The three patterns are board.py's, verbatim. Change them in both places or neither.
DECISION = re.compile(
    r"(?i)\b((owner|we|you) (to|must|should|will|needs? to) decide|decision needed|owner to confirm|"
    r"to be decided|tbd|open question|option [ab12]|which one|either .{0,40} or)\b"
)
VAGUE = re.compile(
    r"(?i)\b(everywhere|every (page|screen|place)|all (pages|screens|places)|across the app|the whole app|"
    r"wherever|similar places|and so on)\b"
)
DECIDED = re.compile(
    r"(?i)\b(decided|decision|owner (said|chose|confirmed|wants)|scope change|out of scope|dod override)"
)

SCHEMA_KEYWORDS = ("schema.prisma", "migration", "new column", "new model", "new field", "prisma migrate")
MAX_PATHS = 20
MAX_TICKETS = 25
# A comment posted with the triage write itself bumps updated_at a moment later; count it.
COMMENT_GRACE_SECONDS = 60

_PATH = re.compile(r"(?<![\w/.:-])((?:[\w.-]+/)+[\w.-]+)")
_EXTENSION = re.compile(r"\.[A-Za-z0-9]{1,8}$")
_TAG = re.compile(r"<[^>]+>")


def flat(text: str) -> str:
    """Whitespace collapsed to single spaces, so a pattern never trips over a line break."""
    return " ".join(text.split())


def keyword_hits(text: str, keywords: Iterable[str]) -> list[str]:
    lowered = text.lower()
    return sorted({word for word in keywords if word and word.lower() in lowered})


def cited_paths(text: str, prefixes: Iterable[str] = ()) -> list[str]:
    """Tokens shaped like repo paths: a `/` and a file extension, or a known top-level dir."""
    tops = {prefix.strip("/") for prefix in prefixes if prefix}
    found: set[str] = set()
    for token in _PATH.findall(text):
        token = token.rstrip(".")
        if "/" in token and (_EXTENSION.search(token) or token.split("/", 1)[0] in tops):
            found.add(token)
    return sorted(found)[:MAX_PATHS]


def decision_words(text: str) -> list[str]:
    return sorted({match.group(0).lower() for match in DECISION.finditer(text)})


def vague_scope(text: str, name: str) -> list[str]:
    return sorted({match.group(0).lower() for match in VAGUE.finditer(f"{text} {name}")})


def comment_facts(comments: list[Any], updated_at: Any) -> dict[str, Any]:
    """Counts over a ticket's comments: how many, how many carry a decision, how many are new."""
    bound = as_datetime(updated_at)
    after = 0
    latest = None
    decided = 0
    for comment in comments:
        created = as_datetime(getattr(comment, "created_at", None))
        if created and (latest is None or created > latest):
            latest = created
        if created and bound and (created - bound).total_seconds() > -COMMENT_GRACE_SECONDS:
            after += 1
        if DECIDED.search(_TAG.sub(" ", getattr(comment, "comment_html", None) or "")):
            decided += 1
    return {
        "comments": len(comments),
        "decision_comments": decided,
        "latest_comment_at": latest.isoformat() if latest else None,
        "comments_after_update": after,
    }
