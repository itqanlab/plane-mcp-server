"""Client-side fallback for Plane deployments that silently ignore ``pql``.

WHY THIS EXISTS
---------------
Plane Community's public v1 issues endpoint has no server-side filtering. It does not
reject an unsupported ``pql`` — it returns **HTTP 200 with the whole board**. Measured on a
live Community v1.3.1 instance with 153 work items: ``?state=<uuid>``, ``?pql=...`` and no
filter at all returned byte-identical full boards.

That is worse than an error. A silently dropped filter is indistinguishable from a filter
that matched everything, so a caller asking for "the open tickets" gets every ticket
including ``Done`` ones, with a plausible ``total_count``, and no way to tell.

WHAT THIS DOES
--------------
1. Evaluates the requested ``pql`` against the rows the server returned.
2. If every row matches, the server honoured the filter — pass through untouched.
3. If any row does **not** match, the server ignored the filter. Say so, and filter locally.
4. If the ``pql`` uses syntax this module cannot evaluate, **do not guess**: return the rows
   with ``pql_verified: false`` so the caller knows the filter is unconfirmed.

The guiding rule: never silently return unfiltered rows for a filtered request.

SUPPORTED SUBSET
----------------
Deliberately small, covering the filters that matter for scheduling work:

    field = "value"        field != "value"
    field IN ("a", "b")    field NOT IN ("a", "b")
    ... AND ...

Fields: ``state``, ``priority``, ``type_id``, ``parent``, ``project``, ``sequence_id``,
``is_draft``. Anything else, and any ``OR``/function call, is treated as unevaluable —
which downgrades to the honest "unverified" path rather than a wrong answer.
"""

from __future__ import annotations

import re
from typing import Any

EVALUABLE_FIELDS = {
    "state",
    "priority",
    "type_id",
    "parent",
    "project",
    "sequence_id",
    "is_draft",
}

_CLAUSE = re.compile(
    r"""^\s*
    (?P<field>[A-Za-z_][A-Za-z0-9_]*)\s*
    (?P<op>!=|=|\bNOT\s+IN\b|\bIN\b)\s*
    (?P<value>\(.*?\)|"[^"]*"|'[^']*'|[^\s()]+)
    \s*$""",
    re.IGNORECASE | re.VERBOSE | re.DOTALL,
)


class Unevaluable(Exception):
    """The pql uses syntax this module will not guess at."""


def _unquote(tok: str) -> str:
    tok = tok.strip()
    if len(tok) >= 2 and tok[0] == tok[-1] and tok[0] in "\"'":
        return tok[1:-1]
    return tok


def _values(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("(") and raw.endswith(")"):
        inner = raw[1:-1]
        return [_unquote(p) for p in re.split(r",", inner) if p.strip()]
    return [_unquote(raw)]


def parse(pql: str) -> list[tuple[str, str, list[str]]]:
    """Parse a supported pql into (field, op, values). Raise Unevaluable otherwise."""
    if not pql or not pql.strip():
        raise Unevaluable("empty")
    if re.search(r"\bOR\b", pql, re.IGNORECASE):
        raise Unevaluable("OR is not evaluated client-side")
    if re.search(r"[A-Za-z_]+\s*\([^)]*\)\s*(AND|$)", pql, re.IGNORECASE) and not re.search(
        r"\b(IN|NOT\s+IN)\b", pql, re.IGNORECASE
    ):
        raise Unevaluable("function calls are not evaluated client-side")

    clauses = []
    for part in re.split(r"\bAND\b", pql, flags=re.IGNORECASE):
        m = _CLAUSE.match(part)
        if not m:
            raise Unevaluable(f"unparsed clause: {part.strip()!r}")
        field = m.group("field")
        if field not in EVALUABLE_FIELDS:
            raise Unevaluable(f"field not evaluable client-side: {field}")
        op = re.sub(r"\s+", " ", m.group("op").strip().upper())
        clauses.append((field, op, _values(m.group("value"))))
    if not clauses:
        raise Unevaluable("no clauses")
    return clauses


def _row_value(row: dict[str, Any], field: str) -> str | None:
    v = row.get(field)
    if v is None:
        return None
    return str(v)


def matches(row: dict[str, Any], clauses: list[tuple[str, str, list[str]]]) -> bool:
    for field, op, values in clauses:
        got = _row_value(row, field)
        vals = [str(v) for v in values]
        if op in ("=", "IN"):
            if got is None or got not in vals:
                return False
        elif op in ("!=", "NOT IN"):
            if got is not None and got in vals:
                return False
        else:  # pragma: no cover - parse() restricts the op set
            return False
    return True


def server_honoured_filter(rows: list[dict[str, Any]], clauses) -> bool:
    """True if every returned row satisfies the filter.

    A single non-matching row proves the server ignored it. All rows matching is not
    absolute proof it filtered — the board may simply contain only matches — but in that
    case the result is identical either way, so passing it through is safe.
    """
    return all(matches(r, clauses) for r in rows)


def apply_fallback(pql: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Decide what to do with `rows` for a `pql` request.

    Returns a dict describing the outcome:
      applied="server"    — server filtered; use rows unchanged
      applied="client"    — server ignored it; `rows` are the filtered subset
      applied="unverified"— pql not evaluable here; rows unchanged, caller warned
    """
    try:
        clauses = parse(pql)
    except Unevaluable as exc:
        return {
            "applied": "unverified",
            "rows": rows,
            "warning": (
                f"This deployment may ignore `pql` and return the whole board with HTTP 200. "
                f"This filter could not be checked client-side ({exc}), so the rows below are "
                f"NOT confirmed to match. Verify before relying on them, or filter locally."
            ),
        }

    if server_honoured_filter(rows, clauses):
        return {"applied": "server", "rows": rows}

    kept = [r for r in rows if matches(r, clauses)]
    return {
        "applied": "client",
        "rows": kept,
        "warning": (
            "This deployment ignored `pql` and returned unfiltered rows with HTTP 200 "
            "(Plane Community has no server-side filtering). The filter was applied "
            "client-side instead. Counts below describe the filtered set; paging reflects "
            "the server's unfiltered pages, so page through fully before treating a count "
            "as complete."
        ),
    }
