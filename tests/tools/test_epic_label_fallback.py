"""Epics on an edition with no work item types (PMCP-23).

Plane Community 1.4 answers 404 on every work item types route. The epic recipe in the
server instructions (resolve the Epic type, create with type_id, list with pql
`type = "<id>"`, list children with childOf) must still work there, through the project's
Epic label.
"""

from __future__ import annotations

from types import SimpleNamespace as NS

import pytest
from plane.errors.errors import HttpError

from plane_mcp.toolkit.label_types import EPIC_COLOR, label_type_pql
from plane_mcp.tools import workitem as workitem_module

NOT_SERVED = HttpError("HTTP 404: Not Found", 404, {"error": "Page not found."})
EPIC_LABEL = "e0000000-0000-0000-0000-000000000001"
OTHER_LABEL = "e0000000-0000-0000-0000-000000000002"
EPIC_TYPE = f"label:{EPIC_LABEL}"


def _labels(*labels):
    return NS(results=list(labels), next_cursor=None, next_page_results=False)


# --- resolve -----------------------------------------------------------------------------


def test_resolve_epic_finds_the_existing_label(registered, spy):
    spy.returns["work_item_types.list"] = NOT_SERVED
    spy.returns["labels.list"] = _labels(NS(id=OTHER_LABEL, name="infra"), NS(id=EPIC_LABEL, name="epic"))

    out = registered["workitem_type"].fn(action="resolve", project_id="p-1", name="Epic")

    assert out["id"] == EPIC_TYPE and out["fallback"] == "label" and out["label_id"] == EPIC_LABEL
    assert out["label_created"] is False
    assert "labels.create" not in spy.recorder.methods


def test_resolve_epic_creates_the_label_when_missing(registered, spy):
    spy.returns["work_item_types.list"] = NOT_SERVED
    spy.returns["labels.list"] = _labels(NS(id=OTHER_LABEL, name="infra"))
    spy.returns["labels.create"] = NS(id=EPIC_LABEL, name="Epic")

    out = registered["workitem_type"].fn(action="resolve", project_id="p-1", name=" epic ")

    assert out["id"] == EPIC_TYPE and out["label_created"] is True
    sent = spy.recorder.calls[-1].kwargs["data"]
    assert (sent.name, sent.color) == ("Epic", EPIC_COLOR)


def test_resolve_another_type_on_community_says_types_are_unavailable(registered, spy):
    spy.returns["work_item_types.list"] = NOT_SERVED

    out = registered["workitem_type"].fn(action="resolve", project_id="p-1", name="Initiative")

    assert out.startswith("Error:") and "not available on this Plane edition" in out and "Initiative" in out
    assert spy.recorder.methods == ["work_item_types.list"]


def test_resolve_keeps_the_types_api_when_it_is_served(registered, spy):
    spy.returns["work_item_types.list"] = [NS(id="t-1", name="Epic")]

    out = registered["workitem_type"].fn(action="resolve", project_id="p-1", name="Epic")

    assert out.id == "t-1"
    assert spy.recorder.methods == ["work_item_types.list"]


def test_resolve_reraises_other_errors(registered, spy):
    spy.returns["work_item_types.list"] = HttpError("HTTP 500", 500, None)
    with pytest.raises(HttpError):
        registered["workitem_type"].fn(action="resolve", project_id="p-1", name="Epic")


# --- create / update ---------------------------------------------------------------------


def _sent(spy):
    return spy.recorder.calls[-1].kwargs["data"].model_dump(exclude_none=True)


def test_create_with_a_label_backed_type_sends_the_label_not_the_type(registered, spy):
    registered["workitem"].fn(action="create", project_id="p-1", name="Big thing", type_id=EPIC_TYPE)

    sent = _sent(spy)
    assert "type_id" not in sent
    assert sent["labels"] == [EPIC_LABEL]


def test_create_merges_the_epic_label_with_labels_passed(registered, spy):
    registered["workitem"].fn(
        action="create", project_id="p-1", name="Big thing", type_id=EPIC_TYPE, labels=[OTHER_LABEL]
    )

    assert _sent(spy)["labels"] == [OTHER_LABEL, EPIC_LABEL]


def test_update_with_a_label_backed_type_keeps_the_item_labels(registered, spy):
    spy.returns["work_items.retrieve"] = NS(labels=[OTHER_LABEL])

    registered["workitem"].fn(action="update", project_id="p-1", workitem_id="w-1", type_id=EPIC_TYPE)

    sent = _sent(spy)
    assert "type_id" not in sent and sent["labels"] == [OTHER_LABEL, EPIC_LABEL]


