"""count and list read the same columns the pql names (PMCP-15).

count used to ask the server for four columns only, so a pql on any other column saw None on
every row and answered 0. The columns it asks for now come from its own request, and a column
the server did not send is an error rather than a silent non-match.
"""

from types import SimpleNamespace as NS

from plane_mcp.toolkit.paging import dump_results
from plane_mcp.toolkit.pql_fallback import count_board, count_fetch_fields, filter_board

TODO, DONE = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
STATES = [NS(id=TODO, name="Todo", group="unstarted"), NS(id=DONE, name="Done", group="completed")]


class Row:
    """A pydantic-like row: it dumps every key, but only some were sent by the backend."""

    def __init__(self, sent, **values):
        self.model_fields_set = set(sent)
        self.values = {"created_at": None, "parent": None, "sequence_id": None, **values}

    def model_dump(self, include=None):
        return {k: v for k, v in self.values.items() if include is None or k in include}


def backend(rows, asked):
    """A list_page that, like the real backend, sends only the columns it is asked for."""

    def list_page(cursor, fields):
        asked.append(fields)
        sent = set(fields.split(","))
        return NS(
            results=[Row(sent & {*r, "id"}, **r) for r in rows],
            next_cursor=None,
            next_page_results=False,
        )

    return list_page


DATED = [
    {"sequence_id": 1, "state": TODO, "priority": "high", "created_at": "2026-10-06T08:00:00Z", "parent": "P1"},
    {"sequence_id": 2, "state": TODO, "priority": "low", "created_at": "2026-10-05T21:00:00Z", "parent": "P1"},
    {"sequence_id": 3, "state": DONE, "priority": "low", "created_at": "2026-09-01T08:00:00Z", "parent": None},
]


def test_count_with_a_date_pql_matches_what_list_returns_for_the_same_pql():
    asked: list[str] = []
    pql = 'created_at > "2026-10-05"'
    page = backend(DATED, [])  # the list path sends no `fields`, so the backend returns every column
    listed = filter_board(
        lambda cur: page(cur, "sequence_id,state,priority,created_at"),
        lambda: STATES,
        pql,
        "sequence_id,created_at",
        dump_results,
    )
    counted = count_board(backend(DATED, asked), lambda: STATES, pql, "", dump_results)
    assert listed["matched"] == 2
    assert counted["total"] == listed["matched"]
    assert "created_at" in asked[0].split(",")


def test_count_fetches_the_columns_the_grouping_reads():
    asked: list[str] = []
    out = count_board(backend(DATED, asked), lambda: STATES, "", "parent", dump_results)
    assert out["groups"] == {"P1": 2, "none": 1}
    assert {"id", "sequence_id", "state", "priority", "parent"} <= set(asked[0].split(","))


def test_count_fetch_fields_come_from_the_clauses_not_a_fixed_list():
    assert count_fetch_fields("", "") == ["id", "priority", "sequence_id", "state"]
    assert "updated_at" in count_fetch_fields('updated_at < "2026-09-18" AND priority = "high"', "")
    assert "type_id" in count_fetch_fields('type_id = "T1"', "state_id")


def test_count_reports_a_clause_field_the_backend_left_out_instead_of_zero():
    def stingy(cursor, fields):  # ignores `fields`, never sends created_at
        rows = [Row({"id", "sequence_id", "state", "priority"}, **r) for r in DATED]
        return NS(results=rows, next_cursor=None, next_page_results=False)

    out = count_board(stingy, lambda: STATES, 'created_at > "2026-10-05"', "", dump_results)
    assert "total" not in out and "created_at" in out["error"]


def test_list_reports_a_clause_field_the_backend_left_out_instead_of_matching_nothing():
    rows = {None: NS(results=[{"sequence_id": 1, "state": TODO}], next_cursor=None, next_page_results=False)}
    out = filter_board(lambda cur: rows[cur], lambda: STATES, 'priority = "high"', None, dump_results)
    assert "results" not in out and "priority" in out["error"]


def test_a_null_the_backend_did_send_is_still_a_value_not_an_error():
    rows = [{"sequence_id": 3, "state": DONE, "priority": "low", "parent": None}]
    page = backend(rows, [])
    out = filter_board(
        lambda cur: page(cur, "sequence_id,state,priority,parent"),
        lambda: STATES,
        'parent != "P1"',
        "sequence_id",
        dump_results,
    )
    assert out["matched"] == 1
