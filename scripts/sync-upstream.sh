#!/usr/bin/env bash
# Sync this fork with makeplane/plane-mcp-server.
# Run this BEFORE starting any work — never build on a stale fork.
set -euo pipefail

cd "$(git rev-parse --show-toplevel)"

if ! git remote get-url upstream >/dev/null 2>&1; then
  git remote add upstream git@github.com:makeplane/plane-mcp-server.git
  git remote set-url --push upstream DISABLED_no_pushing_to_official
fi

# Safety: we never push to the official repo (policy — see FORK.md).
push_url="$(git remote get-url --push upstream 2>/dev/null || true)"
if [[ "$push_url" != DISABLED* ]]; then
  echo "Re-arming the upstream push guard." >&2
  git remote set-url --push upstream DISABLED_no_pushing_to_official
fi

echo "Fetching upstream…"
git fetch upstream --tags --prune

base="${1:-main}"
ahead="$(git rev-list --count "upstream/$base..origin/$base" 2>/dev/null || echo 0)"
behind="$(git rev-list --count "origin/$base..upstream/$base" 2>/dev/null || echo 0)"

echo
echo "origin/$base is $behind commit(s) BEHIND and $ahead commit(s) AHEAD of upstream/$base."
echo
if [[ "$behind" != "0" ]]; then
  echo "New upstream commits:"
  git log --oneline "origin/$base..upstream/$base" | head -25
  echo
  echo "To take them:  git checkout $base && git merge --ff-only upstream/$base && git push origin $base"
  echo "If ff-only fails, our commits have diverged — rebase our work on upstream, do not force-push $base."
else
  echo "Up to date with upstream."
fi

echo
echo "Our commits not in upstream (these are the fork's patches):"
git log --oneline "upstream/$base..origin/$base" | head -25
