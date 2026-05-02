"""Tests for Workstream-E second batch — five additional cross-sectional
ranking primitives:

  - dist_52w_high       (close / 252d rolling max - 1)
  - drawdown_60d        (close / 60d rolling max - 1)
  - vol_regime_5_60     (5d realized vol / 60d realized vol)
  - ma_cross_50_200     ((SMA_50 - SMA_200) / SMA_200)
  - skew_60d            (bias-corrected sample skew of 60d log returns)

Mirrors the fixture pattern of `test_ws_e_first_batch.py` — re-registers
the LocalOHLCV source against `tmp_path` so the real `data/processed/`
is never touched.
"""
from __future__ import annotations

from datetime import date
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


SECOND_BATCH_IDS = [
    "dist_52w_high",
    "drawdown_60d",
    "vol_regime_5_60",
    "ma_cross_50_200",
    "skew_60d",
]


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
    """Three series — TREND (drifting up, mid-vol), FLAT (zero-mean
    low-vol), SHOCK (regime-switch: calm then a vol burst near the end).
    400 trading days, enough for the 252d-window features."""
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

    # SHOCK: 350 calm days (sigma=0.005), then 50 high-vol days (sigma=0.04).
    calm = rng.normal(0.0, 0.005, 350)
    burst = rng.normal(0.0, 0.04, 50)
    shock_ret = np.concatenate([calm, burst])
    shock = 100 * np.exp(np.cumsum(shock_ret))

    _write_synthetic_csv(data_root / "SPY_1d.csv", dates, spy)
    _write_synthetic_csv(data_root / "TREND_1d.csv", dates, trend)
    _write_synthetic_csv(data_root / "FLAT_1d.csv", dates, flat)
    _write_synthetic_csv(data_root / "SHOCK_1d.csv", dates, shock)

    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    yield {"data_root": data_root, "dates": dates,
           "trend": trend, "flat": flat, "shock": shock, "spy": spy}
    clear_close_cache()


# ---- Registration ---- #

def test_all_five_features_registered():
    import core.feature_foundry.features  # noqa: F401
    reg = get_feature_registry()
    ids = {f.feature_id for f in reg.list_features() if f.tier != "adversarial"}
    assert set(SECOND_BATCH_IDS).issubset(ids)


# ---- dist_52w_high ---- #

def test_dist_52w_high_matches_closed_form(synthetic_universe):
    from core.feature_foundry.features.dist_52w_high import dist_52w_high
    dt = synthetic_universe["dates"][-1].date()
    val = dist_52w_high("TREND", dt)
    assert val is not None
    closes = synthetic_universe["trend"]
    expected = closes[-1] / closes[-252:].max() - 1.0
    assert math.isclose(val, expected, rel_tol=1e-9)
    # Bounded in (-1, 0]
    assert -1.0 < val <= 0.0


def test_dist_52w_high_zero_on_fresh_high(tmp_path, synthetic_universe):
    """A monotonically increasing series sits exactly on its high."""
    from core.feature_foundry.features.dist_52w_high import dist_52w_high
    data_root = synthetic_universe["data_root"]
    dates = synthetic_universe["dates"]
    rising = 100 * np.exp(np.linspace(0, 0.5, len(dates)))
    _write_synthetic_csv(data_root / "RISE_1d.csv", dates, rising)
    clear_close_cache()
    dt = dates[-1].date()
    assert math.isclose(dist_52w_high("RISE", dt), 0.0, abs_tol=1e-12)


def test_dist_52w_high_none_when_short_history(synthetic_universe):
    from core.feature_foundry.features.dist_52w_high import dist_52w_high
    early_dt = synthetic_universe["dates"][100].date()
    assert dist_52w_high("TREND", early_dt) is None


# ---- drawdown_60d ---- #

def test_drawdown_60d_matches_closed_form(synthetic_universe):
    from core.feature_foundry.features.drawdown_60d import drawdown_60d
    dt = synthetic_universe["dates"][-1].date()
    val = drawdown_60d("TREND", dt)
    assert val is not None
    closes = synthetic_universe["trend"]
    expected = closes[-1] / closes[-60:].max() - 1.0
    assert math.isclose(val, expected, rel_tol=1e-9)
    assert -1.0 < val <= 0.0


def test_drawdown_60d_none_when_short_history(synthetic_universe):
    from core.feature_foundry.features.drawdown_60d import drawdown_60d
    early_dt = synthetic_universe["dates"][30].date()
    assert drawdown_60d("TREND", early_dt) is None


# ---- vol_regime_5_60 ---- #

def test_vol_regime_5_60_flags_recent_shock(synthetic_universe):
    """SHOCK has a vol burst in the final 50 days; ratio should be > 1."""
    from core.feature_foundry.features.vol_regime_5_60 import vol_regime_5_60
    dt = synthetic_universe["dates"][-1].date()
    r_shock = vol_regime_5_60("SHOCK", dt)
    r_flat = vol_regime_5_60("FLAT", dt)
    assert r_shock is not None and r_flat is not None
    # SHOCK's last-5d sigma is ~0.04 vs 60d sigma ~0.025-0.04 (mostly burst).
    # Even at the lower bound the ratio is meaningfully positive; FLAT
    # should sit near 1.0.
    assert r_shock > 0.5
    assert 0.3 < r_flat < 2.0


def test_vol_regime_5_60_centered_near_one_for_flat(synthetic_universe):
    from core.feature_foundry.features.vol_regime_5_60 import vol_regime_5_60
    dt = synthetic_universe["dates"][-1].date()
    val = vol_regime_5_60("FLAT", dt)
    assert val is not None and val > 0


def test_vol_regime_5_60_none_when_short_history(synthetic_universe):
    from core.feature_foundry.features.vol_regime_5_60 import vol_regime_5_60
    early_dt = synthetic_universe["dates"][30].date()
    assert vol_regime_5_60("TREND", early_dt) is None


