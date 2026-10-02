"""workitem body: one ticket's description as plain text, with its state by name."""

from __future__ import annotations

from types import SimpleNamespace as NS

from plane.errors.errors import HttpError

ITEM = {
    "name": "Fix the thing",
    "state": {"id": "s1", "name": "In Review", "group": "started"},
    "priority": "high",
    "updated_at": "2026-10-02T10:00:00Z",
    "description_html": "<h2>Goal</h2><p>Make it &amp; ship it.</p>" + "<p>" + "x" * 3000 + "</p>",
}


def _item():
    return NS(model_dump=lambda include=None: {k: v for k, v in ITEM.items() if include is None or k in include})


def test_body_returns_plain_text_and_the_state_name(registered, spy):
    spy.returns["work_items.retrieve_by_identifier"] = _item()

    out = registered["workitem"].fn(action="body", workitem_identifier="pmcp-3", chars=20)

    assert out == {
        "identifier": "PMCP-3",
        "name": "Fix the thing",
        "state": "In Review",
        "priority": "high",
        "updated_at": "2026-10-02T10:00:00Z",
        "text_chars": len("Goal\nMake it & ship it.\n") + 3000,
        "truncated": True,
        "text": "Goal\nMake it & ship ",
    }
    call = spy.recorder.only()
    assert call.kwargs["project_identifier"] == "PMCP" and call.kwargs["issue_identifier"] == 3
    assert call.kwargs["params"].expand == "state" and "description_html" in call.kwargs["params"].fields


def test_body_defaults_to_1500_chars_and_zero_means_everything(registered, spy):
    spy.returns["work_items.retrieve_by_identifier"] = _item()

    short = registered["workitem"].fn(action="body", workitem_identifier="PMCP-3")
    full = registered["workitem"].fn(action="body", workitem_identifier="PMCP-3", chars=0)

    assert len(short["text"]) == 1500 and short["truncated"]
    assert len(full["text"]) == full["text_chars"] and not full["truncated"]


def test_unknown_identifier_is_one_line(registered, spy):
    spy.returns["work_items.retrieve_by_identifier"] = HttpError("Not Found", 404, {"error": "not found"})

    out = registered["workitem"].fn(action="body", workitem_identifier="PMCP-999")

    assert out == "Error: work item PMCP-999 not found."


def test_malformed_identifier_never_reaches_plane(registered, spy):
    out = registered["workitem"].fn(action="body", workitem_identifier="PMCP")

    assert out.startswith("Error: invalid work item identifier") and not spy.recorder.calls