def test_update_does_not_duplicate_an_epic_label_already_passed(registered, spy):
    registered["workitem"].fn(
        action="update", project_id="p-1", workitem_id="w-1", type_id=EPIC_TYPE, labels=[EPIC_LABEL]
    )

    assert _sent(spy)["labels"] == [EPIC_LABEL]
    assert "work_items.retrieve" not in spy.recorder.methods


def test_a_real_type_id_is_sent_unchanged(registered, spy):
    registered["workitem"].fn(action="create", project_id="p-1", name="x", type_id="t-1")

    sent = _sent(spy)
    assert sent["type_id"] == "t-1" and "labels" not in sent


# --- list / count / childOf --------------------------------------------------------------

EPIC_ID = "a0000000-0000-0000-0000-000000000001"
REFUSAL = {"pql": "PQL and structured filters are not supported on this Plane edition."}
TODO = "11111111-1111-1111-1111-111111111111"


class CommunityBoard:
    """Refuses pql (1.4 Community), has no count endpoint, and resolves PROJ-N."""

    def __init__(self, rows):
        self.rows = rows
        self.lookups = []
        self.work_items = NS(
            list=self._list,
            count_workspace=self._count,
            retrieve_by_identifier=self._by_identifier,
        )
        self.states = NS(list=lambda **_: NS(results=[NS(id=TODO, name="Todo")]))

    def _list(self, workspace_slug, project_id, params):
        if params.pql:
            raise HttpError("Bad Request", 400, REFUSAL)
        return NS(results=self.rows, next_cursor=None, next_page_results=False)

    def _count(self, **_):
        raise NOT_SERVED

    def _by_identifier(self, workspace_slug, project_identifier, issue_identifier, params):
        self.lookups.append(f"{project_identifier}-{issue_identifier}")
        if issue_identifier == 1:
            return NS(id=EPIC_ID, project="p")
        raise HttpError("HTTP 404: Not Found", 404, None)


def _row(seq, labels=(), parent=None):
    return {
        "id": f"w-{seq}",
        "sequence_id": seq,
        "state": TODO,
        "priority": "none",
        "labels": list(labels),
        "parent": parent,
    }


@pytest.fixture
def community(monkeypatch):
    board = CommunityBoard(
        [
            _row(1, labels=[EPIC_LABEL]),
            _row(2, labels=[OTHER_LABEL], parent=EPIC_ID),
            _row(3, labels=[OTHER_LABEL, EPIC_LABEL]),
            _row(4, parent=EPIC_ID),
            _row(5),
        ]
    )
    monkeypatch.setattr(workitem_module, "get_plane_client_context", lambda: (board, "acme"))
    return board


def _seqs(out):
    return sorted(r["sequence_id"] for r in out["results"])


def test_type_pql_with_a_label_backed_id_reads_as_the_label():
    assert label_type_pql(f'type = "{EPIC_TYPE}"') == f'label = "{EPIC_LABEL}"'
    assert label_type_pql(f"type_id != '{EPIC_TYPE}' AND x") == f'label != "{EPIC_LABEL}" AND x'
    assert label_type_pql('type = "t-1"') == 'type = "t-1"'


def test_list_epics_by_label_backed_type(registered, community):
    out = registered["workitem"].fn(action="list", project_id="p", pql=f'type = "{EPIC_TYPE}"')

    assert _seqs(out) == [1, 3]


def test_list_items_that_are_not_epics(registered, community):
    out = registered["workitem"].fn(action="list", project_id="p", pql=f'type != "{EPIC_TYPE}"')

    assert _seqs(out) == [2, 4, 5]


def test_count_epics_by_label_backed_type(registered, community):
    out = registered["workitem"].fn(action="count", project_id="p", pql=f'type = "{EPIC_TYPE}"')

    assert out["total"] == 2, out


def test_list_children_with_child_of(registered, community):
    out = registered["workitem"].fn(action="list", project_id="p", pql='childOf("PMCP-1")')

    assert _seqs(out) == [2, 4]
    assert community.lookups == ["PMCP-1"]


def test_child_of_combines_with_other_clauses(registered, community):
    out = registered["workitem"].fn(action="list", project_id="p", pql=f'childOf("pmcp-1") AND label = "{OTHER_LABEL}"')

    assert _seqs(out) == [2]


def test_count_children_with_child_of(registered, community):
    out = registered["workitem"].fn(action="count", project_id="p", pql='childOf("PMCP-1")')

    assert out["total"] == 2, out


def test_child_of_an_unknown_item_is_an_error_not_an_empty_list(registered, community):
    out = registered["workitem"].fn(action="list", project_id="p", pql='childOf("PMCP-99")')

    assert "PMCP-99 not found" in out["error"]
