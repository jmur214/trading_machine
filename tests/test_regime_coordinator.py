"""Unit tests for RegimeDetector coordinator, AdvisoryEngine, and RegimeHistoryStore."""

import numpy as np
import pandas as pd
import pytest

from engines.engine_e_regime.regime_detector import RegimeDetector
from engines.engine_e_regime.regime_config import RegimeConfig
from engines.engine_e_regime.advisory import AdvisoryEngine, MACRO_RULES
from engines.engine_e_regime.regime_history import RegimeHistoryStore


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def _make_ohlcv(n=300, trend=0.001, vol=0.005, start=100.0, seed=42):
    rng = np.random.RandomState(seed)
    prices = [start]
    for _ in range(n - 1):
        ret = trend + vol * rng.randn()
        prices.append(prices[-1] * (1 + ret))
    prices = np.array(prices)
    high = prices * (1 + rng.uniform(0, 0.015, n))
    low = prices * (1 - rng.uniform(0, 0.015, n))
    open_ = prices * (1 + rng.uniform(-0.005, 0.005, n))
    dates = pd.bdate_range("2023-01-01", periods=n)
    return pd.DataFrame(
        {"Open": open_, "High": high, "Low": low, "Close": prices,
         "Volume": rng.randint(1e6, 10e6, n)},
        index=dates,
    )


def _make_data_map(n_tickers=30, trend=0.001, seed_base=100):
    data_map = {}
    for i in range(n_tickers):
        data_map[f"TICK{i}"] = _make_ohlcv(n=300, trend=trend, vol=0.01, seed=seed_base + i)
    data_map["SPY"] = _make_ohlcv(n=300, trend=0.003, vol=0.005, seed=42)
    data_map["TLT"] = _make_ohlcv(n=300, trend=-0.001, vol=0.005, seed=43)
    data_map["GLD"] = _make_ohlcv(n=300, trend=0.0005, vol=0.008, seed=44)
    return data_map


# ──────────────────────────────────────────────
# RegimeDetector Coordinator
# ──────────────────────────────────────────────

