"""Epics on an edition with no work item types: an epic is a work item with the Epic label.

Plane Community (1.4.x) does not serve the work item types API -- every types route is a
404 -- so `workitem_type resolve name=Epic` cannot hand back a type id. The rest of the epic
recipe (create with type_id, list with pql `type = "<id>"`) only needs an id that the
other calls understand, so on such an edition resolve answers with a label-backed id:

    label:<uuid of the project's "Epic" label>

`workitem create` / `update` turn that type_id into the label, and `workitem list` / `count`
turn `type = "label:<uuid>"` into `label = "<uuid>"`. A caller never has to know which
edition it is talking to.
"""

from __future__ import annotations

import re
from typing import Any

from plane.models.labels import CreateLabel

LABEL_TYPE_PREFIX = "label:"
EPIC = "Epic"
EPIC_COLOR = "#F97316"
LABEL_PAGES = 10

TYPES_UNAVAILABLE = (
    "Error: work item types are not available on this Plane edition (the types API is not "
    "served, as on Plane Community). Only Epic works here, as a project label; {name!r} "
    "cannot be resolved. Use a label for it instead."
)

_TYPE_CLAUSE = re.compile(
    r"""\btype(?:_id)?\s*(?P<op>!=|=)\s*(?P<q>["'])""" + re.escape(LABEL_TYPE_PREFIX) + r"""(?P<id>[^"']+)(?P=q)""",
    re.IGNORECASE,
)


def is_label_type(type_id: Any) -> bool:
    return isinstance(type_id, str) and type_id.startswith(LABEL_TYPE_PREFIX)


def label_of(type_id: str) -> str:
    return type_id[len(LABEL_TYPE_PREFIX) :]


def label_type_pql(pql: str) -> str:
    """`type = "label:<uuid>"` as `label = "<uuid>"`, which both PQL and the client filter read."""
    return _TYPE_CLAUSE.sub(lambda m: f'label {m.group("op")} "{m.group("id")}"', pql or "")


def _project_labels(client: Any, workspace_slug: str, project_id: str) -> list[Any]:
    labels: list[Any] = []
    cursor = None
    for _ in range(LABEL_PAGES):
        params = {"per_page": 100, **({"cursor": cursor} if cursor else {})}
        page = client.labels.list(workspace_slug=workspace_slug, project_id=project_id, params=params)
        labels.extend(page.results or [])
        if not getattr(page, "next_page_results", False) or not getattr(page, "next_cursor", None):
            break
        cursor = page.next_cursor
    return labels


def resolve_epic_label(client: Any, workspace_slug: str, project_id: str) -> dict[str, Any]:
    """The project's Epic label (created when missing) as a label-backed type."""
    found = next(
        (
            label
            for label in _project_labels(client, workspace_slug, project_id)
            if (label.name or "").strip().lower() == EPIC.lower()
        ),
        None,
    )
    created = found is None
    if created:
        found = client.labels.create(
            workspace_slug=workspace_slug, project_id=project_id, data=CreateLabel(name=EPIC, color=EPIC_COLOR)
        )
    return {
        "id": f"{LABEL_TYPE_PREFIX}{found.id}",
        "name": EPIC,
        "fallback": "label",
        "label_id": str(found.id),
        "label_created": created,
        "note": "This Plane edition has no work item types, so an epic is a work item carrying the "
        "project's Epic label. Pass id as type_id to `workitem create` / `update`, and list epics "
        "with pql='type = \"<id>\"'; both are translated to the label.",
    }
