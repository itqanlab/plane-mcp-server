"""workitem triage: several tickets in one call, Plane-side facts only, failures reported."""

from __future__ import annotations

from types import SimpleNamespace as NS

from plane.errors.errors import HttpError

ITEM = {
    "id": "w-uuid",
    "project": "p-uuid",
    "name": "Invoice drawer",
    "state": {"id": "s", "name": "Todo"},
    "priority": "high",
    "updated_at": "2026-10-02T10:00:00Z",
    "description_html": "<h2>Goal</h2><p>Add a new column in libs/server/data-access/prisma/schema.prisma.</p>"
    "<p>Owner to decide between option A and B.</p>",
}


def _item():
    return NS(model_dump=lambda include=None: {k: v for k, v in ITEM.items() if include is None or k in include})


def test_one_row_per_ticket_without_touching_comments(registered, spy):
    spy.returns["work_items.retrieve_by_identifier"] = _item()

    out = registered["workitem"].fn(
        action="triage", workitem_identifiers=["HLMNA-1", "hlmna-2"], path_prefixes=["libs"]
    )

    assert out["requested"] == 2 and out["failed"] == 0
    row = out["results"][0]
    assert row == {
        "identifier": "HLMNA-1",
        "name": "Invoice drawer",
        "state": "Todo",
        "priority": "high",
        "updated_at": "2026-10-02T10:00:00Z",
        "text_chars": row["text_chars"],
        "keywords": ["new column", "schema.prisma"],
        "paths": ["libs/server/data-access/prisma/schema.prisma"],
        "decision_words": ["option a", "owner to decide"],
        "vague_scope": [],
    }
    assert out["results"][1]["identifier"] == "HLMNA-2"
    assert spy.recorder.methods == ["work_items.retrieve_by_identifier"] * 2, "comments=false makes no comment call"


def test_comments_true_adds_the_comment_facts(registered, spy):
    spy.returns["work_items.retrieve_by_identifier"] = _item()
    spy.returns["work_items.comments.list"] = NS(
        results=[NS(created_at="2026-10-02T11:00:00Z", comment_html="<p>Decision: option A.</p>")],
        next_cursor=None,
        next_page_results=False,
    )

    row = registered["workitem"].fn(action="triage", workitem_identifiers=["HLMNA-1"], comments=True)["results"][0]

    assert row["comments"] == 1 and row["decision_comments"] == 1 and row["comments_after_update"] == 1
    listed = next(c for c in spy.recorder.calls if c.method == "work_items.comments.list").kwargs
    assert listed["project_id"] == "p-uuid" and listed["work_item_id"] == "w-uuid"


def test_a_ticket_that_fails_to_load_is_reported_not_dropped(registered, spy):
    spy.returns["work_items.retrieve_by_identifier"] = HttpError("Not Found", 404, {})

    out = registered["workitem"].fn(action="triage", workitem_identifiers=["HLMNA-999", "bogus"])

    assert out["requested"] == 2 and out["failed"] == 2
    assert out["results"][0] == {"identifier": "HLMNA-999", "error": "not found"}
    assert out["results"][1]["identifier"] == "BOGUS" and "invalid work item identifier" in out["results"][1]["error"]


def test_custom_keywords_replace_the_default_list(registered, spy):
    spy.returns["work_items.retrieve_by_identifier"] = _item()

    row = registered["workitem"].fn(action="triage", workitem_identifiers=["HLMNA-1"], keywords=["drawer", "goal"])[
        "results"
    ][0]

    assert row["keywords"] == ["goal"]  # the name is not searched for keywords


def test_more_than_25_is_refused_before_any_call(registered, spy):
    out = registered["workitem"].fn(action="triage", workitem_identifiers=[f"HLMNA-{n}" for n in range(26)])

    assert out.startswith("Error:") and "25" in out and not spy.recorder.calls
