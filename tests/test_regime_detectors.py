"""Unit tests for the 5 sub-detectors in Engine E."""

import numpy as np
import pandas as pd
import pytest

from engines.engine_e_regime.regime_config import (
    TrendConfig,
    VolatilityConfig,
    BreadthConfig,
    CorrelationConfig,
    ForwardStressConfig,
)
from engines.engine_e_regime.detectors.trend_detector import TrendDetector
from engines.engine_e_regime.detectors.volatility_detector import VolatilityDetector
from engines.engine_e_regime.detectors.breadth_detector import BreadthDetector
from engines.engine_e_regime.detectors.correlation_detector import CorrelationDetector
from engines.engine_e_regime.detectors.forward_stress_detector import ForwardStressDetector


# ──────────────────────────────────────────────
# Helpers: synthetic data generators
# ──────────────────────────────────────────────

def _make_ohlcv(
    n: int = 300,
    start_price: float = 100.0,
    trend: float = 0.0005,
    vol: float = 0.01,
    seed: int = 42,
) -> pd.DataFrame:
    """Generate synthetic OHLCV DataFrame with controlled trend and volatility."""
    rng = np.random.RandomState(seed)
    prices = [start_price]
    for _ in range(n - 1):
        ret = trend + vol * rng.randn()
        prices.append(prices[-1] * (1 + ret))
    prices = np.array(prices)

    # Realistic OHLC from close
    high = prices * (1 + rng.uniform(0, 0.015, n))
    low = prices * (1 - rng.uniform(0, 0.015, n))
    open_ = prices * (1 + rng.uniform(-0.005, 0.005, n))
    volume = rng.randint(1_000_000, 10_000_000, n)

    dates = pd.bdate_range("2023-01-01", periods=n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": prices, "Volume": volume},
        index=dates,
    )


def _make_bull_df(n=300, seed=42):
    """Strong uptrend with high ER — trend >> vol."""
    return _make_ohlcv(n=n, trend=0.003, vol=0.005, seed=seed)


def _make_bear_df(n=300, seed=42):
    """Strong downtrend with high ER."""
    return _make_ohlcv(n=n, start_price=300.0, trend=-0.003, vol=0.005, seed=seed)


def _make_choppy_df(n=300, seed=42):
    """No trend, high vol → low ER."""
    return _make_ohlcv(n=n, trend=0.0, vol=0.02, seed=seed)


def _make_high_vol_df(n=300, seed=42):
    """Low vol early, high vol late — so ATR percentile is high at the end."""
    rng = np.random.RandomState(seed)
    prices = [100.0]
    for i in range(n - 1):
        v = 0.005 if i < 200 else 0.04  # vol regime change
        ret = 0.0002 + v * rng.randn()
        prices.append(prices[-1] * (1 + ret))
    prices = np.array(prices)
    high = prices * (1 + rng.uniform(0, 0.015, n))
    low = prices * (1 - rng.uniform(0, 0.015, n))
    open_ = prices * (1 + rng.uniform(-0.005, 0.005, n))
    dates = pd.bdate_range("2023-01-01", periods=n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": prices, "Volume": rng.randint(1e6, 10e6, n)},
        index=dates,
    )


def _make_low_vol_df(n=300, seed=42):
    """High vol early, low vol late — so ATR percentile is low at the end."""
    rng = np.random.RandomState(seed)
    prices = [100.0]
    for i in range(n - 1):
        v = 0.03 if i < 200 else 0.002  # vol regime change
        ret = 0.0003 + v * rng.randn()
        prices.append(prices[-1] * (1 + ret))
    prices = np.array(prices)
    high = prices * (1 + rng.uniform(0, 0.005, n))
    low = prices * (1 - rng.uniform(0, 0.005, n))
    open_ = prices * (1 + rng.uniform(-0.002, 0.002, n))
    dates = pd.bdate_range("2023-01-01", periods=n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": prices, "Volume": rng.randint(1e6, 10e6, n)},
        index=dates,
    )


# ──────────────────────────────────────────────
# TrendDetector
# ──────────────────────────────────────────────

