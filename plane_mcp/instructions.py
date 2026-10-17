"""Server instructions, sent to a client before it lists the tools.

The few-calls guide and the epic recipe name the tools that do each step, so
`test_references.py` follows every one of them and fails if a name stops resolving.
"""

from __future__ import annotations

SERVER_INSTRUCTIONS = """
## Doing a task in few calls

Plane works on ids. Most can be skipped, so look one up only when a call refuses a name.
1. Find a ticket: by its PROJ-N with `workitem retrieve_by_identifier` or `workitem body`,
   or by words with `workitem search` (whole workspace, no project id). Pick one of these;
   do not run a list and a search for the same thing.
2. Change it in ONE `workitem update` with workitem_identifier="PROJ-N": state by name,
   assignees by email or display name, priority, dates, all together. Decide every field
   first; a second update for a field you forgot is a wasted call.
3. Trust the reply. It echoes every field the call set, as Plane stored it, plus state_name.
   Read the item again only for a field the reply does not show.
4. `workitem_comment create` takes workitem_identifier too, so a note needs no ids either.
Only names that a call refused (a label, a parent, a type) need a lookup: `label list`,
`workitem search`, `workitem_type resolve`.

## Epics

There are no epic tools — an epic is a work item whose type is named "Epic". Work
items always belong to a project; ask which if one is not named.
1. type = `workitem_type resolve` with project_id and name="Epic" — type.id is the type_id.
2. Create: `workitem create` with project_id, type_id=type.id, name=...
3. List: `workitem list` with project_id and pql='type = "<type id>"'.
4. Read / update / delete / nest: `workitem retrieve` / `workitem update` /
   `workitem delete` by work item id (set parent=<work item id> to nest).
5. List an epic's children: `workitem list` with pql='childOf("<EPIC-IDENTIFIER>")'
   using the epic's human-readable identifier (e.g. "PROJ-12") from `workitem retrieve`.
"""
