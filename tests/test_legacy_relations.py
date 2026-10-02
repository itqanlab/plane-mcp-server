"""Tests for the legacy-relations fallback.

The failure this guards against is silent: on a deployment without the dependency
endpoints, a work item that plainly has relations comes back looking like one that has
none. An empty answer and a missing endpoint must not be indistinguishable.
"""

from types import SimpleNamespace

import pytest
from plane.errors.errors import HttpError

from plane_mcp.tools.workitem_relation import (
    CUSTOM_UNAVAILABLE,
    LEGACY_RELATION_KINDS,
    REMOVE_UNSUPPORTED,
    _legacy_create,
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


class FakeRelationsClient:
    """A client with no dependency or custom-relation endpoints, and a working legacy one.

    `legacy` holds what the legacy endpoint stores; `create` adds to it the way Plane does.
    """

    def __init__(self, legacy=None, dependency_error=None, legacy_create_error=None):
        self.legacy = legacy if legacy is not None else {"blocked_by": []}
        self.created = []
        not_found = HttpError(status_code=404, message="Not Found")
        self._dependency_error = dependency_error or not_found
        self._legacy_create_error = legacy_create_error

        def missing(**kwargs):
            raise self._dependency_error

        def _get(path):
            if isinstance(self.legacy, Exception):
                raise self.legacy
            return self.legacy

        def create(workspace_slug, project_id, work_item_id, data):
            if self._legacy_create_error:
                raise self._legacy_create_error
            self.created.append(data.model_dump())
            self.legacy.setdefault(data.relation_type, []).extend(
                {"project_id": project_id, "issue_id": i} for i in data.issues
            )
            return []

        self.work_items = SimpleNamespace(
            dependencies=SimpleNamespace(create=missing),
            custom_relations=SimpleNamespace(create=missing),
            relations=SimpleNamespace(_get=_get, create=create),
        )


@pytest.fixture
def relation_tool(monkeypatch):
    """The registered workitem_relation tool, wired to a client the test supplies."""
    import asyncio

    from fastmcp import FastMCP

    from plane_mcp.tools import workitem_relation as module

    mcp = FastMCP("t")
    module.register(mcp)
    tool = asyncio.new_event_loop().run_until_complete(mcp.get_tool(module.NAME))

    def bind(client):
        monkeypatch.setattr(module, "get_plane_client_context", lambda: (client, "ws"))
        return tool.fn

    return bind


class TestCreateFallback:
    def test_404_on_dependencies_creates_through_the_legacy_endpoint(self, relation_tool):
        client = FakeRelationsClient()
        out = relation_tool(client)(
            action="create", project_id="p", workitem_id="wi", workitem_ids=["a", "b"], relation_type="blocked_by"
        )
        assert client.created == [{"relation_type": "blocked_by", "issues": ["a", "b"]}]
        assert out == {
            "workitem_id": "wi",
            "relation_type": "blocked_by",
            "related_workitem_ids": ["a", "b"],
            "source": "legacy_relations_endpoint",
        }

    def test_confirmation_flags_targets_the_read_back_does_not_show(self):
        client = FakeRelationsClient()
        client.work_items.relations.create = lambda **kwargs: []  # accepted, but stored nothing
        out = _legacy_create(client, "ws", "p", "wi", "blocked_by", ["a"])
        assert out["related_workitem_ids"] == []
        assert out["not_confirmed"] == ["a"]

    def test_unsupported_type_is_a_clear_error_and_nothing_is_sent(self):
        client = FakeRelationsClient()
        out = _legacy_create(client, "ws", "p", "wi", "invented", ["a"])
        assert out.startswith("Error:") and "Nothing was changed" in out
        assert client.created == []

    def test_a_400_from_the_legacy_endpoint_is_reported_not_raised(self):
        client = FakeRelationsClient(legacy_create_error=HttpError(status_code=400, message="Bad Request"))
        out = _legacy_create(client, "ws", "p", "wi", "blocked_by", ["a"])
        assert out.startswith("Error: Plane refused the blocked_by relation")

    def test_non_404_from_dependencies_is_reraised(self, relation_tool):
        client = FakeRelationsClient(dependency_error=HttpError(status_code=403, message="Forbidden"))
        with pytest.raises(HttpError) as info:
            relation_tool(client)(
                action="create", project_id="p", workitem_id="wi", workitem_ids=["a"], relation_type="blocked_by"
            )
        assert info.value.status_code == 403
        assert client.created == []

    def test_404_with_no_legacy_endpoint_either_is_reraised(self, relation_tool):
        client = FakeRelationsClient(legacy=HttpError(status_code=404, message="Not Found"))
        with pytest.raises(HttpError):
            relation_tool(client)(
                action="create", project_id="p", workitem_id="wi", workitem_ids=["a"], relation_type="blocked_by"
            )

    def test_custom_relation_says_it_is_not_available_here(self, relation_tool):
        client = FakeRelationsClient()
        out = relation_tool(client)(
            action="create",
            project_id="p",
            workitem_id="wi",
            workitem_ids=["a"],
            relation_definition_id="def",
            relation_definition_label="causes",
        )
        assert out == CUSTOM_UNAVAILABLE
        assert client.created == []
