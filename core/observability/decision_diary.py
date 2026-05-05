"""Decision Diary — append-only structured log of significant decisions.

Writes JSON Lines to ``data/governor/decision_diary.jsonl``. Each line is
one decision: a flag flip, a merge to main, an edge status change, a config
change, a measurement run, or an agent dispatch. Future analytics, audits,
and post-hoc impact reviews read this file rather than reconstructing
decision history from git log or memory files.

Design properties:

- **Append-only.** ``append_entry`` opens the file with mode ``"a"`` and
  never edits prior lines. ``actual_impact`` is left nullable at write
  time so the same record can later be enriched by a separate process
  (e.g. nightly CI populates impact for ``measurement_run`` entries) by
  appending a new follow-up entry — never by mutating the original.
- **Schema-versioned.** Each entry carries ``schema_version`` so future
  format extensions don't break old readers.
- **Crash-safe.** Each call opens the file fresh, writes one line ending
  in ``\\n``, then closes. Partial writes leave an unparseable trailing
  line at worst, which ``read_entries`` skips with a warning.
- **Lightweight.** No dependencies beyond stdlib ``json`` + ``dataclasses``.
  Safe to call from inside ``mode_controller.run_backtest`` without
  introducing a new import-time dependency on heavy modules.

Example:

    from core.observability import append_entry, DecisionType

    append_entry(
        decision_type=DecisionType.MEASUREMENT_RUN,
        what_changed="2021-2025 multi-year run, mean Sharpe 1.296",
        expected_impact=None,
        rationale_link="docs/Audit/multi_year_foundation_measurement.md",
    )
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Union

logger = logging.getLogger(__name__)


SCHEMA_VERSION: int = 1


class DecisionType(str, Enum):
    """Closed vocabulary of decision types — keep narrow on purpose.

    Add new members deliberately; downstream consumers (dashboards,
    aggregators) may switch on this field.
    """

    FLAG_FLIP = "flag_flip"
    MERGE = "merge"
    EDGE_STATUS_CHANGE = "edge_status_change"
    CONFIG_CHANGE = "config_change"
    MEASUREMENT_RUN = "measurement_run"
    AGENT_DISPATCH = "agent_dispatch"


# Resolved relative to the project root, which we infer as the repo
# containing this file. ``data/governor/`` is gitignored — the diary is
# operational state, not source.
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
DEFAULT_DIARY_PATH: Path = _PROJECT_ROOT / "data" / "governor" / "decision_diary.jsonl"


@dataclass(frozen=True)
class DecisionDiaryEntry:
    """One decision diary record.

    All fields are JSON-safe (no datetime objects, no Path objects);
    ``timestamp`` is ISO-8601 UTC string and ``rationale_link`` is the
    string form of either a path or a commit/PR hash.
    """

    timestamp: str
    decision_type: str
    what_changed: str
    expected_impact: Optional[str] = None
    actual_impact: Optional[str] = None
    rationale_link: Optional[str] = None
    schema_version: int = SCHEMA_VERSION
    extra: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # Validate decision_type against the enum without forcing callers
        # to import the enum (they may pass a literal string).
        valid = {t.value for t in DecisionType}
        if self.decision_type not in valid:
            raise ValueError(
                f"decision_type {self.decision_type!r} not in "
                f"{sorted(valid)}"
            )
        if not self.what_changed:
            raise ValueError("what_changed must be non-empty")
        if len(self.what_changed) > 200:
            raise ValueError(
                f"what_changed must be ≤200 chars, got {len(self.what_changed)}"
            )

    def to_json_line(self) -> str:
        """Serialize as a single JSON line (no embedded newlines)."""
        payload = asdict(self)
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _now_iso() -> str:
    """ISO-8601 UTC timestamp with seconds resolution.

    We intentionally drop sub-second precision: the diary is for human
    audit, not high-frequency event correlation. Microseconds make
    files harder to scan visually.
    """
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def append_entry(
    *,
    decision_type: Union[DecisionType, str],
    what_changed: str,
    expected_impact: Optional[str] = None,
    actual_impact: Optional[str] = None,
    rationale_link: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    diary_path: Optional[Union[Path, str]] = None,
    timestamp: Optional[str] = None,
) -> DecisionDiaryEntry:
    """Append one decision to the diary file (append-only, JSONL).

    Parameters
    ----------
    decision_type
        One of ``DecisionType`` or the matching string. Validated.
    what_changed
        Free-text, ≤200 chars. Validated.
    expected_impact, actual_impact, rationale_link, extra
        Optional. ``actual_impact`` is typically left ``None`` at write
        time and filled in by a follow-up entry once measured.
    diary_path
        Override (mainly for tests). Defaults to ``DEFAULT_DIARY_PATH``.
    timestamp
        Override (mainly for tests). Defaults to current UTC time.

    Returns
    -------
    DecisionDiaryEntry
        The exact record that was written, useful for asserting in tests.

    Notes
    -----
    Writes are best-effort: if the parent directory cannot be created or
    the file cannot be opened for append, we log at WARNING and re-raise
    so callers explicitly opt into swallowing errors. The wiring point
    in ``mode_controller.run_backtest`` wraps this in try/except so a
    diary failure cannot crash a backtest.
    """
    path = Path(diary_path) if diary_path is not None else DEFAULT_DIARY_PATH
    dt_value = (
        decision_type.value
        if isinstance(decision_type, DecisionType)
        else str(decision_type)
    )
    entry = DecisionDiaryEntry(
        timestamp=timestamp or _now_iso(),
        decision_type=dt_value,
        what_changed=what_changed,
        expected_impact=expected_impact,
        actual_impact=actual_impact,
        rationale_link=rationale_link,
        extra=dict(extra or {}),
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    line = entry.to_json_line() + "\n"
    # Mode "a" guarantees POSIX append semantics on Linux/macOS — multiple
    # processes appending concurrently won't interleave bytes within a
    # single line.
    with path.open("a", encoding="utf-8") as fh:
        fh.write(line)
    return entry


def read_entries(
    diary_path: Optional[Union[Path, str]] = None,
    decision_types: Optional[Iterable[Union[DecisionType, str]]] = None,
) -> List[DecisionDiaryEntry]:
    """Read all entries from the diary file.

    Returns an empty list if the file does not exist (a fresh checkout
    has no history yet, which is fine).

    Lines that fail to parse — corrupted by a partial write or a
    schema-incompatible writer — are skipped with a WARNING log and the
    rest of the file is processed. Callers should not assume the
    returned list is in 1:1 correspondence with on-disk lines.
    """
    path = Path(diary_path) if diary_path is not None else DEFAULT_DIARY_PATH
    if not path.exists():
        return []

    wanted: Optional[set] = None
    if decision_types is not None:
        wanted = {
            t.value if isinstance(t, DecisionType) else str(t)
            for t in decision_types
        }

    out: List[DecisionDiaryEntry] = []
    with path.open("r", encoding="utf-8") as fh:
        for lineno, raw in enumerate(fh, start=1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                logger.warning(
                    "decision_diary: skipping malformed line %d in %s: %s",
                    lineno, path, exc,
                )
                continue
            try:
                entry = DecisionDiaryEntry(
                    timestamp=payload["timestamp"],
                    decision_type=payload["decision_type"],
                    what_changed=payload["what_changed"],
                    expected_impact=payload.get("expected_impact"),
                    actual_impact=payload.get("actual_impact"),
                    rationale_link=payload.get("rationale_link"),
                    schema_version=int(payload.get("schema_version", 1)),
                    extra=dict(payload.get("extra") or {}),
                )
            except (KeyError, ValueError, TypeError) as exc:
                logger.warning(
                    "decision_diary: skipping invalid line %d in %s: %s",
                    lineno, path, exc,
                )
                continue
            if wanted is not None and entry.decision_type not in wanted:
                continue
            out.append(entry)
    return out
