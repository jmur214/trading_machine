"""Observability — cross-cutting introspection helpers.

This package collects small, narrowly-scoped components that surface
operational state across the rest of the system without belonging to
any one engine.

Currently:
- `decision_diary` — append-only JSONL log of significant config flips,
  merges, edge status changes, and measurement runs.
- `leakage_detector` — static-analysis advisor that flags common
  forward-shift / look-ahead patterns in @feature-decorated functions.

Both are intentionally lightweight. Neither owns lifecycle decisions
nor blocks execution; they exist to make later humans (and agents) faster
at reasoning about what changed and why.
"""
from __future__ import annotations

from .decision_diary import (
    DecisionDiaryEntry,
    DecisionType,
    append_entry,
    read_entries,
    DEFAULT_DIARY_PATH,
)
from .leakage_detector import (
    LeakageWarning,
    LeakagePattern,
    scan_source,
    scan_callable,
)

__all__ = [
    "DecisionDiaryEntry",
    "DecisionType",
    "append_entry",
    "read_entries",
    "DEFAULT_DIARY_PATH",
    "LeakageWarning",
    "LeakagePattern",
    "scan_source",
    "scan_callable",
]
