#!/usr/bin/env bash
# scripts/setup_agent_worktree.sh
# ================================
# Set up an isolated git worktree for an agent session.
#
# Each parallel agent gets its own worktree (so HEAD is per-session) and its
# own COPY of mutable governor state (so concurrent backtests don't collide
# on data/governor/ writes). Read-only caches (price data, FRED, earnings)
# are symlinked back to the main repo so we don't duplicate gigabytes.
#
# Usage:
#   ./scripts/setup_agent_worktree.sh <agent-name> <branch-name>
#   # Example:
#   ./scripts/setup_agent_worktree.sh alpha cap-recalibration
#
# Result:
#   ../trading_machine-alpha/  (new worktree, on branch cap-recalibration)
#       data/processed/        → symlink to main worktree's processed/
#       data/macro_data/       → symlink (if exists)
#       data/earnings/         → symlink (if exists)
#       data/trade_logs/       → symlink (UUID-keyed, no collision)
#       data/research/         → symlink (mostly unique filenames)
#       data/governor/         → COPY (mutable state, per-agent isolation)
#
# Prerequisites:
#   - You are inside the main worktree's root directory.
#   - origin/main is up to date (script runs `git fetch origin` first).
#
# Cleanup after the agent's branch is merged:
#   ./scripts/cleanup_agent_worktree.sh <agent-name>

set -euo pipefail

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <agent-name> <branch-name>" >&2
  echo "Example: $0 alpha cap-recalibration" >&2
  exit 1
fi

NAME="$1"
BRANCH="$2"
MAIN="$(git rev-parse --show-toplevel)"
WT="${MAIN}/../trading_machine-${NAME}"

# Make sure we're in the main worktree, not an existing agent worktree.
# Main repo is `trading_machine-2`; agent worktrees use alphabetic suffixes
# like `trading_machine-agentA`. The check excludes purely-numeric suffixes
# so the canonical main repo isn't blocked.
basename_main="$(basename "$MAIN")"
if [[ "$basename_main" =~ ^trading_machine-[a-zA-Z][a-zA-Z0-9_-]*$ ]]; then
  echo "Error: refusing to set up an agent worktree from inside another agent worktree." >&2
  echo "  Current dir: $MAIN" >&2
  echo "  Run this script from the main repo (e.g. trading_machine-2)." >&2
  exit 1
fi

if [ -e "$WT" ]; then
  echo "Error: worktree path already exists: $WT" >&2
  echo "  Run scripts/cleanup_agent_worktree.sh ${NAME} first if you're recycling the slot." >&2
  exit 1
fi

echo "[1/4] Fetching origin..."
git fetch origin

echo "[2/4] Creating worktree at $WT on branch '$BRANCH' from origin/main..."
git worktree add "$WT" -b "$BRANCH" origin/main

echo "[3/4] Setting up data/ isolation..."
mkdir -p "$WT/data"

# Symlink ALL directories under data/ except governor (which gets per-agent copy
# below). Robust to future additions — no need to maintain a hardcoded allowlist.
# governor is the only mutable shared state file group; the rest are read-only
# caches (price data, macro, news, earnings, etc.) or UUID-keyed write dirs
# (trade_logs, research) where collision is impossible.
for entry in "${MAIN}/data"/*; do
  if [ -d "$entry" ]; then
    name=$(basename "$entry")
    if [ "$name" != "governor" ]; then
      ln -s "$entry" "$WT/data/${name}"
      echo "    symlinked data/${name}"
    fi
  fi
done

# Symlink any non-governor files in data/ root (e.g., fundamentals_static.csv).
for entry in "${MAIN}/data"/*; do
  if [ -f "$entry" ]; then
    name=$(basename "$entry")
    ln -s "$entry" "$WT/data/${name}"
    echo "    symlinked data/${name}"
  fi
done

# Mutable governor state — COPY so concurrent backtests don't collide on writes.
# Each agent's lifecycle decisions stay in their own worktree until merged.
if [ -e "${MAIN}/data/governor" ]; then
  cp -r "${MAIN}/data/governor" "$WT/data/governor"
  echo "    copied data/governor (per-agent isolation for mutable state)"
fi

echo "[4/4] Verifying setup..."
cd "$WT"
echo "    pwd: $(pwd)"
echo "    branch: $(git branch --show-current)"
echo "    HEAD: $(git rev-parse --short HEAD)"

cat <<EOF

Done. Start the agent's Claude session with working directory:
    $WT

When the agent's branch is merged to main, clean up with:
    ./scripts/cleanup_agent_worktree.sh ${NAME}
EOF
