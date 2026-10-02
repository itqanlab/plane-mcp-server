"""Labels within a project."""

from __future__ import annotations

from typing import Any, Literal

from fastmcp import FastMCP
from plane.models.labels import CreateLabel, Label, PaginatedLabelResponse, UpdateLabel

from plane_mcp.client import get_plane_client_context
from plane_mcp.toolkit import Action, build_annotations, build_description, envelope, missing, opt, page_params

NAME = "label"
TITLE = "Labels"

ACTIONS = (
    Action("list", ("project_id",), ("cursor", "per_page", "fields"), read=True),
    Action("retrieve", ("project_id", "label_id"), read=True),
    Action(
        "create",
        ("project_id", "name"),
        ("color", "description", "parent", "sort_order", "external_source", "external_id"),
    ),
    Action(
        "update",
        ("project_id", "label_id"),
        ("name", "color", "description", "parent", "sort_order", "external_source", "external_id"),
        note="only the fields you pass are changed",
    ),
    Action("delete", ("project_id", "label_id"), destructive=True),
)

# A full label row is ~580 bytes, nearly all timestamps and owner ids. An agent resolving a
# label name to its id needs none of that.
COMPACT_ROW = "id,name,parent,color"

FOOTER = (
    "list returns compact rows (" + COMPACT_ROW + ") unless fields is given; fields=all returns "
    "every field.\n"
    "color is a hex code such as #EF4444. parent is the UUID of another label, for nesting."
)

LEGACY = {
    "list_labels": "list",
    "retrieve_label": "retrieve",
    "create_label": "create",
    "update_label": "update",
    "delete_label": "delete",
}


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name=NAME,
        description=build_description("Labels within a project.", ACTIONS, FOOTER),
        annotations=build_annotations(TITLE, ACTIONS),
    )
    def label(
        action: Literal["list", "retrieve", "create", "update", "delete"],
        project_id: str = "",
        label_id: str = "",
        name: str = "",
        color: str = "",
        description: str = "",
        parent: str = "",
        # 0 is a real sort position, so it cannot use the 0 sentinel.
        sort_order: float | None = None,
        external_source: str = "",
        external_id: str = "",
        cursor: str = "",
        per_page: int = 0,
        fields: str = "",
    ) -> Label | dict[str, Any] | str | None:
        client, workspace_slug = get_plane_client_context()

        if not project_id:
            return missing(action, "project_id")

        if action == "list":
            response: PaginatedLabelResponse = client.labels.list(
                workspace_slug=workspace_slug,
                project_id=project_id,
                params=page_params(cursor, per_page),
            )
            return envelope(response, None if fields == "all" else (fields or COMPACT_ROW))

        if action == "create":
            if not name:
                return missing(action, "name")
            return client.labels.create(
                workspace_slug=workspace_slug,
                project_id=project_id,
                data=CreateLabel(
                    name=name,
                    color=opt(color),
                    description=opt(description),
                    parent=opt(parent),
                    sort_order=sort_order,
                    external_source=opt(external_source),
                    external_id=opt(external_id),
                ),
            )

        if not label_id:
            return missing(action, "label_id")

        if action == "retrieve":
            return client.labels.retrieve(workspace_slug=workspace_slug, project_id=project_id, label_id=label_id)

        if action == "update":
            return client.labels.update(
                workspace_slug=workspace_slug,
                project_id=project_id,
                label_id=label_id,
                data=UpdateLabel(
                    name=opt(name),
                    color=opt(color),
                    description=opt(description),
                    parent=opt(parent),
                    sort_order=sort_order,
                    external_source=opt(external_source),
                    external_id=opt(external_id),
                ),
            )

        client.labels.delete(workspace_slug=workspace_slug, project_id=project_id, label_id=label_id)
        return None
