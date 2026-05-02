"""Path A — Tax-Efficient Core: unit tests.

Covers the four shipped components:
    A1. HRP slice 2 — composition vs replacement
    A2. Turnover penalty rejection (slice 1's TurnoverPenalty, reused)
    A3. LT hold preference (math + 380-day hard cap + below-window passthrough)
    A4. Wash-sale 30-day window (record_fill + should_block_buy)

Plus an integration test that walks Engine A's hrp_composed signal through
to RiskEngine.prepare_order to verify optimizer_weight flows end-to-end.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.engine_a_alpha.signal_processor import (
    SignalProcessor, RegimeSettings, HygieneSettings, EnsembleSettings,
    PortfolioOptimizerSettings,
)
from engines.engine_b_risk.risk_engine import RiskEngine
from engines.engine_b_risk.wash_sale_avoidance import (
    WashSaleAvoidance, WashSaleAvoidanceConfig,
)
from engines.engine_b_risk.lt_hold_preference import (
    LTHoldPreference, LTHoldPreferenceConfig,
)


# ============================================================================
# A4 — Wash-sale avoidance
# ============================================================================
class TestWashSaleAvoidance:
    def test_disabled_module_is_noop(self):
        ws = WashSaleAvoidance(WashSaleAvoidanceConfig(enabled=False))
        ws.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": -500.0, "qty": 10},
            pd.Timestamp("2025-01-15"),
        )
        # Even with a recorded loss, disabled module never blocks.
        assert ws.should_block_buy("AAPL", pd.Timestamp("2025-01-20")) is False

    def test_records_loss_exit(self):
        ws = WashSaleAvoidance(WashSaleAvoidanceConfig(enabled=True))
        ws.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": -500.0, "qty": 10},
            pd.Timestamp("2025-01-15"),
        )
        assert ws.stats["loss_exits_recorded"] == 1

    def test_ignores_non_loss_exits(self):
        ws = WashSaleAvoidance(WashSaleAvoidanceConfig(enabled=True))
        # Profitable exit — not a wash-sale risk
        ws.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": 500.0, "qty": 10},
            pd.Timestamp("2025-01-15"),
        )
        # Tiny loss below threshold — also ignored
        ws.record_fill(
            {"ticker": "MSFT", "side": "exit", "pnl": -0.5, "qty": 1},
            pd.Timestamp("2025-01-15"),
        )
        # Open fills — never recorded as loss-exit
        ws.record_fill(
            {"ticker": "GOOG", "side": "long", "pnl": 0.0, "qty": 5},
            pd.Timestamp("2025-01-15"),
        )
        assert ws.stats["loss_exits_recorded"] == 0

    def test_blocks_buy_within_30_day_window(self):
        ws = WashSaleAvoidance(WashSaleAvoidanceConfig(enabled=True, window_days=30))
        ws.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": -500.0, "qty": 10},
            pd.Timestamp("2025-01-01"),
        )
        # Day 1, 15, 30 → blocked
        assert ws.should_block_buy("AAPL", pd.Timestamp("2025-01-02")) is True
        assert ws.should_block_buy("AAPL", pd.Timestamp("2025-01-16")) is True
        assert ws.should_block_buy("AAPL", pd.Timestamp("2025-01-31")) is True
        # Day 31 → no longer blocked
        assert ws.should_block_buy("AAPL", pd.Timestamp("2025-02-01")) is False

    def test_does_not_affect_other_tickers(self):
        ws = WashSaleAvoidance(WashSaleAvoidanceConfig(enabled=True))
        ws.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": -500.0, "qty": 10},
            pd.Timestamp("2025-01-15"),
        )
        assert ws.should_block_buy("AAPL", pd.Timestamp("2025-01-20")) is True
        assert ws.should_block_buy("MSFT", pd.Timestamp("2025-01-20")) is False

    def test_window_uses_most_recent_loss(self):
        ws = WashSaleAvoidance(WashSaleAvoidanceConfig(enabled=True, window_days=30))
        ws.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": -100.0, "qty": 1},
            pd.Timestamp("2025-01-01"),
        )
        ws.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": -50.0, "qty": 1},
            pd.Timestamp("2025-02-15"),
        )
        # Day 50 days after first loss but only 5 days after second → blocked
        assert ws.should_block_buy("AAPL", pd.Timestamp("2025-02-20")) is True

    def test_stats_count_proposed_and_blocked(self):
        ws = WashSaleAvoidance(WashSaleAvoidanceConfig(enabled=True))
        ws.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": -500.0, "qty": 10},
            pd.Timestamp("2025-01-15"),
        )
        ws.should_block_buy("AAPL", pd.Timestamp("2025-01-20"))  # blocked
        ws.should_block_buy("AAPL", pd.Timestamp("2025-03-01"))  # not blocked
        ws.should_block_buy("MSFT", pd.Timestamp("2025-01-20"))  # not blocked
        s = ws.stats
        assert s["buys_proposed"] == 3
        assert s["buys_blocked"] == 1
        assert s["block_rate"] == pytest.approx(1 / 3)

    def test_reset_clears_state(self):
        ws = WashSaleAvoidance(WashSaleAvoidanceConfig(enabled=True))
        ws.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": -500.0, "qty": 10},
            pd.Timestamp("2025-01-15"),
        )
        ws.should_block_buy("AAPL", pd.Timestamp("2025-01-20"))
        ws.reset()
        assert ws.stats["loss_exits_recorded"] == 0
        assert ws.stats["buys_proposed"] == 0
        assert ws.should_block_buy("AAPL", pd.Timestamp("2025-01-20")) is False


# ============================================================================
# A3 — LT hold preference
# ============================================================================
class TestLTHoldPreference:
    def test_disabled_module_is_noop(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(enabled=False))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        # Even at 350-day mark with massive gain, disabled = no defer
        assert lt.should_defer_exit(
            ticker="AAPL", current_qty=10, avg_price=100.0,
            current_price=200.0, now=pd.Timestamp("2024-12-17"),
        ) is False

    def test_below_window_no_defer(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(enabled=True))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        # Day 200 — below defer_window_start_days=300
        assert lt.should_defer_exit(
            ticker="AAPL", current_qty=10, avg_price=100.0,
            current_price=200.0, now=pd.Timestamp("2024-07-19"),
        ) is False

    def test_within_window_with_gain_defers(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(
            enabled=True, min_hold_savings_threshold=50.0,
            short_term_rate=0.30, long_term_rate=0.15,
        ))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        # Day 350: gain = 10 * (200 - 100) = $1000; rate_delta = 0.15;
        # tax_savings = $150 > $50 threshold → defer.
        assert lt.should_defer_exit(
            ticker="AAPL", current_qty=10, avg_price=100.0,
            current_price=200.0, now=pd.Timestamp("2024-12-17"),
        ) is True
        assert lt.stats["exits_deferred"] == 1

    def test_within_window_with_loss_no_defer(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(enabled=True))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        # Day 350: position at a loss → no tax benefit → don't defer
        assert lt.should_defer_exit(
            ticker="AAPL", current_qty=10, avg_price=100.0,
            current_price=80.0, now=pd.Timestamp("2024-12-17"),
        ) is False

    def test_within_window_below_threshold_no_defer(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(
            enabled=True, min_hold_savings_threshold=200.0,  # high bar
        ))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        # tax_savings = 10 * 100 * 0.15 = $150 < $200 → don't defer
        assert lt.should_defer_exit(
            ticker="AAPL", current_qty=10, avg_price=100.0,
            current_price=200.0, now=pd.Timestamp("2024-12-17"),
        ) is False

    def test_past_long_term_no_defer(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(enabled=True))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        # Day 366 — already long-term, no further benefit
        assert lt.should_defer_exit(
            ticker="AAPL", current_qty=10, avg_price=100.0,
            current_price=200.0, now=pd.Timestamp("2025-01-02"),
        ) is False

    def test_hard_cap_releases_exit(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(
            enabled=True, hard_cap_days=380,
        ))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        # Day 381 — past hard cap; even with massive gain, allow exit.
        # Note: this branch would only fire if the rest of the rule wanted
        # to defer; the hard-cap counter increments regardless.
        assert lt.should_defer_exit(
            ticker="AAPL", current_qty=10, avg_price=100.0,
            current_price=500.0, now=pd.Timestamp("2025-01-17"),
        ) is False
        assert lt.stats["exits_hard_capped"] == 1

    def test_short_position_gain(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(enabled=True))
        lt.record_fill({"ticker": "AAPL", "side": "short", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=-10)
        # Short: gain on price drop. avg=200, cur=100, qty=-10 → gain $1000
        assert lt.should_defer_exit(
            ticker="AAPL", current_qty=-10, avg_price=200.0,
            current_price=100.0, now=pd.Timestamp("2024-12-17"),
        ) is True

    def test_record_fill_clears_on_full_close(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(enabled=True))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        assert lt.get_entry_dt("AAPL") == pd.Timestamp("2024-01-01")
        lt.record_fill({"ticker": "AAPL", "side": "exit", "qty": 10},
                       pd.Timestamp("2024-06-01"), post_fill_qty=0)
        assert lt.get_entry_dt("AAPL") is None

    def test_record_fill_keeps_on_partial_close(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(enabled=True))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        lt.record_fill({"ticker": "AAPL", "side": "exit", "qty": 5},
                       pd.Timestamp("2024-06-01"), post_fill_qty=5)
        assert lt.get_entry_dt("AAPL") == pd.Timestamp("2024-01-01")

    def test_exit_alpha_value_overrides_defer(self):
        lt = LTHoldPreference(LTHoldPreferenceConfig(enabled=True))
        lt.record_fill({"ticker": "AAPL", "side": "long", "qty": 10},
                       pd.Timestamp("2024-01-01"), post_fill_qty=10)
        # tax_savings = 10*100*0.15 = $150; if alpha_lift = $200 > $150 → no defer
        assert lt.should_defer_exit(
            ticker="AAPL", current_qty=10, avg_price=100.0, current_price=200.0,
            now=pd.Timestamp("2024-12-17"), exit_alpha_value=200.0,
        ) is False


# ============================================================================
# A1 — HRP slice 2 (composition) vs slice 1 (replacement)
# ============================================================================
class TestHRPCompositionVsReplacement:
    def _build_data_map(self, n_tickers=5, n_bars=120, seed=0):
        """Two-cluster synthetic returns so HRP doesn't degenerate to equal-weight."""
        rng = np.random.default_rng(seed)
        idx = pd.date_range("2024-01-01", periods=n_bars, freq="D")
        out = {}
        for i in range(n_tickers):
            cluster_drift = 0.02 if i < n_tickers // 2 else -0.01
            base = 100.0 * (1 + cluster_drift) ** np.arange(n_bars)
            noise = rng.normal(0, 0.5, n_bars)
            close = base + noise.cumsum()
            close = np.maximum(close, 1.0)
            out[f"T{i}"] = pd.DataFrame({
                "Close": close,
                "Open": close * 0.999,
                "High": close * 1.005,
                "Low": close * 0.995,
                "Volume": 1_000_000.0,
            }, index=idx)
        return out

    def _processor(self, method: str):
        return SignalProcessor(
            regime=RegimeSettings(enable_trend=False, enable_vol=False),
            hygiene=HygieneSettings(min_history=10, clamp=1.0),
            ensemble=EnsembleSettings(enable_shrink=False),
            edge_weights={"e1": 1.0},
            portfolio_optimizer_settings=PortfolioOptimizerSettings(
                method=method, cov_lookback=60, min_history=20,
                turnover_enabled=False,
            ),
        )

    def test_weighted_sum_no_optimizer_weight_emitted(self):
        data = self._build_data_map()
        proc = self._processor("weighted_sum")
        # Direct aggregate scores per ticker
        raw = {t: {"e1": 0.7} for t in data}
        out = proc.process(data, pd.Timestamp("2024-04-30"), raw)
        for t, info in out.items():
            assert "optimizer_weight" not in info
            # tanh(0.7/1.0) ≈ 0.604 — we just check the score is set; the
            # composition tests below compare against this baseline.
            assert "aggregate_score" in info

    def test_hrp_replacement_overwrites_aggregate_score(self):
        """Replicates slice-1 behavior: aggregate_score is replaced."""
        data = self._build_data_map()
        baseline = self._processor("weighted_sum").process(
            data, pd.Timestamp("2024-04-30"),
            {t: {"e1": 0.7} for t in data},
        )
        baseline_score = next(iter(baseline.values()))["aggregate_score"]

        proc = self._processor("hrp")
        out = proc.process(
            data, pd.Timestamp("2024-04-30"),
            {t: {"e1": 0.7} for t in data},
        )
        scores = [info["aggregate_score"] for info in out.values()]
        assert all("hrp_weight" in info for info in out.values())
        # Slice 1 sets optimizer_weight=1.0 (already absorbed).
        assert all(info["optimizer_weight"] == 1.0 for info in out.values())
        # Score magnitudes differ from the weighted_sum baseline
        assert max(abs(s) for s in scores) <= 1.0
        # At least one score should differ meaningfully from the baseline
        # (HRP-weight × N replacement → covariance-driven, not conviction)
        assert any(abs(abs(s) - abs(baseline_score)) > 0.05 for s in scores), (
            f"slice-1 should change at least one ticker's magnitude from "
            f"baseline {baseline_score:.4f}; got scores {scores}"
        )

    def test_hrp_composed_preserves_aggregate_score(self):
        """Slice-3: aggregate_score == weighted_sum baseline; optimizer_weight emitted."""
        data = self._build_data_map()
        baseline = self._processor("weighted_sum").process(
            data, pd.Timestamp("2024-04-30"),
            {t: {"e1": 0.7} for t in data},
        )

        proc = self._processor("hrp_composed")
        out = proc.process(
            data, pd.Timestamp("2024-04-30"),
            {t: {"e1": 0.7} for t in data},
        )
        for t, info in out.items():
            # Conviction preserved exactly (matches weighted_sum baseline)
            assert info["aggregate_score"] == pytest.approx(
                baseline[t]["aggregate_score"], abs=1e-9
            )
            # Optimizer weight emitted as composition multiplier
            assert "optimizer_weight" in info
            assert "hrp_weight" in info
            # Slice 3: lower-clamped at 0, no upper clamp (HRP weights are
            # non-negative by construction so no negative output ever).
            ow = info["optimizer_weight"]
            assert ow >= 0.0

    def test_hrp_slice3_redistribution_not_reduction(self):
        """Slice 3 invariant: optimizer_weight has mean ≈ 1.0 across firing
        set AND at least one position is amplified (>1.0) and at least one
        attenuated (<1.0). Slice 2's clamp at 1.0 made every position ≤ 1.0,
        so this test would FAIL on slice 2.
        """
        data = self._build_data_map(n_tickers=8, n_bars=120, seed=0)
        proc = self._processor("hrp_composed")
        out = proc.process(
            data, pd.Timestamp("2024-04-30"),
            {t: {"e1": 0.7} for t in data},
        )
        active = [info for info in out.values() if "optimizer_weight" in info]
        assert len(active) >= 4, (
            f"need ≥4 firing tickers to exercise redistribution; got {len(active)}"
        )
        weights = [info["optimizer_weight"] for info in active]
        mean_w = sum(weights) / len(weights)
        # Mean of HRP_weight × N over all members exactly equals 1.0 by
        # construction (committed sums to 1.0). Allow small float epsilon.
        assert mean_w == pytest.approx(1.0, abs=1e-9)
        # Redistribution invariant: at least one above and one below 1.0.
        # On the synthetic 2-cluster data this is guaranteed by the cluster
        # variance asymmetry HRP detects.
        assert max(weights) > 1.0, (
            f"slice 3 must amplify above-mean tickers; max={max(weights):.4f} "
            f"means slice-2 clamp is still active"
        )
        assert min(weights) < 1.0, (
            f"slice 3 should attenuate below-mean tickers; min={min(weights):.4f}"
        )

    def test_hrp_slice3_no_upper_clamp_degeneracy(self):
        """Construct a high-concentration covariance (one ticker with sharply
        higher HRP weight) and verify the resulting optimizer_weight goes
        materially above 1.0 — the exact behaviour slice 2 was suppressing.
        """
        # Build 4 tickers where one has a much lower variance — HRP will
        # concentrate weight on it.
        rng = np.random.default_rng(42)
        idx = pd.date_range("2024-01-01", periods=120, freq="D")
        out_data = {}
        for i in range(4):
            sigma = 0.005 if i == 0 else 0.05  # T0 is 10× lower vol
            close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, sigma, 120)))
            out_data[f"T{i}"] = pd.DataFrame({
                "Close": close, "Open": close, "High": close * 1.001,
                "Low": close * 0.999, "Volume": 1_000_000.0,
            }, index=idx)

        proc = self._processor("hrp_composed")
        out = proc.process(
            out_data, pd.Timestamp("2024-04-30"),
            {t: {"e1": 0.7} for t in out_data},
        )
        # T0 should receive the highest HRP weight → optimizer_weight > 1.0
        # (would be capped at exactly 1.0 under slice 2's clamp)
        ow_t0 = out["T0"]["optimizer_weight"]
        assert ow_t0 > 1.05, (
            f"low-vol ticker should be amplified; got optimizer_weight={ow_t0:.4f}. "
            f"Value ≈ 1.0 would indicate slice-2 clamp is still in place."
        )


