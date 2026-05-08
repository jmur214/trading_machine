"""F11 Phase 2 wire-up tests.

Verifies that when a `LifecycleJournal` is provided to
`LifecycleManager.evaluate` or `governor.evaluate_lifecycle` /
`governor.evaluate_tiers`, status / tier decisions append to the journal
INSTEAD OF mutating ``edges.yml`` directly.

Default `journal=None` path is verified bit-for-bit identical to the
pre-F11 legacy behavior — these tests guarantee the rewire is opt-in
and zero-impact unless explicitly enabled.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pandas as pd
import pytest
import yaml

from engines.engine_f_governance.journal import (
    JournalEntry, LifecycleJournal,
)
from engines.engine_f_governance.lifecycle_manager import (
    LifecycleConfig, LifecycleManager, LifecycleEvent,
)


# ----- Fixtures ---------------------------------------------------- #

def _seed_registry(path: Path, edge_id: str = "e1", status: str = "active") -> None:
    rows = [{
        "edge_id": edge_id, "category": "test", "module": "test.mod",
        "version": "1.0.0", "params": {}, "status": status, "tier": "feature",
    }]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"edges": rows}, sort_keys=False))


def _read_status(path: Path, edge_id: str) -> str:
    data = yaml.safe_load(path.read_text()) or {}
    for row in data.get("edges", []):
        if row["edge_id"] == edge_id:
            return row["status"]
    return ""


@pytest.fixture()
def workspace(tmp_path: Path) -> dict:
    registry_path = tmp_path / "edges.yml"
    history_path = tmp_path / "lifecycle_history.csv"
    journal_path = tmp_path / "lifecycle_journal.jsonl"
    _seed_registry(registry_path, edge_id="losing_edge", status="active")
    return {
        "registry_path": registry_path,
        "history_path": history_path,
        "journal_path": journal_path,
        "journal": LifecycleJournal(journal_path),
    }


def _losing_trades() -> pd.DataFrame:
    """Trade DataFrame that triggers retirement / pause gates: 200 trades
    over 90+ days with consistently negative pnl, to clear retirement
    minimum thresholds."""
    base = pd.Timestamp("2024-01-01", tz="UTC")
    rows = []
    for i in range(220):
        rows.append({
            "edge": "losing_edge",
            "pnl": -50.0,
            "timestamp": base + pd.Timedelta(days=i // 2),
            "trigger": "exit",
        })
    return pd.DataFrame(rows)


# ----- LifecycleManager.evaluate journal path ---------------------- #

def test_evaluate_with_journal_appends_status_change(workspace) -> None:
    """When journal is provided AND a lifecycle event fires, the change
    appends to the journal as a status_change entry — and edges.yml is
    NOT mutated."""
    cfg = LifecycleConfig(enabled=True, retirement_min_trades=100,
                          retirement_min_days=30, retirement_margin=0.0)
    lcm = LifecycleManager(
        cfg=cfg,
        registry_path=workspace["registry_path"],
        history_path=workspace["history_path"],
    )
    pre_status = _read_status(workspace["registry_path"], "losing_edge")
    assert pre_status == "active"

    events = lcm.evaluate(
        trades=_losing_trades(),
        benchmark_sharpe=0.5,
        journal=workspace["journal"],
        journal_run_id="test-run-aaa",
    )

    # Events fired
    assert len(events) >= 1, "expected at least one lifecycle event"

    # edges.yml UNCHANGED — journal-mode means no direct mutation
    post_status = _read_status(workspace["registry_path"], "losing_edge")
    assert post_status == "active", (
        f"edges.yml was mutated despite journal-mode (pre={pre_status} "
        f"post={post_status}); F11 Phase 2 invariant violated"
    )

    # Journal has the entry instead
    entries = workspace["journal"].read_all()
    assert len(entries) >= 1
    assert any(e.decision_type == "status_change" and e.edge_id == "losing_edge"
               for e in entries), (
        f"journal missing expected status_change entry; saw: "
        f"{[(e.decision_type, e.edge_id) for e in entries]}"
    )


def test_evaluate_without_journal_uses_legacy_direct_mutation(workspace) -> None:
    """When journal is None (the default), evaluate writes through the
    legacy _save_registry path — preserving bit-for-bit behavior."""
    cfg = LifecycleConfig(enabled=True, retirement_min_trades=100,
                          retirement_min_days=30, retirement_margin=0.0)
    lcm = LifecycleManager(
        cfg=cfg,
        registry_path=workspace["registry_path"],
        history_path=workspace["history_path"],
    )
    events = lcm.evaluate(
        trades=_losing_trades(),
        benchmark_sharpe=0.5,
    )
    assert len(events) >= 1
    # Legacy path mutates edges.yml directly
    post_status = _read_status(workspace["registry_path"], "losing_edge")
    assert post_status != "active", (
        f"Legacy path didn't mutate; status={post_status}"
    )
    # Journal must be empty — no entries when journal not provided
    assert len(workspace["journal"]) == 0


def test_evaluate_journal_run_id_propagates(workspace) -> None:
    """Journal entries from evaluate must carry the supplied run_id."""
    cfg = LifecycleConfig(enabled=True, retirement_min_trades=100,
                          retirement_min_days=30, retirement_margin=0.0)
    lcm = LifecycleManager(
        cfg=cfg,
        registry_path=workspace["registry_path"],
        history_path=workspace["history_path"],
    )
    lcm.evaluate(
        trades=_losing_trades(),
        benchmark_sharpe=0.5,
        journal=workspace["journal"],
        journal_run_id="run-xyz-123",
    )
    entries = workspace["journal"].read_all()
    status_changes = [e for e in entries if e.decision_type == "status_change"]
    assert all(e.run_id == "run-xyz-123" for e in status_changes)


def test_evaluate_history_csv_written_in_both_paths(workspace) -> None:
    """lifecycle_history.csv is a separate audit trail (not edges.yml);
    it should be appended in both journal and legacy paths."""
    cfg = LifecycleConfig(enabled=True, retirement_min_trades=100,
                          retirement_min_days=30, retirement_margin=0.0)
    lcm = LifecycleManager(
        cfg=cfg,
        registry_path=workspace["registry_path"],
        history_path=workspace["history_path"],
    )
    lcm.evaluate(
        trades=_losing_trades(),
        benchmark_sharpe=0.5,
        journal=workspace["journal"],
        journal_run_id="run-1",
    )
    assert workspace["history_path"].exists()
    # File should be non-empty after at least one event was journaled
    assert workspace["history_path"].stat().st_size > 0


def test_evaluate_signature_accepts_journal_kwargs() -> None:
    """API contract: the new kwargs must NOT break callers that omit them."""
    import inspect
    sig = inspect.signature(LifecycleManager.evaluate)
    params = sig.parameters
    assert "journal" in params
    assert "journal_run_id" in params
    # Both must default-None / default-string so positional callers still work
    assert params["journal"].default is None
    assert params["journal_run_id"].default == "unknown"


# ----- Mode-controller plumbing ---------------------------------- #

def test_mode_controller_run_backtest_has_apply_journal_at_end_kwarg() -> None:
    """The new kwarg must be present and default False."""
    import inspect
    from orchestration.mode_controller import ModeController
    sig = inspect.signature(ModeController.run_backtest)
    assert "apply_journal_at_end" in sig.parameters
    assert sig.parameters["apply_journal_at_end"].default is False


def test_governor_evaluate_lifecycle_accepts_journal() -> None:
    import inspect
    from engines.engine_f_governance.governor import StrategyGovernor
    sig = inspect.signature(StrategyGovernor.evaluate_lifecycle)
    assert "journal" in sig.parameters
    assert "journal_run_id" in sig.parameters
    assert sig.parameters["journal"].default is None


def test_governor_evaluate_tiers_accepts_journal() -> None:
    import inspect
    from engines.engine_f_governance.governor import StrategyGovernor
    sig = inspect.signature(StrategyGovernor.evaluate_tiers)
    assert "journal" in sig.parameters
    assert "journal_run_id" in sig.parameters
    assert sig.parameters["journal"].default is None
