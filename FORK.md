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

Tested 2026-09-05 against a live self-hosted Plane Community instance, using MCP `0.3.2` +
`plane-sdk 0.2.23/0.2.24`.

> **Correction, later the same day.** An earlier draft said we were "already the latest release —
> we cannot upgrade out of any of this". That was wrong. It came from the instance's own
> `latest_version` field, which freezes at install time when telemetry is off (`last_checked_at`
> was still 2026-06-27). We were on **1.3.1** while upstream was on **1.4.2** — three releases
> behind, including a security release. **The instance has since been upgraded to 1.4.2.**
> Never trust a self-hosted instance's self-reported "latest"; check upstream releases.

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
| 1 | **`pql` ignored (1.3.1) / rejected (1.4.2)** | Edition-gated **by design** | This repo — client-side fallback |
| 2 | **`relations.list()` raises `ValidationError`** | Confirmed on SDK **0.2.24** (latest) | `plane-python-sdk`; workaround here |
| 3 | `count_workspace` → HTTP 404 | Community gap | This repo — count locally |
| 4 | `advanced_search` → HTTP **403** | Edition-gated, not a bug | Not fixable |

**On (1) — read this before "fixing" it upstream.** Filtering is **deliberately excluded** from
open-source Plane, not missing by accident. From `apps/api/plane/api/views/issue.py` on main:

```python
unsupported_filters = [p for p in ("pql", "filters") if request.GET.get(p)]
if unsupported_filters:
    return Response({"pql":
        "PQL and structured filters are not supported on this Plane edition. "
        "Remove the pql/filters parameter and filter results client-side, or use "
        "a Plane edition that supports work item query filtering."
    }, status=400)
```

**Plane's own advice is "filter results client-side"** — exactly what our fallback does.

Behaviour differs by version, and both are worth handling:

| version | behaviour | why it matters |
|---|---|---|
| 1.3.1 (what we ran) | silent `200` + the whole board | worst case — a dropped filter looks identical to one that matched everything |
| 1.4.2 (what we run now) | explicit `400` with the message above | loud and honest; already handled by `pql_failure()` |

Upgrading turned a silent wrong answer into a clear error. The fallback still earns its place: it
protects any deployment still on the old behaviour, and it is the documented remedy.

**New finding while verifying the upgrade:** on 1.4.2 the MCP answers every rejected `pql` call
with `PQL_FULL_REFERENCE` — about **4,000 tokens** of syntax guide — on an edition where PQL can
never work. That waste repeats on every attempt. The response should detect "not supported on
this Plane edition" and reply with one short line, no reference. Worth its own PR.

**On (2):** `WorkItemRelationResponse` types its relation lists as `list[str]`; the API returns
`list[dict]`. Any work item with a real relation fails to parse. Reproduced on
`blocked_by` relations created 2026-09-05.

**On (4):** `advanced_search` returns 403 on every input shape — including an empty query — so
it is a licensing gate, not a malformed request. It carries a `filters` field and would have
solved (1) if it were available to us.