# ============================================================================
# A2 — Turnover penalty rejection (slice 1's TurnoverPenalty, reused)
# ============================================================================
class TestTurnoverPenaltyRejection:
    def test_turnover_gate_rejects_low_alpha_high_cost_rebalance(self):
        from engines.engine_c_portfolio.optimizers.turnover import (
            TurnoverPenalty, TurnoverConfig,
        )
        gate = TurnoverPenalty(TurnoverConfig(
            enabled=True, flat_cost_bps=100.0, min_turnover_to_check=0.0,
        ))
        # First call accepts unconditionally
        w0 = pd.Series({"A": 0.5, "B": 0.5})
        mu0 = pd.Series({"A": 0.01, "B": 0.01})
        accepted = gate.evaluate(w0, mu0)
        assert (accepted == w0).all()
        # Now propose a high-turnover, near-zero-alpha rebalance
        w1 = pd.Series({"A": 0.8, "B": 0.2})
        mu1 = pd.Series({"A": 0.0001, "B": 0.0001})  # tiny alpha
        result = gate.evaluate(w1, mu1)
        # Cost = 0.6 * 0.01 = 0.006; alpha_lift ≈ 0 → reject, return prior
        assert (result == w0).all()
        assert gate.stats["rejected"] == 1


# ============================================================================
# Integration — Engine A → Engine B optimizer_weight propagation
# ============================================================================
class TestOptimizerWeightFlowsToRiskEngine:
    def test_risk_engine_default_optimizer_weight_is_one(self):
        """Without hrp_composed, signal lacks optimizer_weight key → 1.0."""
        risk = RiskEngine({})
        # Build a minimal signal + df_hist
        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        df = pd.DataFrame({
            "Open": 100.0, "High": 101.0, "Low": 99.0,
            "Close": 100.0, "Volume": 1_000_000, "ATR": 10.0,
        }, index=idx)
        signal = {
            "ticker": "AAPL", "side": "long", "strength": 0.8,
            "edge": "test_edge", "edge_id": "test_v1",
            "meta": {},  # no optimizer_weight
        }
        # Attach an empty portfolio so prepare_order doesn't crash
        from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine
        risk.portfolio = PortfolioEngine(initial_capital=100_000.0)
        order = risk.prepare_order(
            signal=signal, equity=100_000.0, df_hist=df, current_qty=0,
        )
        assert order is not None
        assert order["qty"] >= 1
        baseline_qty = order["qty"]

        # Same setup but with optimizer_weight=0.5 → smaller qty
        risk2 = RiskEngine({})
        risk2.portfolio = PortfolioEngine(initial_capital=100_000.0)
        signal2 = dict(signal)
        signal2["meta"] = {"optimizer_weight": 0.5}
        order2 = risk2.prepare_order(
            signal=signal2, equity=100_000.0, df_hist=df, current_qty=0,
        )
        assert order2 is not None
        # 0.5 multiplier should yield strictly smaller (or equal if forced to 1) qty
        assert order2["qty"] <= baseline_qty
        # And meaningfully smaller when the baseline is comfortably > 1
        if baseline_qty >= 4:
            assert order2["qty"] < baseline_qty

    def test_wash_sale_blocks_buy_via_record_fill(self):
        """End-to-end: record loss exit → next buy on same ticker is blocked."""
        risk = RiskEngine({}, wash_sale_cfg={"enabled": True, "window_days": 30})
        from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine
        risk.portfolio = PortfolioEngine(initial_capital=100_000.0)

        idx = pd.date_range("2024-01-01", periods=60, freq="D")
        df = pd.DataFrame({
            "Open": 100.0, "High": 101.0, "Low": 99.0,
            "Close": 100.0, "Volume": 1_000_000, "ATR": 10.0,
        }, index=idx)
        # Record a loss exit on day 60
        risk.record_fill(
            {"ticker": "AAPL", "side": "exit", "pnl": -500.0, "qty": 10},
            ts=idx[-1],
        )
        signal = {
            "ticker": "AAPL", "side": "long", "strength": 0.8,
            "edge": "test_edge", "edge_id": "test_v1",
            "meta": {},
        }
        # Attempt to buy on day 60 (within 30d window) → blocked
        order = risk.prepare_order(
            signal=signal, equity=100_000.0, df_hist=df, current_qty=0,
        )
        assert order is None
        assert risk.last_skip_by_ticker.get("AAPL") == "wash_sale_window_active"
        assert risk.wash_sale.stats["buys_blocked"] == 1