class TestTrendDetector:
    def test_bull_detection(self):
        df = _make_bull_df()
        det = TrendDetector(TrendConfig())
        state, conf, details = det.detect(df)
        assert state == "bull"
        assert 0.1 <= conf <= 0.95
        assert details["price"] > details["sma200"]
        assert details["er_60"] > 0

    def test_bear_detection(self):
        df = _make_bear_df()
        det = TrendDetector(TrendConfig())
        state, conf, details = det.detect(df)
        assert state == "bear"
        assert details["price"] < details["sma200"]

    def test_range_detection(self):
        df = _make_choppy_df()
        det = TrendDetector(TrendConfig())
        state, conf, details = det.detect(df)
        assert state == "range"
        assert details["er_60"] < 0.25

    def test_insufficient_data(self):
        df = _make_bull_df(n=50)  # too short for SMA200 + slope window
        det = TrendDetector(TrendConfig())
        state, conf, details = det.detect(df)
        assert state == "range"
        assert conf == 0.1

    def test_empty_df(self):
        df = pd.DataFrame()
        det = TrendDetector(TrendConfig())
        state, conf, details = det.detect(df)
        assert state == "range"

    def test_enriched_details_keys(self):
        df = _make_bull_df()
        det = TrendDetector(TrendConfig())
        _, _, details = det.detect(df)
        expected_keys = {
            "price", "sma200", "sma50", "er_60", "er_14",
            "slope_50", "trend_quality", "sma200_separation",
            "momentum_consistency",
        }
        assert set(details.keys()) == expected_keys

    def test_trend_quality_values(self):
        df = _make_bull_df()
        det = TrendDetector(TrendConfig())
        _, _, details = det.detect(df)
        assert details["trend_quality"] in ("improving", "degrading", "stable")


# ──────────────────────────────────────────────
# VolatilityDetector
# ──────────────────────────────────────────────

class TestVolatilityDetector:
    def test_normal_vol(self):
        # Constant moderate vol → ATR should be stable, percentile near center
        df = _make_ohlcv(n=300, start_price=100.0, trend=0.0, vol=0.01, seed=42)
        det = VolatilityDetector(VolatilityConfig())
        state, conf, details = det.detect(df)
        assert state in ("normal", "low")
        assert 0.1 <= conf <= 0.95

    def test_high_vol(self):
        # Low vol for first 250 bars, then spike for last 50 → ATR percentile should be high
        rng = np.random.RandomState(42)
        n = 300
        prices = [100.0]
        for i in range(n - 1):
            v = 0.003 if i < 250 else 0.05
            ret = v * rng.randn()
            prices.append(prices[-1] * (1 + ret))
        prices = np.array(prices)
        high = prices * (1 + rng.uniform(0, 0.015, n))
        low = prices * (1 - rng.uniform(0, 0.015, n))
        open_ = prices * (1 + rng.uniform(-0.005, 0.005, n))
        dates = pd.bdate_range("2023-01-01", periods=n)
        df = pd.DataFrame(
            {"Open": open_, "High": high, "Low": low, "Close": prices,
             "Volume": rng.randint(1e6, 10e6, n)},
            index=dates,
        )
        det = VolatilityDetector(VolatilityConfig())
        state, conf, details = det.detect(df)
        assert state in ("high", "shock")
        assert details["atr_percentile"] > 70

    def test_low_vol(self):
        df = _make_low_vol_df()
        det = VolatilityDetector(VolatilityConfig())
        state, conf, details = det.detect(df)
        assert state == "low"
        assert details["atr_percentile"] < 30

    def test_insufficient_data(self):
        df = _make_bull_df(n=50)
        det = VolatilityDetector(VolatilityConfig())
        state, conf, details = det.detect(df)
        assert state == "normal"
        assert conf == 0.3

    def test_yang_zhang_positive(self):
        df = _make_bull_df()
        det = VolatilityDetector(VolatilityConfig())
        _, _, details = det.detect(df)
        assert details["yang_zhang_vol"] >= 0

    def test_vol_ratio_positive(self):
        df = _make_bull_df()
        det = VolatilityDetector(VolatilityConfig())
        _, _, details = det.detect(df)
        assert details["vol_ratio_5_60"] > 0

    def test_enriched_details_keys(self):
        df = _make_bull_df()
        det = VolatilityDetector(VolatilityConfig())
        _, _, details = det.detect(df)
        expected_keys = {"atr", "atr_percentile", "yang_zhang_vol", "vol_ratio_5_60"}
        assert set(details.keys()) == expected_keys


