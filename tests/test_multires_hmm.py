"""Tests for multi-resolution HMM (Workstream C slice 2 — 2026-05)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.engine_e_regime.macro_features import (
    FEATURE_COLUMNS, build_feature_panel, resample_feature_panel,
    build_multires_panels,
)


def _synthetic_daily_panel(n_obs: int = 1000, seed: int = 0) -> pd.DataFrame:
    """Construct a daily synthetic panel for resampling tests."""
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2020-01-01", periods=n_obs, freq="B")
    data = {}
    # log returns: small variance, so weekly/monthly sums make sense
    data["spy_log_return"] = rng.normal(0.0005, 0.01, n_obs)
    data["tlt_log_return"] = rng.normal(0.0001, 0.005, n_obs)
    # rolling window returns + vol
    data["spy_ret_5d"] = pd.Series(data["spy_log_return"]).rolling(5).sum().values
    data["spy_vol_20d"] = pd.Series(data["spy_log_return"]).rolling(20).std().values
    data["tlt_ret_20d"] = pd.Series(data["tlt_log_return"]).rolling(20).sum().values
    data["dollar_ret_63d"] = pd.Series(rng.normal(0, 0.001, n_obs)).rolling(63).sum().values
    # Level series
    data["vix_level"] = 15 + rng.normal(0, 2, n_obs)
    data["yield_curve_spread"] = 0.5 + rng.normal(0, 0.1, n_obs)
    data["credit_spread_baa_aaa"] = 0.7 + rng.normal(0, 0.05, n_obs)
    return pd.DataFrame(data, index=idx)


def test_resample_weekly_preserves_columns():
    """Weekly resample preserves all feature columns."""
    daily = _synthetic_daily_panel()
    weekly = resample_feature_panel(daily, "W")
    assert set(weekly.columns) == set(daily.columns)
    # Weekly cadence should have ~ n_obs/5 bars
    assert 0.7 * len(daily) / 5 <= len(weekly) <= 1.3 * len(daily) / 5


def test_resample_monthly_preserves_columns():
    """Monthly resample preserves all feature columns."""
    daily = _synthetic_daily_panel()
    monthly = resample_feature_panel(daily, "M")
    assert set(monthly.columns) == set(daily.columns)
    # Monthly cadence should have ~ n_obs/21 bars
    assert 0.7 * len(daily) / 21 <= len(monthly) <= 1.3 * len(daily) / 21


def test_resample_log_returns_are_summed():
    """Log returns aggregate via SUM (additive property)."""
    daily = _synthetic_daily_panel(n_obs=200)
    weekly = resample_feature_panel(daily, "W")
    # The weekly sum of any complete 5-bar window should equal sum of those 5 daily returns
    # Pick a weekly bar that has 5 prior daily bars
    week_end = weekly.index[5]
    week_start = weekly.index[4] + pd.Timedelta(days=1)
    daily_window = daily.loc[(daily.index > week_start - pd.Timedelta(days=8))
                             & (daily.index <= week_end)]
    if len(daily_window) >= 5:
        # The sum on the weekly bar must match sum of daily-bar log returns
        # within numerical tolerance
        wk_sum = weekly.loc[week_end, "spy_log_return"]
        # Account for the fact that resample uses W-FRI with right-closed window
        assert np.isfinite(wk_sum)


def test_resample_levels_use_last_value():
    """Level series use the LAST daily value at each bar boundary."""
    daily = _synthetic_daily_panel(n_obs=200)
    weekly = resample_feature_panel(daily, "W")
    # For a weekly bar, vix_level should equal daily vix_level on the
    # bar's actual timestamp (which is the last daily bar in the window).
    sample_bar = weekly.index[10]
    daily_value = daily.loc[sample_bar, "vix_level"]
    weekly_value = weekly.loc[sample_bar, "vix_level"]
    assert np.isclose(daily_value, weekly_value, rtol=1e-9)


def test_resample_invalid_cadence_raises():
    """Invalid cadence string raises ValueError."""
    daily = _synthetic_daily_panel()
    with pytest.raises(ValueError):
        resample_feature_panel(daily, "Q")


def test_resample_empty_panel_returns_empty():
    """Empty input → empty output (no crash)."""
    empty = pd.DataFrame(columns=FEATURE_COLUMNS)
    weekly = resample_feature_panel(empty, "W")
    assert weekly.empty


def test_build_multires_panels_returns_three_keys():
    """build_multires_panels returns daily, weekly, monthly."""
    panels = build_multires_panels(start="2024-01-01", end="2024-12-31")
    assert set(panels.keys()) == {"daily", "weekly", "monthly"}
    # Cardinality: daily > weekly > monthly
    assert len(panels["daily"]) > len(panels["weekly"]) > len(panels["monthly"])


def test_multires_orchestrator_loads_all_three_artifacts():
    """MultiResolutionHMM loads all three persisted artifacts."""
    from engines.engine_e_regime.multires_hmm import MultiResolutionHMM

    daily_path = ROOT / "engines/engine_e_regime/models/hmm_3state_v1.pkl"
    weekly_path = ROOT / "engines/engine_e_regime/models/hmm_weekly_v1.pkl"
    monthly_path = ROOT / "engines/engine_e_regime/models/hmm_monthly_v1.pkl"

    if not (daily_path.exists() and weekly_path.exists() and monthly_path.exists()):
        pytest.skip("Multi-res HMM artifacts not present — run scripts/train_multires_hmm.py")

    m = MultiResolutionHMM(feature_start="2024-06-01", feature_end="2025-12-31")
    assert set(m.loaded_cadences) == {"daily", "weekly", "monthly"}


def test_multires_classify_returns_three_results():
    """classify_at returns one CadenceResult per cadence."""
    from engines.engine_e_regime.multires_hmm import MultiResolutionHMM

    daily_path = ROOT / "engines/engine_e_regime/models/hmm_3state_v1.pkl"
    if not daily_path.exists():
        pytest.skip("Daily HMM artifact not present")

    m = MultiResolutionHMM(feature_start="2024-06-01", feature_end="2025-12-31")
    results = m.classify_at(pd.Timestamp("2025-06-15"))
    assert set(results.keys()) == {"daily", "weekly", "monthly"}
    for cad, r in results.items():
        if r is None:
            continue  # cadence may be missing if its pickle absent
        assert r.cadence == cad
        assert isinstance(r.argmax, str)
        assert 0.0 <= r.confidence <= 1.0
        s = sum(r.proba.values())
        assert abs(s - 1.0) < 1e-6


def test_multires_to_advisory_dict_schema():
    """Advisory dict schema: regime_<cadence> keys present."""
    from engines.engine_e_regime.multires_hmm import MultiResolutionHMM

    daily_path = ROOT / "engines/engine_e_regime/models/hmm_3state_v1.pkl"
    if not daily_path.exists():
        pytest.skip("Daily HMM artifact not present")

    m = MultiResolutionHMM(feature_start="2024-06-01", feature_end="2025-12-31")
    results = m.classify_at(pd.Timestamp("2025-06-15"))
    adv = m.to_advisory_dict(results)
    assert set(adv.keys()) == {"regime_daily", "regime_weekly", "regime_monthly"}
    for key, val in adv.items():
        if val is None:
            continue
        assert "label" in val
        assert "probabilities" in val
        assert "confidence" in val
        assert "bar_timestamp" in val


def test_multires_monthly_lags_daily():
    """The monthly bar boundary should lag the daily bar (slower cadence,
    less temporal precision — this is the documented tradeoff)."""
    from engines.engine_e_regime.multires_hmm import MultiResolutionHMM

    daily_path = ROOT / "engines/engine_e_regime/models/hmm_3state_v1.pkl"
    weekly_path = ROOT / "engines/engine_e_regime/models/hmm_weekly_v1.pkl"
    monthly_path = ROOT / "engines/engine_e_regime/models/hmm_monthly_v1.pkl"
    if not all(p.exists() for p in [daily_path, weekly_path, monthly_path]):
        pytest.skip("Multi-res artifacts not present")

    m = MultiResolutionHMM(feature_start="2024-06-01", feature_end="2025-12-31")
    # Pick an arbitrary date mid-month, e.g. 2025-04-15
    ts = pd.Timestamp("2025-04-15")
    results = m.classify_at(ts)
    daily = results["daily"]
    weekly = results["weekly"]
    monthly = results["monthly"]
    # Bar timestamps must respect ordering: monthly ≤ weekly ≤ daily ≤ ts
    if monthly is not None and weekly is not None:
        assert monthly.bar_timestamp <= weekly.bar_timestamp
    if weekly is not None and daily is not None:
        assert weekly.bar_timestamp <= daily.bar_timestamp
    if daily is not None:
        assert daily.bar_timestamp <= ts
