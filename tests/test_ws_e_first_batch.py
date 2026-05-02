"""Tests for Workstream-E first batch — cross-sectional ranking primitives.

Five features under test:
  - mom_12_1
  - mom_6_1
  - reversal_1m
  - realized_vol_60d
  - beta_252d

Each test runs against synthetic OHLCV CSVs in a tmp dir; the
LocalOHLCV source is re-registered against `tmp_path` per test so the
real `data/processed/` is never read.

Also exercises the substrate's `generate_twin` and `run_ablation`
against the new features to confirm they integrate without
substrate-side changes.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
import sys
import math

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from core.feature_foundry import (
    get_feature_registry,
    get_source_registry,
    generate_twin,
    run_ablation,
    validate_all_model_cards,
)
from core.feature_foundry.sources.local_ohlcv import (
    LocalOHLCV,
    clear_close_cache,
)


def _write_synthetic_csv(path: Path, dates: pd.DatetimeIndex,
                        closes: np.ndarray, volume: float = 1e6) -> None:
    df = pd.DataFrame({
        "Date": dates,
        "Open": closes,
        "High": closes * 1.01,
        "Low": closes * 0.99,
        "Close": closes,
        "Volume": volume,
        "ATR": np.nan,
        "PrevClose": np.concatenate(([np.nan], closes[:-1])),
    })
    df.to_csv(path, index=False)


@pytest.fixture
def synthetic_universe(tmp_path):
    """Two tickers (TREND, FLAT) plus SPY, 400 trading days each."""
    data_root = tmp_path / "processed"
    data_root.mkdir()

    dates = pd.bdate_range(start="2024-01-02", periods=400)
    rng = np.random.default_rng(42)

    spy_ret = rng.normal(0.0004, 0.01, len(dates))
    spy = 100 * np.exp(np.cumsum(spy_ret))

    trend_ret = rng.normal(0.001, 0.012, len(dates))
    trend = 100 * np.exp(np.cumsum(trend_ret))

    flat_ret = rng.normal(0.0, 0.005, len(dates))
    flat = 100 * np.exp(np.cumsum(flat_ret))

    _write_synthetic_csv(data_root / "SPY_1d.csv", dates, spy)
    _write_synthetic_csv(data_root / "TREND_1d.csv", dates, trend)
    _write_synthetic_csv(data_root / "FLAT_1d.csv", dates, flat)

    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    yield {"data_root": data_root, "dates": dates,
           "trend": trend, "flat": flat, "spy": spy}
    clear_close_cache()


# ---- Feature loading ---- #
# Importing the package registers all features; do it once and assert
# that all 5 are present.

def test_all_five_features_registered():
    import core.feature_foundry.features  # noqa: F401  triggers self-register
    reg = get_feature_registry()
    ids = {f.feature_id for f in reg.list_features() if f.tier != "adversarial"}
    expected = {"mom_12_1", "mom_6_1", "reversal_1m",
                "realized_vol_60d", "beta_252d"}
    assert expected.issubset(ids)


# ---- Per-feature value tests ---- #

def test_mom_12_1_returns_close_to_realized_growth(synthetic_universe):
    from core.feature_foundry.features.mom_12_1 import mom_12_1
    dt = synthetic_universe["dates"][-1].date()
    val = mom_12_1("TREND", dt)
    assert val is not None
    closes = synthetic_universe["trend"]
    expected = closes[-21] / closes[-252] - 1.0
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_mom_12_1_none_when_not_enough_history(synthetic_universe):
    from core.feature_foundry.features.mom_12_1 import mom_12_1
    early_dt = synthetic_universe["dates"][100].date()
    assert mom_12_1("TREND", early_dt) is None


def test_mom_6_1_returns_close_to_realized_growth(synthetic_universe):
    from core.feature_foundry.features.mom_6_1 import mom_6_1
    dt = synthetic_universe["dates"][-1].date()
    val = mom_6_1("TREND", dt)
    assert val is not None
    closes = synthetic_universe["trend"]
    expected = closes[-21] / closes[-126] - 1.0
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_reversal_1m_matches_one_month_return(synthetic_universe):
    from core.feature_foundry.features.reversal_1m import reversal_1m
    dt = synthetic_universe["dates"][-1].date()
    val = reversal_1m("TREND", dt)
    assert val is not None
    closes = synthetic_universe["trend"]
    expected = closes[-1] / closes[-22] - 1.0
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_realized_vol_60d_within_expected_range(synthetic_universe):
    from core.feature_foundry.features.realized_vol_60d import realized_vol_60d
    dt = synthetic_universe["dates"][-1].date()
    val_trend = realized_vol_60d("TREND", dt)
    val_flat = realized_vol_60d("FLAT", dt)
    assert val_trend is not None and val_flat is not None
    # FLAT was generated with std=0.005 daily, TREND with 0.012 daily.
    # Annualized: ~0.079 and ~0.190 respectively. FLAT must be lower.
    assert val_flat < val_trend
    assert 0.0 < val_flat < 0.20
    assert 0.10 < val_trend < 0.30


def test_beta_252d_for_spy_returns_none(synthetic_universe):
    from core.feature_foundry.features.beta_252d import beta_252d
    dt = synthetic_universe["dates"][-1].date()
    assert beta_252d("SPY", dt) is None


def test_beta_252d_in_plausible_range(synthetic_universe):
    from core.feature_foundry.features.beta_252d import beta_252d
    dt = synthetic_universe["dates"][-1].date()
    b_trend = beta_252d("TREND", dt)
    b_flat = beta_252d("FLAT", dt)
    assert b_trend is not None and b_flat is not None
    # Synthetic series are independent of SPY, so beta should be near 0
    # but the 252-sample noise gives ±0.5 typical bound.
    assert -1.5 < b_trend < 1.5
    assert -1.5 < b_flat < 1.5


def test_features_return_none_for_unknown_ticker(synthetic_universe):
    from core.feature_foundry.features.mom_12_1 import mom_12_1
    from core.feature_foundry.features.beta_252d import beta_252d
    dt = synthetic_universe["dates"][-1].date()
    assert mom_12_1("ZZZZ_NOT_REAL", dt) is None
    assert beta_252d("ZZZZ_NOT_REAL", dt) is None


# ---- Substrate integration: twin + ablation ---- #

def test_adversarial_twins_can_be_generated_for_all_five(synthetic_universe):
    import core.feature_foundry.features  # noqa: F401
    from core.feature_foundry.adversarial import twin_id_for
    reg = get_feature_registry()
    fids = ["mom_12_1", "mom_6_1", "reversal_1m",
            "realized_vol_60d", "beta_252d"]

    twins = []
    for fid in fids:
        real = reg.get(fid)
        assert real is not None, f"feature {fid!r} not registered"
        twin = generate_twin(real)
        assert twin.tier == "adversarial"
        assert twin.feature_id == twin_id_for(fid)
        twins.append(twin)

    # Twin determinism: regenerating yields same per-(ticker) values.
    dt = synthetic_universe["dates"][-1].date()
    for twin in twins:
        v1 = twin("TREND", dt)
        v2 = twin("TREND", dt)
        assert v1 == v2 or (v1 is None and v2 is None)


def test_ablation_runs_with_synthetic_backtest_fn(tmp_path, synthetic_universe):
    """Substrate integration smoke test — give the ablation runner a
    synthetic linear-contribution backtest_fn over the 5 real features
    and verify the contribution numbers come out as designed."""
    import core.feature_foundry.features  # noqa: F401

    fids = ["mom_12_1", "mom_6_1", "reversal_1m",
            "realized_vol_60d", "beta_252d"]
    # Designed contributions: each feature adds a fixed Sharpe.
    weights = {
        "mom_12_1": 0.30,
        "mom_6_1": 0.10,
        "reversal_1m": 0.05,
        "realized_vol_60d": 0.20,
        "beta_252d": 0.15,
    }

    def synthetic_backtest_fn(active: set) -> float:
        return sum(weights[f] for f in active if f in weights)

    out_root = tmp_path / "ablation"
    results = run_ablation(
        feature_ids=fids,
        baseline_run_uuid="ws-e-first-batch-test",
        backtest_fn=synthetic_backtest_fn,
        out_root=out_root,
    )

    assert set(results.keys()) == set(fids)
    for fid, weight in weights.items():
        assert math.isclose(results[fid].contribution_sharpe, weight,
                            rel_tol=1e-9)

    # Persisted file readable.
    persisted = out_root / "ws-e-first-batch-test.json"
    assert persisted.exists()


def test_model_cards_validate_clean():
    """All 5 features have well-formed cards with matching license."""
    import core.feature_foundry.features  # noqa: F401
    errors = validate_all_model_cards()
    new_feature_errors = [
        e for e in errors
        if any(fid in e for fid in (
            "mom_12_1", "mom_6_1", "reversal_1m",
            "realized_vol_60d", "beta_252d",
        ))
    ]
    assert new_feature_errors == [], (
        f"Model card validation errors for new features:\n"
        + "\n".join(new_feature_errors)
    )