# ──────────────────────────────────────────────
# BreadthDetector
# ──────────────────────────────────────────────

class TestBreadthDetector:
    def _make_data_map(self, n_tickers=30, trend=0.001, seed_base=100):
        """Create a data_map of n_tickers all trending similarly."""
        data_map = {}
        for i in range(n_tickers):
            data_map[f"TICK{i}"] = _make_ohlcv(
                n=300, trend=trend, vol=0.01, seed=seed_base + i
            )
        return data_map

    def test_strong_breadth(self):
        """All tickers trending up → strong."""
        data_map = self._make_data_map(trend=0.001)
        det = BreadthDetector(BreadthConfig())
        state, conf, details = det.detect(data_map)
        assert state == "strong"
        assert details["pct_above_sma200"] > 0.6

    def test_weak_breadth(self):
        """All tickers trending down → weak."""
        data_map = self._make_data_map(trend=-0.001)
        det = BreadthDetector(BreadthConfig())
        state, conf, details = det.detect(data_map)
        assert state in ("weak", "deteriorating")
        assert details["pct_above_sma200"] < 0.5

    def test_insufficient_tickers(self):
        data_map = {f"T{i}": _make_ohlcv(n=300) for i in range(5)}
        det = BreadthDetector(BreadthConfig())
        state, conf, details = det.detect(data_map)
        assert state == "strong"  # default fallback
        assert conf == 0.3

    def test_exclude_tickers(self):
        data_map = self._make_data_map(n_tickers=15)
        data_map["SPY"] = _make_bull_df()
        det = BreadthDetector(BreadthConfig(), exclude_tickers={"SPY"})
        state, _, _ = det.detect(data_map)
        # SPY should not be counted
        assert state in ("strong", "narrow", "recovering", "weak", "deteriorating")

    def test_enriched_details_keys(self):
        data_map = self._make_data_map()
        det = BreadthDetector(BreadthConfig())
        _, _, details = det.detect(data_map)
        expected_keys = {
            "pct_above_sma200", "pct_above_sma50", "breadth_slope",
            "nh_nl_pct", "leadership_quality", "breadth_trend",
        }
        assert set(details.keys()) == expected_keys

    def test_reset_clears_history(self):
        data_map = self._make_data_map()
        det = BreadthDetector(BreadthConfig())
        det.detect(data_map)
        assert len(det._history) > 0
        det.reset()
        assert len(det._history) == 0

    def test_slope_computation_after_multiple_bars(self):
        """Slope requires multiple calls to build history."""
        data_map = self._make_data_map()
        det = BreadthDetector(BreadthConfig())
        for _ in range(15):
            det.detect(data_map)
        _, _, details = det.detect(data_map)
        # After 15 bars of the same data, slope should be near 0
        assert abs(details["breadth_slope"]) < 0.05


# ──────────────────────────────────────────────
# CorrelationDetector
# ──────────────────────────────────────────────

