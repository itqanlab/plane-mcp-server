"""workitem update/create: PROJ-N in place of uuids, state by name, priority untouched, escaped bodies flagged."""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from plane.errors.errors import HttpError

TODO = "11111111-1111-1111-1111-111111111111"
REVIEW = "22222222-2222-2222-2222-222222222222"
STATES = NS(results=[NS(id=TODO, name="Todo"), NS(id=REVIEW, name="In Review")])


def _written(state=REVIEW, description="<p>ok</p>"):
    data = {
        "id": "w",
        "sequence_id": 5,
        "name": "n",
        "state": state,
        "priority": "high",
        "parent": None,
        "updated_at": "t",
        "description_html": description,
    }
    return NS(model_dump=lambda: data)


@pytest.fixture
def board(spy):
    spy.returns["work_items.retrieve_by_identifier"] = NS(id="w-uuid", project="p-uuid")
    spy.returns["states.list"] = STATES
    spy.returns["work_items.update"] = _written()
    spy.returns["work_items.create"] = _written()
    return spy


def _call(spy, method):
    return next(call for call in spy.recorder.calls if call.method == method)


def test_identifier_and_state_name_in_one_call(registered, board):
    out = registered["workitem"].fn(action="update", workitem_identifier="pmcp-5", state="in review")

    target = _call(board, "work_items.retrieve_by_identifier").kwargs
    assert target["project_identifier"] == "PMCP" and target["issue_identifier"] == 5
    update = _call(board, "work_items.update").kwargs
    assert update["project_id"] == "p-uuid" and update["work_item_id"] == "w-uuid"
    assert update["data"].model_dump(exclude_unset=True) == {"state": REVIEW}
    assert out["state"] == REVIEW and out["state_name"] == "In Review" and out["priority"] == "high"
    assert out["description_escaped"] is False and "warning" not in out


def test_a_state_only_update_never_carries_priority(registered, board):
    registered["workitem"].fn(action="update", project_id="p", workitem_id="w", state=TODO)

    assert _call(board, "work_items.update").kwargs["data"].model_dump(exclude_unset=True) == {"state": TODO}


def test_unknown_state_name_lists_the_known_ones_and_writes_nothing(registered, board):
    out = registered["workitem"].fn(action="update", project_id="p", workitem_id="w", state="Shipped")

    assert out == "Error: unknown state 'Shipped' on this project. Known states: In Review, Todo."
    assert "work_items.update" not in board.recorder.methods


def test_both_forms_at_once_is_refused(registered, board):
    out = registered["workitem"].fn(action="update", workitem_identifier="PMCP-5", project_id="p", state="Todo")

    assert out.startswith("Error:") and "not both" in out
    assert not board.recorder.calls


def test_unknown_identifier_is_one_line(registered, board):
    board.returns["work_items.retrieve_by_identifier"] = HttpError("Not Found", 404, {})

    out = registered["workitem"].fn(action="update", workitem_identifier="PMCP-999", state="Todo")

    assert out == "Error: work item PMCP-999 not found."
    assert "work_items.update" not in board.recorder.methods


def test_create_takes_a_state_name(registered, board):
    out = registered["workitem"].fn(action="create", project_id="p", name="x", state="todo")

    assert _call(board, "work_items.create").kwargs["data"].state == TODO
    assert out["state_name"] == "In Review"  # what the server stored, named


@pytest.mark.parametrize(
    ("stored", "escaped"),
    [
        ("&lt;p&gt;hello&lt;/p&gt;", True),
        ("<p>&lt;h2&gt;Goal&lt;/h2&gt;</p>", True),
        ("<p>use a &lt;br&gt; here</p><p>and more</p>", False),
        ("<p>hello</p>", False),
    ],
)
def test_escaped_description_is_flagged_with_a_warning(stored, escaped, registered, board):
    board.returns["work_items.update"] = _written(description=stored)

    out = registered["workitem"].fn(action="update", project_id="p", workitem_id="w", name="x")

    assert out["description_escaped"] is escaped
    assert ("warning" in out) is escaped
    assert "state_name" not in out  # no state write, no states lookup
    assert "states.list" not in board.recorder.methods
