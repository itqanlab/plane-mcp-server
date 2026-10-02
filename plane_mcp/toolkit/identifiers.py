"""Human work item identifiers (`PROJ-42`), the form people and tickets use.

Plane's API addresses a work item by project uuid and work item uuid, but every prompt,
commit message and comment names it `PROJ-42`. Taking that form directly saves the caller a
lookup round trip on every call.
"""

from __future__ import annotations

from typing import Any

from plane.errors.errors import HttpError
from plane.models.query_params import RetrieveQueryParams


def split_identifier(identifier: str) -> tuple[str, int] | str:
    """`("PROJ", 42)` for `PROJ-42`, or an error string naming the expected form.

    The project part is upper-cased: Plane matches it case-sensitively and answers a
    lowercase `proj-42` with 403, which reads as a permissions problem rather than a typo.
    """
    head, _, sequence = (identifier or "").strip().rpartition("-")
    if not head or not sequence.isdigit():
        return f"Error: invalid work item identifier {identifier!r}. Expected PROJECT-N, for example ENG-42."
    return head.upper(), int(sequence)


def resolve_workitem(client: Any, workspace_slug: str, identifier: str) -> tuple[str, str] | str:
    """`(project_id, workitem_id)` for `PROJ-42` in one call, or a one-line error."""
    parsed = split_identifier(identifier)
    if isinstance(parsed, str):
        return parsed
    head, sequence = parsed
    try:
        item = client.work_items.retrieve_by_identifier(
            workspace_slug=workspace_slug,
            project_identifier=head,
            issue_identifier=sequence,
            params=RetrieveQueryParams(fields="id,project"),
        )
    except HttpError as exc:
        if exc.status_code == 404:  # noqa: PLR2004
            return f"Error: work item {head}-{sequence} not found."
        raise
    return str(item.project), str(item.id)
