"""
tests/test_lifecycle_manager.py
================================
Regression tests for the autonomous edge lifecycle manager
(`engines/engine_f_governance/lifecycle_manager.py`).

These tests promote the synthetic smoke-tests that were run inline during
development (2026-04-24) into permanent regression coverage. They verify
that the lifecycle:

- Pauses consistently-losing edges based on the loss-fraction gate
- Leaves winning edges alone
- Protects edges that are recently recovering (revival-window check)
- Honors the cycle caps (max retirements/pauses per cycle)
- Writes status changes to the registry yaml AND the audit CSV
- Reads benchmark-relative thresholds correctly

This file complements `tests/test_edge_registry.py`'s Write Contract
enforcement — together they cover the autonomy machinery end-to-end.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_f_governance.lifecycle_manager import (
    LifecycleConfig,
    LifecycleManager,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _seed_registry(path: Path, edges: list[dict]) -> None:
    """Write a minimal edges.yml at `path` from a list of dicts."""
    path.write_text(yaml.dump({"edges": edges}, sort_keys=False))


def _make_trades(edge_pnls: dict[str, np.ndarray],
                 start: str = "2024-01-01") -> pd.DataFrame:
    """Build a synthetic trade log: each edge gets N trades, one per day."""
    rows = []
    for edge_id, pnls in edge_pnls.items():
        dates = pd.date_range(start=start, periods=len(pnls), freq="D", tz="UTC")
        for ts, pnl in zip(dates, pnls):
            rows.append({"timestamp": ts, "edge": edge_id, "pnl": float(pnl)})
    return pd.DataFrame(rows)


@pytest.fixture
def cfg() -> LifecycleConfig:
    return LifecycleConfig(
        enabled=True,
        retirement_min_trades=100,
        retirement_min_days=90,
        retirement_margin=0.3,
    )


@pytest.fixture
def lcm_factory(tmp_path, cfg):
    """Factory that builds a LifecycleManager pointed at temp paths."""
    def _make() -> tuple[LifecycleManager, Path, Path]:
        registry_path = tmp_path / "edges.yml"
        history_path = tmp_path / "lifecycle_history.csv"
        return LifecycleManager(
            cfg=cfg, registry_path=registry_path, history_path=history_path,
        ), registry_path, history_path
    return _make


# ---------------------------------------------------------------------------
# Pause gate: consistently-losing edge gets paused
# ---------------------------------------------------------------------------

def test_pause_fires_on_loss_fraction_gate(lcm_factory):
    """An edge with trailing 30-trade loss > 30% of deployed gross should pause.

    Construct the trade history so RECENT trades are clearly catastrophic
    (loss_fraction << -0.30) while overall history isn't severe enough for
    retirement to bypass the pause check. This isolates the pause-gate path.
    """
    lcm, registry_path, _ = lcm_factory()
    rng = np.random.default_rng(42)
    # First 120 trades roughly flat; last 30 consistently negative
    # → recent loss_fraction strongly negative (pause), but overall sharpe
    # not so negative that retirement bypasses pause
    flat = rng.normal(loc=0.5, scale=8.0, size=120)
    recent_blowup = rng.normal(loc=-12.0, scale=5.0, size=30)
    losing = np.concatenate([flat, recent_blowup])
    _seed_registry(registry_path, [
        {"edge_id": "loser", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    trades = _make_trades({"loser": losing})

    events = lcm.evaluate(trades, benchmark_sharpe=1.0)

    assert len(events) == 1
    ev = events[0]
    assert ev.edge_id == "loser"
    assert ev.new_status == "paused", (
        f"expected pause (recent blowup), got {ev.new_status} via {ev.triggering_gate}"
    )
    assert "loss_fraction" in ev.triggering_gate

    # Registry persisted
    final = yaml.safe_load(registry_path.read_text())
    statuses = {e["edge_id"]: e["status"] for e in final["edges"]}
    assert statuses["loser"] == "paused"


# ---------------------------------------------------------------------------
# Winning edge: stays active, no transitions
# ---------------------------------------------------------------------------

def test_winning_edge_stays_active(lcm_factory):
    lcm, registry_path, _ = lcm_factory()
    rng = np.random.default_rng(42)
    winning = rng.normal(loc=8.0, scale=15.0, size=150)  # solidly winning
    _seed_registry(registry_path, [
        {"edge_id": "winner", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    trades = _make_trades({"winner": winning})

    events = lcm.evaluate(trades, benchmark_sharpe=1.0)

    assert len(events) == 0
    statuses = {e["edge_id"]: e["status"]
                for e in yaml.safe_load(registry_path.read_text())["edges"]}
    assert statuses["winner"] == "active"


# ---------------------------------------------------------------------------
# Revival protection: edge that's recovering should NOT be retired
# ---------------------------------------------------------------------------

def test_recovering_edge_not_retired(lcm_factory):
    """Historical losses but recent recovery — protect from retirement."""
    lcm, registry_path, _ = lcm_factory()
    rng = np.random.default_rng(42)
    # First 120 trades losing badly, last 30 strong recovery
    pnls = np.concatenate([
        rng.normal(loc=-5.0, scale=20.0, size=120),
        rng.normal(loc=15.0, scale=10.0, size=30),
    ])
    _seed_registry(registry_path, [
        {"edge_id": "reviving", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    trades = _make_trades({"reviving": pnls})

    events = lcm.evaluate(trades, benchmark_sharpe=1.0)

    # Recent recovery should keep it from retiring.
    # (Pause may still fire on loss-fraction since recent-30 may be mixed,
    # depending on rng — but retirement specifically should NOT happen.)
    retire_events = [e for e in events if e.new_status == "retired"]
    assert len(retire_events) == 0


# ---------------------------------------------------------------------------
# Audit trail: every transition logged with full evidence
# ---------------------------------------------------------------------------

def test_audit_trail_written(lcm_factory):
    """Any transition (pause OR retire) must be captured with full evidence."""
    lcm, registry_path, history_path = lcm_factory()
    rng = np.random.default_rng(42)
    # Use the recent-blowup pattern to deterministically trigger pause
    flat = rng.normal(loc=0.5, scale=8.0, size=120)
    recent_blowup = rng.normal(loc=-12.0, scale=5.0, size=30)
    losing = np.concatenate([flat, recent_blowup])
    _seed_registry(registry_path, [
        {"edge_id": "auditme", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    trades = _make_trades({"auditme": losing})

    events = lcm.evaluate(trades, benchmark_sharpe=1.0)
    assert len(events) == 1

    audit = pd.read_csv(history_path)
    assert len(audit) == 1
    row = audit.iloc[0]
    # Full evidence captured regardless of which gate fired
    assert row["edge_id"] == "auditme"
    assert row["old_status"] == "active"
    assert row["new_status"] in ("paused", "retired")
    # Triggering gate is non-empty and informative
    assert isinstance(row["triggering_gate"], str) and row["triggering_gate"]
    assert pd.notna(row["edge_sharpe"])
    assert pd.notna(row["benchmark_sharpe"])
    assert row["trade_count"] == 150


# ---------------------------------------------------------------------------
# Cycle caps: limit damage from cascading transitions
# ---------------------------------------------------------------------------

def test_max_pauses_per_cycle_cap(lcm_factory):
    """If 5 edges all qualify for pause, only `max_pauses_per_cycle` fire."""
    lcm, registry_path, _ = lcm_factory()
    lcm.cfg.max_pauses_per_cycle = 2  # explicit cap
    rng = np.random.default_rng(42)
    edge_pnls = {
        f"loser_{i}": rng.normal(loc=-5.0, scale=20.0, size=150)
        for i in range(5)
    }
    _seed_registry(registry_path, [
        {"edge_id": eid, "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
        for eid in edge_pnls
    ])
    trades = _make_trades(edge_pnls)

    events = lcm.evaluate(trades, benchmark_sharpe=1.0)
    pauses = [e for e in events if e.new_status == "paused"]
    assert len(pauses) == 2, f"expected 2 pauses (cap), got {len(pauses)}"


# ---------------------------------------------------------------------------
# Disabled lifecycle: no events fire
# ---------------------------------------------------------------------------

def test_disabled_lifecycle_no_op(lcm_factory):
    lcm, registry_path, _ = lcm_factory()
    lcm.cfg.enabled = False  # disable
    rng = np.random.default_rng(42)
    losing = rng.normal(loc=-5.0, scale=20.0, size=150)
    _seed_registry(registry_path, [
        {"edge_id": "ignore_me", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    trades = _make_trades({"ignore_me": losing})

    events = lcm.evaluate(trades, benchmark_sharpe=1.0)
    assert events == []
    # Registry unchanged
    statuses = {e["edge_id"]: e["status"]
                for e in yaml.safe_load(registry_path.read_text())["edges"]}
    assert statuses["ignore_me"] == "active"


# ---------------------------------------------------------------------------
# Empty / sparse trade data: graceful no-op
# ---------------------------------------------------------------------------

def test_empty_trades_no_op(lcm_factory):
    lcm, registry_path, _ = lcm_factory()
    _seed_registry(registry_path, [
        {"edge_id": "no_data", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    empty = pd.DataFrame(columns=["timestamp", "edge", "pnl"])
    events = lcm.evaluate(empty, benchmark_sharpe=1.0)
    assert events == []


def test_insufficient_trades_no_pause(lcm_factory):
    """Edges with < pause_min_trades should not be paused regardless of pnl."""
    lcm, registry_path, _ = lcm_factory()
    rng = np.random.default_rng(42)
    # Only 20 trades — below the default pause_min_trades of 30
    short_losing = rng.normal(loc=-5.0, scale=20.0, size=20)
    _seed_registry(registry_path, [
        {"edge_id": "tiny_sample", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    trades = _make_trades({"tiny_sample": short_losing})

    events = lcm.evaluate(trades, benchmark_sharpe=1.0)
    assert events == [], "should not pause on insufficient evidence"


# ---------------------------------------------------------------------------
# Mixed roster — winner stays, loser pauses, recovering protected (the integration test)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Phase α v3: divergence detection
# ---------------------------------------------------------------------------

def test_divergence_check_no_op_with_empty_history(lcm_factory):
    """No history file → no divergence to detect → empty list, no warning."""
    lcm, registry_path, history_path = lcm_factory()
    _seed_registry(registry_path, [
        {"edge_id": "e1", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    # history_path doesn't exist yet
    divergences = lcm._audit_registry_divergence_check()
    assert divergences == []


def test_divergence_check_no_op_when_audit_and_registry_agree(lcm_factory):
    """Audit trail says 'paused' and registry says 'paused' → no divergence."""
    lcm, registry_path, history_path = lcm_factory()
    _seed_registry(registry_path, [
        {"edge_id": "agreed", "status": "paused", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    history_path.write_text(
        "timestamp,edge_id,old_status,new_status,triggering_gate,"
        "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
        "2024-12-31T00:00:00+00:00,agreed,active,paused,test_gate,"
        "0.0,1.0,0.0,150,90,\n"
    )
    divergences = lcm._audit_registry_divergence_check()
    assert divergences == []


def test_divergence_check_flags_status_reverted(lcm_factory):
    """The 2026-04-25 stomp-bug signature: audit trail says 'paused' but
    the registry has been silently reverted to 'active'. The check should
    flag this so the next bug class is impossible to hide."""
    lcm, registry_path, history_path = lcm_factory()
    _seed_registry(registry_path, [
        {"edge_id": "stomped", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    # Simulate accumulated audit trail: lifecycle paused this edge yesterday,
    # but something (e.g., a registry-stomp bug) reverted it to active before
    # today's check.
    history_path.write_text(
        "timestamp,edge_id,old_status,new_status,triggering_gate,"
        "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
        "2024-12-30T00:00:00+00:00,stomped,active,paused,loss_fraction,"
        "-0.3,1.0,-0.4,150,90,\n"
    )
    divergences = lcm._audit_registry_divergence_check()
    assert len(divergences) == 1
    d = divergences[0]
    assert d["edge_id"] == "stomped"
    assert d["audit_says"] == "paused"
    assert d["registry_says"] == "active"
    assert d["kind"] == "status_reverted"


def test_divergence_check_flags_missing_from_registry(lcm_factory):
    """If the audit trail mentions an edge_id not in the current registry,
    flag with a different kind so consumers can distinguish revert vs
    rename/removal."""
    lcm, registry_path, history_path = lcm_factory()
    _seed_registry(registry_path, [
        {"edge_id": "kept", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    history_path.write_text(
        "timestamp,edge_id,old_status,new_status,triggering_gate,"
        "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
        "2024-12-30T00:00:00+00:00,gone_edge,active,paused,test,"
        "-0.3,1.0,-0.4,150,90,\n"
    )
    divergences = lcm._audit_registry_divergence_check()
    assert len(divergences) == 1
    assert divergences[0]["kind"] == "missing_from_registry"


def test_divergence_check_uses_most_recent_event(lcm_factory):
    """When an edge has multiple audit-trail rows, only the latest one
    matters. paused → active (revival) → paused (re-pause) should compare
    'paused' (the latest) against the registry, not 'active' (an earlier row)."""
    lcm, registry_path, history_path = lcm_factory()
    _seed_registry(registry_path, [
        {"edge_id": "multi", "status": "paused", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    history_path.write_text(
        "timestamp,edge_id,old_status,new_status,triggering_gate,"
        "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
        "2024-12-29T00:00:00+00:00,multi,active,paused,gate1,-0.3,1.0,-0.4,150,90,\n"
        "2024-12-30T00:00:00+00:00,multi,paused,active,revival,0.6,1.0,-0.1,170,120,\n"
        "2024-12-31T00:00:00+00:00,multi,active,paused,gate2,-0.2,1.0,-0.3,180,130,\n"
    )
    # Latest event is 'paused' and registry is 'paused' → agree → no divergence
    divergences = lcm._audit_registry_divergence_check()
    assert divergences == [], (
        f"latest audit row says 'paused', registry is 'paused'; "
        f"should agree, got divergences {divergences}"
    )


def test_evaluate_runs_divergence_check_without_breaking(lcm_factory):
    """Calling evaluate() should run the divergence check as a side
    effect (warning only) and still complete normally even when
    divergence is present."""
    lcm, registry_path, history_path = lcm_factory()
    _seed_registry(registry_path, [
        {"edge_id": "diverged", "status": "active", "category": "technical",
         "module": "m", "version": "1.0.0", "params": {}}
    ])
    history_path.write_text(
        "timestamp,edge_id,old_status,new_status,triggering_gate,"
        "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
        "2024-12-30T00:00:00+00:00,diverged,active,paused,gate1,-0.3,1.0,-0.4,150,90,\n"
    )
    # Provide some trades; evaluate should run (and log the divergence
    # warning internally) without raising
    rng = np.random.default_rng(42)
    trades = _make_trades({"diverged": rng.normal(0, 5, 50)})
    events = lcm.evaluate(trades, benchmark_sharpe=1.0)
    # Just need to confirm it doesn't crash. Returned events list is
    # implementation-detail (may or may not pause again given the flat-ish trades).
    assert isinstance(events, list)


def test_three_edge_integration(lcm_factory):
    """The exact synthetic test that proved the lifecycle works on 2026-04-24."""
    lcm, registry_path, _ = lcm_factory()
    rng = np.random.default_rng(42)

    losing = rng.normal(loc=-5.0, scale=30.0, size=150)        # consistently losing
    winning = rng.normal(loc=8.0, scale=25.0, size=150)         # consistently winning
    reviving = np.concatenate([                                 # losing then winning
        rng.normal(loc=-5.0, scale=30.0, size=120),
        rng.normal(loc=20.0, scale=15.0, size=30),
    ])

    _seed_registry(registry_path, [
        {"edge_id": "atr_breakout_v1", "status": "active",
         "category": "technical", "module": "m", "version": "1.0.0", "params": {}},
        {"edge_id": "momentum_edge_v1", "status": "active",
         "category": "technical", "module": "m", "version": "1.0.0", "params": {}},
        {"edge_id": "reviving_edge_v1", "status": "active",
         "category": "technical", "module": "m", "version": "1.0.0", "params": {}},
    ])
    trades = _make_trades({
        "atr_breakout_v1": losing,
        "momentum_edge_v1": winning,
        "reviving_edge_v1": reviving,
    })

    events = lcm.evaluate(trades, benchmark_sharpe=1.0)
    statuses = {e["edge_id"]: e["status"]
                for e in yaml.safe_load(registry_path.read_text())["edges"]}

    # Loser: paused or retired (retire is gated by cycle cap; either is correct)
    assert statuses["atr_breakout_v1"] in ("paused", "retired")
    # Winner: stays active
    assert statuses["momentum_edge_v1"] == "active"
    # Reviving: should NOT be retired (recent recovery protects)
    # (May still pause if loss-fraction window catches it; that's acceptable.)
    assert statuses["reviving_edge_v1"] != "retired"


# ---------------------------------------------------------------------------
# paused → retired: long-stuck negative edge gets retired from soft-pause
# ---------------------------------------------------------------------------

def _write_pause_history(history_path: Path, edge_id: str, pause_ts: str) -> None:
    """Write a lifecycle_history.csv with one pause event for edge_id."""
    import csv
    with history_path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "timestamp", "edge_id", "old_status", "new_status",
            "triggering_gate", "edge_sharpe", "benchmark_sharpe",
            "edge_mdd", "trade_count", "days_active", "notes",
        ])
        w.writeheader()
        w.writerow({
            "timestamp": pause_ts,
            "edge_id": edge_id,
            "old_status": "active",
            "new_status": "paused",
            "triggering_gate": "loss_fraction_-0.41",
            "edge_sharpe": -0.33,
            "benchmark_sharpe": 0.87,
            "edge_mdd": -0.41,
            "trade_count": 300,
            "days_active": 400,
            "notes": "",
        })


def test_paused_edge_retired_after_min_days(tmp_path):
    """A paused edge that stays negative past paused_retirement_min_days is retired."""
    registry_path = tmp_path / "edges.yml"
    history_path = tmp_path / "lifecycle_history.csv"
    cfg = LifecycleConfig(
        enabled=True,
        paused_retirement_min_days=90,
        retirement_margin=0.3,
        max_retirements_per_cycle=2,
    )
    lcm = LifecycleManager(cfg=cfg, registry_path=registry_path, history_path=history_path)

    # Edge has been paused 120 days ago — past the 90-day min
    pause_ts = "2024-09-01T00:00:00+00:00"
    _write_pause_history(history_path, "bad_edge_v1", pause_ts)

    _seed_registry(registry_path, [
        {"edge_id": "bad_edge_v1", "status": "paused",
         "category": "technical", "module": "m", "version": "1.0.0", "params": {}},
    ])
    rng = np.random.default_rng(0)
    losing = rng.normal(loc=-5.0, scale=20.0, size=150)
    trades = _make_trades({"bad_edge_v1": losing}, start="2024-01-01")
    as_of = pd.Timestamp("2025-01-01", tz="UTC")

    events = lcm.evaluate(trades, benchmark_sharpe=0.87, as_of=as_of)
    statuses = {e["edge_id"]: e["status"]
                for e in yaml.safe_load(registry_path.read_text())["edges"]}

    assert statuses["bad_edge_v1"] == "retired"
    assert any(ev.new_status == "retired" and ev.edge_id == "bad_edge_v1" for ev in events)


def test_paused_edge_not_retired_before_min_days(tmp_path):
    """A paused edge inside the min-days hold period is NOT retired."""
    registry_path = tmp_path / "edges.yml"
    history_path = tmp_path / "lifecycle_history.csv"
    cfg = LifecycleConfig(
        enabled=True,
        paused_retirement_min_days=90,
        retirement_margin=0.3,
        max_retirements_per_cycle=2,
    )
    lcm = LifecycleManager(cfg=cfg, registry_path=registry_path, history_path=history_path)

    # Paused only 10 days ago — well inside the 90-day hold
    pause_ts = "2024-12-22T00:00:00+00:00"
    _write_pause_history(history_path, "fresh_pause_v1", pause_ts)

    _seed_registry(registry_path, [
        {"edge_id": "fresh_pause_v1", "status": "paused",
         "category": "technical", "module": "m", "version": "1.0.0", "params": {}},
    ])
    rng = np.random.default_rng(0)
    losing = rng.normal(loc=-5.0, scale=20.0, size=150)
    trades = _make_trades({"fresh_pause_v1": losing}, start="2024-01-01")
    as_of = pd.Timestamp("2025-01-01", tz="UTC")

    events = lcm.evaluate(trades, benchmark_sharpe=0.87, as_of=as_of)
    statuses = {e["edge_id"]: e["status"]
                for e in yaml.safe_load(registry_path.read_text())["edges"]}

    assert statuses["fresh_pause_v1"] == "paused"
    assert not any(ev.new_status == "retired" for ev in events)


def test_paused_edge_not_retired_when_reviving(tmp_path):
    """A paused edge with recent recovery in last N trades is NOT retired."""
    registry_path = tmp_path / "edges.yml"
    history_path = tmp_path / "lifecycle_history.csv"
    cfg = LifecycleConfig(
        enabled=True,
        paused_retirement_min_days=90,
        retirement_margin=0.3,
        revival_sharpe=0.3,
        revival_wr=0.45,
        revival_window=20,
        max_retirements_per_cycle=2,
    )
    lcm = LifecycleManager(cfg=cfg, registry_path=registry_path, history_path=history_path)

    pause_ts = "2024-09-01T00:00:00+00:00"
    _write_pause_history(history_path, "recovering_v1", pause_ts)

    _seed_registry(registry_path, [
        {"edge_id": "recovering_v1", "status": "paused",
         "category": "technical", "module": "m", "version": "1.0.0", "params": {}},
    ])
    rng = np.random.default_rng(0)
    # Long losing history, then strong recent recovery in the last 20 trades
    losing = rng.normal(loc=-5.0, scale=20.0, size=130)
    winning_recent = rng.normal(loc=20.0, scale=5.0, size=20)
    trades = _make_trades({"recovering_v1": np.concatenate([losing, winning_recent])}, start="2024-01-01")
    as_of = pd.Timestamp("2025-01-01", tz="UTC")

    events = lcm.evaluate(trades, benchmark_sharpe=0.87, as_of=as_of)
    statuses = {e["edge_id"]: e["status"]
                for e in yaml.safe_load(registry_path.read_text())["edges"]}

    # Revival gate should fire (revived to active), not retired
    assert statuses["recovering_v1"] == "active"


def test_paused_retirement_disabled_when_min_days_zero(tmp_path):
    """Setting paused_retirement_min_days=0 disables the paused → retired path."""
    registry_path = tmp_path / "edges.yml"
    history_path = tmp_path / "lifecycle_history.csv"
    cfg = LifecycleConfig(
        enabled=True,
        paused_retirement_min_days=0,  # disabled
        retirement_margin=0.3,
        max_retirements_per_cycle=2,
    )
    lcm = LifecycleManager(cfg=cfg, registry_path=registry_path, history_path=history_path)

    pause_ts = "2020-01-01T00:00:00+00:00"  # very old pause
    _write_pause_history(history_path, "legacy_paused_v1", pause_ts)

    _seed_registry(registry_path, [
        {"edge_id": "legacy_paused_v1", "status": "paused",
         "category": "technical", "module": "m", "version": "1.0.0", "params": {}},
    ])
    rng = np.random.default_rng(0)
    losing = rng.normal(loc=-5.0, scale=20.0, size=150)
    trades = _make_trades({"legacy_paused_v1": losing}, start="2024-01-01")
    as_of = pd.Timestamp("2025-01-01", tz="UTC")

    events = lcm.evaluate(trades, benchmark_sharpe=0.87, as_of=as_of)
    statuses = {e["edge_id"]: e["status"]
                for e in yaml.safe_load(registry_path.read_text())["edges"]}

    assert statuses["legacy_paused_v1"] == "paused"
    assert not any(ev.new_status == "retired" for ev in events)


# ---------------------------------------------------------------------------
# readonly mode: events returned but registry + history left unchanged
# ---------------------------------------------------------------------------

def test_readonly_mode_does_not_write_registry(tmp_path):
    """In readonly mode, gates fire and events are returned but registry is NOT written."""
    registry_path = tmp_path / "edges.yml"
    history_path = tmp_path / "lifecycle_history.csv"
    cfg = LifecycleConfig(
        enabled=True,
        readonly=True,
        paused_retirement_min_days=90,
        retirement_margin=0.3,
        max_retirements_per_cycle=2,
    )
    lcm = LifecycleManager(cfg=cfg, registry_path=registry_path, history_path=history_path)

    pause_ts = "2024-09-01T00:00:00+00:00"
    _write_pause_history(history_path, "bad_edge_v1", pause_ts)
    _seed_registry(registry_path, [
        {"edge_id": "bad_edge_v1", "status": "paused",
         "category": "technical", "module": "m", "version": "1.0.0", "params": {}},
    ])
    registry_mtime_before = registry_path.stat().st_mtime

    rng = np.random.default_rng(0)
    losing = rng.normal(loc=-5.0, scale=20.0, size=150)
    trades = _make_trades({"bad_edge_v1": losing}, start="2024-01-01")
    as_of = pd.Timestamp("2025-01-01", tz="UTC")

    events = lcm.evaluate(trades, benchmark_sharpe=0.87, as_of=as_of)

    # Events are returned (gate logic ran)
    assert any(ev.new_status == "retired" for ev in events)

    # Registry file was NOT modified
    assert registry_path.stat().st_mtime == registry_mtime_before
    statuses = {e["edge_id"]: e["status"]
                for e in yaml.safe_load(registry_path.read_text())["edges"]}
    assert statuses["bad_edge_v1"] == "paused"  # still paused, not retired


def test_readonly_mode_does_not_append_history(tmp_path):
    """In readonly mode, lifecycle history CSV is not written despite gate firing."""
    registry_path = tmp_path / "edges.yml"
    history_path = tmp_path / "lifecycle_history.csv"
    cfg = LifecycleConfig(
        enabled=True,
        readonly=True,
        pause_loss_fraction_threshold=-0.1,  # easy to trigger
        pause_min_trades=5,
        max_pauses_per_cycle=2,
    )
    lcm = LifecycleManager(cfg=cfg, registry_path=registry_path, history_path=history_path)
    _seed_registry(registry_path, [
        {"edge_id": "loser_v1", "status": "active",
         "category": "technical", "module": "m", "version": "1.0.0", "params": {}},
    ])

    rng = np.random.default_rng(7)
    losing = rng.normal(loc=-20.0, scale=5.0, size=60)
    trades = _make_trades({"loser_v1": losing}, start="2024-01-01")

    events = lcm.evaluate(trades, benchmark_sharpe=0.0)

    # Gate fired (events returned) but history file should NOT exist
    assert any(ev.new_status == "paused" for ev in events)
    assert not history_path.exists()
