"""The workitem tool against an edition that refuses pql: what the caller asked for reaches the fallback."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from plane.errors.errors import HttpError

from plane_mcp.tools import workitem as workitem_module

TODO, DONE = "11111111-1111-1111-1111-111111111111", "22222222-2222-2222-2222-222222222222"
REFUSAL = {"pql": "PQL and structured filters are not supported on this Plane edition."}


class CommunityBoard:
    """Refuses pql with the 1.4 Community 400 and pages the whole project otherwise."""

    def __init__(self, rows):
        self.rows = rows
        self.page_params = []
        self.work_items = NS(list=self._list)
        self.states = NS(list=lambda **_: NS(results=[NS(id=TODO, name="Todo"), NS(id=DONE, name="Done")]))

    def _list(self, workspace_slug, project_id, params):
        if params.pql:
            raise HttpError("Bad Request", 400, REFUSAL)
        self.page_params.append(params)
        return NS(results=self.rows, next_cursor=None, next_page_results=False)


@pytest.fixture
def community(monkeypatch):
    board = CommunityBoard(
        [
            {"sequence_id": 1, "state": TODO, "priority": "low", "updated_at": "2026-09-01T00:00:00Z"},
            {"sequence_id": 2, "state": TODO, "priority": "urgent", "updated_at": "2026-09-02T00:00:00Z"},
            {"sequence_id": 3, "state": TODO, "priority": "high", "updated_at": "2026-10-01T00:00:00Z"},
            {"sequence_id": 4, "state": DONE, "priority": "urgent", "updated_at": "2026-08-01T00:00:00Z"},
        ]
    )
    monkeypatch.setattr(workitem_module, "get_plane_client_context", lambda: (board, "acme"))
    return board


def _list(registered, **kwargs):
    return registered["workitem"].fn(action="list", project_id="p", fields="sequence_id", **kwargs)


def test_per_page_caps_the_client_filtered_rows_in_priority_order(registered, community):
    out = _list(registered, pql='state = "Todo"', per_page=2)

    assert [r["sequence_id"] for r in out["results"]] == [2, 3]
    assert out["count"] == 2 and out["matched"] == 3 and out["scanned"] == 4


def test_order_by_is_applied_client_side_and_not_sent_to_the_pages(registered, community):
    out = _list(registered, pql='state = "Todo"', order_by="-updated_at")

    assert [r["sequence_id"] for r in out["results"]] == [3, 2, 1]
    assert all(params.order_by is None for params in community.page_params)


def test_an_unsupported_order_by_is_refused_not_ignored(registered, community):
    out = _list(registered, pql='state = "Todo"', order_by="name")

    assert "not supported" in out["error"] and "priority" in out["supported_order_by"]
    assert not community.page_params, "paged the board for an order it cannot honour"


def test_stale_recipe_through_the_tool(registered, community):
    out = _list(registered, pql='state NOT IN ("Done") AND updated_at < "2026-09-18"')

    assert [r["sequence_id"] for r in out["results"]] == [2, 1]
