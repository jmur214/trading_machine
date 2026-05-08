"""Tests for MultiSleeveAggregator + TrendFollowingSleeve."""
from __future__ import annotations

from typing import Dict

import numpy as np
import pandas as pd
import pytest

from engines.engine_c_portfolio.sleeves.aggregator import MultiSleeveAggregator
from engines.engine_c_portfolio.sleeves.sleeve_base import (
    Sleeve, SleeveSpec, SleeveOutput,
)
from engines.engine_c_portfolio.sleeves.trend_following_sleeve import (
    TrendFollowingSleeve,
)


# ----- Synthetic test sleeves --------------------------------------- #

class StaticSleeve(Sleeve):
    """Always returns a fixed weight map; useful for aggregator tests."""
    def __init__(self, spec: SleeveSpec, weights: Dict[str, float]):
        super().__init__(spec)
        self._fixed = dict(weights)

    def propose_weights(self, as_of, signals, price_data, regime_meta=None):
        self._record_rebalance(as_of, self._fixed)
        return SleeveOutput(
            sleeve_name=self.spec.name,
            target_weights=dict(self._fixed),
            rebalance_due=True,
            last_rebalance=as_of,
        )


class CrashingSleeve(Sleeve):
    """Always raises during propose_weights — used to verify aggregator
    isolation (one bad sleeve shouldn't take down the whole step)."""
    def propose_weights(self, as_of, signals, price_data, regime_meta=None):
        raise RuntimeError("simulated crash inside propose_weights")


def _spec(
    name: str, *, capital_pct: float = 0.5, enabled: bool = True,
    cadence: str = "bar", max_w: float = 1.0,
) -> SleeveSpec:
    return SleeveSpec(
        name=name, capital_pct=capital_pct,
        rebalance_cadence=cadence,
        universe_id="test_universe",
        edge_set=["e1", "e2"],
        sizing_rule="weighted_sum",
        objective_function="sortino_skew_upside",
        enabled=enabled,
        max_position_weight=max_w,
    )


# ----- Aggregator construction ------------------------------------- #

def test_aggregator_requires_at_least_one_sleeve() -> None:
    with pytest.raises(ValueError, match="≥1 sleeve"):
        MultiSleeveAggregator([])


def test_aggregator_rejects_duplicate_sleeve_names() -> None:
    s1 = StaticSleeve(_spec("a", capital_pct=0.3), {"X": 1.0})
    s2 = StaticSleeve(_spec("a", capital_pct=0.3), {"Y": 1.0})
    with pytest.raises(ValueError, match="duplicates"):
        MultiSleeveAggregator([s1, s2])


def test_aggregator_rejects_capital_overflow() -> None:
    s1 = StaticSleeve(_spec("a", capital_pct=0.6), {})
    s2 = StaticSleeve(_spec("b", capital_pct=0.6), {})
    with pytest.raises(ValueError, match="capital_pct"):
        MultiSleeveAggregator([s1, s2])


def test_aggregator_allows_capital_overflow_with_strict_off() -> None:
    s1 = StaticSleeve(_spec("a", capital_pct=0.6), {})
    s2 = StaticSleeve(_spec("b", capital_pct=0.6), {})
    agg = MultiSleeveAggregator([s1, s2], strict_capital_check=False)
    assert len(agg) == 2


def test_aggregator_ignores_disabled_sleeves_in_capital_sum() -> None:
    s1 = StaticSleeve(_spec("a", capital_pct=0.6), {})
    s2 = StaticSleeve(_spec("b", capital_pct=0.6, enabled=False), {})
    # 0.6 enabled + 0.6 disabled — passes the strict check
    agg = MultiSleeveAggregator([s1, s2])
    assert len(agg) == 2


# ----- Aggregator step --------------------------------------------- #

