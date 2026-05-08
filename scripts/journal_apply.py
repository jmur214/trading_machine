"""journal_apply — apply LifecycleJournal entries to data/governor/edges.yml.

F11 Phase 1 CLI driver. Reads append-only journal entries since the last
apply mark, projects them onto the EdgeRegistry as a single transaction,
writes the result via atomic temp-file-rename, then advances the apply
mark.

## Why explicit-apply rather than per-entry mutation

A backtest run is supposed to be a measurement. Per-entry mutation of
edges.yml is what created the 4-file snapshot/restore harness in
run_isolated.py. Apply-as-explicit-step decouples measurement from
state mutation; backtests append to journal but never write edges.yml.
The user (or a wrapping autonomous-cycle script) decides when to apply.

## Idempotency

Each call records the timestamp of the latest applied entry to
``data/governor/.journal_apply_mark``. Subsequent calls process only
entries with timestamp > mark. Re-running with no new entries is a
no-op.

## Crash safety

Apply is a read-modify-write transaction:
  1. Read journal entries since mark
  2. Read current edges.yml into memory
  3. Project decisions onto in-memory specs
  4. Write to ``edges.yml.tmp`` then ``os.replace`` (POSIX atomic)
  5. Advance the mark (a separate atomic write)

If steps 1-4 crash, edges.yml is unchanged (rename never happened) and
the mark is unchanged. Next run re-applies the same entries — safe
because each apply is by design idempotent at the entry level
(``status_change`` overwrites, ``weight_update`` overwrites).

## CLI

    python -m scripts.journal_apply --dry-run    # report what WOULD apply
    python -m scripts.journal_apply              # apply pending entries
    python -m scripts.journal_apply --since "2026-05-01T00:00:00+00:00"
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from engines.engine_f_governance.journal import LifecycleJournal


DEFAULT_MARK_PATH = Path("data/governor/.journal_apply_mark")
DEFAULT_REGISTRY_PATH = Path("data/governor/edges.yml")
DEFAULT_JOURNAL_PATH = Path("data/governor/lifecycle_journal.jsonl")


# ---------------------------------------------------------------------- #

@dataclass
class ApplyResult:
    n_processed: int
    n_status_changes: int
    n_weight_updates: int
    n_tier_changes: int
    n_skipped_unknown_edge: int
    n_skipped_unknown_type: int
    new_mark_iso: Optional[str]
    dry_run: bool

    def to_dict(self) -> dict:
        return {
            "n_processed": self.n_processed,
            "n_status_changes": self.n_status_changes,
            "n_weight_updates": self.n_weight_updates,
            "n_tier_changes": self.n_tier_changes,
            "n_skipped_unknown_edge": self.n_skipped_unknown_edge,
            "n_skipped_unknown_type": self.n_skipped_unknown_type,
            "new_mark_iso": self.new_mark_iso,
            "dry_run": self.dry_run,
        }


# ---------------------------------------------------------------------- #

def read_mark(mark_path: Path) -> Optional[str]:
    if not mark_path.exists():
        return None
    try:
        s = mark_path.read_text(encoding="utf-8").strip()
        if not s:
            return None
        # Validate parseable
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return s
    except (OSError, ValueError):
        return None


def write_mark(mark_path: Path, ts_iso: str) -> None:
    mark_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = mark_path.with_suffix(mark_path.suffix + ".tmp")
    tmp.write_text(ts_iso, encoding="utf-8")
    os.replace(tmp, mark_path)


# ---------------------------------------------------------------------- #

def apply(
    *,
    journal_path: Path = DEFAULT_JOURNAL_PATH,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    mark_path: Path = DEFAULT_MARK_PATH,
    dry_run: bool = False,
    since_iso: Optional[str] = None,
    verbose: bool = True,
) -> ApplyResult:
    """Apply pending journal entries to edges.yml.

    Returns a structured result. When dry_run=True, reports what would
    happen without touching edges.yml or the apply mark.
    """
    # Avoid cycle: import EdgeRegistry lazily so journal-only environments
    # don't pay the cost.
    from engines.engine_a_alpha.edge_registry import EdgeRegistry

    journal = LifecycleJournal(journal_path)

    cutoff = since_iso if since_iso is not None else read_mark(mark_path)
    if cutoff:
        entries = journal.filter_since(cutoff)
    else:
        entries = journal.read_all()

    if not entries:
        if verbose:
            print(f"[journal_apply] no pending entries (cutoff={cutoff!r})")
        return ApplyResult(
            n_processed=0, n_status_changes=0, n_weight_updates=0,
            n_tier_changes=0, n_skipped_unknown_edge=0,
            n_skipped_unknown_type=0, new_mark_iso=cutoff, dry_run=dry_run,
        )

    if not registry_path.exists():
        raise FileNotFoundError(
            f"registry not found at {registry_path}; cannot apply"
        )

    # Sort by timestamp ascending so within-batch decisions resolve in
    # the order they were made (last-write-wins on identical edge_id).
    entries.sort(key=lambda e: e.timestamp)

    reg = EdgeRegistry(store_path=str(registry_path))
    counter = Counter()
    n_unknown_edge = 0
    n_unknown_type = 0

    for e in entries:
        if e.edge_id is None and e.decision_type != "manual":
            n_unknown_edge += 1
            continue
        if e.edge_id and e.edge_id not in reg._specs:
            # An entry referring to an edge we don't know about. Likely
            # a journal from a different branch / pre-archive. Skip with
            # a warning rather than erroring.
            n_unknown_edge += 1
            continue

        if e.decision_type == "status_change":
            new_status = e.payload.get("new_status")
            if new_status:
                if not dry_run:
                    reg._specs[e.edge_id].status = new_status
                counter["status_change"] += 1

        elif e.decision_type == "weight_update":
            # Weight lives in edge_weights.json today, not edges.yml.
            # Phase 1: count + report; Phase 2 will route to the right
            # store. For now we only mutate edges.yml fields.
            counter["weight_update"] += 1

        elif e.decision_type == "tier_change":
            new_tier = e.payload.get("new_tier")
            if new_tier:
                if not dry_run:
                    reg._specs[e.edge_id].tier = new_tier
                counter["tier_change"] += 1

        elif e.decision_type == "regime_weight_update":
            # Regime gate field on the spec. Payload shape: {"regime": <label>, "weight": float}
            label = e.payload.get("regime")
            wt = e.payload.get("weight")
            if label is not None and wt is not None:
                if not dry_run:
                    spec = reg._specs[e.edge_id]
                    if spec.regime_gate is None:
                        spec.regime_gate = {}
                    spec.regime_gate[str(label)] = float(wt)
                counter["regime_weight_update"] += 1

        elif e.decision_type == "manual":
            # Free-form payload; treat as advisory log only.
            counter["manual"] += 1

        else:
            n_unknown_type += 1

    # Commit transaction.
    new_mark = entries[-1].timestamp
    if not dry_run:
        reg._save()
        write_mark(mark_path, new_mark)

    result = ApplyResult(
        n_processed=len(entries),
        n_status_changes=counter["status_change"],
        n_weight_updates=counter["weight_update"],
        n_tier_changes=counter["tier_change"],
        n_skipped_unknown_edge=n_unknown_edge,
        n_skipped_unknown_type=n_unknown_type,
        new_mark_iso=new_mark,
        dry_run=dry_run,
    )

    if verbose:
        prefix = "[journal_apply][DRY-RUN]" if dry_run else "[journal_apply]"
        print(f"{prefix} processed {result.n_processed} entries: "
              f"status={result.n_status_changes} "
              f"weight={result.n_weight_updates} "
              f"tier={result.n_tier_changes} "
              f"regime={counter['regime_weight_update']} "
              f"manual={counter['manual']} | "
              f"skipped: unknown_edge={n_unknown_edge} "
              f"unknown_type={n_unknown_type}")
        if not dry_run:
            print(f"{prefix} advanced apply mark → {new_mark}")

    return result


# ---------------------------------------------------------------------- #

def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Apply LifecycleJournal entries to edges.yml")
    p.add_argument("--journal", type=str, default=str(DEFAULT_JOURNAL_PATH))
    p.add_argument("--registry", type=str, default=str(DEFAULT_REGISTRY_PATH))
    p.add_argument("--mark", type=str, default=str(DEFAULT_MARK_PATH))
    p.add_argument("--dry-run", action="store_true", help="report what would apply, no writes")
    p.add_argument("--since", type=str, default=None,
                   help="ISO-8601 cutoff; overrides apply mark")
    p.add_argument("--json", action="store_true", help="emit JSON result instead of human text")
    args = p.parse_args(argv)

    try:
        result = apply(
            journal_path=Path(args.journal),
            registry_path=Path(args.registry),
            mark_path=Path(args.mark),
            dry_run=args.dry_run,
            since_iso=args.since,
            verbose=not args.json,
        )
    except FileNotFoundError as exc:
        print(f"[journal_apply] {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
