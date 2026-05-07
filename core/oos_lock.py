"""
core/oos_lock.py
================
Frozen-code OOS window discipline (audit finding F8).

The 2026-05-09 evening lessons-learned entry captured the meta-bias the
audit machinery did not catch: load-bearing parameters were hand-swept
against biased / OOS-contaminating targets. F8 from the consolidated
audit said: "define a real frozen-code OOS window where parameters are
NOT retuned. Discipline going forward."

This module implements that discipline as code so it can be enforced
programmatically rather than relying on every contributor to remember.

Schema: ``config/oos_window.json``

```json
{
  "schema_version": 1,
  "active": true,
  "window_start": "2026-Q1",        // ISO date or quarter
  "window_start_iso": "2026-01-01",
  "code_state_hash": "abc123def...",  // git rev at lock time
  "frozen_parameters": [
    "fill_share_cap",
    "PAUSED_MAX_WEIGHT",
    "sustained_score",
    "adv_floors"
  ],
  "lock_reason": "Post-engine-completion baseline; do not retune through 2026-Q4.",
  "locked_at": "2026-05-09T22:00:00+00:00",
  "locked_by": "<user>"
}
```

Usage from a parameter-sweep / tuning script:

```python
from core.oos_lock import assert_not_tuning_in_oos, load_oos_lock

lock = load_oos_lock()
# Asserts (start_date, end_date) overlap with OOS window for any
# frozen parameter being tuned. Raises OOSLockViolation if they do.
assert_not_tuning_in_oos(
    parameter="fill_share_cap",
    sweep_start="2026-01-01",
    sweep_end="2026-12-31",
    lock=lock,
)
```

When ``active=false`` or the lock file is absent, all helpers no-op.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable, List, Optional, Union

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LOCK_PATH = ROOT / "config" / "oos_window.json"


class OOSLockViolation(RuntimeError):
    """Raised when a parameter sweep would touch the OOS window."""


@dataclass(frozen=True)
class OOSLock:
    """In-memory representation of an OOS window lock."""
    active: bool = False
    window_start_iso: Optional[str] = None
    code_state_hash: Optional[str] = None
    frozen_parameters: List[str] = field(default_factory=list)
    lock_reason: Optional[str] = None
    locked_at: Optional[str] = None
    locked_by: Optional[str] = None

    @property
    def window_start_date(self) -> Optional[date]:
        if not self.window_start_iso:
            return None
        return date.fromisoformat(self.window_start_iso)

    def is_parameter_frozen(self, parameter: str) -> bool:
        if not self.active:
            return False
        return parameter in self.frozen_parameters


def load_oos_lock(path: Union[str, Path] = DEFAULT_LOCK_PATH) -> OOSLock:
    """Load the OOS lock from disk. Returns an inactive lock if file missing.

    The "inactive" return is the safe default — code that calls this from
    measurement scripts gets a no-op lock when no discipline window has
    been declared, preserving current behavior.
    """
    path = Path(path)
    if not path.exists():
        return OOSLock(active=False)
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return OOSLock(active=False)
    return OOSLock(
        active=bool(data.get("active", False)),
        window_start_iso=data.get("window_start_iso"),
        code_state_hash=data.get("code_state_hash"),
        frozen_parameters=list(data.get("frozen_parameters", [])),
        lock_reason=data.get("lock_reason"),
        locked_at=data.get("locked_at"),
        locked_by=data.get("locked_by"),
    )


def _to_date(value: Union[str, date, datetime]) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return date.fromisoformat(str(value))


def is_in_oos_window(
    when: Union[str, date, datetime], lock: Optional[OOSLock] = None
) -> bool:
    """True if ``when`` is on or after the lock's window_start.

    No-op (returns False) when the lock is inactive or has no start date.
    """
    if lock is None:
        lock = load_oos_lock()
    if not lock.active or lock.window_start_date is None:
        return False
    return _to_date(when) >= lock.window_start_date


def date_range_overlaps_oos(
    start: Union[str, date, datetime],  # noqa: ARG001 — accepted for caller clarity; see body
    end: Union[str, date, datetime],
    lock: Optional[OOSLock] = None,
) -> bool:
    """True if [start, end] overlaps the OOS window (anything ≥ window_start).

    The OOS window is open-ended on the right — once locked, it doesn't expire
    until the lock is explicitly retired or rolled forward. So the overlap
    check reduces to: does ``end`` fall inside the window? The ``start``
    parameter is accepted for caller-side readability (the call site reads
    naturally as "does this date range overlap…") but doesn't change the
    answer because anything ≤ end and ≥ window_start is automatically inside.
    """
    if lock is None:
        lock = load_oos_lock()
    if not lock.active or lock.window_start_date is None:
        return False
    return _to_date(end) >= lock.window_start_date


def assert_not_tuning_in_oos(
    parameter: str,
    sweep_start: Union[str, date, datetime],
    sweep_end: Union[str, date, datetime],
    lock: Optional[OOSLock] = None,
) -> None:
    """Raise ``OOSLockViolation`` if ``parameter`` is frozen AND the sweep
    window would observe data inside the OOS window.

    No-op when the lock is inactive, when ``parameter`` is not in the
    lock's frozen_parameters list, or when the sweep window ends before
    the OOS window starts.

    This is the load-bearing helper sweep scripts must call before tuning
    a parameter against a measurement window. Plays the same role that
    test isolation plays for unit tests: a forced check that prevents
    the most common discipline failure mode (silent leakage of OOS data
    into parameter selection).
    """
    if lock is None:
        lock = load_oos_lock()
    if not lock.is_parameter_frozen(parameter):
        return
    if not date_range_overlaps_oos(sweep_start, sweep_end, lock=lock):
        return
    raise OOSLockViolation(
        f"Parameter {parameter!r} is frozen by the OOS lock "
        f"(window starts {lock.window_start_iso}). "
        f"Sweep window {sweep_start}..{sweep_end} overlaps the OOS window. "
        f"Lock reason: {lock.lock_reason}. "
        f"To proceed: (a) restrict the sweep to data BEFORE {lock.window_start_iso}, "
        f"(b) explicitly retire the lock in config/oos_window.json with a "
        f"recorded rationale, or (c) roll the OOS window forward."
    )


def report_lock_status(lock: Optional[OOSLock] = None) -> str:
    """Render a one-paragraph human-readable summary of the current lock."""
    if lock is None:
        lock = load_oos_lock()
    if not lock.active:
        return (
            "OOS lock is INACTIVE. No parameter freezing in effect. "
            "Tuning scripts run unrestricted. (Set active=true and a "
            "window_start_iso in config/oos_window.json to enable.)"
        )
    return (
        f"OOS lock ACTIVE since {lock.locked_at} "
        f"(by {lock.locked_by or 'unknown'}). "
        f"Window starts {lock.window_start_iso}; code-state hash {lock.code_state_hash}. "
        f"Frozen parameters: {', '.join(lock.frozen_parameters) or 'none'}. "
        f"Reason: {lock.lock_reason}"
    )


def _git_rev_short(repo_root: Path = ROOT) -> str:
    """Best-effort git rev parse for lock-time code-state recording."""
    try:
        import subprocess
        out = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            cwd=repo_root, capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def write_lock(
    window_start_iso: str,
    frozen_parameters: Iterable[str],
    lock_reason: str,
    locked_by: str = "auto",
    path: Union[str, Path] = DEFAULT_LOCK_PATH,
) -> OOSLock:
    """Persist a new active OOS lock to ``path``.

    Records the current git rev at lock time so a future audit can verify
    that no code drift occurred between lock and use. If git rev is
    unavailable (not a repo), records ``"unknown"`` and proceeds.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 1,
        "active": True,
        "window_start_iso": window_start_iso,
        "code_state_hash": _git_rev_short(),
        "frozen_parameters": sorted(set(frozen_parameters)),
        "lock_reason": lock_reason,
        "locked_at": datetime.now(timezone.utc).replace(microsecond=0, tzinfo=None).isoformat() + "+00:00",
        "locked_by": locked_by,
    }
    path.write_text(json.dumps(payload, indent=2) + "\n")
    return load_oos_lock(path)
