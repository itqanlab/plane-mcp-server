"""PMCP-15, end to end through the workitem tool on a Community-shaped Plane.

The fake Plane below behaves like Community 1.4: no count endpoint, pql refused on
list, and `fields` honoured, so a row carries only the columns that were asked for.
That last part is what hid the bug: a count that never asked for `created_at`
saw None on every row and returned 0.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from plane.errors.errors import HttpError

from plane_mcp.tools import workitem as workitem_module

PROJECT = "33b047c5-5a5d-436f-922d-6add83764fbe"
TODO = "11111111-1111-1111-1111-111111111111"
DONE = "22222222-2222-2222-2222-222222222222"
EPIC = "99999999-9999-9999-9999-999999999999"
BUG = "88888888-8888-8888-8888-888888888888"
REFUSAL = "PQL and structured filters are not supported on this Plane edition."

BOARD = [
    {
        "id": "a1",
        "sequence_id": 1,
        "state": TODO,
        "priority": "high",
        "parent": None,
        "type_id": BUG,
        "created_at": "2026-09-20T10:00:00Z",
        "updated_at": "2026-10-06T10:00:00Z",
    },
    {
        "id": "a2",
        "sequence_id": 2,
        "state": DONE,
        "priority": "low",
        "parent": EPIC,
        "type_id": None,
        "created_at": "2026-10-04T23:59:59Z",
        "updated_at": "2026-10-04T23:59:59Z",
    },
    {
        "id": "a3",
        "sequence_id": 3,
        "state": TODO,
        "priority": "high",
        "parent": EPIC,
        "type_id": BUG,
        "created_at": "2026-10-05T00:00:01Z",
        "updated_at": "2026-10-05T00:00:01Z",
    },
    {
        "id": "a4",
        "sequence_id": 4,
        "state": DONE,
        "priority": "none",
        "parent": None,
        "type_id": None,
        "created_at": "2026-10-06T08:00:00Z",
        "updated_at": "2026-10-06T08:00:00Z",
    },
    {
        "id": "a5",
        "sequence_id": 5,
        "state": TODO,
        "priority": "urgent",
        "parent": EPIC,
        "type_id": None,
        "created_at": "2026-10-07T12:00:00Z",
        "updated_at": "2026-10-07T12:00:00Z",
    },
]
# created_at > "2026-10-05" (midnight UTC): 3, 4, 5 match; 1 and 2 must be dropped.
AFTER = [3, 4, 5]


class FakeWorkItems:
    def __init__(self, board, withhold=()):
        self.board = board
        self.withhold = set(withhold)
        self.list_fields: list[str | None] = []

    def count_workspace(self, workspace_slug, params=None):
        raise HttpError("Not Found", status_code=404, response={"detail": "Not found."})

    def list(self, workspace_slug, project_id, params=None):
        if getattr(params, "pql", None):
            raise HttpError(REFUSAL, status_code=400, response={"error": REFUSAL})
        fields = getattr(params, "fields", None)
        self.list_fields.append(fields)
        wanted = set(fields.split(",")) if fields else None
        rows = [
            {k: v for k, v in row.items() if (wanted is None or k in wanted) and k not in self.withhold}
            for row in self.board
        ]
        return NS(results=rows, next_cursor=None, next_page_results=False, total_count=len(rows))


def _client(work_items):
    states = NS(results=[NS(id=TODO, name="Todo", group="unstarted"), NS(id=DONE, name="Done", group="completed")])
    return NS(work_items=work_items, states=NS(list=lambda workspace_slug, project_id: states))


@pytest.fixture
def plane(monkeypatch):
    def install(work_items):
        monkeypatch.setattr(workitem_module, "get_plane_client_context", lambda: (_client(work_items), "acme"))
        return work_items

    return install


def _call(registered, **kwargs):
    return registered["workitem"].fn(project_id=PROJECT, **kwargs)


def test_count_on_a_date_drops_the_older_rows_and_counts_the_rest(registered, plane):
    items = plane(FakeWorkItems(BOARD))
    out = _call(registered, action="count", pql='created_at > "2026-10-05"')
    assert out["total"] == len(AFTER), out
    # the column the clause reads was asked for, not just the four defaults
    assert any(f and "created_at" in f.split(",") for f in items.list_fields), items.list_fields


def test_count_and_list_agree_on_the_same_date_pql(registered, plane):
    plane(FakeWorkItems(BOARD))
    pql = 'created_at > "2026-10-05" AND state = "Todo"'
    listed = _call(registered, action="list", pql=pql, fields="sequence_id,created_at")
    counted = _call(registered, action="count", pql=pql)
    assert sorted(r["sequence_id"] for r in listed["results"]) == [3, 5]
    assert counted["total"] == listed["matched"] == 2


def test_count_on_updated_at_excludes_as_well(registered, plane):
    plane(FakeWorkItems(BOARD))
    out = _call(registered, action="count", pql='updated_at < "2026-10-05"')
    assert out["total"] == 1  # only #2; #1 was created early but touched later


def test_count_filtered_by_parent_fetches_parent_and_keeps_top_level_rows_out(registered, plane):
    items = plane(FakeWorkItems(BOARD))
    out = _call(registered, action="count", pql=f'parent = "{EPIC}" AND created_at > "2026-10-05"')
    assert out["total"] == 2  # #3 and #5; #2 is a child but too old, #4 is new but top level
    assert any(f and {"parent", "created_at"} <= set(f.split(",")) for f in items.list_fields), items.list_fields


def test_count_grouped_by_type_fetches_type_id(registered, plane):
    items = plane(FakeWorkItems(BOARD))
    out = _call(registered, action="count", pql='created_at > "2026-10-05"', group_by="type_id")
    assert out["total"] == 3 and sum(out["groups"].values()) == 3, out
    assert any(f and "type_id" in f.split(",") for f in items.list_fields), items.list_fields


def _is_error_naming(outcome, field):
    if isinstance(outcome, BaseException):
        return field in str(outcome)
    return isinstance(outcome, dict) and "error" in outcome and field in str(outcome["error"])


def _outcome(fn):
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 - either a raise or an error dict is acceptable
        return exc


@pytest.mark.parametrize("action", ["count", "list"])
def test_a_clause_column_missing_from_the_rows_is_an_error_not_a_zero(registered, plane, action):
    plane(FakeWorkItems(BOARD, withhold={"created_at"}))
    outcome = _outcome(lambda: _call(registered, action=action, pql='created_at > "2026-10-05"'))
    assert _is_error_naming(outcome, "created_at"), outcome


class HonoursPql(FakeWorkItems):
    """An edition that filters server-side and honours `fields`, like Plane Cloud."""

    def list(self, workspace_slug, project_id, params=None):
        fields = getattr(params, "fields", None)
        wanted = set(fields.split(",")) if fields else None
        rows = [
            {k: v for k, v in row.items() if wanted is None or k in wanted}
            for row in self.board
            if row["sequence_id"] in AFTER  # the server applied created_at > "2026-10-05"
        ]
        return NS(
            results=rows,
            next_cursor=None,
            prev_cursor=None,
            next_page_results=False,
            prev_page_results=False,
            total_count=len(rows),
            count=len(rows),
        )


def test_list_on_an_edition_that_filters_does_not_turn_trimmed_columns_into_a_false_zero(registered, plane):
    # The server filtered correctly and sent 3 rows, but `fields` left created_at out of
    # them. The client-side check must not read the missing column as "no match".
    plane(HonoursPql(BOARD))
    outcome = _outcome(lambda: _call(registered, action="list", pql='created_at > "2026-10-05"', fields="sequence_id"))
    if isinstance(outcome, dict) and "results" in outcome:
        assert sorted(r["sequence_id"] for r in outcome["results"]) == AFTER, outcome
    else:
        assert _is_error_naming(outcome, "created_at"), outcome
