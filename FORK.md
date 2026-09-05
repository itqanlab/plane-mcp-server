# Itqan Lab fork of `makeplane/plane-mcp-server`

This is a **tracking fork**, not a hard fork. Upstream is official, actively maintained
(pushed 2026-09-03) and we intend to stay close to it.

- `origin`   → `itqanlab/plane-mcp-server` (ours — all work goes here)
- `upstream` → `makeplane/plane-mcp-server` (fetch only; **push is deliberately disabled**)

Forked from upstream `main` @ `ae6bad6`, version **0.3.2**.

## Working rules

1. **Sync before you start. Every time.**
   ```bash
   ./scripts/sync-upstream.sh
   ```
   It fetches upstream, tells you how far ahead/behind we are, lists the new upstream commits
   and lists our own patches. Never build on a stale fork — upstream moves weekly, and a fix
   we write against a stale base is a merge conflict we chose to create.

2. **Normal PR flow.** Branch off `main`, open a PR against `itqanlab/plane-mcp-server`, review,
   merge. Same as any repo we own.

3. **Do NOT open PRs against `makeplane/plane-mcp-server` yet.** That is a deliberate decision,
   not an oversight — we upstream later, once our patches have run in production for a while.
   The push URL for `upstream` is set to a bogus value so an absent-minded `git push upstream`
   fails loudly instead of opening something on the official repo. `sync-upstream.sh` re-arms
   that guard if it is ever cleared.

4. **Keep each fix a separate, self-contained commit.** When we do upstream them, they should
   lift out cleanly as individual PRs. A patch tangled with three unrelated changes is one we
   will never be able to offer back.

5. **Say which layer a fix belongs in.** Some bugs are in `plane-sdk`
   (`makeplane/plane-python-sdk`), a *different* package we depend on. If a fix belongs there,
   note it in the commit message even when we work around it here.

## Why this fork exists — measured, not assumed

Tested 2026-09-05 against a live self-hosted **Plane Community v1.3.1** instance (already the
latest release — we cannot upgrade out of any of this), using MCP `0.3.2` + `plane-sdk 0.2.23/0.2.24`.

### Already fixed upstream — do NOT re-patch these

Our older notes (written against `0.2.9`) listed these as broken. They are not, on current
versions. This is exactly why we tested before writing code.

| Item | Old note | Reality on 0.3.2 |
|---|---|---|
| `retrieve_by_identifier` without `fields` | Pydantic crash on labelled items | **Works** — `labels` is now `list[str] \| list[Label]` |
| `search_work_items` | "returns empty for titles you can see" | **Works** — found a ticket by title |

A local hand-patch to `plane/models/work_items.py` existed in the running venv
(`~/.local/share/plane-mcp-patched/`) with no git history and no note. It was the labels fix,
and it is now **redundant** — upstream shipped the same change. It should be dropped, not
carried forward.

### Genuinely still broken — the fork's actual reason to exist

| # | Item | Status | Where the fix belongs |
|---|---|---|---|
| 1 | **`pql` is silently ignored** | Confirmed on Community 1.3.1 | This repo — client-side fallback |
| 2 | **`relations.list()` raises `ValidationError`** | Confirmed on SDK **0.2.24** (latest) | `plane-python-sdk`; workaround here |
| 3 | `count_workspace` → HTTP 404 | Community gap | This repo — count locally |
| 4 | `advanced_search` → HTTP **403** | Edition-gated, not a bug | Not fixable |

**On (1) — this is the big one.** Plane Community's public v1 issues endpoint has no
server-side filtering. Measured on a 153-item board: `?state=<uuid>`, `?pql=...` and no filter
returned **identical full boards** (153 rows, 13 actually matching). The MCP is not at fault —
it sends `pql` correctly and even handles a `400` with a PQL error. Community just returns
`200` with everything, so the caller cannot tell the filter was dropped. **A silently ignored
filter is indistinguishable from a filter that matched everything**, which is how an agent ends
up reviewing `Done` tickets believing they are open.

Every Community self-hoster has this. A client-side fallback in the server is the fix.

**On (2):** `WorkItemRelationResponse` types its relation lists as `list[str]`; the API returns
`list[dict]`. Any work item with a real relation fails to parse. Reproduced on
`blocked_by` relations created 2026-09-05.

**On (4):** `advanced_search` returns 403 on every input shape — including an empty query — so
it is a licensing gate, not a malformed request. It carries a `filters` field and would have
solved (1) if it were available to us.
