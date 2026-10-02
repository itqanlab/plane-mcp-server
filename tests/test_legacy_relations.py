"""Tests for the legacy-relations fallback.

The failure this guards against is silent: on a deployment without the dependency
endpoints, a work item that plainly has relations comes back looking like one that has
none. An empty answer and a missing endpoint must not be indistinguishable.
"""

from types import SimpleNamespace

import pytest
from plane.errors.errors import HttpError

from plane_mcp.tools.workitem_relation import (
    LEGACY_RELATION_KINDS,
    REMOVE_UNSUPPORTED,
    _legacy_relations,
    _remove_relation,
)


def client_returning(payload):
    def _get(path):
        return payload

    return SimpleNamespace(work_items=SimpleNamespace(relations=SimpleNamespace(_get=_get)))


def client_raising(exc):
    def _get(path):
        raise exc

    return SimpleNamespace(work_items=SimpleNamespace(relations=SimpleNamespace(_get=_get)))


class TestLegacyRelations:
    def test_reads_relations_the_sdk_model_cannot_parse(self):
        """The API returns list[dict]; the SDK model demands list[str] and raises."""
        payload = {
            "blocked_by": [
                {"project_id": "p1", "issue_id": "i1"},
                {"project_id": "p1", "issue_id": "i2"},
            ],
            "blocking": [],
        }
        out = _legacy_relations(client_returning(payload), "ws", "p1", "wi")
        assert out["source"] == "legacy_relations_endpoint"
        assert [r["issue_id"] for r in out["dependencies"]["blocked_by"]] == ["i1", "i2"]

    def test_every_known_kind_is_present_even_when_empty(self):
        out = _legacy_relations(client_returning({"blocked_by": []}), "ws", "p", "wi")
        assert set(out["dependencies"]) == set(LEGACY_RELATION_KINDS)

    def test_unknown_kinds_are_reported_not_dropped(self):
        """A relation kind we do not know about must surface, not vanish."""
        out = _legacy_relations(
            client_returning({"blocked_by": [], "invented_kind": [{"issue_id": "x"}]}), "ws", "p", "wi"
        )
        assert out["unrecognised_relation_kinds"] == ["invented_kind"]

    def test_says_custom_relations_are_unavailable_here(self):
        out = _legacy_relations(client_returning({}), "ws", "p", "wi")
        assert out["custom"] == {}
        assert "custom relations are not available" in out["note"].lower()

    @pytest.mark.parametrize(
        "bad_client",
        [
            client_raising(HttpError(status_code=404, message="Not Found")),
            client_returning(["not", "a", "dict"]),
        ],
    )
    def test_returns_none_so_the_caller_reraises(self, bad_client):
        """Never invent an empty result — the caller must re-raise the original 404."""
        assert _legacy_relations(bad_client, "ws", "p", "wi") is None


def removal_client(remove_error, legacy_payload):
    """A client whose remove calls raise `remove_error` (or succeed when None)."""
    calls = []

    def remove(**kwargs):
        calls.append(kwargs)
        if remove_error:
            raise remove_error

    def _get(path):
        if isinstance(legacy_payload, Exception):
            raise legacy_payload
        return legacy_payload

    work_items = SimpleNamespace(
        dependencies=SimpleNamespace(remove=remove),
        custom_relations=SimpleNamespace(remove=remove),
        relations=SimpleNamespace(_get=_get),
    )
    return SimpleNamespace(work_items=work_items), calls


class TestRemoveRelation:
    def test_success_returns_none(self):
        client, calls = removal_client(None, {})
        assert _remove_relation(client, "ws", "p", "wi", "other", True) is None
        assert calls[0]["related_work_item_id"] == "other"

    def test_404_on_a_legacy_deployment_says_removal_is_unsupported(self):
        """A bare 404 reads like "relation not found"; the relation exists, the API can't delete it."""
        client, _ = removal_client(HttpError(status_code=404, message="Not Found"), {"blocked_by": []})
        assert _remove_relation(client, "ws", "p", "wi", "other", True) == REMOVE_UNSUPPORTED

    def test_404_with_no_legacy_endpoint_either_is_reraised(self):
        client, _ = removal_client(
            HttpError(status_code=404, message="Not Found"), HttpError(status_code=404, message="Not Found")
        )
        with pytest.raises(HttpError):
            _remove_relation(client, "ws", "p", "wi", "other", True)

    def test_other_errors_are_reraised(self):
        client, _ = removal_client(HttpError(status_code=403, message="Forbidden"), {})
        with pytest.raises(HttpError):
            _remove_relation(client, "ws", "p", "wi", "other", False)