class TestCorrelationDetector:
    def _make_sector_data(self, n_per_sector=4, n_sectors=6, correlation_level=0.3, seed=42):
        """Create data_map with tickers organized by sector."""
        rng = np.random.RandomState(seed)
        sector_names = [
            "Technology", "Financials", "Healthcare",
            "Energy", "Consumer Cyclical", "Industrials",
        ][:n_sectors]

        data_map = {}
        sector_map = {}
        dates = pd.bdate_range("2023-01-01", periods=300)

        # Market factor
        market_ret = rng.randn(300) * 0.01

        for s_idx, sector in enumerate(sector_names):
            sector_factor = rng.randn(300) * 0.01
            for t_idx in range(n_per_sector):
                ticker = f"{sector[:3].upper()}{t_idx}"
                idio = rng.randn(300) * 0.01
                ret = (
                    correlation_level * market_ret
                    + (1 - correlation_level) * 0.5 * sector_factor
                    + (1 - correlation_level) * 0.5 * idio
                )
                prices = 100 * np.exp(np.cumsum(ret))
                high = prices * (1 + rng.uniform(0, 0.01, 300))
                low = prices * (1 - rng.uniform(0, 0.01, 300))
                open_ = prices * (1 + rng.uniform(-0.003, 0.003, 300))
                df = pd.DataFrame(
                    {"Open": open_, "High": high, "Low": low, "Close": prices,
                     "Volume": rng.randint(1e6, 5e6, 300)},
                    index=dates,
                )
                data_map[ticker] = df
                sector_map[ticker] = sector

        # Add SPY and TLT for cross-asset
        spy_prices = 100 * np.exp(np.cumsum(market_ret))
        data_map["SPY"] = pd.DataFrame(
            {"Open": spy_prices, "High": spy_prices * 1.005, "Low": spy_prices * 0.995,
             "Close": spy_prices, "Volume": rng.randint(5e6, 20e6, 300)},
            index=dates,
        )
        sector_map["SPY"] = "Benchmark"

        # TLT inversely correlated with SPY
        tlt_ret = -0.5 * market_ret + rng.randn(300) * 0.005
        tlt_prices = 100 * np.exp(np.cumsum(tlt_ret))
        data_map["TLT"] = pd.DataFrame(
            {"Open": tlt_prices, "High": tlt_prices * 1.003, "Low": tlt_prices * 0.997,
             "Close": tlt_prices, "Volume": rng.randint(1e6, 5e6, 300)},
            index=dates,
        )

        # GLD with mild positive correlation
        gld_ret = 0.1 * market_ret + rng.randn(300) * 0.008
        gld_prices = 100 * np.exp(np.cumsum(gld_ret))
        data_map["GLD"] = pd.DataFrame(
            {"Open": gld_prices, "High": gld_prices * 1.003, "Low": gld_prices * 0.997,
             "Close": gld_prices, "Volume": rng.randint(1e6, 5e6, 300)},
            index=dates,
        )

        return data_map, sector_map

    def test_normal_correlation(self):
        data_map, sector_map = self._make_sector_data(correlation_level=0.1)
        det = CorrelationDetector(CorrelationConfig(), sector_map=sector_map)
        state, conf, details = det.detect(data_map)
        assert state in ("normal", "dispersed")
        assert 0.1 <= conf <= 0.95

    def test_high_correlation(self):
        data_map, sector_map = self._make_sector_data(correlation_level=0.9)
        det = CorrelationDetector(CorrelationConfig(), sector_map=sector_map)
        state, conf, details = det.detect(data_map)
        assert state in ("elevated", "spike")
        assert details["pc1_explained"] > 0.3

    def test_enriched_details_keys(self):
        data_map, sector_map = self._make_sector_data()
        det = CorrelationDetector(CorrelationConfig(), sector_map=sector_map)
        _, _, details = det.detect(data_map)
        expected_keys = {
            "avg_sector_corr", "pc1_explained",
            "spy_tlt_corr", "spy_tlt_corr_change", "spy_gld_corr",
        }
        assert set(details.keys()) == expected_keys

    def test_spy_tlt_negative_normal_market(self):
        """In normal markets, SPY-TLT should be negatively correlated."""
        data_map, sector_map = self._make_sector_data(correlation_level=0.3)
        det = CorrelationDetector(CorrelationConfig(), sector_map=sector_map)
        _, _, details = det.detect(data_map)
        assert details["spy_tlt_corr"] < 0  # inversely correlated

    def test_insufficient_sectors(self):
        data_map, sector_map = self._make_sector_data(n_sectors=3, n_per_sector=2)
        det = CorrelationDetector(
            CorrelationConfig(min_sectors=5), sector_map=sector_map
        )
        state, _, _ = det.detect(data_map)
        assert state == "normal"  # falls back due to insufficient data


# ──────────────────────────────────────────────
# ForwardStressDetector
# ──────────────────────────────────────────────

