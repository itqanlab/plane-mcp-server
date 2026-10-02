"""State and label lists are compact by default; a sparse work item retrieve is only what was asked for."""

from __future__ import annotations

import pytest
from plane.models.labels import Label, PaginatedLabelResponse
from plane.models.states import PaginatedStateResponse, State
from plane.models.work_items import WorkItemDetail

from plane_mcp.tools import label as label_mod
from plane_mcp.tools import state as state_mod

PAGE = {
    "total_count": 1,
    "next_cursor": "n",
    "prev_cursor": "p",
    "next_page_results": False,
    "prev_page_results": False,
    "count": 1,
    "total_pages": 1,
    "total_results": 1,
}


def _state_page():
    row = State(
        id="s1",
        name="Todo",
        color="#000000",
        group="unstarted",
        sequence=25000,
        default=False,
        created_at="2026-10-02T00:00:00Z",
        created_by="u1",
        workspace="w1",
    )
    return PaginatedStateResponse(results=[row], **PAGE)


def _label_page():
    row = Label(
        id="l1",
        name="bug",
        color="#ff0000",
        parent=None,
        created_at="2026-10-02T00:00:00Z",
        created_by="u1",
        workspace="w1",
    )
    return PaginatedLabelResponse(results=[row], **PAGE)


@pytest.mark.parametrize(
    ("tool", "path", "page", "compact"),
    [
        ("state", "states.list", _state_page, state_mod.COMPACT_ROW),
        ("label", "labels.list", _label_page, label_mod.COMPACT_ROW),
    ],
)
def test_list_rows_are_compact_by_default(registered, spy, tool, path, page, compact):
    spy.returns[path] = page()

    result = registered[tool].fn(action="list", project_id="p1")

    assert set(result["results"][0]) == set(compact.split(","))
    assert result["next_cursor"] == "n", "compacting rows must not lose the cursor"


def test_state_compact_row_is_what_resolving_a_state_needs():
    assert state_mod.COMPACT_ROW.split(",") == ["id", "name", "group", "sequence", "default"]


def test_label_compact_row_is_what_resolving_a_label_needs():
    assert label_mod.COMPACT_ROW.split(",") == ["id", "name", "parent", "color"]


@pytest.mark.parametrize(
    ("tool", "path", "page"), [("state", "states.list", _state_page), ("label", "labels.list", _label_page)]
)
def test_fields_all_returns_every_field(registered, spy, tool, path, page):
    spy.returns[path] = page()

    row = registered[tool].fn(action="list", project_id="p1", fields="all")["results"][0]

    assert {"created_at", "created_by", "workspace"} <= set(row)


@pytest.mark.parametrize(
    ("tool", "path", "page"), [("state", "states.list", _state_page), ("label", "labels.list", _label_page)]
)
def test_explicit_fields_win_over_the_compact_default(registered, spy, tool, path, page):
    spy.returns[path] = page()

    row = registered[tool].fn(action="list", project_id="p1", fields="id,color")["results"][0]

    assert set(row) == {"id", "color"}


def test_workspace_state_list_is_compact_too(registered, spy):
    spy.returns["workspace_states.list"] = _state_page()

    row = registered["state"].fn(action="list")["results"][0]

    assert set(row) == set(state_mod.COMPACT_ROW.split(","))


def _detail():
    return WorkItemDetail(id="w1", name="n", description_html="<p>body</p>", target_date=None)


@pytest.mark.parametrize(
    ("path", "args"),
    [
        ("work_items.retrieve", {"action": "retrieve", "project_id": "p1", "workitem_id": "w1"}),
        ("work_items.retrieve_by_identifier", {"action": "retrieve_by_identifier", "workitem_identifier": "ENG-4"}),
    ],
)
def test_sparse_retrieve_returns_only_the_requested_keys(registered, spy, path, args):
    spy.returns[path] = _detail()

    result = registered["workitem"].fn(**args, fields="description_html")

    assert result == {"description_html": "<p>body</p>"}


@pytest.mark.parametrize(
    ("path", "args"),
    [
        ("work_items.retrieve", {"action": "retrieve", "project_id": "p1", "workitem_id": "w1"}),
        ("work_items.retrieve_by_identifier", {"action": "retrieve_by_identifier", "workitem_identifier": "ENG-4"}),
    ],
)
def test_a_requested_field_that_is_null_is_still_present(registered, spy, path, args):
    spy.returns[path] = _detail()

    result = registered["workitem"].fn(**args, fields="name,target_date")

    assert result == {"name": "n", "target_date": None}


def test_retrieve_without_fields_is_the_full_item(registered, spy):
    spy.returns["work_items.retrieve"] = _detail()

    result = registered["workitem"].fn(action="retrieve", project_id="p1", workitem_id="w1")

    assert isinstance(result, WorkItemDetail)
