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


# ---------------------------------------------------------------------------
# Editions that REFUSE pql (Plane 1.4+ Community answers 400 "not supported on this
# edition"). Plane's own advice is "filter results client-side", so do exactly that for
# the subset above, instead of handing the caller a refusal and a 4,000-token syntax guide
# for a language this edition will never accept.
# ---------------------------------------------------------------------------

EDITION_REFUSAL = "not supported on this plane edition"
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)
MAX_PAGES = 50  # 100 rows a page: a 5,000-item project is still one call


def edition_refuses_pql(detail: Any) -> bool:
    return EDITION_REFUSAL in str(detail).lower()


def _resolve_state_names(clauses, state_ids_by_name: dict[str, str]):
    """`state = "Todo"` is how people write it; rows carry the state's uuid."""
    unknown: list[str] = []
    resolved = []
    for field, op, values in clauses:
        if field == "state":
            mapped = []
            for value in values:
                if _UUID.match(value):
                    mapped.append(value)
                elif value.lower() in state_ids_by_name:
                    mapped.append(state_ids_by_name[value.lower()])
                else:
                    unknown.append(value)
            values = mapped
        resolved.append((field, op, values))
    return resolved, unknown


def filter_board(list_page, list_states, pql: str, fields: str | None, dump) -> dict[str, Any]:
    """Every row of a project that matches `pql`, filtered here.

    `list_page(cursor) -> response` fetches one page (no pql), `list_states() -> [state]`
    lists the project's states and `dump(results, fields)` serialises a page. Kept free of
    the tool module so it can be tested without a server.
    """
    try:
        clauses = parse(pql) if pql.strip() else []  # no pql: every row
    except Unevaluable as exc:
        return {
            "error": f"This Plane edition cannot filter server-side, and this pql cannot be "
            f"evaluated client-side ({exc}).",
            "supported_here": 'field = "v", field != "v", field IN ("a","b"), NOT IN, joined by AND. '
            "Fields: " + ", ".join(sorted(EVALUABLE_FIELDS)) + '. state accepts a name, e.g. state = "Todo".',
        }
    if any(field == "state" for field, _, _ in clauses):
        names = {str(s.name).lower(): str(s.id) for s in list_states()}
        clauses, unknown = _resolve_state_names(clauses, names)
        if unknown:
            return {"error": f"unknown state name(s): {unknown}", "known_states": sorted(names)}

    wanted = None
    if fields:
        wanted = ",".join(sorted({*fields.split(","), *(f for f, _, _ in clauses)}))
    rows: list[dict[str, Any]] = []
    cursor = None
    for _ in range(MAX_PAGES):
        response = list_page(cursor)
        rows.extend(dump(response.results, wanted))
        if not getattr(response, "next_page_results", False) or not response.next_cursor:
            break
        cursor = response.next_cursor
    else:
        return {"error": f"project has more than {MAX_PAGES * 100} work items; narrow the request"}

    matched = [r for r in rows if matches(r, clauses)]
    if fields:
        keep = {f.strip() for f in fields.split(",")}
        matched = [{k: v for k, v in r.items() if k in keep} for r in matched]
    return {
        "results": matched,
        "count": len(matched),
        "total_count": len(matched),
        "next_cursor": None,
        "next_page_results": False,
        "pql_applied": "client",
        "scanned": len(rows),
    }


def count_board(list_page, list_states, pql: str, group_by: str, dump) -> dict[str, Any]:
    """`count` for editions whose count endpoint is absent (Community answers 404).

    Counts the rows `filter_board` returns. group_by `state_id` and `state__group` are
    keyed by state name / group rather than uuid, so the answer reads without a lookup.
    """
    states = list(list_states())
    page = filter_board(list_page, lambda: states, pql, "sequence_id,state,priority", dump)
    if "error" in page:
        return page
    out: dict[str, Any] = {"total": page["count"], "counted": "client", "scanned": page["scanned"]}
    if group_by:
        by_id = {str(s.id): s for s in states}

        def key(row: dict[str, Any]) -> str:
            state = by_id.get(str(row.get("state")))
            if group_by == "state_id":
                return str(state.name) if state else str(row.get("state"))
            if group_by == "state__group":
                return str(getattr(state, "group", None) or "unknown")
            return str(row.get(group_by.removesuffix("_id")) or "none")

        groups: dict[str, int] = {}
        for row in page["results"]:
            groups[key(row)] = groups.get(key(row), 0) + 1
        out["group_by"] = group_by
        out["groups"] = dict(sorted(groups.items(), key=lambda kv: -kv[1]))
    return out
