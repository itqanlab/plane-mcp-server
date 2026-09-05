"""Tests for the Community-edition pql fallback.

The behaviour under test is not "does it filter" — it is "does it ever return unfiltered
rows while looking like it filtered". That is the failure mode on Plane Community, where an
unsupported `pql` comes back as HTTP 200 with the whole board.
"""

import pytest

from plane_mcp.toolkit.pql_fallback import Unevaluable, apply_fallback, matches, parse

TODO = "6a626ac6-todo"
DONE = "08f1c549-done"


def row(seq, state=TODO, priority="high", **kw):
    return {"sequence_id": seq, "state": state, "priority": priority, **kw}


class TestParse:
    def test_equality(self):
        assert parse('state = "abc"') == [("state", "=", ["abc"])]

    def test_not_equal(self):
        assert parse('priority != "low"') == [("priority", "!=", ["low"])]

    def test_in_list(self):
        field, op, vals = parse('priority IN ("urgent", "high")')[0]
        assert (field, op) == ("priority", "IN")
        assert vals == ["urgent", "high"]

    def test_and_chains(self):
        assert len(parse('state = "a" AND priority = "urgent"')) == 2

    @pytest.mark.parametrize(
        "bad",
        [
            'state = "a" OR priority = "b"',  # OR not evaluated
            "assignee = currentUser()",  # function call
            'labels = "x"',  # field we refuse to guess at
            "",
        ],
    )
    def test_refuses_rather_than_guesses(self, bad):
        """Anything outside the supported subset must raise, never silently mis-evaluate."""
        with pytest.raises(Unevaluable):
            parse(bad)


class TestMatches:
    def test_equality_and_negation(self):
        clauses = parse(f'state = "{TODO}"')
        assert matches(row(1, state=TODO), clauses)
        assert not matches(row(2, state=DONE), clauses)

    def test_missing_field_never_matches_positive_filter(self):
        assert not matches({"sequence_id": 1}, parse('state = "x"'))

    def test_missing_field_passes_negative_filter(self):
        assert matches({"sequence_id": 1}, parse('state != "x"'))


class TestApplyFallback:
    def test_server_filtered_is_passed_through_untouched(self):
        rows = [row(1), row(2)]
        out = apply_fallback(f'state = "{TODO}"', rows)
        assert out["applied"] == "server"
        assert out["rows"] == rows
        assert "warning" not in out

    def test_one_bad_row_proves_the_filter_was_dropped(self):
        """The Community case: 200 OK, whole board, no error anywhere."""
        rows = [row(1, state=TODO), row(2, state=DONE), row(3, state=TODO)]
        out = apply_fallback(f'state = "{TODO}"', rows)
        assert out["applied"] == "client"
        assert [r["sequence_id"] for r in out["rows"]] == [1, 3]
        assert "ignored" in out["warning"].lower()

    def test_unevaluable_pql_is_reported_not_guessed(self):
        rows = [row(1), row(2, state=DONE)]
        out = apply_fallback("assignee = currentUser()", rows)
        assert out["applied"] == "unverified"
        assert out["rows"] == rows, "must not drop rows it cannot evaluate"
        assert "not confirmed" in out["warning"].lower()

    def test_and_filter_narrows_on_both_clauses(self):
        rows = [
            row(1, state=TODO, priority="urgent"),
            row(2, state=TODO, priority="low"),
            row(3, state=DONE, priority="urgent"),
        ]
        out = apply_fallback(f'state = "{TODO}" AND priority = "urgent"', rows)
        assert out["applied"] == "client"
        assert [r["sequence_id"] for r in out["rows"]] == [1]

    def test_empty_page_is_not_treated_as_proof(self):
        """No rows means nothing contradicts the filter; passing through is safe."""
        out = apply_fallback('state = "x"', [])
        assert out["applied"] == "server"
        assert out["rows"] == []
