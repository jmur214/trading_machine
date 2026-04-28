"""
tests/test_discovery_regime_features.py
========================================
Regression tests for FeatureEngineer._compute_regime_features.

The prior code read top-level `regime_meta["correlation"]` which does not exist
on RegimeDetector.detect_regime output (only `correlation_regime["state"]`
exists). Result: Regime_CorrSpike was hardcoded 0 for every TreeScanner hunt,
silently denying the discovery loop a regime feature.
"""
from __future__ import annotations

import os
import sys

import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_d_discovery.feature_engineering import FeatureEngineer


def _bare_df() -> pd.DataFrame:
    return pd.DataFrame({"Close": [100.0, 101.0, 102.0]})


def test_corr_spike_reads_correlation_regime_state():
    fe = FeatureEngineer()
    regime_meta = {
        "trend_regime": {"state": "bull", "confidence": 0.9},
        "volatility_regime": {"state": "normal", "confidence": 0.5},
        "correlation_regime": {"state": "spike", "confidence": 0.8},
    }
    df = fe._compute_regime_features(_bare_df(), regime_meta)
    assert df["Regime_CorrSpike"].iloc[0] == 1


def test_corr_spike_zero_when_correlation_regime_normal():
    fe = FeatureEngineer()
    regime_meta = {
        "correlation_regime": {"state": "normal", "confidence": 0.7},
    }
    df = fe._compute_regime_features(_bare_df(), regime_meta)
    assert df["Regime_CorrSpike"].iloc[0] == 0


def test_corr_spike_fires_on_elevated_state():
    fe = FeatureEngineer()
    regime_meta = {
        "correlation_regime": {"state": "elevated", "confidence": 0.6},
    }
    df = fe._compute_regime_features(_bare_df(), regime_meta)
    assert df["Regime_CorrSpike"].iloc[0] == 1


def test_trend_regime_state_takes_precedence_over_backward_compat_key():
    fe = FeatureEngineer()
    # If both shapes are present, the structured form wins.
    regime_meta = {
        "trend_regime": {"state": "bear", "confidence": 0.8},
        "trend": "bull",  # backward-compat says bull, structured says bear
    }
    df = fe._compute_regime_features(_bare_df(), regime_meta)
    assert df["Regime_Bull"].iloc[0] == 0
    assert df["Regime_Bear"].iloc[0] == 1


def test_falls_back_to_legacy_top_level_keys():
    """Old callers that only pass `regime_meta = {'trend': 'bull', ...}` still work."""
    fe = FeatureEngineer()
    regime_meta = {"trend": "bull", "volatility": "high"}
    df = fe._compute_regime_features(_bare_df(), regime_meta)
    assert df["Regime_Bull"].iloc[0] == 1
    assert df["Regime_VolHigh"].iloc[0] == 1
    # No correlation_regime → CorrSpike defaults to 0
    assert df["Regime_CorrSpike"].iloc[0] == 0


def test_missing_regime_meta_does_not_crash():
    fe = FeatureEngineer()
    df = fe._compute_regime_features(_bare_df(), {})
    assert df["Regime_Bull"].iloc[0] == 0
    assert df["Regime_VolHigh"].iloc[0] == 0
    assert df["Regime_CorrSpike"].iloc[0] == 0
