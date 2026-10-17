"""workitem assignees: a uuid, an email or a display name, resolved against the project's members."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from plane.models.projects import ProjectMember

ALICE = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
BOB = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
BOB2 = "cccccccc-cccc-cccc-cccc-cccccccccccc"
GONE = "dddddddd-dddd-dddd-dddd-dddddddddddd"


def _members():
    return [
        ProjectMember(id=ALICE, email="alice@example.com", display_name="alice.ui", is_active=True),
        ProjectMember(id=BOB, email="bob@example.com", display_name="bob", is_active=True),
        ProjectMember(id=BOB2, email="bob@other.com", display_name="Bob", is_active=True),
        ProjectMember(id=GONE, email="gone@example.com", display_name="gone", is_active=False),
    ]


@pytest.fixture
def board(spy):
    spy.returns["projects.get_members"] = _members()
    spy.returns["work_items.update"] = NS(model_dump=lambda: {"id": "w", "assignees": [ALICE]})
    spy.returns["work_items.create"] = NS(model_dump=lambda: {"id": "w", "assignees": [ALICE]})
    spy.returns["work_items.retrieve"] = NS(assignees=[BOB])
    return spy


def _sent(spy, method="work_items.update"):
    return next(call for call in spy.recorder.calls if call.method == method).kwargs["data"]


@pytest.mark.parametrize("value", ["alice@example.com", "ALICE@example.com", "alice.ui", "@Alice.UI"])
def test_email_or_display_name_resolves_to_the_uuid(registered, board, value):
    out = registered["workitem"].fn(action="update", project_id="p", workitem_id="w", assignees=[value])

    assert _sent(board).assignees == [ALICE]
    assert out["assignees"] == [ALICE]


def test_create_resolves_names_too(registered, board):
    registered["workitem"].fn(action="create", project_id="p", name="x", assignees=["alice@example.com"])

    assert _sent(board, "work_items.create").assignees == [ALICE]


def test_uuids_make_no_members_call(registered, board):
    registered["workitem"].fn(action="update", project_id="p", workitem_id="w", assignees=[ALICE])

    assert "projects.get_members" not in board.recorder.methods
    assert _sent(board).assignees == [ALICE]


def test_clearing_assignees_makes_no_members_call(registered, board):
    registered["workitem"].fn(action="update", project_id="p", workitem_id="w", assignees=[])

    assert "projects.get_members" not in board.recorder.methods
    assert _sent(board).assignees == []


@pytest.mark.parametrize(
    ("value", "problem"),
    [("carol", "is not a member of this project"), ("gone", "is not a member"), ("bob", "more than one member")],
)
def test_unknown_or_ambiguous_names_write_nothing_and_list_members(registered, board, value, problem):
    out = registered["workitem"].fn(action="update", project_id="p", workitem_id="w", assignees=[value])

    assert out.startswith(f"Error: assignee '{value}'") and problem in out
    assert "alice.ui <alice@example.com>" in out and "gone@example.com" not in out
    assert "work_items.update" not in board.recorder.methods


def test_manage_assignee_resolves_both_sides(registered, board):
    registered["workitem"].fn(
        action="manage_assignee",
        project_id="p",
        workitem_id="w",
        add_user_id="alice@example.com",
        remove_user_id="bob@example.com",
    )

    assert _sent(board).assignees == [ALICE]


def test_manage_assignee_unknown_name_writes_nothing(registered, board):
    out = registered["workitem"].fn(action="manage_assignee", project_id="p", workitem_id="w", add_user_id="carol")

    assert out.startswith("Error: assignee 'carol'")
    assert "work_items.update" not in board.recorder.methods