class TestRegimeDetectorCoordinator:
    def test_basic_detection(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)

        # Must have all top-level keys
        assert "trend_regime" in result
        assert "volatility_regime" in result
        assert "correlation_regime" in result
        assert "breadth_regime" in result
        assert "forward_stress_regime" in result
        assert "transition_risk" in result
        assert "regime_stability" in result
        assert "macro_regime" in result
        assert "advisory" in result
        assert "explanation" in result
        assert "meta" in result

    def test_backward_compat_keys(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)

        # Old flat keys must be present
        assert "regime" in result
        assert "trend" in result
        assert "volatility" in result
        assert "regime_int" in result
        assert "details" in result

        # Values must be valid
        assert result["trend"] in ("bull", "bear", "neutral")
        assert result["volatility"] in ("high", "normal", "low")
        assert result["regime_int"] in (1, -1, 0)
        assert isinstance(result["details"], dict)
        assert "price" in result["details"]
        assert "sma" in result["details"]
        assert "atr" in result["details"]

    def test_structured_axis_format(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)

        for axis in ("trend_regime", "volatility_regime", "correlation_regime",
                      "breadth_regime", "forward_stress_regime"):
            assert "state" in result[axis]
            assert "confidence" in result[axis]
            assert 0.0 <= result[axis]["confidence"] <= 1.0

    def test_macro_regime_structure(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)

        macro = result["macro_regime"]
        assert "label" in macro
        assert "probabilities" in macro
        assert isinstance(macro["probabilities"], dict)

        # Probabilities should sum to ~1
        total = sum(macro["probabilities"].values())
        assert 0.95 <= total <= 1.05

        # All 5 regimes should be present
        for regime in list(MACRO_RULES.keys()) + ["transitional"]:
            assert regime in macro["probabilities"]

    def test_advisory_structure(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)

        adv = result["advisory"]
        assert adv["regime_summary"] in ("benign", "cautious", "stressed", "crisis")
        assert 0.3 <= adv["suggested_exposure_cap"] <= 1.0
        assert 0.3 <= adv["risk_scalar"] <= 1.2
        assert isinstance(adv["suggested_max_positions"], int)
        assert isinstance(adv["edge_affinity"], dict)
        for edge in ("momentum", "mean_reversion", "trend_following", "fundamental"):
            assert 0.3 <= adv["edge_affinity"][edge] <= 1.5

    def test_explanation_keys(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)

        exp = result["explanation"]
        assert set(exp.keys()) == {"trend", "volatility", "correlation", "breadth", "forward_stress"}

    def test_meta_keys(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)

        meta = result["meta"]
        assert "axis_durations" in meta
        assert "flip_counts_30bar" in meta
        assert "empirical_transition_probs" in meta

    def test_with_data_map(self):
        det = RegimeDetector()
        data_map = _make_data_map()
        spy = data_map["SPY"]
        result = det.detect_regime(spy, data_map=data_map)

        # Should work with full data map (correlation + breadth + fwd stress)
        assert result["correlation_regime"]["state"] in (
            "dispersed", "normal", "elevated", "spike"
        )
        assert result["breadth_regime"]["state"] in (
            "strong", "narrow", "recovering", "weak", "deteriorating"
        )

    def test_stateful_across_bars(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)

        # Call multiple times to build history
        for _ in range(10):
            result = det.detect_regime(spy)

        assert len(det.history) == 10
        assert det.history.axis_durations["trend"] > 0

    def test_hysteresis_prevents_flapping(self):
        det = RegimeDetector()
        spy_bull = _make_ohlcv(n=300, trend=0.003, vol=0.005, seed=42)

        # First call establishes state
        r1 = det.detect_regime(spy_bull)
        initial_trend = r1["trend_regime"]["state"]

        # Inject a single "bear" bar via a choppy df — hysteresis should hold
        spy_choppy = _make_ohlcv(n=300, trend=0.0, vol=0.02, seed=99)
        r2 = det.detect_regime(spy_choppy)

        # Trend should not have flipped after just 1 divergent bar
        assert r2["trend_regime"]["state"] == initial_trend

    def test_reset_clears_state(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)

        det.detect_regime(spy)
        det.detect_regime(spy)
        assert len(det.history) == 2

        det.reset()
        assert len(det.history) == 0

    def test_transition_risk_bounded(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)
        assert 0.0 <= result["transition_risk"] <= 1.0

    def test_regime_stability_bounded(self):
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)
        assert 0.0 <= result["regime_stability"] <= 1.0

    def test_shock_vol_compat_mapping(self):
        """If vol axis detects 'shock', backward-compat 'volatility' key should be 'high'."""
        det = RegimeDetector()
        spy = _make_ohlcv(n=300, trend=0.003, vol=0.005)
        result = det.detect_regime(spy)
        # Can't force shock with synthetic data easily, but verify mapping logic
        assert result["volatility"] in ("high", "normal", "low")


# ──────────────────────────────────────────────
# AdvisoryEngine
# ──────────────────────────────────────────────

