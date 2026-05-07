"""Engine C — HRP optimizer + turnover penalty + signal_processor dispatch.

Tests cover:
  HRP weight invariants
    - sum to 1.0
    - non-negative (long-only)
    - falls back to equal-weight when history is insufficient
    - sensible concentration: equal-corr inputs → near-equal weights;
      block-correlated inputs → tilt toward the diversifying block
  Turnover penalty
    - first proposal accepted unconditionally
    - low-alpha-lift rebalance rejected (returns previous committed)
    - high-alpha-lift rebalance accepted
    - flat_cost_bps zero → always accept
  SignalProcessor dispatch
    - method="weighted_sum" → strictly identical output to no PO settings
    - method="hrp" → reshapes magnitudes but preserves signs
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.engine_c_portfolio.optimizers import HRPOptimizer, TurnoverPenalty
from engines.engine_c_portfolio.optimizers.hrp import HRPConfig
from engines.engine_c_portfolio.optimizers.turnover import TurnoverConfig
from engines.engine_a_alpha.signal_processor import (
    SignalProcessor,
    RegimeSettings,
    HygieneSettings,
    EnsembleSettings,
)
from engines.engine_c_portfolio.composer import (
    PortfolioComposer,
    PortfolioOptimizerSettings,
)


# --------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------- #

def _synthetic_returns(n_tickers: int, n_days: int, seed: int = 42, corr: float = 0.0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    if corr <= 0:
        data = rng.standard_normal((n_days, n_tickers)) * 0.01
    else:
        common = rng.standard_normal(n_days) * 0.01
        data = np.zeros((n_days, n_tickers))
        for j in range(n_tickers):
            idio = rng.standard_normal(n_days) * 0.01
            data[:, j] = corr * common + (1 - corr) * idio
    cols = [f"T{i}" for i in range(n_tickers)]
    idx = pd.date_range("2024-01-01", periods=n_days, freq="B")
    return pd.DataFrame(data, index=idx, columns=cols)


def _data_map_from_returns(returns: pd.DataFrame, base_price: float = 100.0) -> dict:
    prices = (1.0 + returns).cumprod() * base_price
    out = {}
    for t in prices.columns:
        out[t] = pd.DataFrame({"Close": prices[t], "Volume": 1_000_000.0})
    return out


# --------------------------------------------------------------------- #
# HRP optimizer
# --------------------------------------------------------------------- #

class TestHRPWeights:
    def test_weights_sum_to_one(self):
        returns = _synthetic_returns(8, 120)
        opt = HRPOptimizer()
        w = opt.optimize(returns)
        assert len(w) == 8
        assert w.sum() == pytest.approx(1.0, abs=1e-9)

    def test_weights_are_long_only(self):
        returns = _synthetic_returns(8, 120)
        w = HRPOptimizer().optimize(returns)
        assert (w >= 0).all()

    def test_weights_finite(self):
        returns = _synthetic_returns(6, 100)
        w = HRPOptimizer().optimize(returns)
        assert np.isfinite(w.values).all()

    def test_insufficient_history_falls_back_to_equal_weight(self):
        returns = _synthetic_returns(5, 10)
        cfg = HRPConfig(cov_lookback=60, min_history=30)
        w = HRPOptimizer(cfg).optimize(returns)
        assert len(w) == 5
        for v in w.values:
            assert v == pytest.approx(1.0 / 5, abs=1e-9)

    def test_single_ticker_returns_full_weight(self):
        returns = _synthetic_returns(1, 80)
        w = HRPOptimizer().optimize(returns)
        assert len(w) == 1
        assert w.iloc[0] == pytest.approx(1.0)

    def test_equal_correlation_gives_near_equal_weights(self):
        """When all tickers have the same vol and same correlation,
        HRP should converge close to equal-weight."""
        returns = _synthetic_returns(8, 200, seed=7, corr=0.0)
        w = HRPOptimizer().optimize(returns)
        assert w.std() < 0.05

    def test_block_correlation_concentrates_on_diversifier(self):
        """Build two tightly-correlated blocks plus one independent
        ticker. HRP should give the independent ticker an above-average
        share because it's the diversifying asset.
        """
        rng = np.random.default_rng(99)
        n_days = 200
        block_a = rng.standard_normal(n_days) * 0.01
        block_b = rng.standard_normal(n_days) * 0.01
        idio = rng.standard_normal((n_days, 5)) * 0.001

        cols = {
            "A1": block_a + idio[:, 0],
            "A2": block_a + idio[:, 1],
            "B1": block_b + idio[:, 2],
            "B2": block_b + idio[:, 3],
            "C":  rng.standard_normal(n_days) * 0.01,
        }
        idx = pd.date_range("2024-01-01", periods=n_days, freq="B")
        returns = pd.DataFrame(cols, index=idx)

        w = HRPOptimizer().optimize(returns)
        assert w["C"] > 1.0 / len(cols)


# --------------------------------------------------------------------- #
# Turnover penalty
# --------------------------------------------------------------------- #

class TestTurnoverPenalty:
    def test_first_proposal_always_accepted(self):
        gate = TurnoverPenalty(TurnoverConfig(flat_cost_bps=100.0))
        w = pd.Series({"A": 0.5, "B": 0.5})
        mu = pd.Series({"A": 0.0, "B": 0.0})
        out = gate.evaluate(w, mu)
        assert out.equals(w)
        assert gate.stats["accepted"] == 1
        assert gate.stats["rejected"] == 0

    def test_low_alpha_lift_rejected(self):
        gate = TurnoverPenalty(TurnoverConfig(flat_cost_bps=100.0))  # 1% cost
        committed = pd.Series({"A": 0.5, "B": 0.5})
        gate.evaluate(committed, pd.Series({"A": 0.0, "B": 0.0}))

        proposed = pd.Series({"A": 0.4, "B": 0.6})
        # alpha lift = (-0.1)*0 + 0.1*0.001 = 0.0001 ; cost = 0.2 * 0.01 = 0.002
        out = gate.evaluate(proposed, pd.Series({"A": 0.0, "B": 0.001}))
        assert out.equals(committed)
        assert gate.stats["rejected"] == 1

    def test_high_alpha_lift_accepted(self):
        gate = TurnoverPenalty(TurnoverConfig(flat_cost_bps=10.0))  # 0.1% cost
        committed = pd.Series({"A": 0.5, "B": 0.5})
        gate.evaluate(committed, pd.Series({"A": 0.0, "B": 0.0}))

        proposed = pd.Series({"A": 0.2, "B": 0.8})
        # alpha lift = -0.3*0 + 0.3*0.5 = 0.15 ; cost = 0.6 * 0.001 = 0.0006
        out = gate.evaluate(proposed, pd.Series({"A": 0.0, "B": 0.5}))
        assert out.equals(proposed)
        assert gate.stats["accepted"] == 2

    def test_zero_cost_always_accepts(self):
        gate = TurnoverPenalty(TurnoverConfig(flat_cost_bps=0.0))
        gate.evaluate(pd.Series({"A": 0.5, "B": 0.5}), pd.Series({"A": 0.0, "B": 0.0}))

        # Any positive alpha lift ≥ 0 cost → accept
        proposed = pd.Series({"A": 0.3, "B": 0.7})
        out = gate.evaluate(proposed, pd.Series({"A": 0.0, "B": 0.001}))
        assert out.equals(proposed)

    def test_below_min_turnover_skip(self):
        gate = TurnoverPenalty(TurnoverConfig(min_turnover_to_check=0.1, flat_cost_bps=10000.0))
        gate.evaluate(pd.Series({"A": 0.5, "B": 0.5}), pd.Series({"A": 0.0, "B": 0.0}))

        # tiny rebalance: 0.01 + 0.01 = 0.02 turnover < 0.1 → bypass
        proposed = pd.Series({"A": 0.49, "B": 0.51})
        out = gate.evaluate(proposed, pd.Series({"A": 0.0, "B": 0.0}))
        assert out.equals(proposed)

    def test_disabled_passes_through(self):
        gate = TurnoverPenalty(TurnoverConfig(enabled=False, flat_cost_bps=10000.0))
        # Even crazy cost is bypassed when disabled
        gate.evaluate(pd.Series({"A": 1.0}), pd.Series({"A": 0.0}))
        out = gate.evaluate(pd.Series({"A": 0.0, "B": 1.0}), pd.Series({"A": 0.0, "B": 0.0}))
        assert out.iloc[1] == 1.0

    def test_reset_clears_state(self):
        gate = TurnoverPenalty()
        gate.evaluate(pd.Series({"A": 0.5, "B": 0.5}), pd.Series({"A": 0.0, "B": 0.0}))
        assert gate.stats["accepted"] == 1
        gate.reset()
        assert gate.stats["accepted"] == 0
        assert gate._committed is None


# --------------------------------------------------------------------- #
# SignalProcessor + Engine C composer dispatch
#
# Post-2026-05 F4 close: HRP + turnover live in
# engines/engine_c_portfolio/composer.py. SignalProcessor produces pure
# per-ticker aggregate_score; PortfolioComposer mutates that dict to add
# hrp_weight/optimizer_weight (or, for slice-1 method "hrp", overwrite
# aggregate_score).
# --------------------------------------------------------------------- #

class TestSignalProcessorDispatch:
    def _make_inputs(self, seed: int = 0):
        returns = _synthetic_returns(5, 120, seed=seed)
        data_map = _data_map_from_returns(returns)
        raw_scores = {
            "T0": {"edge_a": 0.5},
            "T1": {"edge_a": 0.3},
            "T2": {"edge_a": -0.4},
            "T3": {"edge_a": 0.2},
            "T4": {"edge_a": -0.1},
        }
        now = returns.index[-1]
        return data_map, now, raw_scores

    def _processor(self):
        return SignalProcessor(
            regime=RegimeSettings(enable_trend=False, enable_vol=False),
            hygiene=HygieneSettings(min_history=20, clamp=1.5),
            ensemble=EnsembleSettings(enable_shrink=False),
            edge_weights={"edge_a": 1.0},
        )

    def _run(self, method: str, data_map, now, raw):
        proc = self._processor()
        out = proc.process(data_map, now, raw)
        composer = PortfolioComposer(PortfolioOptimizerSettings(method=method))
        return composer.compose(out, data_map)

    def test_weighted_sum_strict_passthrough(self):
        """method="weighted_sum" composer is a strict no-op."""
        data_map, now, raw = self._make_inputs(seed=11)
        a = self._processor().process(data_map, now, raw)
        b = self._run("weighted_sum", data_map, now, raw)

        assert a.keys() == b.keys()
        for t in a:
            assert a[t]["aggregate_score"] == pytest.approx(b[t]["aggregate_score"])
            assert "hrp_weight" not in b[t]
            assert "optimizer_weight" not in b[t]

    def test_hrp_preserves_signs(self):
        data_map, now, raw = self._make_inputs(seed=22)
        out_ws = self._run("weighted_sum", data_map, now, raw)
        out_hrp = self._run("hrp", data_map, now, raw)
        assert set(out_ws.keys()) == set(out_hrp.keys())
        for t in out_ws:
            sign_ws = np.sign(out_ws[t]["aggregate_score"])
            sign_hrp = np.sign(out_hrp[t]["aggregate_score"])
            if sign_ws != 0:
                assert sign_ws == sign_hrp, f"sign flipped for {t}"

    def test_hrp_reshapes_magnitudes(self):
        """HRP output should differ from weighted_sum on a synthetic
        block-correlated universe — that's the whole point.
        """
        rng = np.random.default_rng(7)
        n_days = 200
        block = rng.standard_normal(n_days) * 0.01
        idio = rng.standard_normal((n_days, 5)) * 0.001
        cols_data = {
            f"T{i}": block + idio[:, i] for i in range(4)
        }
        cols_data["T4"] = rng.standard_normal(n_days) * 0.01
        idx = pd.date_range("2024-01-01", periods=n_days, freq="B")
        returns = pd.DataFrame(cols_data, index=idx)
        data_map = _data_map_from_returns(returns)
        raw = {t: {"edge_a": 0.4} for t in returns.columns}
        now = returns.index[-1]

        out_hrp = self._run("hrp", data_map, now, raw)

        assert "hrp_weight" in out_hrp["T4"]
        weights = np.array([out_hrp[t]["hrp_weight"] for t in returns.columns])
        assert weights.sum() == pytest.approx(1.0, abs=1e-9)
        assert weights.std() > 1e-3

    def test_hrp_deterministic_across_runs(self):
        """Same inputs → identical outputs across re-instantiations."""
        data_map, now, raw = self._make_inputs(seed=33)
        out1 = self._run("hrp", data_map, now, raw)
        out2 = self._run("hrp", data_map, now, raw)
        out3 = self._run("hrp", data_map, now, raw)
        assert set(out1.keys()) == set(out2.keys()) == set(out3.keys())
        for t in out1:
            assert out1[t]["aggregate_score"] == pytest.approx(out2[t]["aggregate_score"])
            assert out2[t]["aggregate_score"] == pytest.approx(out3[t]["aggregate_score"])

    def test_signal_processor_no_engine_c_imports(self):
        """Charter check (F4): signal_processor.py must not reference
        HRPOptimizer or TurnoverPenalty after the 2026-05 migration.
        """
        from pathlib import Path
        sp_src = Path(__file__).parent.parent / "engines" / "engine_a_alpha" / "signal_processor.py"
        text = sp_src.read_text()
        assert "HRPOptimizer" not in text
        assert "TurnoverPenalty" not in text
        assert "engine_c_portfolio" not in text
