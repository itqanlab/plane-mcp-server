"""Client-side filtering for editions that refuse pql (Community 1.4+)."""

from types import SimpleNamespace as NS

from plane_mcp.toolkit.paging import dump_results
from plane_mcp.toolkit.pql_fallback import edition_refuses_pql, filter_board

TODO, DONE = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
STATES = [NS(id=TODO, name="Todo"), NS(id=DONE, name="Done")]
PAGES = {
    None: NS(
        results=[
            {"sequence_id": 1, "state": TODO, "priority": "high"},
            {"sequence_id": 2, "state": DONE, "priority": "high"},
        ],
        next_cursor="c2",
        next_page_results=True,
    ),
    "c2": NS(
        results=[
            {"sequence_id": 3, "state": TODO, "priority": "low"},
            {"sequence_id": 4, "state": TODO, "priority": "high"},
        ],
        next_cursor=None,
        next_page_results=False,
    ),
}


def run(pql, fields=None):
    return filter_board(lambda cur: PAGES[cur], lambda: STATES, pql, fields, dump_results)


def test_filters_by_state_name_across_every_page():
    out = run('state = "Todo" AND priority = "high"')
    assert [r["sequence_id"] for r in out["results"]] == [1, 4]  # 2 is Done, 3 is low
    assert out["scanned"] == 4 and out["pql_applied"] == "client" and out["next_cursor"] is None


def test_excludes_rather_than_passing_everything_through():
    assert [r["sequence_id"] for r in run('state != "Todo"')["results"]] == [2]


def test_fields_trim_the_rows_but_the_filter_still_sees_its_own_fields():
    out = run('priority = "low"', fields="sequence_id")
    assert out["results"] == [{"sequence_id": 3}]


def test_unknown_state_name_names_the_known_ones():
    out = run('state = "Nope"')
    assert "Nope" in out["error"] and out["known_states"] == ["done", "todo"]


def test_unevaluable_pql_says_what_is_supported():
    out = run('name ~ "x"')
    assert "cannot be evaluated" in out["error"] and "state accepts a name" in out["supported_here"]


def test_edition_refusal_is_recognised():
    assert edition_refuses_pql("PQL and structured filters are not supported on this Plane edition.")
    assert not edition_refuses_pql("Invalid PQL near 'stat'")
