"""
core/engine_versions.py
=======================
Engine versioning per audit recommendation (2026-05-09 evening).

Each engine package exposes a ``__version__`` (semver string) and a
``__charter_status__`` (human-readable drift note). This module reads
them at import time and exposes:

- ``get_all_engine_versions()`` → ``Dict[engine_letter, version_string]``
- ``get_charter_statuses()`` → ``Dict[engine_letter, status_string]``
- ``write_engine_versions_for_run()`` → snapshots versions to a per-run
  JSON file alongside ``performance_summary.json``

Why per-run versioning matters
------------------------------
The audit's recommendation: every trade should be tagged with the
engine versions used at decision time. Pragmatic implementation: write
a single ``engine_versions.json`` per run (alongside the trade log) at
backtest start. Every trade in the run inherits the snapshot via run_id.
Forensic reconstruction at any future date can map run_id → engine
versions used → diff of code state vs current state.

Semver semantics
----------------
``MAJOR.MINOR.PATCH`` per https://semver.org/. Pre-1.0 (current state)
indicates pre-stable engine implementation; the engine-completion
dispatches (C-engines-1 through C-engines-5) will bump engines past
0.1.0 as their respective charter drift gets closed.

Conventions:
- 0.x.y indicates the engine has charter drift / not stable
- 1.0.0 marks "engine satisfies its charter" (post-engine-completion)
- After 1.0.0: MAJOR for charter-shape changes, MINOR for capability
  additions, PATCH for bug fixes
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional

ROOT = Path(__file__).resolve().parents[1]

ENGINE_LETTERS = {
    "A": "engines.engine_a_alpha",
    "B": "engines.engine_b_risk",
    "C": "engines.engine_c_portfolio",
    "D": "engines.engine_d_discovery",
    "E": "engines.engine_e_regime",
    "F": "engines.engine_f_governance",
}

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def _import_engine(module_path: str):
    """Best-effort import; returns None on failure (engine package missing)."""
    try:
        return __import__(module_path, fromlist=["__version__"])
    except Exception:
        return None


def get_all_engine_versions() -> Dict[str, str]:
    """Return {engine_letter: version} for every engine. Missing
    ``__version__`` returns ``"0.0.0"`` so the caller never sees a
    KeyError or None."""
    out: Dict[str, str] = {}
    for letter, mod_path in ENGINE_LETTERS.items():
        mod = _import_engine(mod_path)
        version = getattr(mod, "__version__", None) if mod else None
        out[letter] = str(version) if version else "0.0.0"
    return out


def get_charter_statuses() -> Dict[str, str]:
    """Return {engine_letter: charter_status_string} for every engine."""
    out: Dict[str, str] = {}
    for letter, mod_path in ENGINE_LETTERS.items():
        mod = _import_engine(mod_path)
        status = getattr(mod, "__charter_status__", None) if mod else None
        out[letter] = str(status) if status else "(not declared)"
    return out


def is_valid_semver(version: str) -> bool:
    """Strict ``MAJOR.MINOR.PATCH`` only. Pre-release and build metadata
    not supported (KISS — extend if pre-release tags are ever needed)."""
    return bool(SEMVER_RE.match(version))


def get_engine_versions_snapshot(run_id: Optional[str] = None) -> Dict[str, object]:
    """Build the full snapshot dict to write to disk. Includes versions,
    charter statuses, ISO timestamp, and (optionally) run_id."""
    snap: Dict[str, object] = {
        "schema_version": 1,
        "snapshot_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "engine_versions": get_all_engine_versions(),
        "charter_statuses": get_charter_statuses(),
    }
    if run_id:
        snap["run_id"] = run_id
    return snap


def write_engine_versions_for_run(
    run_id: str, trade_logs_dir: Optional[Path] = None,
) -> Path:
    """Write ``engine_versions.json`` to ``trade_logs/<run_id>/``.

    Default ``trade_logs_dir = ROOT / "data" / "trade_logs"``. Caller can
    override for tests / non-default trade-log paths.

    Returns the path written. Does NOT overwrite an existing file —
    raises FileExistsError to surface accidental run_id collisions.
    """
    if trade_logs_dir is None:
        trade_logs_dir = ROOT / "data" / "trade_logs"
    out_dir = Path(trade_logs_dir) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "engine_versions.json"
    if out_path.exists():
        raise FileExistsError(
            f"engine_versions.json already exists at {out_path}. "
            f"Run-id collision? Refusing to overwrite — every backtest "
            f"run should produce exactly one snapshot."
        )
    snap = get_engine_versions_snapshot(run_id=run_id)
    out_path.write_text(json.dumps(snap, indent=2) + "\n")
    return out_path


def load_engine_versions_for_run(
    run_id: str, trade_logs_dir: Optional[Path] = None,
) -> Optional[Dict[str, object]]:
    """Read back the snapshot for forensic reconstruction. Returns None
    if no snapshot was written (legacy runs from before this feature)."""
    if trade_logs_dir is None:
        trade_logs_dir = ROOT / "data" / "trade_logs"
    snap_path = Path(trade_logs_dir) / run_id / "engine_versions.json"
    if not snap_path.exists():
        return None
    return json.loads(snap_path.read_text())


def report_engine_versions() -> str:
    """Render a one-paragraph summary string. Useful for stdout logging."""
    versions = get_all_engine_versions()
    statuses = get_charter_statuses()
    lines = ["Engine versions:"]
    for letter in sorted(ENGINE_LETTERS.keys()):
        v = versions.get(letter, "?")
        s = statuses.get(letter, "?")
        lines.append(f"  Engine {letter}: {v}  ({s})")
    return "\n".join(lines)


if __name__ == "__main__":
    print(report_engine_versions())
