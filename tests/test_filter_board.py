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


def test_count_groups_by_state_name_and_group():
    from plane_mcp.toolkit.pql_fallback import count_board

    states = [NS(id=TODO, name="Todo", group="unstarted"), NS(id=DONE, name="Done", group="completed")]
    by_name = count_board(lambda cur: PAGES[cur], lambda: states, "", "state_id", dump_results)
    assert by_name["total"] == 4 and by_name["groups"] == {"Todo": 3, "Done": 1}
    high = count_board(lambda cur: PAGES[cur], lambda: states, 'priority = "high"', "state__group", dump_results)
    assert high["total"] == 3 and high["groups"] == {"unstarted": 2, "completed": 1}


# A board shaped like the scheduler's question: which open tickets matter, and which went stale.
URGENT, HIGH, LOW, YESTERDAY, OLD = 10, 11, 12, 13, 14
BOARD = NS(
    results=[
        {"sequence_id": URGENT, "state": TODO, "priority": "urgent", "updated_at": "2026-10-01T09:00:00Z"},
        {"sequence_id": HIGH, "state": TODO, "priority": "high", "updated_at": "2026-09-01T09:00:00Z"},
        {"sequence_id": LOW, "state": TODO, "priority": "low", "updated_at": "2026-09-02T09:00:00Z"},
        {"sequence_id": YESTERDAY, "state": TODO, "priority": "none", "updated_at": "2026-10-01T23:59:59+00:00"},
        {"sequence_id": OLD, "state": DONE, "priority": "high", "updated_at": "2026-08-01T09:00:00.123456Z"},
    ],
    next_cursor=None,
    next_page_results=False,
)


CANCELLED = "33333333-3333-3333-3333-333333333333"
BOARD_STATES = [*STATES, NS(id=CANCELLED, name="Cancelled")]


def board(pql, fields="sequence_id", **kw):
    return filter_board(lambda cur: BOARD, lambda: BOARD_STATES, pql, fields, dump_results, **kw)


def seqs(out):
    return [r["sequence_id"] for r in out["results"]]


def test_stale_recipe_excludes_closed_and_recently_touched():
    out = board('state NOT IN ("Done", "Cancelled") AND updated_at < "2026-09-18"')
    assert sorted(seqs(out)) == [HIGH, LOW]  # urgent and yesterday are fresh; OLD is Done


def test_date_without_time_is_midnight_utc():
    assert sorted(seqs(board('updated_at >= "2026-10-01"'))) == [URGENT, YESTERDAY]
    assert seqs(board('updated_at > "2026-10-01T09:00:00Z"')) == [YESTERDAY]
    assert sorted(seqs(board('updated_at <= "2026-10-01T09:00:00Z"'))) == [URGENT, HIGH, LOW, OLD]


def test_created_at_is_evaluable_and_missing_dates_never_match():
    out = board('created_at < "2030-01-01"')
    assert out["results"] == [] and out["scanned"] == 5


def test_comparisons_are_for_dates_only_and_need_a_real_date():
    assert "dates only" in board('priority < "high"')["error"]
    assert "ISO date" in board('updated_at < "last week"')["error"]
    assert "dates only" in board('updated_at = "2026-09-18"')["error"]


def test_count_accepts_the_date_operators():
    from plane_mcp.toolkit.pql_fallback import count_board

    out = count_board(lambda cur: BOARD, lambda: BOARD_STATES, 'updated_at < "2026-09-18"', "", dump_results)
    assert out["total"] == 3  # HIGH, LOW, OLD
