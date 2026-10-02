"""workitem_comment by PROJ-N, confirmed in a few fields instead of echoing the comment."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from plane.errors.errors import HttpError
from plane.models.projects import ProjectMember
from plane.models.work_items import WorkItemComment

ALICE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
BOB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"


@pytest.fixture
def board(spy):
    spy.returns["work_items.retrieve_by_identifier"] = NS(id="w-uuid", project="p-uuid")
    spy.returns["work_items.comments.create"] = WorkItemComment(
        id="c1", comment_html="<p>" + "x" * 2000 + "</p>", created_at="2026-10-02T10:00:00Z"
    )
    return spy


def _call(spy, method):
    return next(call for call in spy.recorder.calls if call.method == method)


def test_create_by_identifier_returns_the_short_shape(registered, board):
    out = registered["workitem_comment"].fn(action="create", workitem_identifier="pmcp-6", comment_html="<p>hi</p>")

    assert out == {
        "id": "c1",
        "workitem": "PMCP-6",
        "created_at": out["created_at"],
        "comment_chars": 2007,
        "comment_escaped": False,
    }
    assert str(out["created_at"]).startswith("2026-10-02")
    create = _call(board, "work_items.comments.create").kwargs
    assert create["project_id"] == "p-uuid" and create["work_item_id"] == "w-uuid"


def test_create_by_uuid_names_the_uuid(registered, board):
    out = registered["workitem_comment"].fn(action="create", project_id="p", workitem_id="w", comment_html="<p>hi</p>")

    assert out["workitem"] == "w" and "work_items.retrieve_by_identifier" not in board.recorder.methods


@pytest.mark.parametrize(
    ("stored", "escaped"),
    [("&lt;p&gt;hi&lt;/p&gt;", True), ("<p>&lt;b&gt;hi&lt;/b&gt;</p>", True), ("<p>hi</p>", False)],
)
def test_escaped_comment_is_flagged(stored, escaped, registered, board):
    board.returns["work_items.comments.create"] = WorkItemComment(id="c1", comment_html=stored)

    out = registered["workitem_comment"].fn(action="create", workitem_identifier="PMCP-6", comment_html="x")

    assert out["comment_escaped"] is escaped and ("warning" in out) is escaped


def test_update_returns_the_same_short_shape(registered, board):
    board.returns["work_items.comments.update"] = WorkItemComment(id="c1", comment_html="<p>edited</p>")

    out = registered["workitem_comment"].fn(
        action="update", project_id="p", workitem_id="w", comment_id="c1", comment_html="<p>edited</p>"
    )

    assert set(out) == {"id", "workitem", "created_at", "comment_chars", "comment_escaped"}


def test_list_by_identifier(registered, board):
    registered["workitem_comment"].fn(action="list", workitem_identifier="PMCP-6")

    assert _call(board, "work_items.comments.list").kwargs["work_item_id"] == "w-uuid"


def test_both_forms_is_refused(registered, board):
    out = registered["workitem_comment"].fn(
        action="create", workitem_identifier="PMCP-6", workitem_id="w", comment_html="<p>x</p>"
    )

    assert out.startswith("Error:") and "not both" in out and not board.recorder.calls


def test_unknown_identifier_writes_nothing(registered, board):
    board.returns["work_items.retrieve_by_identifier"] = HttpError("Not Found", 404, {})

    out = registered["workitem_comment"].fn(action="create", workitem_identifier="PMCP-999", comment_html="<p>x</p>")

    assert out == "Error: work item PMCP-999 not found."
    assert "work_items.comments.create" not in board.recorder.methods


def test_mentions_are_still_validated_before_the_write(registered, board):
    board.returns["projects.get_members"] = [ProjectMember(id=ALICE, is_active=True)]

    out = registered["workitem_comment"].fn(
        action="create", workitem_identifier="PMCP-6", comment_html=f"<p>@[{BOB}] look</p>"
    )

    assert isinstance(out, str) and BOB in out
    assert "work_items.comments.create" not in board.recorder.methods
    assert _call(board, "projects.get_members").kwargs["project_id"] == "p-uuid"
