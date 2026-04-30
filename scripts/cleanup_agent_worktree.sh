#!/usr/bin/env bash
# scripts/cleanup_agent_worktree.sh
# ==================================
# Remove an agent worktree after its branch has been merged to main.
#
# Usage:
#   ./scripts/cleanup_agent_worktree.sh <agent-name>
#   # Example:
#   ./scripts/cleanup_agent_worktree.sh alpha
#
# Safety:
#   - Refuses to remove a worktree with uncommitted changes (use --force to
#     override only if you know the work is preserved elsewhere).
#   - Does NOT delete the branch — you can do that manually with
#     `git branch -d <branch-name>` once you're sure no further work is needed.

set -euo pipefail

if [ "$#" -lt 1 ]; then
  echo "Usage: $0 <agent-name> [--force]" >&2
  exit 1
fi

NAME="$1"
FORCE="${2:-}"
MAIN="$(git rev-parse --show-toplevel)"
WT="${MAIN}/../trading_machine-${NAME}"

if [ ! -e "$WT" ]; then
  echo "Worktree not found at $WT — nothing to clean up." >&2
  exit 0
fi

if [ "$FORCE" = "--force" ]; then
  git worktree remove --force "$WT"
else
  git worktree remove "$WT"
fi

echo "Removed worktree: $WT"
echo "Note: the branch is preserved. Delete it with 'git branch -d <branch>' or '-D' to force."
