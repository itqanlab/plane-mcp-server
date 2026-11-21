"""workitem list by external_source + external_id returns the row, not a validation error (PMCP-24)."""

import pytest
from plane.errors.errors import HttpError

from plane_mcp.toolkit.pql_fallback import matches, parse
from plane_mcp.tools.workitem import external_lookup

ROW = {"id": "u1", "sequence_id": 1558, "name": "n", "state": "s", "external_source": "sentry", "external_id": "42"}


def test_a_match_comes_back_as_one_row():
    calls = []

    def get(path, params):
        calls.append((path, params))
        return dict(ROW)

    out = external_lookup(get, "ws/projects/p/work-items", "sentry", "42", "sequence_id,state")
    assert out["count"] == 1 and out["results"] == [{"sequence_id": 1558, "state": "s"}]
    assert calls == [("ws/projects/p/work-items", {"external_source": "sentry", "external_id": "42"})]


def test_a_404_is_an_empty_list_not_an_error():
    def get(path, params):
        raise HttpError("Not Found", 404)

    out = external_lookup(get, "x", "sentry", "nope", None)
    assert out["results"] == [] and out["count"] == 0 and out["next_cursor"] is None


def test_other_http_errors_still_raise():
    def get(path, params):
        raise HttpError("boom", 500)

    with pytest.raises(HttpError):
        external_lookup(get, "x", "sentry", "42", None)


def test_a_paginated_answer_is_read_too():
    out = external_lookup(lambda p, params: {"results": [ROW]}, "x", "sentry", "42", None)
    assert out["results"] == [ROW]


def test_client_side_pql_evaluates_external_fields():
    clauses = parse('external_source = "sentry" AND external_id = "42"')
    assert matches(ROW, clauses)
    assert not matches({**ROW, "external_id": "43"}, clauses)
