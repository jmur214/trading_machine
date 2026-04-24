"""
scripts/reset_base_edges.py
===========================
Phase ε (step 2): demote hand-entered "active" base edges to `candidate` status
so they pass through the same Phase γ validation pipeline as Discovery candidates.

Rationale: the 13 active edges in edges.yml were hand-typed from project genesis
and never validated. The current 1 paused + 12 active roster is curated by human
decision, not evidence. This script puts the base edges under the same autonomous
discipline as Discovery candidates.

After running this, the next full backtest OR autonomous cycle (`run_autonomous_cycle.py`)
will:
1. See candidate edges needing validation
2. Run WFO (now fixed in Phase γ to call WalkForwardOptimizer directly)
3. Apply benchmark-relative Gate 1 (edge OOS Sharpe must beat SPY - 0.3)
4. Auto-promote edges that pass ALL 4 gates → `active`
5. Mark edges that fail → `failed`

IMPORTANT — This script mutates `data/governor/edges.yml`. It backs up the file
to `edges.yml.pre-phase-epsilon` before mutating. Requires `--confirm` flag.

Usage:
  # Preview what will change (no mutation)
  python -m scripts.reset_base_edges

  # Apply changes
  python -m scripts.reset_base_edges --confirm

  # Restore from backup
  python -m scripts.reset_base_edges --restore
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
EDGES_YML = ROOT / "data" / "governor" / "edges.yml"
BACKUP = ROOT / "data" / "governor" / "edges.yml.pre-phase-epsilon"

# Edges that should NOT be demoted — these already earned their status through
# the autonomous lifecycle (paused on evidence) or are discovery candidates.
# Everything else in `active` is hand-entered base and should be demoted.
SKIP_STATUSES = {"candidate", "paused", "retired", "failed", "archived", "error"}


def load_edges() -> dict:
    if not EDGES_YML.exists():
        raise FileNotFoundError(f"Registry not found: {EDGES_YML}")
    return yaml.safe_load(EDGES_YML.read_text()) or {"edges": []}


def save_edges(data: dict) -> None:
    EDGES_YML.write_text(yaml.safe_dump(data, sort_keys=False))


def preview(data: dict) -> list[str]:
    """Return edge_ids that would be demoted."""
    demoted = []
    for edge in data.get("edges", []):
        if edge.get("status") == "active":
            demoted.append(edge.get("edge_id", "?"))
    return demoted


def demote(data: dict) -> int:
    """Mutate in place: active → candidate. Returns count."""
    n = 0
    for edge in data.get("edges", []):
        if edge.get("status") == "active":
            edge["status"] = "candidate"
            n += 1
    return n


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--confirm", action="store_true",
                   help="Actually mutate edges.yml (default: preview only)")
    p.add_argument("--restore", action="store_true",
                   help=f"Restore edges.yml from {BACKUP.name}")
    args = p.parse_args()

    if args.restore:
        if not BACKUP.exists():
            print(f"[ERROR] No backup at {BACKUP}")
            return 1
        shutil.copy(BACKUP, EDGES_YML)
        print(f"[OK] Restored {EDGES_YML} from {BACKUP.name}")
        return 0

    data = load_edges()
    demoted_ids = preview(data)

    print(f"Current registry: {EDGES_YML}")
    print(f"Edges currently `active` (will be demoted to `candidate`): {len(demoted_ids)}")
    for eid in demoted_ids:
        print(f"  - {eid}")

    # Show counts for statuses we won't touch
    from collections import Counter
    counts = Counter(e.get("status", "?") for e in data.get("edges", []))
    print(f"\nStatus distribution (untouched except active): {dict(counts)}")

    if not args.confirm:
        print("\n[PREVIEW] No changes made. Re-run with --confirm to apply.")
        print(f"[PREVIEW] Backup will be written to {BACKUP.name} before any mutation.")
        return 0

    # Confirm mode: back up first
    shutil.copy(EDGES_YML, BACKUP)
    print(f"\n[BACKUP] Saved {EDGES_YML} -> {BACKUP.name}")

    n = demote(data)
    save_edges(data)
    print(f"[APPLIED] Demoted {n} edge(s) from `active` to `candidate`")

    print("\nNext steps:")
    print("  1. Run full backtest (without --no-governor) to generate trade data")
    print("  2. Run autonomous cycle to validate candidates:")
    print("       python -m scripts.run_autonomous_cycle")
    print("  3. Candidates that pass all 4 validation gates will auto-promote to `active`.")
    print("  4. Candidates that fail will go to `failed` status with logged reason.")
    print(f"\nTo revert: python -m scripts.reset_base_edges --restore")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