def test_aggregator_combines_two_sleeves_proportional_to_capital_pct() -> None:
    s_core = StaticSleeve(_spec("core", capital_pct=0.7), {"AAPL": 1.0})
    s_moon = StaticSleeve(_spec("moonshot", capital_pct=0.3), {"AAPL": 1.0})
    agg = MultiSleeveAggregator([s_core, s_moon])
    out = agg.step(pd.Timestamp("2024-01-15"), signals={}, price_data={})
    # AAPL gets 0.7 * 1.0 + 0.3 * 1.0 = 1.0
    assert out.target_weights["AAPL"] == pytest.approx(1.0)
    assert out.capital_used_pct == pytest.approx(1.0)


def test_aggregator_keeps_per_sleeve_outputs() -> None:
    s1 = StaticSleeve(_spec("s1", capital_pct=0.5), {"AAPL": 1.0})
    s2 = StaticSleeve(_spec("s2", capital_pct=0.5), {"MSFT": 1.0})
    agg = MultiSleeveAggregator([s1, s2])
    out = agg.step(pd.Timestamp("2024-01-15"), signals={}, price_data={})
    assert "s1" in out.per_sleeve
    assert "s2" in out.per_sleeve
    assert out.per_sleeve["s1"].target_weights == {"AAPL": 1.0}


def test_aggregator_skips_disabled_sleeves() -> None:
    s_active = StaticSleeve(_spec("a", capital_pct=0.5), {"AAPL": 1.0})
    s_off = StaticSleeve(_spec("b", capital_pct=0.5, enabled=False), {"MSFT": 1.0})
    agg = MultiSleeveAggregator([s_active, s_off])
    out = agg.step(pd.Timestamp("2024-01-15"), signals={}, price_data={})
    # Only AAPL — disabled sleeve's MSFT was skipped
    assert out.target_weights == {"AAPL": pytest.approx(0.5)}
    assert "b" not in out.per_sleeve
    assert out.capital_used_pct == pytest.approx(0.5)


def test_aggregator_isolates_crashing_sleeve() -> None:
    """A sleeve raising during propose_weights must not cascade."""
    s_good = StaticSleeve(_spec("good", capital_pct=0.5), {"AAPL": 1.0})
    s_bad = CrashingSleeve(_spec("bad", capital_pct=0.5))
    agg = MultiSleeveAggregator([s_good, s_bad])
    out = agg.step(pd.Timestamp("2024-01-15"), signals={}, price_data={})
    assert "AAPL" in out.target_weights
    # Bad sleeve emits a zero-weight output with error diagnostic
    assert out.per_sleeve["bad"].target_weights == {}
    assert "error" in out.per_sleeve["bad"].diagnostics


def test_sleeve_by_name_lookup() -> None:
    s1 = StaticSleeve(_spec("a", capital_pct=0.5), {})
    s2 = StaticSleeve(_spec("b", capital_pct=0.5), {})
    agg = MultiSleeveAggregator([s1, s2])
    assert agg.sleeve_by_name("a") is s1
    assert agg.sleeve_by_name("nonexistent") is None


# ----- TrendFollowingSleeve --------------------------------------- #

def _make_trending_data(n: int = 300, start: float = 100.0, daily_drift: float = 0.001, vol: float = 0.012, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rets = rng.normal(daily_drift, vol, n)
    prices = start * np.cumprod(1.0 + rets)
    idx = pd.date_range("2023-01-02", periods=n, freq="B")
    return pd.DataFrame({
        "Open": prices, "High": prices * 1.001, "Low": prices * 0.999,
        "Close": prices, "Volume": 1_000_000,
    }, index=idx)


def test_trend_sleeve_filters_to_top_n_momentum_positive() -> None:
    spec = _spec("trend", capital_pct=1.0, max_w=1.0)
    sleeve = TrendFollowingSleeve(spec, top_n=2)

    # 3 trending names + 1 strongly negative-drift name. Use vol=0.005
    # for FLAT so the −0.005 drift dominates noise; the synthetic-noise
    # version with vol=0.012 occasionally produces positive 252-day
    # cumulative return purely by chance.
    price_data = {
        "WIN1": _make_trending_data(daily_drift=0.002, seed=1),
        "WIN2": _make_trending_data(daily_drift=0.0015, seed=2),
        "WIN3": _make_trending_data(daily_drift=0.001, seed=3),
        "FLAT": _make_trending_data(daily_drift=-0.005, vol=0.005, seed=4),
    }
    signals = {t: 1.0 for t in price_data}
    out = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-12-15"),
        signals=signals,
        price_data=price_data,
    )
    # FLAT excluded (definitively negative momentum); top_n=2 keeps the best 2
    assert "FLAT" not in out.target_weights
    assert len(out.target_weights) <= 2
    # Weights sum to 1.0 within sleeve
    assert sum(out.target_weights.values()) == pytest.approx(1.0, abs=1e-6)


