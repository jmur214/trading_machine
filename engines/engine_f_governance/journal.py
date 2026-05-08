"""LifecycleJournal — append-only journal of governance decisions.

F11 architectural redesign per
`docs/Core/Ideas_Pipeline/F11_journal_redesign_proposal_2026_05_07.md`.

## Why this exists

A backtest is supposed to be a measurement. The pre-fix architecture
mutated the source-of-truth governor file (`data/governor/edges.yml`)
mid-run from two distinct write paths:
  1. `governor.update_from_trades()` (EMA-smoothed edge weights)
  2. `lifecycle_manager.evaluate()` (status changes: active → paused → retired)

Consequences:
  - Same config + same window can produce different output across runs
    unless governor state is snapshotted
  - The 4-file snapshot/restore harness in `scripts/run_isolated.py`
    exists *only* to bandage this
  - Live trading has no "snapshot/restore" — whatever happens at bar N
    is what bar N+1 inherits, so the harness creates backtest-vs-live
    divergence by construction

## Design — append-only journal + explicit apply

A backtest run NEVER mutates `edges.yml`. Period. All lifecycle decisions
append to a JSONL journal at `data/governor/lifecycle_journal.jsonl`.
A separate `journal_apply.py` CLI reads the journal and applies entries
to `edges.yml` as a single transaction at a configurable cadence
(end-of-cycle, end-of-day, or never for pure-measurement runs).

This makes backtest mechanics IDENTICAL to live mechanics — both
append-only to journal, both apply at the same cadence — and removes
a category of backtest-vs-live divergence by construction.

## Phase 1 (this module): journal class only — additive, non-breaking

Phase 1 ships the writer, the schema, and tests. Existing callers
(`governor.update_from_trades`, `lifecycle_manager.evaluate`) are
NOT yet rewired. Phase 2 (separate dispatch, propose-first per
CLAUDE.md Engine F rules) wires the production write paths through
this journal.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional


# Closed vocabulary for decision_type. Keep narrow on purpose —
# every entry should be classifiable into one of these.
ALLOWED_DECISION_TYPES = frozenset({
    "weight_update",          # governor.update_from_trades EMA write
    "status_change",          # lifecycle_manager: active → paused/retired
    "tier_change",            # tier_classifier reclassification
    "regime_weight_update",   # per-regime weight learn
    "manual",                 # human-initiated change (rare)
})


# Schema version. Increment on breaking change to `JournalEntry` shape.
JOURNAL_SCHEMA_VERSION = 1


@dataclass
class JournalEntry:
    """One append-only journal record.

    Fields are deliberately minimal:
      - timestamp: ISO-8601 UTC at which the decision was MADE
      - run_id:    the backtest run_id (or live-session id) for forensics
      - decision_type: one of ALLOWED_DECISION_TYPES
      - edge_id:   the edge being modified (None for global decisions)
      - payload:   decision-type-specific dict (must be JSON-serializable)
      - schema_version: for forward-compatibility
    """
    timestamp: str
    run_id: str
    decision_type: str
    edge_id: Optional[str]
    payload: Dict[str, Any]
    schema_version: int = JOURNAL_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.decision_type not in ALLOWED_DECISION_TYPES:
            raise ValueError(
                f"decision_type={self.decision_type!r} not in allowed set "
                f"{sorted(ALLOWED_DECISION_TYPES)}"
            )
        # Validate timestamp parses as ISO-8601
        try:
            datetime.fromisoformat(self.timestamp.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"timestamp must be ISO-8601, got {self.timestamp!r}: {exc}")
        if not isinstance(self.payload, dict):
            raise TypeError(f"payload must be dict, got {type(self.payload).__name__}")

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), separators=(",", ":"), sort_keys=True)


def now_utc_iso() -> str:
    """Single source of truth for journal timestamp generation."""
    return datetime.now(timezone.utc).isoformat()


class LifecycleJournal:
    """Append-only writer + reader for governance decisions.

    Thread-safe within a single process via an internal lock. NOT
    multi-process safe — the apply layer holds an exclusive file lock
    on edges.yml during the read+apply transaction.

    Default path: `data/governor/lifecycle_journal.jsonl` (gitignored).
    """

    DEFAULT_PATH = Path("data/governor/lifecycle_journal.jsonl")

    def __init__(self, path: Optional[Path | str] = None):
        self.path: Path = Path(path) if path is not None else self.DEFAULT_PATH
        self._lock = threading.Lock()
        # Ensure parent dir exists. Idempotent.
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def append(self, entry: JournalEntry) -> None:
        """Append one entry to the journal. Atomic at the line level
        (POSIX guarantees write(2) <= PIPE_BUF is atomic; JSONL lines
        are well below 4 KiB)."""
        line = entry.to_json_line() + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                # Force kernel-level durability so a crashed run still
                # leaves the journal consistent.
                try:
                    os.fsync(f.fileno())
                except (OSError, AttributeError):
                    # Some filesystems / mock FDs don't support fsync;
                    # we tried, that's the most we can do.
                    pass

    def append_many(self, entries: Iterable[JournalEntry]) -> int:
        """Append a batch. Returns count written. Single lock acquisition
        is faster than N individual append() calls."""
        n = 0
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                for entry in entries:
                    f.write(entry.to_json_line() + "\n")
                    n += 1
                f.flush()
                try:
                    os.fsync(f.fileno())
                except (OSError, AttributeError):
                    pass
        return n

    # ------------------------------------------------------------------ #
    def read_all(self) -> List[JournalEntry]:
        """Read every entry. For small-to-medium journals (~thousands).
        For larger volumes use `iter_entries`."""
        return list(self.iter_entries())

    def iter_entries(self) -> Iterator[JournalEntry]:
        """Stream entries one-at-a-time. Skips malformed lines with a
        log warning rather than aborting — resilience > strictness."""
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8") as f:
            for lineno, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                    yield JournalEntry(**obj)
                except (json.JSONDecodeError, TypeError, ValueError) as exc:
                    # Don't raise — corrupt or future-schema lines must
                    # not lock the apply layer out of the rest of the
                    # journal. Surface via stderr only.
                    import sys
                    print(
                        f"[LifecycleJournal] skipping malformed line "
                        f"{lineno} of {self.path}: {exc}",
                        file=sys.stderr,
                    )
                    continue

    # ------------------------------------------------------------------ #
    def filter_since(self, after_iso: str) -> List[JournalEntry]:
        """Return entries whose timestamp > `after_iso`. Used by the
        apply layer to read only un-applied entries."""
        try:
            cutoff = datetime.fromisoformat(after_iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"after_iso must be ISO-8601: {exc}")
        out: List[JournalEntry] = []
        for entry in self.iter_entries():
            try:
                ts = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                continue
            if ts > cutoff:
                out.append(entry)
        return out

    # ------------------------------------------------------------------ #
    def truncate(self, before_iso: Optional[str] = None) -> int:
        """Remove journal entries.

        - `before_iso=None` → wipe the file entirely. Returns count removed.
        - `before_iso="2026-05-01T00:00:00+00:00"` → remove entries with
          timestamp < cutoff (post-apply archiving). Returns count removed.

        Implementation: read-modify-rewrite via temp file + os.rename so
        the operation is crash-safe. POSIX atomic rename is the contract.
        """
        if before_iso is None:
            n = sum(1 for _ in self.iter_entries())
            with self._lock:
                self.path.write_text("", encoding="utf-8")
            return n

        try:
            cutoff = datetime.fromisoformat(before_iso.replace("Z", "+00:00"))
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"before_iso must be ISO-8601: {exc}")

        kept: List[str] = []
        removed = 0
        for entry in self.iter_entries():
            try:
                ts = datetime.fromisoformat(entry.timestamp.replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                # Keep unparseable entries; truncate is meant to be
                # conservative, not to silently drop edge cases.
                kept.append(entry.to_json_line())
                continue
            if ts < cutoff:
                removed += 1
            else:
                kept.append(entry.to_json_line())

        with self._lock:
            tmp = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp.open("w", encoding="utf-8") as f:
                if kept:
                    f.write("\n".join(kept) + "\n")
            os.replace(tmp, self.path)  # POSIX atomic
        return removed

    # ------------------------------------------------------------------ #
    def __len__(self) -> int:
        if not self.path.exists():
            return 0
        return sum(1 for _ in self.iter_entries())


# ---------------------------------------------------------------------- #
# Convenience constructors for the three most common decision types.

def make_weight_update(
    *, run_id: str, edge_id: str, new_weight: float,
    prior_weight: Optional[float] = None,
    timestamp: Optional[str] = None,
) -> JournalEntry:
    return JournalEntry(
        timestamp=timestamp or now_utc_iso(),
        run_id=run_id,
        decision_type="weight_update",
        edge_id=edge_id,
        payload={
            "new_weight": float(new_weight),
            "prior_weight": float(prior_weight) if prior_weight is not None else None,
        },
    )


def make_status_change(
    *, run_id: str, edge_id: str, new_status: str,
    prior_status: Optional[str] = None,
    reason: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> JournalEntry:
    return JournalEntry(
        timestamp=timestamp or now_utc_iso(),
        run_id=run_id,
        decision_type="status_change",
        edge_id=edge_id,
        payload={
            "new_status": str(new_status),
            "prior_status": str(prior_status) if prior_status else None,
            "reason": reason,
        },
    )


def make_tier_change(
    *, run_id: str, edge_id: str, new_tier: str,
    prior_tier: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> JournalEntry:
    return JournalEntry(
        timestamp=timestamp or now_utc_iso(),
        run_id=run_id,
        decision_type="tier_change",
        edge_id=edge_id,
        payload={
            "new_tier": str(new_tier),
            "prior_tier": str(prior_tier) if prior_tier else None,
        },
    )