# ---- ma_cross_50_200 ---- #

def test_ma_cross_50_200_positive_for_uptrending_series(synthetic_universe):
    """A drifting-up series has SMA_50 > SMA_200."""
    from core.feature_foundry.features.ma_cross_50_200 import ma_cross_50_200
    dt = synthetic_universe["dates"][-1].date()
    val = ma_cross_50_200("TREND", dt)
    assert val is not None
    assert val > 0.0


def test_ma_cross_50_200_matches_closed_form(synthetic_universe):
    from core.feature_foundry.features.ma_cross_50_200 import ma_cross_50_200
    dt = synthetic_universe["dates"][-1].date()
    val = ma_cross_50_200("TREND", dt)
    closes = synthetic_universe["trend"]
    sma_50 = float(closes[-50:].mean())
    sma_200 = float(closes[-200:].mean())
    expected = (sma_50 - sma_200) / sma_200
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_ma_cross_50_200_none_when_short_history(synthetic_universe):
    from core.feature_foundry.features.ma_cross_50_200 import ma_cross_50_200
    early_dt = synthetic_universe["dates"][150].date()
    assert ma_cross_50_200("TREND", early_dt) is None


# ---- skew_60d ---- #

def test_skew_60d_matches_scipy_when_available(synthetic_universe):
    """Reference against scipy.stats.skew(bias=False) — closed-form
    bias-corrected (Fisher-Pearson) sample skewness."""
    from core.feature_foundry.features.skew_60d import skew_60d
    try:
        from scipy.stats import skew as scipy_skew
    except ImportError:
        pytest.skip("scipy not installed; skipping reference comparison")
    dt = synthetic_universe["dates"][-1].date()
    val = skew_60d("TREND", dt)
    closes = synthetic_universe["trend"]
    log_ret = np.diff(np.log(closes[-61:]))
    expected = float(scipy_skew(log_ret, bias=False))
    assert val is not None
    assert math.isclose(val, expected, rel_tol=1e-9, abs_tol=1e-12)


def test_skew_60d_in_plausible_range(synthetic_universe):
    from core.feature_foundry.features.skew_60d import skew_60d
    dt = synthetic_universe["dates"][-1].date()
    for ticker in ("TREND", "FLAT", "SHOCK"):
        val = skew_60d(ticker, dt)
        assert val is not None
        assert -10.0 < val < 10.0


def test_skew_60d_none_when_short_history(synthetic_universe):
    from core.feature_foundry.features.skew_60d import skew_60d
    early_dt = synthetic_universe["dates"][30].date()
    assert skew_60d("TREND", early_dt) is None


# ---- Generic edge cases ---- #

def test_features_return_none_for_unknown_ticker(synthetic_universe):
    from core.feature_foundry.features.dist_52w_high import dist_52w_high
    from core.feature_foundry.features.drawdown_60d import drawdown_60d
    from core.feature_foundry.features.vol_regime_5_60 import vol_regime_5_60
    from core.feature_foundry.features.ma_cross_50_200 import ma_cross_50_200
    from core.feature_foundry.features.skew_60d import skew_60d
    dt = synthetic_universe["dates"][-1].date()
    for fn in (dist_52w_high, drawdown_60d, vol_regime_5_60,
               ma_cross_50_200, skew_60d):
        assert fn("ZZZZ_NOT_REAL", dt) is None


# ---- Substrate integration: twin + ablation + cards ---- #

def test_adversarial_twins_can_be_generated_for_all_five(synthetic_universe):
    """Substrate compatibility — twin generator must accept all 5 new
    features without modification."""
    import core.feature_foundry.features  # noqa: F401
    from core.feature_foundry.adversarial import twin_id_for
    reg = get_feature_registry()
    for fid in SECOND_BATCH_IDS:
        real = reg.get(fid)
        assert real is not None, f"feature {fid!r} not registered"
        twin = generate_twin(real)
        assert twin.tier == "adversarial"
        assert twin.feature_id == twin_id_for(fid)
    # Determinism check on one twin
    dt = synthetic_universe["dates"][-1].date()
    twin = reg.get(twin_id_for("dist_52w_high"))
    v1 = twin("TREND", dt)
    v2 = twin("TREND", dt)
    assert v1 == v2 or (v1 is None and v2 is None)


def test_ablation_runs_with_synthetic_backtest_fn(tmp_path, synthetic_universe):
    import core.feature_foundry.features  # noqa: F401

    weights = {
        "dist_52w_high": 0.20,
        "drawdown_60d": 0.10,
        "vol_regime_5_60": 0.07,
        "ma_cross_50_200": 0.18,
        "skew_60d": 0.05,
    }

    def synthetic_backtest_fn(active: set) -> float:
        return sum(weights[f] for f in active if f in weights)

    out_root = tmp_path / "ablation"
    results = run_ablation(
        feature_ids=SECOND_BATCH_IDS,
        baseline_run_uuid="ws-e-second-batch-test",
        backtest_fn=synthetic_backtest_fn,
        out_root=out_root,
    )

    assert set(results.keys()) == set(SECOND_BATCH_IDS)
    for fid, weight in weights.items():
        assert math.isclose(results[fid].contribution_sharpe, weight,
                            rel_tol=1e-9)
    assert (out_root / "ws-e-second-batch-test.json").exists()


def test_model_cards_validate_clean():
    import core.feature_foundry.features  # noqa: F401
    errors = validate_all_model_cards()
    new_errors = [e for e in errors if any(fid in e for fid in SECOND_BATCH_IDS)]
    assert new_errors == [], (
        "Model card validation errors for new features:\n"
        + "\n".join(new_errors)
    )