def test_trend_sleeve_respects_max_position_weight_cap() -> None:
    spec = _spec("trend", capital_pct=1.0, max_w=0.4)
    sleeve = TrendFollowingSleeve(spec, top_n=10)
    # 5 names, all eligible
    price_data = {
        f"T{i}": _make_trending_data(daily_drift=0.001 + i * 0.0001, seed=i)
        for i in range(5)
    }
    signals = {t: 1.0 for t in price_data}
    out = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-12-15"),
        signals=signals,
        price_data=price_data,
    )
    # No single weight exceeds the cap (after re-normalization)
    if out.target_weights:
        assert max(out.target_weights.values()) <= 0.40 + 1e-9


def test_trend_sleeve_returns_empty_when_no_momentum_positive_names() -> None:
    spec = _spec("trend", capital_pct=1.0)
    sleeve = TrendFollowingSleeve(spec, top_n=5, min_momentum=0.0)
    price_data = {
        "DOWN1": _make_trending_data(daily_drift=-0.002, seed=1),
        "DOWN2": _make_trending_data(daily_drift=-0.001, seed=2),
    }
    signals = {t: 1.0 for t in price_data}
    out = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-12-15"),
        signals=signals,
        price_data=price_data,
    )
    assert out.target_weights == {}
    assert out.diagnostics.get("n_eligible") == 0


def test_trend_sleeve_honors_cadence_via_cached_weights() -> None:
    spec = _spec("trend", capital_pct=1.0, cadence="monthly")
    sleeve = TrendFollowingSleeve(spec, top_n=3)
    price_data = {
        f"T{i}": _make_trending_data(daily_drift=0.001 + i * 0.0001, seed=i)
        for i in range(3)
    }
    signals = {t: 1.0 for t in price_data}
    # First call → rebalance
    out1 = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-12-02"), signals=signals, price_data=price_data,
    )
    assert out1.rebalance_due is True
    # Same month → no rebalance, returns cached weights
    out2 = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-12-15"), signals=signals, price_data=price_data,
    )
    assert out2.rebalance_due is False
    assert out2.target_weights == out1.target_weights


def test_trend_sleeve_skips_tickers_with_insufficient_history() -> None:
    spec = _spec("trend", capital_pct=1.0)
    sleeve = TrendFollowingSleeve(spec, top_n=5, lookback_days=252)
    # Short ticker has only 50 bars — far less than the 252 lookback
    short_idx = pd.date_range("2024-10-01", periods=50, freq="B")
    short_df = pd.DataFrame({"Close": np.linspace(100, 110, 50)}, index=short_idx)
    long_df = _make_trending_data(daily_drift=0.001, seed=99)
    price_data = {"SHORT": short_df, "LONG": long_df}
    signals = {"SHORT": 1.0, "LONG": 1.0}
    out = sleeve.propose_weights(
        as_of=pd.Timestamp("2024-12-15"), signals=signals, price_data=price_data,
    )
    # SHORT excluded for insufficient history
    assert "SHORT" not in out.target_weights
