"""The Plane-side pre-pick patterns: each must hit what it is for and miss the rest."""

from types import SimpleNamespace as NS

import pytest

from plane_mcp.toolkit.triage import (
    cited_paths,
    comment_facts,
    decision_words,
    flat,
    keyword_hits,
    vague_scope,
)


@pytest.mark.parametrize(
    ("text", "hits"),
    [
        ("Owner to decide between the two layouts.", ["owner to decide"]),
        ("Status: TBD. Option A keeps it.", ["option a", "tbd"]),
        ("either the drawer or the page", ["either the drawer or"]),
        ("We decided on the drawer. Ship option C.", []),
    ],
)
def test_decision_words(text, hits):
    assert decision_words(text) == hits


@pytest.mark.parametrize(
    ("text", "name", "hits"),
    [
        ("Fix the button everywhere", "", ["everywhere"]),
        ("Fix it on the invoice page", "Apply across the app", ["across the app"]),
        ("Fix the invoice page button", "Invoice button", []),
    ],
)
def test_vague_scope_reads_text_and_name(text, name, hits):
    assert vague_scope(text, name) == hits


def test_schema_keywords_are_case_insensitive_and_only_the_listed_ones():
    text = "Add a NEW COLUMN and run prisma migrate. No schema change elsewhere."
    assert keyword_hits(text, ("schema.prisma", "migration", "new column", "prisma migrate")) == [
        "new column",
        "prisma migrate",
    ]
    assert keyword_hits("nothing relevant", ("migration",)) == []


def test_paths_need_an_extension_or_a_known_top_level_dir():
    text = (
        "See libs/client/ui/src/button.ts and apps/server/src. Also and/or, 1/2, "
        "https://github.com/org/repo/blob/x.md and docs/adr/0021.md."
    )
    assert cited_paths(text) == ["docs/adr/0021.md", "libs/client/ui/src/button.ts"]
    assert cited_paths(text, ["apps"]) == ["apps/server/src", "docs/adr/0021.md", "libs/client/ui/src/button.ts"]


def test_flat_collapses_line_breaks_so_patterns_span_them():
    assert decision_words(flat("either the drawer\nor the page")) == ["either the drawer or"]


def test_comment_facts_count_decisions_and_comments_since_the_update():
    comments = [
        NS(created_at="2026-10-01T09:00:00Z", comment_html="<p>Started.</p>"),
        NS(created_at="2026-10-02T09:59:30Z", comment_html="<p><b>Decision</b>: drawer</p>"),
        NS(created_at="2026-10-02T11:00:00Z", comment_html="<p>Owner said use the page.</p>"),
    ]
    facts = comment_facts(comments, "2026-10-02T10:00:00Z")

    assert facts == {
        "comments": 3,
        "decision_comments": 2,
        "latest_comment_at": "2026-10-02T11:00:00+00:00",
        "comments_after_update": 2,  # the one 30s before the update still counts
    }


def test_comment_facts_with_no_comments():
    assert comment_facts([], "2026-10-02T10:00:00Z") == {
        "comments": 0,
        "decision_comments": 0,
        "latest_comment_at": None,
        "comments_after_update": 0,
    }