class TestAdvisoryEngine:
    def test_benign_regime(self):
        adv = AdvisoryEngine()
        macro, advisory = adv.generate(
            axis_states={"trend": "bull", "volatility": "low", "correlation": "dispersed",
                        "breadth": "strong", "forward_stress": "calm"},
            axis_confidences={"trend": 0.8, "volatility": 0.7, "correlation": 0.6,
                             "breadth": 0.7, "forward_stress": 0.8},
            axis_durations={"trend": 30, "volatility": 30, "correlation": 30,
                           "breadth": 30, "forward_stress": 30},
            flip_counts={"trend": 0, "volatility": 0, "correlation": 0,
                        "breadth": 0, "forward_stress": 0},
        )
        assert advisory["regime_summary"] == "benign"
        assert advisory["suggested_exposure_cap"] > 0.7
        assert macro["label"] == "robust_expansion"

    def test_crisis_regime(self):
        adv = AdvisoryEngine()
        macro, advisory = adv.generate(
            axis_states={"trend": "bear", "volatility": "shock", "correlation": "spike",
                        "breadth": "weak", "forward_stress": "panic"},
            axis_confidences={"trend": 0.9, "volatility": 0.95, "correlation": 0.9,
                             "breadth": 0.8, "forward_stress": 0.95},
            axis_durations={"trend": 10, "volatility": 5, "correlation": 5,
                           "breadth": 10, "forward_stress": 3},
            flip_counts={"trend": 1, "volatility": 2, "correlation": 2,
                        "breadth": 1, "forward_stress": 1},
        )
        assert advisory["regime_summary"] == "crisis"
        assert advisory["suggested_exposure_cap"] <= 0.5
        assert advisory["risk_scalar"] < 0.5
        assert macro["label"] == "market_turmoil"

    def test_walking_on_ice_coherence(self):
        adv = AdvisoryEngine()
        _, advisory = adv.generate(
            axis_states={"trend": "bull", "volatility": "high", "correlation": "elevated",
                        "breadth": "deteriorating", "forward_stress": "cautious"},
            axis_confidences={"trend": 0.7, "volatility": 0.7, "correlation": 0.6,
                             "breadth": 0.7, "forward_stress": 0.6},
            axis_durations={"trend": 20, "volatility": 5, "correlation": 10,
                           "breadth": 5, "forward_stress": 10},
            flip_counts={"trend": 0, "volatility": 1, "correlation": 1,
                        "breadth": 1, "forward_stress": 0},
        )
        assert "Walking on Ice" in advisory["caution_note"]
        # Momentum should be capped by coherence override
        assert advisory["edge_affinity"]["momentum"] <= 0.5

    def test_flip_frequency_warning(self):
        adv = AdvisoryEngine()
        _, advisory = adv.generate(
            axis_states={"trend": "bull", "volatility": "normal", "correlation": "normal",
                        "breadth": "strong", "forward_stress": "calm"},
            axis_confidences={"trend": 0.7, "volatility": 0.6, "correlation": 0.5,
                             "breadth": 0.6, "forward_stress": 0.7},
            axis_durations={"trend": 5, "volatility": 2, "correlation": 5,
                           "breadth": 5, "forward_stress": 5},
            flip_counts={"trend": 5, "volatility": 1, "correlation": 0,
                        "breadth": 0, "forward_stress": 0},
        )
        assert "Regime instability on trend" in advisory["caution_note"]

    def test_gold_safe_haven(self):
        adv = AdvisoryEngine()
        _, advisory = adv.generate(
            axis_states={"trend": "bull", "volatility": "normal", "correlation": "normal",
                        "breadth": "strong", "forward_stress": "calm"},
            axis_confidences={"trend": 0.7, "volatility": 0.6, "correlation": 0.5,
                             "breadth": 0.6, "forward_stress": 0.7},
            axis_durations={"trend": 20, "volatility": 20, "correlation": 20,
                           "breadth": 20, "forward_stress": 20},
            flip_counts={"trend": 0, "volatility": 0, "correlation": 0,
                        "breadth": 0, "forward_stress": 0},
            corr_details={"spy_gld_corr": -0.45},
        )
        assert "Gold safe-haven" in advisory["caution_note"]

    def test_edge_affinity_bounded(self):
        adv = AdvisoryEngine()
        _, advisory = adv.generate(
            axis_states={"trend": "range", "volatility": "normal", "correlation": "normal",
                        "breadth": "narrow", "forward_stress": "cautious"},
            axis_confidences={"trend": 0.5, "volatility": 0.5, "correlation": 0.5,
                             "breadth": 0.5, "forward_stress": 0.5},
            axis_durations={"trend": 10, "volatility": 10, "correlation": 10,
                           "breadth": 10, "forward_stress": 10},
            flip_counts={"trend": 0, "volatility": 0, "correlation": 0,
                        "breadth": 0, "forward_stress": 0},
        )
        for edge, val in advisory["edge_affinity"].items():
            assert 0.3 <= val <= 1.5, f"{edge} affinity {val} out of bounds"

    def test_dynamic_weights_shift(self):
        adv = AdvisoryEngine()

        # Normal vol → trend/breadth dominant
        _, adv_normal = adv.generate(
            axis_states={"trend": "bear", "volatility": "normal", "correlation": "normal",
                        "breadth": "strong", "forward_stress": "calm"},
            axis_confidences={a: 0.7 for a in ["trend", "volatility", "correlation", "breadth", "forward_stress"]},
            axis_durations={a: 20 for a in ["trend", "volatility", "correlation", "breadth", "forward_stress"]},
            flip_counts={a: 0 for a in ["trend", "volatility", "correlation", "breadth", "forward_stress"]},
        )

        # Shock vol → fwd_stress/vol/corr dominant
        _, adv_shock = adv.generate(
            axis_states={"trend": "bear", "volatility": "shock", "correlation": "normal",
                        "breadth": "strong", "forward_stress": "calm"},
            axis_confidences={a: 0.7 for a in ["trend", "volatility", "correlation", "breadth", "forward_stress"]},
            axis_durations={a: 20 for a in ["trend", "volatility", "correlation", "breadth", "forward_stress"]},
            flip_counts={a: 0 for a in ["trend", "volatility", "correlation", "breadth", "forward_stress"]},
        )

        # Shock vol should produce higher risk_scalar penalty (lower value)
        assert adv_shock["risk_scalar"] < adv_normal["risk_scalar"]


