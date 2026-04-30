"""tests/test_lifecycle_triggers_2026_04.py
==============================================
Phase 2.10d Task A regression tests for the autonomous lifecycle's
new detection primitives:

- **Trigger 1**: Zero-fill / sparse-fill timeout (active → paused,
  paused → retired) for edges that don't accumulate per-trade
  evidence the legacy gates require.
- **Trigger 2**: Sustained-noise pause (active → paused) for edges
  whose rolling-3yr per-year contribution is low-magnitude AND has
  at least one clearly-negative year.

The KEEP / CUT decisions in `docs/Audit/pruning_proposal_2026_04.md`
are the ground truth these triggers were calibrated against. The
end-to-end validation script
`scripts/validate_lifecycle_triggers.py` runs the full 22-edge
match against the per-year audit data; this file isolates each
trigger to verify the gate logic itself behaves as designed.
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

from engines.engine_f_governance.lifecycle_manager import (  # noqa: E402
    LifecycleConfig,
    LifecycleManager,
)


def _seed_registry(path: Path, edges: list[dict]) -> None:
    path.write_text(yaml.dump({"edges": edges}, sort_keys=False))


def _make_trades_full(rows: list[dict]) -> pd.DataFrame:
    """Build a synthetic trade log with explicit timestamp / edge / pnl /
    trigger columns. Caller provides each row dict."""
    return pd.DataFrame(rows)


def _entry(edge: str, ts: str, pnl_close: float | None = None) -> list[dict]:
    """Helper: emit one entry row, optionally followed by a closing row
    with the realized pnl."""
    rows = [{"timestamp": ts, "edge": edge, "pnl": np.nan,
             "trigger": "entry"}]
    if pnl_close is not None:
        ts_close = (pd.Timestamp(ts) + pd.Timedelta(days=1)).isoformat()
        rows.append({"timestamp": ts_close, "edge": edge, "pnl": pnl_close,
                     "trigger": "exit"})
    return rows


@pytest.fixture
def lcm_factory_lite(tmp_path):
    """Factory like the existing one but with the noise-gate min-history
    knocked down so synthetic windowed tests can still exercise it."""
    def _make(noise_min_history: int = 365) -> tuple[LifecycleManager, Path, Path]:
        cfg = LifecycleConfig(
            enabled=True,
            zero_fill_lookback_days=365,
            zero_fill_min_fills=2,
            zero_fill_paused_retire_days=365,
            noise_window_years=3,
            noise_mean_threshold=0.001,
            noise_negative_year_threshold=-0.0003,
            noise_min_fills_in_window=5,
            noise_min_history_days=noise_min_history,
        )
        registry_path = tmp_path / "edges.yml"
        history_path = tmp_path / "lifecycle_history.csv"
        return (
            LifecycleManager(
                cfg=cfg, registry_path=registry_path, history_path=history_path,
            ),
            registry_path,
            history_path,
        )
    return _make


# ============================================================
# Trigger 1 — Zero-fill timeout
# ============================================================

class TestTrigger1ZeroFillTimeout:
    """Active edges with < min_fills in the lookback window auto-pause.
    Paused edges that continue not to fire auto-retire."""

    def test_zero_fill_active_pauses_after_lookback(self, lcm_factory_lite):
        """An active edge with literally 0 entry fills in the window pauses."""
        lcm, registry_path, _ = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "rsi_bounce_v1", "status": "active", "category": "technical",
             "module": "m", "version": "1.0.0", "params": {}},
            # Sentinel that DOES fire — keeps as_of pinned at 2025-12-31
            # so days_since_last for rsi_bounce is large.
            {"edge_id": "active_sentinel", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        rows = []
        for d in pd.date_range("2024-06-01", "2025-12-31", freq="W"):
            rows.extend(_entry("active_sentinel", d.isoformat(), pnl_close=10.0))
        trades = _make_trades_full(rows)

        events = lcm.evaluate(trades, benchmark_sharpe=0.5)
        edge_status = {e["edge_id"]: e["status"]
                       for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert edge_status["rsi_bounce_v1"] == "paused", (
            "zero-fill active edge should auto-pause"
        )
        assert any(
            ev.edge_id == "rsi_bounce_v1" and ev.new_status == "paused"
            and "zero_fill" in ev.triggering_gate
            for ev in events
        )

    def test_zero_fill_active_does_not_pause_when_firing_recently(self, lcm_factory_lite):
        """An edge with adequate recent fills (>= min_fills) stays active."""
        lcm, registry_path, _ = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "alive_edge", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        rows = []
        # 5 entries in the last 365 days — well above the 2-fill threshold
        for d in pd.date_range("2025-06-01", periods=5, freq="30D"):
            rows.extend(_entry("alive_edge", d.isoformat(), pnl_close=5.0))
        trades = _make_trades_full(rows)

        events = lcm.evaluate(trades, benchmark_sharpe=0.5)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert statuses["alive_edge"] == "active"
        assert all(ev.edge_id != "alive_edge" for ev in events)

    def test_zero_fill_paused_retires_after_extra_window(self, lcm_factory_lite):
        """A paused edge that continues to not fire retires after the
        zero_fill_paused_retire_days has elapsed since pause."""
        lcm, registry_path, history_path = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "macro_yield_curve_v1", "status": "paused",
             "category": "macro", "module": "m", "version": "1.0.0",
             "params": {}},
            {"edge_id": "active_sentinel", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        # Seed pause history far in the past so days_since_pause >> 365
        with history_path.open("w") as f:
            f.write(
                "timestamp,edge_id,old_status,new_status,triggering_gate,"
                "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
            )
            f.write(
                "2022-01-01T00:00:00+00:00,macro_yield_curve_v1,active,paused,"
                "loss_fraction_-0.41,-0.10,1.00,-0.41,150,200,\n"
            )
        rows = []
        for d in pd.date_range("2024-06-01", "2025-12-31", freq="W"):
            rows.extend(_entry("active_sentinel", d.isoformat(), pnl_close=10.0))
        trades = _make_trades_full(rows)

        events = lcm.evaluate(trades, benchmark_sharpe=0.5)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert statuses["macro_yield_curve_v1"] == "retired"
        assert any(
            ev.edge_id == "macro_yield_curve_v1" and ev.new_status == "retired"
            and "zero_fill_paused" in ev.triggering_gate
            for ev in events
        )

    def test_zero_fill_paused_does_not_retire_within_holding_window(self, lcm_factory_lite):
        """A paused edge with zero fills but only recently paused should
        NOT retire — the cumulative holding window protects it."""
        lcm, registry_path, history_path = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "fresh_pause", "status": "paused", "category": "technical",
             "module": "m", "version": "1.0.0", "params": {}},
            {"edge_id": "active_sentinel", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        # Pause history just 30 days before as_of (well under the 365 retire window)
        with history_path.open("w") as f:
            f.write(
                "timestamp,edge_id,old_status,new_status,triggering_gate,"
                "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
            )
            f.write(
                "2025-12-01T00:00:00+00:00,fresh_pause,active,paused,"
                "loss_fraction_-0.41,-0.10,1.00,-0.41,150,200,\n"
            )
        rows = []
        for d in pd.date_range("2024-06-01", "2025-12-31", freq="W"):
            rows.extend(_entry("active_sentinel", d.isoformat(), pnl_close=10.0))
        trades = _make_trades_full(rows)

        lcm.evaluate(trades, benchmark_sharpe=0.5)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert statuses["fresh_pause"] == "paused", (
            "should not retire within holding window"
        )

    def test_zero_fill_audit_trail_written(self, lcm_factory_lite):
        """Trigger 1 transitions are logged to lifecycle_history.csv."""
        lcm, registry_path, history_path = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "rsi_bounce_v1", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
            {"edge_id": "active_sentinel", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        rows = []
        for d in pd.date_range("2024-06-01", "2025-12-31", freq="W"):
            rows.extend(_entry("active_sentinel", d.isoformat(), pnl_close=10.0))
        trades = _make_trades_full(rows)
        lcm.evaluate(trades, benchmark_sharpe=0.5)

        history = pd.read_csv(history_path)
        assert "rsi_bounce_v1" in history["edge_id"].tolist()
        rsi_rows = history[history["edge_id"] == "rsi_bounce_v1"]
        assert (rsi_rows["new_status"] == "paused").any()
        assert rsi_rows["triggering_gate"].iloc[0].startswith("zero_fill_")


# ============================================================
# Trigger 2 — Sustained-noise pause
# ============================================================

class TestTrigger2SustainedNoise:
    """Active edges with low-magnitude rolling mean AND at least one
    clearly-negative year auto-pause."""

    def test_noise_fires_on_panic_v1_like_pattern(self, lcm_factory_lite):
        """Mimic panic_v1: 2023=0, 2024=0, 2025=-0.16% of capital. Mean
        -0.05% (|mean|<0.10% threshold). Min year < -0.03% threshold."""
        lcm, registry_path, _ = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "panic_v1", "status": "active", "category": "technical",
             "module": "m", "version": "1.0.0", "params": {}},
        ])
        rows = []
        # Spread some no-pnl entries across 2023+2024 so days_history >= 365
        for d in pd.date_range("2023-01-15", periods=8, freq="60D"):
            rows.extend(_entry("panic_v1", d.isoformat(), pnl_close=0.0))
        # Then in 2025 generate -$160 of net loss across 8 trades to land
        # at -0.16% of $100k capital
        loss_dates = pd.date_range("2025-03-01", periods=8, freq="30D")
        for d in loss_dates:
            rows.extend(_entry("panic_v1", d.isoformat(), pnl_close=-20.0))
        trades = _make_trades_full(rows)

        events = lcm.evaluate(trades, benchmark_sharpe=0.5)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert statuses["panic_v1"] == "paused"
        gate = next(ev.triggering_gate for ev in events if ev.edge_id == "panic_v1")
        assert "sustained_noise" in gate

    def test_noise_does_not_fire_on_pead_v1_like_pattern(self, lcm_factory_lite):
        """Mimic pead_v1: rare but never-negative years.
        2023=+$0, 2024=+$0, 2025=+$12 (= +0.012% of capital). No negative
        year, so even with low |mean| the gate must not fire."""
        lcm, registry_path, _ = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "pead_v1", "status": "active", "category": "technical",
             "module": "m", "version": "1.0.0", "params": {}},
        ])
        rows = []
        for d in pd.date_range("2023-01-15", periods=6, freq="60D"):
            rows.extend(_entry("pead_v1", d.isoformat(), pnl_close=0.0))
        for d in pd.date_range("2025-04-15", periods=5, freq="60D"):
            rows.extend(_entry("pead_v1", d.isoformat(), pnl_close=2.4))  # +$12 total
        trades = _make_trades_full(rows)

        lcm.evaluate(trades, benchmark_sharpe=0.5)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert statuses["pead_v1"] == "active", (
            "pead_v1 has no negative year — noise gate must not fire"
        )

    def test_noise_does_not_fire_on_meaningful_positive_mean(self, lcm_factory_lite):
        """Mimic macro_credit_spread_v1: 5-year mean +0.15%/yr clearly
        above the noise threshold even though year-to-year is small."""
        lcm, registry_path, _ = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "macro_credit_spread_v1", "status": "active",
             "category": "macro", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        rows = []
        # +0.05% / +0.10% / +0.30% across 2023/2024/2025 = +0.15% mean
        for amt, year in [(50.0, 2023), (100.0, 2024), (300.0, 2025)]:
            for d in pd.date_range(f"{year}-01-15", periods=10, freq="30D"):
                rows.extend(_entry("macro_credit_spread_v1", d.isoformat(),
                                   pnl_close=amt / 10))
        trades = _make_trades_full(rows)

        lcm.evaluate(trades, benchmark_sharpe=0.5)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert statuses["macro_credit_spread_v1"] == "active"

    def test_noise_does_not_fire_within_min_history(self, lcm_factory_lite):
        """An edge with < noise_min_history_days of trade history is not
        evaluated — too-young to judge."""
        lcm, registry_path, _ = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "freshly_minted", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        rows = []
        # 6 trades all in last 90 days; the panic_v1 pattern in shape
        # but inside the 365-day min-history floor → not evaluable
        for d in pd.date_range("2025-10-01", periods=6, freq="10D"):
            rows.extend(_entry("freshly_minted", d.isoformat(),
                               pnl_close=-30.0))
        trades = _make_trades_full(rows)

        lcm.evaluate(trades, benchmark_sharpe=0.5)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert statuses["freshly_minted"] == "active"

    def test_noise_does_not_fire_on_too_few_fills(self, lcm_factory_lite):
        """Edge with < noise_min_fills_in_window stays active (sparse,
        not noise — Trigger 1 handles the sparse case)."""
        lcm, registry_path, _ = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "sparse_edge", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
            # Sentinel keeps as_of pinned to 2025-12-31 even though
            # sparse_edge is sparse-but-not-zero (3 fills > 2 zero-fill min)
            {"edge_id": "active_sentinel", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        rows = []
        # 3 fills over 3 years — passes Trigger 1 (>= 2 in 365d? actually
        # only 1 in 365d). Hmm — to isolate Trigger 2's min-fills gate
        # specifically, we need the edge to pass Trigger 1 first. Use 2
        # fills in the 365d window, well below the noise_min_fills_in_window=5
        rows.extend(_entry("sparse_edge", "2023-06-01", pnl_close=-10.0))
        rows.extend(_entry("sparse_edge", "2024-06-01", pnl_close=-10.0))
        rows.extend(_entry("sparse_edge", "2025-06-01", pnl_close=-30.0))
        rows.extend(_entry("sparse_edge", "2025-09-01", pnl_close=-30.0))
        # Sentinel ensures as_of = 2025-12-31
        for d in pd.date_range("2024-01-01", "2025-12-31", freq="W"):
            rows.extend(_entry("active_sentinel", d.isoformat(), pnl_close=10.0))
        trades = _make_trades_full(rows)

        lcm.evaluate(trades, benchmark_sharpe=0.5)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        # 4 fills total < noise_min_fills_in_window (5) → noise gate
        # does not fire. Trigger 1 might or might not (depends on lookback);
        # at minimum we shouldn't see a 'sustained_noise' event.
        # (Sparse_edge may still trip Trigger 1 — that's correct behavior;
        # we only assert noise gate did not fire.)
        # Cross-reference: the assertion is the audit trail.
        # If Trigger 1 fires it'll be paused with a 'zero_fill_*' gate.
        if statuses["sparse_edge"] == "paused":
            # ensure it was Trigger 1, NOT Trigger 2
            history_lines = (
                lcm.history_path.read_text().splitlines()
                if lcm.history_path.exists() else []
            )
            sparse_lines = [ln for ln in history_lines if "sparse_edge" in ln]
            assert all("sustained_noise" not in ln for ln in sparse_lines)


# ============================================================
# Cross-trigger interaction
# ============================================================

class TestTrigger3TierClassifierScheduling:
    """Trigger 3 wires TierClassifier.classify_from_trades to fire after every
    backtest's lifecycle evaluation. The hook is gated on
    `tier_reclassification_enabled` and is a no-op when disabled."""

    def _make_governor(self, tmp_path, enabled: bool):
        """Helper: build a StrategyGovernor with the tier-reclass flag set
        without writing a real config file. Patches `cfg` directly."""
        from engines.engine_f_governance.governor import StrategyGovernor
        gov = StrategyGovernor(
            config_path=tmp_path / "no_such_config.json",
            state_path=tmp_path / "weights.json",
        )
        gov.cfg.tier_reclassification_enabled = enabled
        return gov

    def test_governor_evaluate_tiers_no_op_when_disabled(self, tmp_path):
        """The hook must be a no-op when `tier_reclassification_enabled` is False."""
        gov = self._make_governor(tmp_path, enabled=False)
        result = gov.evaluate_tiers(trades_path=tmp_path / "nonexistent_trades.csv")
        assert result == []

    def test_governor_evaluate_tiers_handles_missing_trade_log(self, tmp_path):
        """Hook must not crash when the trade log is missing (e.g. before
        the first backtest writes one)."""
        gov = self._make_governor(tmp_path, enabled=True)
        result = gov.evaluate_tiers(trades_path=tmp_path / "nonexistent_trades.csv")
        assert result == []

    def test_evaluate_tiers_signature_accepts_initial_capital(self):
        """Verify the public surface — caller can override the
        normalization basis for paper/live with non-default capital."""
        import inspect
        from engines.engine_f_governance.governor import StrategyGovernor
        sig = inspect.signature(StrategyGovernor.evaluate_tiers)
        params = list(sig.parameters.keys())
        assert "trades_path" in params
        assert "initial_capital" in params

    def test_mode_controller_calls_evaluate_tiers_after_lifecycle(self):
        """Source-level guard: the post-backtest hook in run_backtest must
        invoke `governor.evaluate_tiers` AFTER `governor.evaluate_lifecycle`,
        ordered so tier classifications reflect the latest pause/retire
        decisions rather than racing them."""
        ROOT = Path(__file__).resolve().parents[1]
        src = (ROOT / "orchestration" / "mode_controller.py").read_text()
        idx_lifecycle = src.find("governor.evaluate_lifecycle(metrics.trades)")
        idx_tiers = src.find("governor.evaluate_tiers(")
        assert idx_lifecycle > 0, "evaluate_lifecycle hook missing"
        assert idx_tiers > 0, "evaluate_tiers hook missing"
        assert idx_lifecycle < idx_tiers, (
            "evaluate_tiers must run after evaluate_lifecycle"
        )


class TestRevivalVeto:
    """A paused edge with heavy lifetime cumulative loss must NOT revive
    even when its recent 20-trade slice happens to look positive — the
    soft-pause leak the validation 5-year run exposed."""

    def test_heavy_loser_paused_edge_cannot_revive(self, lcm_factory_lite):
        """Mimic momentum_edge_v1: lifetime cumulative -7.35% of capital,
        with a recent 20-trade slice that looks like a strong recovery."""
        lcm, registry_path, history_path = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "heavy_loser", "status": "paused",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        # Pause history far enough back that the holding-window check
        # passes — we want the revival/retire decision to actually happen.
        with history_path.open("w") as f:
            f.write(
                "timestamp,edge_id,old_status,new_status,triggering_gate,"
                "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
            )
            f.write(
                "2024-04-25T00:00:00+00:00,heavy_loser,active,paused,"
                "loss_fraction_-0.41,-0.30,0.85,-0.41,150,200,\n"
            )
        rows = []
        # 200 trades summing to -$7,350 (-7.35% of $100k starting cap).
        # Most are losers, but pad the LAST 20 to look revival-strong.
        # First 180: each -$50 → -$9,000.  Last 20: each +$82.5 → +$1,650.
        # Total cumulative: -$7,350 → -7.35% — well below the -0.5% veto.
        early = pd.date_range("2022-01-15", periods=180, freq="3D")
        for d in early:
            rows.extend(_entry("heavy_loser", d.isoformat(), pnl_close=-50.0))
        recent = pd.date_range("2025-09-01", periods=20, freq="3D")
        for d in recent:
            rows.extend(_entry("heavy_loser", d.isoformat(), pnl_close=82.5))
        trades = _make_trades_full(rows)

        lcm.evaluate(trades, benchmark_sharpe=0.875)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert statuses["heavy_loser"] != "active", (
            "heavy lifetime loser must not revive on a 20-trade slice"
        )

    def test_modest_loser_paused_edge_can_still_revive(self, lcm_factory_lite):
        """A paused edge whose lifetime cumulative is well above the veto
        threshold and whose recent slice looks strong should still revive."""
        lcm, registry_path, history_path = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "modest_recover", "status": "paused",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        with history_path.open("w") as f:
            f.write(
                "timestamp,edge_id,old_status,new_status,triggering_gate,"
                "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
            )
            f.write(
                "2024-04-25T00:00:00+00:00,modest_recover,active,paused,"
                "loss_fraction_-0.41,-0.30,0.85,-0.41,150,200,\n"
            )
        rows = []
        # 50 trades. First 30: -$10 each = -$300. Last 20: +$120 each = +$2400.
        # Cumulative +$2100 = +2.1% > -0.5% veto. Recent slice strong → revive.
        early = pd.date_range("2024-06-01", periods=30, freq="5D")
        rng = np.random.default_rng(7)
        early_pnls = rng.normal(loc=-10.0, scale=15.0, size=30)
        for d, p in zip(early, early_pnls):
            rows.extend(_entry("modest_recover", d.isoformat(), pnl_close=float(p)))
        # Recovery slice: positive mean with non-zero variance so Sharpe
        # can be computed meaningfully.
        recent = pd.date_range("2025-09-01", periods=20, freq="3D")
        recent_pnls = rng.normal(loc=120.0, scale=40.0, size=20)
        for d, p in zip(recent, recent_pnls):
            rows.extend(_entry("modest_recover", d.isoformat(), pnl_close=float(p)))
        trades = _make_trades_full(rows)

        lcm.evaluate(trades, benchmark_sharpe=0.5)
        statuses = {e["edge_id"]: e["status"]
                    for e in yaml.safe_load(registry_path.read_text())["edges"]}
        assert statuses["modest_recover"] == "active", (
            "modest cumulative loss + strong recovery should still revive"
        )


class TestTriggerInteraction:
    """Triggers 1 and 2 must not collide. When both could fire, the
    earlier-listed trigger (zero-fill) takes precedence, but a fully-
    firing edge that's only noise should hit Trigger 2."""

    def test_zero_fill_and_noise_trigger_simultaneously_zero_fill_wins(
        self, lcm_factory_lite
    ):
        """An edge with 0 recent fills but historical noise pattern →
        Trigger 1 fires first (correct: dormancy is a stronger signal
        than noise pattern)."""
        lcm, registry_path, _ = lcm_factory_lite()
        _seed_registry(registry_path, [
            {"edge_id": "noisy_then_dormant", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
            {"edge_id": "active_sentinel", "status": "active",
             "category": "technical", "module": "m", "version": "1.0.0",
             "params": {}},
        ])
        rows = []
        # Old noisy fills (2022-2023) — would qualify Trigger 2 in shape
        for d in pd.date_range("2022-01-01", "2023-12-31", freq="60D"):
            rows.extend(_entry("noisy_then_dormant", d.isoformat(),
                               pnl_close=-15.0))
        # Sentinel fires through 2025-12-31 → as_of = 2025-12-31
        # noisy_then_dormant has zero entries in last 365 days → Trigger 1
        for d in pd.date_range("2024-01-01", "2025-12-31", freq="W"):
            rows.extend(_entry("active_sentinel", d.isoformat(),
                               pnl_close=10.0))
        trades = _make_trades_full(rows)

        events = lcm.evaluate(trades, benchmark_sharpe=0.5)
        gate = next(
            ev.triggering_gate for ev in events
            if ev.edge_id == "noisy_then_dormant"
        )
        # Trigger 1 should win (zero_fill_), not Trigger 2 (sustained_noise_)
        assert gate.startswith("zero_fill_")
