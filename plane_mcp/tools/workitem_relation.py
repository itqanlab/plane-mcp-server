"""Relations between work items, and the workspace definitions that type them.

Two systems behind one tool: built-in dependencies (six fixed directional types)
and custom relations (workspace-defined, each with an outward and inward label).
`create` routes between them by which arguments are supplied.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from fastmcp import FastMCP
from plane.errors.errors import HttpError
from plane.models.work_item_relation_definitions import (
    CreateWorkItemRelationDefinition,
    PaginatedWorkItemRelationDefinitionResponse,
    UpdateWorkItemRelationDefinition,
    WorkItemRelationDefinition,
)
from plane.models.work_items import (
    CreateWorkItemCustomRelation,
    CreateWorkItemDependency,
    CreateWorkItemRelation,
    DependencyTypeEnum,
)

from plane_mcp import session
from plane_mcp.client import get_plane_client_context
from plane_mcp.toolkit import (
    Action,
    build_annotations,
    build_description,
    coerce_list,
    missing,
    needs,
    one_of,
    opt,
)

NAME = "workitem_relation"
TITLE = "Work item relations"

DEPENDENCY_TYPES: tuple[str, ...] = get_args(DependencyTypeEnum)

_OTHER_RELATIONS = (
    "For any other relationship pass relation_definition_id and "
    "relation_definition_label from the list_definitions action."
)

ACTIONS = (
    Action("list", ("project_id", "workitem_id"), read=True),
    Action(
        "create",
        ("project_id", "workitem_id", "workitem_ids"),
        ("relation_type", "relation_definition_id", "relation_definition_label"),
        note="pass relation_type for a dependency, or definition id + label for a custom relation",
    ),
    Action(
        "delete",
        ("project_id", "workitem_id", "related_workitem_id"),
        ("is_dependency",),
        note="removes one relation; dependencies and custom relations are independent, so "
        "is_dependency must match the kind that was created (default false)",
        destructive=True,
    ),
    Action("list_definitions", optional=("is_default", "is_active"), read=True),
    Action("create_definition", ("name",), ("outward", "inward", "is_active", "color")),
    Action("update_definition", ("definition_id",), ("name", "outward", "inward", "is_active", "color")),
    Action("delete_definition", ("definition_id",), destructive=True),
)

FOOTER = (
    "Call list_definitions first and match the user's wording to an entry. A "
    f"built_in_dependencies value ({', '.join(DEPENDENCY_TYPES)}) goes in relation_type; a "
    "custom definition needs its id in relation_definition_id and the matched outward or "
    "inward label in relation_definition_label, which sets direction."
)

LEGACY = {
    "list_work_item_relations": "list",
    "create_work_item_relation": "create",
    "remove_work_item_relation": "delete",
    "list_work_item_relation_definitions": "list_definitions",
    "create_work_item_relation_definition": "create_definition",
    "update_work_item_relation_definition": "update_definition",
    "delete_work_item_relation_definition": "delete_definition",
}


def _all_definitions(client, workspace_slug: str, is_default, is_active) -> list[WorkItemRelationDefinition]:
    """Definitions are a small set an agent must see whole, so page through them."""
    results: list[WorkItemRelationDefinition] = []
    cursor: str | None = None
    while True:
        page: PaginatedWorkItemRelationDefinitionResponse = client.work_item_relation_definitions.list(
            workspace_slug=workspace_slug,
            is_default=is_default,
            is_active=is_active,
            per_page=100,
            cursor=cursor,
        )
        results.extend(page.results)
        cursor = page.next_cursor
        if not page.next_page_results or not cursor:
            return results


HTTP_NOT_FOUND = 404

# Relation kinds the legacy endpoint returns. Kept explicit so an unknown key is reported
# rather than silently dropped.
LEGACY_RELATION_KINDS = (
    "blocking",
    "blocked_by",
    "duplicate",
    "relates_to",
    "start_after",
    "start_before",
    "finish_after",
    "finish_before",
)


def _legacy_relations(client, workspace_slug: str, project_id: str, work_item_id: str):
    """Read relations from the legacy endpoint, bypassing a broken SDK model.

    Two separate problems make this necessary on older deployments:

    1. `dependencies` and `custom_relations` do not exist there — both 404 — so the normal
       path returns nothing at all and a work item with relations looks like one without.
    2. The legacy endpoint DOES work, but `WorkItemRelationResponse` types its relation
       lists as `list[str]` while the API returns `list[dict]`. Calling
       `client.work_items.relations.list()` therefore raises ValidationError on any item
       that actually has a relation. Confirmed on plane-sdk 0.2.23 and 0.2.24.

    So we use the SDK's own transport and skip its model. Reaching for `_get` is not
    something to do lightly, but the alternative is duplicating base-url and auth handling
    here, which would drift. The real fix belongs in plane-sdk; when it lands, this whole
    function should go.

    Returns None if the legacy endpoint is missing too, so the caller re-raises the
    original 404 rather than inventing an empty result.
    """
    try:
        raw = client.work_items.relations._get(  # noqa: SLF001 - see docstring
            f"{workspace_slug}/projects/{project_id}/work-items/{work_item_id}/relations"
        )
    except HttpError:
        return None

    if not isinstance(raw, dict):
        return None

    known = {kind: raw.get(kind) or [] for kind in LEGACY_RELATION_KINDS}
    unknown = sorted(set(raw) - set(LEGACY_RELATION_KINDS))
    result = {
        "dependencies": known,
        "custom": {},
        "source": "legacy_relations_endpoint",
        "note": (
            "This deployment has no dependency or custom-relation endpoints, so relations were "
            "read from the legacy endpoint. Custom relations are not available here."
        ),
    }
    if unknown:
        result["unrecognised_relation_kinds"] = unknown
    return result


REMOVE_UNSUPPORTED = (
    "Error: this Plane deployment cannot remove relations through its API. It has no "
    "dependency or custom-relation endpoints, and the legacy relations endpoint only lists "
    "and creates (checked against Plane 1.4.2; removal exists only in the web app, behind a "
    "browser session). Nothing was changed. Remove the relation in the Plane web UI, or set "
    f"{session.EMAIL_ENV} and {session.PASSWORD_ENV} for a Plane user who is a member of the "
    "project so this server can remove it through a web session."
)

HTTP_FORBIDDEN = 403


def _relation_kind(legacy: dict | None, related_work_item_id: str) -> str | None:
    """The relation kind linking to `related_work_item_id` in a legacy read, or None."""
    for kind, entries in ((legacy or {}).get("dependencies") or {}).items():
        if related_work_item_id in _related_ids(entries):
            return kind
    return None


def _identifier(client, workspace_slug, project_id, work_item_id) -> str:
    """PROJ-12 for a work item, falling back to its id when either lookup fails."""
    try:
        item = client.work_items.retrieve(
            workspace_slug=workspace_slug, project_id=project_id, work_item_id=work_item_id
        )
        project = client.projects.retrieve(workspace_slug=workspace_slug, project_id=project_id)
        return f"{project.identifier}-{item.sequence_id}"
    except Exception:  # noqa: BLE001 - a label only; never fail the removal over it
        return work_item_id


def _project_label(client, workspace_slug, project_id) -> str:
    try:
        project = client.projects.retrieve(workspace_slug=workspace_slug, project_id=project_id)
        return f"{project.name} ({project.identifier})"
    except Exception:  # noqa: BLE001 - a label only
        return project_id


def _session_remove(client, workspace_slug, project_id, work_item_id, related_work_item_id, before):
    """Remove a relation through the web app's session-only route, then read back.

    The server's `remove_relation` view takes `.first()` and deletes it without a None
    check, so asking it to remove a relation that does not exist is a 500. Refuse that case
    here from the legacy read instead.
    """
    kind = _relation_kind(before, related_work_item_id)
    if kind is None:
        return (
            f"Error: work item {work_item_id} has no relation to {related_work_item_id}. "
            "Nothing was changed. List the item's relations to see what it is linked to."
        )

    path = f"api/workspaces/{workspace_slug}/projects/{project_id}/issues/{work_item_id}/remove-relation/"
    try:
        response = session.get_session().post(path, {"related_issue": related_work_item_id})
    except session.SessionSignInError as exc:
        return f"Error: {exc} Nothing was changed."

    if response.status_code == HTTP_FORBIDDEN:
        return (
            f"Error: the session user {session.get_session().email} is not allowed to edit project "
            f"{_project_label(client, workspace_slug, project_id)}. Nothing was changed. Add it to the "
            "project (re-run the plane-bot membership line in reference_plane_selfhosted_limits.md)."
        )
    if not 200 <= response.status_code < 300:
        raise HttpError(status_code=response.status_code, message=f"remove-relation failed: {response.text[:200]}")

    after = _legacy_relations(client, workspace_slug, project_id, work_item_id)
    return {
        "workitem": _identifier(client, workspace_slug, project_id, work_item_id),
        "related_workitem": _related_label(client, workspace_slug, before, kind, related_work_item_id),
        "relation_type": kind,
        "removed": _relation_kind(after, related_work_item_id) is None,
        "source": "web_session_remove_relation",
    }


def _related_label(client, workspace_slug, legacy, kind, related_work_item_id) -> str:
    """Identifier for the related item, which may sit in another project."""
    for entry in (legacy.get("dependencies") or {}).get(kind) or []:
        if isinstance(entry, dict) and str(entry.get("issue_id") or entry.get("id")) == related_work_item_id:
            if entry.get("project_id"):
                return _identifier(client, workspace_slug, str(entry["project_id"]), related_work_item_id)
    return related_work_item_id


def _remove_relation(client, workspace_slug, project_id, work_item_id, related_work_item_id, is_dependency):
    """Remove one relation, through a web session if the API cannot, or say plainly why not.

    On deployments without the dependency endpoints (e.g. Plane Community) both remove
    calls 404, and a bare 404 reads like "relation not found". It is not: the relation is
    there, the API just has no way to delete it. With session credentials configured, remove
    it through the web app's route instead; without them, report that.
    """
    remove = client.work_items.dependencies.remove if is_dependency else client.work_items.custom_relations.remove
    try:
        remove(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            related_work_item_id=related_work_item_id,
        )
    except HttpError as exc:
        if exc.status_code != HTTP_NOT_FOUND:
            raise
        before = _legacy_relations(client, workspace_slug, project_id, work_item_id)
        if before is None:
            raise
        if not session.session_configured():
            return REMOVE_UNSUPPORTED
        return _session_remove(client, workspace_slug, project_id, work_item_id, related_work_item_id, before)
    return None


CUSTOM_UNAVAILABLE = (
    "Error: this Plane deployment has no custom-relation endpoint, so custom relations are not "
    "available here. Nothing was changed. Use a built-in relation_type instead."
)

HTTP_BAD_REQUEST = 400


def _related_ids(entries) -> list[str]:
    """Pull work item ids out of legacy relation entries, which are dicts (or bare ids)."""
    ids = []
    for entry in entries:
        if isinstance(entry, dict):
            ids.append(str(entry.get("issue_id") or entry.get("id") or ""))
        else:
            ids.append(str(entry))
    return [i for i in ids if i]


def _legacy_create(client, workspace_slug, project_id, work_item_id, relation_type, targets):
    """Create relations through the legacy endpoint, then read them back.

    Used when `dependencies.create` 404s (e.g. Plane Community 1.4.2). The legacy endpoint
    takes `{"relation_type": ..., "issues": [...]}` and accepts every kind in
    LEGACY_RELATION_KINDS. `relations.create` returns raw JSON without a response model, so
    the SDK call is safe here; the read-back goes through `_legacy_relations`, which skips the
    broken list model.

    Returns None when the legacy endpoint is missing too, so the caller re-raises the
    original 404.
    """
    if _legacy_relations(client, workspace_slug, project_id, work_item_id) is None:
        return None
    if relation_type not in LEGACY_RELATION_KINDS:
        return (
            f"Error: relation_type {relation_type!r} is not supported by this deployment's relations "
            f"endpoint. Supported: {', '.join(LEGACY_RELATION_KINDS)}. Nothing was changed."
        )
    try:
        client.work_items.relations.create(
            workspace_slug=workspace_slug,
            project_id=project_id,
            work_item_id=work_item_id,
            data=CreateWorkItemRelation(relation_type=relation_type, issues=targets),  # type: ignore[arg-type]
        )
    except HttpError as exc:
        if exc.status_code != HTTP_BAD_REQUEST:
            raise
        return f"Error: Plane refused the {relation_type} relation: {exc}. Nothing was changed."

    after = _legacy_relations(client, workspace_slug, project_id, work_item_id) or {}
    present = set(_related_ids((after.get("dependencies") or {}).get(relation_type) or []))
    result = {
        "workitem_id": work_item_id,
        "relation_type": relation_type,
        "related_workitem_ids": [t for t in targets if t in present],
        "source": "legacy_relations_endpoint",
    }
    not_confirmed = [t for t in targets if t not in present]
    if not_confirmed:
        result["not_confirmed"] = not_confirmed
    return result


def register(mcp: FastMCP) -> None:
    @mcp.tool(
        name=NAME,
        description=build_description(
            "Relations between work items, and the definitions that type them.", ACTIONS, FOOTER
        ),
        annotations=build_annotations(TITLE, ACTIONS),
    )
    def workitem_relation(
        action: Literal[
            "list",
            "create",
            "delete",
            "list_definitions",
            "create_definition",
            "update_definition",
            "delete_definition",
        ],
        project_id: str = "",
        workitem_id: str = "",
        workitem_ids: list[str] | None = None,
        related_workitem_id: str = "",
        relation_type: str = "",
        relation_definition_id: str = "",
        relation_definition_label: str = "",
        definition_id: str = "",
        name: str = "",
        outward: str = "",
        inward: str = "",
        color: str = "",
        # Tri-state: False is a real filter value, distinct from "no filter".
        is_default: bool | None = None,
        is_active: bool | None = None,
        is_dependency: bool = False,
    ) -> Any:
        client, workspace_slug = get_plane_client_context()

        if action == "list_definitions":
            return {
                "built_in_dependencies": list(DEPENDENCY_TYPES),
                "custom_definitions": [
                    d.model_dump() for d in _all_definitions(client, workspace_slug, is_default, is_active)
                ],
            }

        if action == "create_definition":
            if not name:
                return missing(action, "name")
            return client.work_item_relation_definitions.create(
                workspace_slug=workspace_slug,
                data=CreateWorkItemRelationDefinition(
                    name=name,
                    outward=opt(outward),
                    inward=opt(inward),
                    is_active=is_active,
                    color=opt(color),
                ),
            )

        if action in ("update_definition", "delete_definition"):
            if not definition_id:
                return missing(action, "definition_id")
            if action == "update_definition":
                return client.work_item_relation_definitions.update(
                    workspace_slug=workspace_slug,
                    definition_id=definition_id,
                    data=UpdateWorkItemRelationDefinition(
                        name=opt(name),
                        outward=opt(outward),
                        inward=opt(inward),
                        is_active=is_active,
                        color=opt(color),
                    ),
                )
            client.work_item_relation_definitions.delete(workspace_slug=workspace_slug, definition_id=definition_id)
            return None

        if error := needs(action, project_id=project_id, workitem_id=workitem_id):
            return error

        if action == "list":
            try:
                dependencies = client.work_items.dependencies.list(
                    workspace_slug=workspace_slug, project_id=project_id, work_item_id=workitem_id
                )
                custom = client.work_items.custom_relations.list(
                    workspace_slug=workspace_slug, project_id=project_id, work_item_id=workitem_id
                )
            except HttpError as exc:
                if exc.status_code != HTTP_NOT_FOUND:
                    raise
                # Older deployments (e.g. Plane Community) have no dependency or custom-relation
                # endpoints. They do serve the legacy relations endpoint, so fall back to it
                # rather than reporting a work item has no relations when it plainly does.
                legacy = _legacy_relations(client, workspace_slug, project_id, workitem_id)
                if legacy is None:
                    raise
                return legacy
            return {
                "dependencies": dependencies.model_dump(),
                "custom": {label: [item.model_dump() for item in items] for label, items in custom.items()},
            }

        if action == "create":
            targets = coerce_list(workitem_ids)
            if not targets:
                return missing(action, "workitem_ids")
            if relation_type:
                if error := one_of("relation_type", relation_type, DEPENDENCY_TYPES, _OTHER_RELATIONS):
                    return error
                try:
                    return client.work_items.dependencies.create(
                        workspace_slug=workspace_slug,
                        project_id=project_id,
                        work_item_id=workitem_id,
                        data=CreateWorkItemDependency(
                            relation_type=relation_type,  # type: ignore[arg-type]
                            work_item_ids=targets,
                        ),
                    )
                except HttpError as exc:
                    if exc.status_code != HTTP_NOT_FOUND:
                        raise
                    # No dependency endpoint (e.g. Plane Community): create through the legacy
                    # relations endpoint instead, the same fallback `list` uses.
                    created = _legacy_create(client, workspace_slug, project_id, workitem_id, relation_type, targets)
                    if created is None:
                        raise
                    return created
            if relation_definition_id and relation_definition_label:
                try:
                    return client.work_items.custom_relations.create(
                        workspace_slug=workspace_slug,
                        project_id=project_id,
                        work_item_id=workitem_id,
                        data=CreateWorkItemCustomRelation(
                            relation_definition_id=relation_definition_id,
                            relation_definition_type=relation_definition_label,
                            work_item_ids=targets,
                        ),
                    )
                except HttpError as exc:
                    if exc.status_code != HTTP_NOT_FOUND:
                        raise
                    if _legacy_relations(client, workspace_slug, project_id, workitem_id) is None:
                        raise
                    return CUSTOM_UNAVAILABLE
            return (
                "Error: provide relation_type for a built-in dependency, or both "
                "relation_definition_id and relation_definition_label for a custom relation. "
                "Call the list_definitions action to find one."
            )

        if not related_workitem_id:
            return missing(action, "related_workitem_id")
        return _remove_relation(client, workspace_slug, project_id, workitem_id, related_workitem_id, is_dependency)