class TestForwardStressDetector:
    def _make_vix_df(self, level=15.0, n=300, seed=42):
        rng = np.random.RandomState(seed)
        vals = level + rng.randn(n) * 2
        vals = np.maximum(vals, 5)
        dates = pd.bdate_range("2023-01-01", periods=n)
        return pd.DataFrame(
            {"Open": vals, "High": vals + 0.5, "Low": vals - 0.5,
             "Close": vals, "Volume": rng.randint(1e6, 5e6, n)},
            index=dates,
        )

    def test_tier1_calm(self):
        vix = self._make_vix_df(level=14)
        vix3m = self._make_vix_df(level=17, seed=43)  # contango
        data_map = {"^VIX": vix, "^VIX3M": vix3m}
        det = ForwardStressDetector(ForwardStressConfig())
        state, conf, details = det.detect(_make_bull_df(), data_map)
        assert state == "calm"
        assert details["data_tier"] == "tier1_term_structure"
        assert details["term_spread"] is not None

    def test_tier1_stressed(self):
        vix = self._make_vix_df(level=28)
        vix3m = self._make_vix_df(level=25, seed=43)  # backwardation
        data_map = {"^VIX": vix, "^VIX3M": vix3m}
        det = ForwardStressDetector(ForwardStressConfig())
        state, conf, details = det.detect(_make_bull_df(), data_map)
        assert state in ("stressed", "panic")

    def test_tier2_fallback(self):
        vix = self._make_vix_df(level=14)
        data_map = {"^VIX": vix}  # no VIX3M
        det = ForwardStressDetector(ForwardStressConfig())
        state, conf, details = det.detect(_make_bull_df(), data_map)
        assert details["data_tier"] == "tier2_vix_only"
        assert details["vix3m"] is None
        assert conf <= 0.85  # tier 2 cap

    def test_tier3_fallback(self):
        det = ForwardStressDetector(ForwardStressConfig())
        state, conf, details = det.detect(_make_bull_df(), {})  # no VIX data
        assert details["data_tier"] == "tier3_synthetic"
        assert conf <= 0.75  # tier 3 cap

    def test_enriched_details_keys(self):
        vix = self._make_vix_df(level=14)
        vix3m = self._make_vix_df(level=17, seed=43)
        data_map = {"^VIX": vix, "^VIX3M": vix3m}
        det = ForwardStressDetector(ForwardStressConfig())
        _, _, details = det.detect(_make_bull_df(), data_map)
        expected_keys = {"vix", "vix3m", "term_spread", "vix_z_score", "data_tier"}
        assert set(details.keys()) == expected_keys

    def test_empty_benchmark(self):
        det = ForwardStressDetector(ForwardStressConfig())
        state, conf, details = det.detect(pd.DataFrame(), {})
        assert state == "calm"
        assert conf == 0.3

    def test_panic_detection(self):
        """VIX at 45 with heavy backwardation."""
        rng = np.random.RandomState(42)
        n = 300
        # Normal VIX for most of history, spike at end
        vals = np.concatenate([
            15 + rng.randn(280) * 2,
            np.linspace(15, 45, 20),
        ])
        vals = np.maximum(vals, 5)
        dates = pd.bdate_range("2023-01-01", periods=n)
        vix = pd.DataFrame(
            {"Open": vals, "High": vals + 1, "Low": vals - 1,
             "Close": vals, "Volume": rng.randint(1e6, 5e6, n)},
            index=dates,
        )
        # VIX3M lower than VIX = backwardation
        vals3m = vals - 8
        vals3m = np.maximum(vals3m, 5)
        vix3m = pd.DataFrame(
            {"Open": vals3m, "High": vals3m + 0.5, "Low": vals3m - 0.5,
             "Close": vals3m, "Volume": rng.randint(1e6, 5e6, n)},
            index=dates,
        )
        data_map = {"^VIX": vix, "^VIX3M": vix3m}
        det = ForwardStressDetector(ForwardStressConfig())
        state, conf, details = det.detect(_make_bull_df(), data_map)
        assert state == "panic"
        assert details["term_spread"] < -5


# ──────────────────────────────────────────────
# RegimeConfig loading
# ──────────────────────────────────────────────

class TestRegimeConfig:
    def test_default_config(self):
        from engines.engine_e_regime.regime_config import RegimeConfig
        cfg = RegimeConfig()
        assert cfg.trend.sma_long == 200
        assert cfg.volatility.atr_window == 14
        assert cfg.forward_stress.vix_ticker == "^VIX"
        assert "SPY" in cfg.benchmarks

    def test_from_json(self):
        from engines.engine_e_regime.regime_config import RegimeConfig
        cfg = RegimeConfig.from_json()
        assert cfg.trend.sma_long == 200
        assert cfg.correlation.rolling_window == 60
        assert cfg.breadth.slope_window == 10

    def test_missing_file_uses_defaults(self):
        from engines.engine_e_regime.regime_config import RegimeConfig
        cfg = RegimeConfig.from_json("/nonexistent/path.json")
        assert cfg.trend.sma_long == 200