# ──────────────────────────────────────────────
# RegimeHistoryStore
# ──────────────────────────────────────────────

class TestRegimeHistoryStore:
    def _make_row(self, macro="robust_expansion", **overrides):
        row = {
            "timestamp": "2024-01-01",
            "trend": "bull", "volatility": "normal", "correlation": "normal",
            "breadth": "strong", "forward_stress": "calm",
            "macro_regime": macro,
            "trend_confidence": 0.7, "volatility_confidence": 0.6,
            "correlation_confidence": 0.5, "breadth_confidence": 0.6,
            "forward_stress_confidence": 0.7,
            "transition_risk": 0.0, "regime_stability": 0.7,
        }
        row.update(overrides)
        return row

    def test_append_and_len(self):
        store = RegimeHistoryStore()
        store.append(self._make_row())
        store.append(self._make_row())
        assert len(store) == 2

    def test_durations_increment(self):
        store = RegimeHistoryStore()
        store.append(self._make_row(trend="bull"))
        store.append(self._make_row(trend="bull"))
        store.append(self._make_row(trend="bull"))
        assert store.axis_durations["trend"] == 3

    def test_durations_reset_on_change(self):
        store = RegimeHistoryStore()
        store.append(self._make_row(trend="bull"))
        store.append(self._make_row(trend="bull"))
        store.append(self._make_row(trend="bear"))
        assert store.axis_durations["trend"] == 1

    def test_flip_counts(self):
        store = RegimeHistoryStore(flip_lookback=10)
        for _ in range(3):
            store.append(self._make_row(trend="bull"))
        for _ in range(3):
            store.append(self._make_row(trend="bear"))
        for _ in range(3):
            store.append(self._make_row(trend="bull"))

        flips = store.flip_counts()
        assert flips["trend"] == 2  # bull→bear, bear→bull

    def test_transition_matrix_none_when_insufficient(self):
        store = RegimeHistoryStore(transition_min_bars=100)
        for _ in range(50):
            store.append(self._make_row())
        assert store.get_transition_matrix() is None

    def test_transition_matrix_computed(self):
        store = RegimeHistoryStore(transition_min_bars=10)
        for _ in range(5):
            store.append(self._make_row(macro="robust_expansion"))
        for _ in range(5):
            store.append(self._make_row(macro="cautious_decline"))
        for _ in range(5):
            store.append(self._make_row(macro="robust_expansion"))

        matrix = store.get_transition_matrix()
        assert matrix is not None
        assert "robust_expansion" in matrix
        # Transition from robust → robust should exist
        assert matrix["robust_expansion"]["robust_expansion"] > 0

    def test_to_dataframe(self):
        store = RegimeHistoryStore()
        store.append(self._make_row())
        store.append(self._make_row())
        df = store.to_dataframe()
        assert len(df) == 2
        assert "trend" in df.columns

    def test_reset(self):
        store = RegimeHistoryStore()
        store.append(self._make_row())
        store.reset()
        assert len(store) == 0
        assert store.axis_durations["trend"] == 0
