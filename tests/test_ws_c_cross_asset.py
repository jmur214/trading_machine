"""Tests for the three Workstream-C cross-asset Foundry features:

  - hyg_lqd_spread   (HY-IG OAS spread 60d z-score; substitute for HYG/LQD ETF ratio)
  - dxy_change_20d   (DTWEXBGS broad USD index 20d % change)
  - vvix_or_proxy    (30d realized vol of VIXCLS; substitute for CBOE VVIX)

The 2-of-3 cross-asset confirmation gate that originally consumed these
features was archived 2026-05-06 (TPR=0% on -5% drawdowns over 1086 days;
falsified empirically). The features themselves remain — VVIX-proxy was
the lone salvageable signal (AUC 0.64) per the regime-validation work —
and are still independently testable here.

Same synthetic-fixture pattern as `test_ws_e_third_batch.py` — re-registers
source plugins against `tmp_path` so the real `data/` directory is never
touched. Re-import autouse fixture rebinds the feature modules in case
any earlier test cleared the registry.
"""
from __future__ import annotations

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
from core.feature_foundry.sources.fred_macro import (
    FREDMacro,
    clear_series_cache,
)


WS_C_FEATURE_IDS = [
    "hyg_lqd_spread",
    "dxy_change_20d",
    "vvix_or_proxy",
]


@pytest.fixture(autouse=True)
def _ensure_ws_c_registered():
    import importlib
    from core.feature_foundry.features import (
        hyg_lqd_spread, dxy_change_20d, vvix_or_proxy,
    )
    reg = get_feature_registry()
    registered_ids = {f.feature_id for f in reg.list_features()}
    for mod, fid in (
        (hyg_lqd_spread, "hyg_lqd_spread"),
        (dxy_change_20d, "dxy_change_20d"),
        (vvix_or_proxy, "vvix_or_proxy"),
    ):
        if fid not in registered_ids:
            importlib.reload(mod)
    yield


@pytest.fixture
def credit_universe(tmp_path):
    """Synthetic BAML HY/IG OAS series with deterministic spread so the
    60d z-score has a known sign on the last bar.

    HY widens steadily, IG holds flat → spread (HY - IG) trends UP, so
    the current value is well above its 60d mean → positive z-score.
    """
    data_root = tmp_path / "macro_credit"
    data_root.mkdir(exist_ok=True)

    dates = pd.bdate_range(start="2024-01-02", periods=100)
    # HY OAS rises 3.0 -> 5.0 over the window; IG holds at 0.8.
    hy = np.linspace(3.0, 5.0, len(dates))
    ig = np.full(len(dates), 0.8)
    pd.DataFrame({"value": hy},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "BAMLH0A0HYM2.parquet")
    pd.DataFrame({"value": ig},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "BAMLC0A0CM.parquet")

    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    yield {"data_root": data_root, "dates": dates, "hy": hy, "ig": ig}
    clear_series_cache()


@pytest.fixture
def dxy_universe(tmp_path):
    """Synthetic DTWEXBGS series with deterministic 20d ramp.

    Linear 100 -> 110 over 30 bdays → 20d pct change at the end is
    fully determined by the ramp endpoints.
    """
    data_root = tmp_path / "macro_dxy"
    data_root.mkdir(exist_ok=True)
    dates = pd.bdate_range(start="2024-01-02", periods=30)
    dxy = np.linspace(100.0, 110.0, len(dates))
    pd.DataFrame({"value": dxy},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "DTWEXBGS.parquet")

    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    yield {"data_root": data_root, "dates": dates, "dxy": dxy}
    clear_series_cache()


@pytest.fixture
def vix_proxy_universe(tmp_path):
    """Synthetic VIXCLS with controlled vol-of-vol.

    Two regimes spliced together: 50 bdays of low-vol VIX (~16 ± 0.2)
    then 50 bdays of high-vol VIX (~25 ± 5). A 30d window ending in the
    second half should produce a much higher realized-vol-of-VIX than a
    window in the first half.
    """
    data_root = tmp_path / "macro_vix"
    data_root.mkdir(exist_ok=True)

    rng = np.random.default_rng(11)
    dates = pd.bdate_range(start="2024-01-02", periods=100)
    calm = 16.0 + rng.normal(0, 0.2, 50)
    chaotic = 25.0 + rng.normal(0, 5.0, 50)
    vix = np.concatenate([calm, np.maximum(chaotic, 5.0)])

    pd.DataFrame({"value": vix},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "VIXCLS.parquet")

    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    yield {"data_root": data_root, "dates": dates, "vix": vix}
    clear_series_cache()


# ---- Registration ---- #

def test_all_three_features_registered():
    import core.feature_foundry.features  # noqa: F401
    reg = get_feature_registry()
    ids = {f.feature_id for f in reg.list_features() if f.tier != "adversarial"}
    assert set(WS_C_FEATURE_IDS).issubset(ids)


# ---- hyg_lqd_spread ---- #

def test_hyg_lqd_spread_positive_when_widening(credit_universe):
    from core.feature_foundry.features.hyg_lqd_spread import hyg_lqd_spread
    dt = credit_universe["dates"][-1].date()
    val = hyg_lqd_spread("AAPL", dt)
    assert val is not None
    # Spread is monotonically widening → current value above 60d mean → z > 0
    assert val > 0


def test_hyg_lqd_spread_matches_closed_form(credit_universe):
    from core.feature_foundry.features.hyg_lqd_spread import hyg_lqd_spread
    dt = credit_universe["dates"][-1].date()
    val = hyg_lqd_spread("AAPL", dt)
    spread = credit_universe["hy"] - credit_universe["ig"]
    window = spread[-60:]
    expected = (spread[-1] - window.mean()) / window.std(ddof=1)
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_hyg_lqd_spread_ticker_independent(credit_universe):
    from core.feature_foundry.features.hyg_lqd_spread import hyg_lqd_spread
    dt = credit_universe["dates"][-1].date()
    a = hyg_lqd_spread("AAPL", dt)
    b = hyg_lqd_spread("JPM", dt)
    c = hyg_lqd_spread("ZZZZ", dt)
    assert a == b == c


def test_hyg_lqd_spread_none_when_short_history(tmp_path):
    """Series shorter than 61 bars → None (60d window unbuildable)."""
    from core.feature_foundry.features.hyg_lqd_spread import hyg_lqd_spread
    data_root = tmp_path / "macro"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=30)
    pd.DataFrame({"value": np.linspace(3.0, 5.0, 30)},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "BAMLH0A0HYM2.parquet")
    pd.DataFrame({"value": np.full(30, 0.8)},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "BAMLC0A0CM.parquet")
    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    try:
        assert hyg_lqd_spread("AAPL", dates[-1].date()) is None
    finally:
        clear_series_cache()


def test_hyg_lqd_spread_none_when_one_series_missing(tmp_path):
    """Only HY parquet present → None (alignment fails on missing IG)."""
    from core.feature_foundry.features.hyg_lqd_spread import hyg_lqd_spread
    data_root = tmp_path / "macro"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=80)
    pd.DataFrame({"value": np.linspace(3.0, 5.0, 80)},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "BAMLH0A0HYM2.parquet")
    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    try:
        assert hyg_lqd_spread("AAPL", dates[-1].date()) is None
    finally:
        clear_series_cache()


# ---- dxy_change_20d ---- #

def test_dxy_change_20d_matches_closed_form(dxy_universe):
    from core.feature_foundry.features.dxy_change_20d import dxy_change_20d
    dt = dxy_universe["dates"][-1].date()
    val = dxy_change_20d("AAPL", dt)
    assert val is not None
    dxy = dxy_universe["dxy"]
    expected = dxy[-1] / dxy[-21] - 1.0
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_dxy_change_20d_positive_on_rising_ramp(dxy_universe):
    from core.feature_foundry.features.dxy_change_20d import dxy_change_20d
    dt = dxy_universe["dates"][-1].date()
    val = dxy_change_20d("AAPL", dt)
    assert val > 0


def test_dxy_change_20d_ticker_independent(dxy_universe):
    from core.feature_foundry.features.dxy_change_20d import dxy_change_20d
    dt = dxy_universe["dates"][-1].date()
    a = dxy_change_20d("AAPL", dt)
    b = dxy_change_20d("JPM", dt)
    c = dxy_change_20d("ZZZZ", dt)
    assert a is not None and b is not None and c is not None
    assert a == b == c


def test_dxy_change_20d_none_when_short_history(tmp_path):
    """Series with only 5 points — under the 21-point requirement."""
    from core.feature_foundry.features.dxy_change_20d import dxy_change_20d
    data_root = tmp_path / "macro"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=5)
    pd.DataFrame({"value": [100.0, 101.0, 102.0, 103.0, 104.0]},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "DTWEXBGS.parquet")
    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    try:
        assert dxy_change_20d("AAPL", dates[-1].date()) is None
    finally:
        clear_series_cache()


# ---- vvix_or_proxy ---- #

def test_vvix_or_proxy_higher_on_chaotic_window(vix_proxy_universe):
    """Realized vol-of-VIX in the second-half (chaotic) window is much
    higher than in the first-half (calm) window."""
    from core.feature_foundry.features.vvix_or_proxy import vvix_or_proxy
    dates = vix_proxy_universe["dates"]
    dt_calm = dates[40].date()       # window ends inside the calm regime
    dt_chaotic = dates[-1].date()    # window ends inside chaotic regime
    val_calm = vvix_or_proxy("AAPL", dt_calm)
    val_chaotic = vvix_or_proxy("AAPL", dt_chaotic)
    assert val_calm is not None and val_chaotic is not None
    assert val_chaotic > val_calm * 5  # very large gap; calm should be tiny


def test_vvix_or_proxy_ticker_independent(vix_proxy_universe):
    from core.feature_foundry.features.vvix_or_proxy import vvix_or_proxy
    dt = vix_proxy_universe["dates"][-1].date()
    a = vvix_or_proxy("AAPL", dt)
    b = vvix_or_proxy("JPM", dt)
    c = vvix_or_proxy("ZZZZ", dt)
    assert a is not None and b is not None and c is not None
    assert a == b == c


def test_vvix_or_proxy_handles_nan_holes(tmp_path):
    """FRED VIXCLS has a NaN on Christmas / federal holidays. The feature
    must drop those rows rather than letting NaN poison the window."""
    from core.feature_foundry.features.vvix_or_proxy import vvix_or_proxy
    data_root = tmp_path / "macro"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=40)
    vix = np.linspace(15.0, 20.0, 40).astype(float)
    vix[20] = np.nan  # inject a hole mid-window
    pd.DataFrame({"value": vix},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "VIXCLS.parquet")
    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    try:
        # 39 valid bars > 31 required → must produce a finite result
        val = vvix_or_proxy("AAPL", dates[-1].date())
        assert val is not None
        assert math.isfinite(val)
    finally:
        clear_series_cache()


def test_vvix_or_proxy_none_when_short_history(tmp_path):
    """Series with only 5 points — under the 31-point requirement."""
    from core.feature_foundry.features.vvix_or_proxy import vvix_or_proxy
    data_root = tmp_path / "macro"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=5)
    pd.DataFrame({"value": [15.0, 16.0, 17.0, 18.0, 19.0]},
                 index=pd.DatetimeIndex(dates, name="date")
                 ).to_parquet(data_root / "VIXCLS.parquet")
    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    try:
        assert vvix_or_proxy("AAPL", dates[-1].date()) is None
    finally:
        clear_series_cache()


# ---- Substrate integration: twin + ablation + cards ---- #

def test_adversarial_twins_can_be_generated_for_all_three():
    """Twin generator must accept all three new features without
    modification. No data fixtures needed — twin generation is metadata-
    only and doesn't call the underlying function on real data."""
    import core.feature_foundry.features  # noqa: F401
    from core.feature_foundry.adversarial import twin_id_for
    reg = get_feature_registry()
    for fid in WS_C_FEATURE_IDS:
        real = reg.get(fid)
        assert real is not None, f"feature {fid!r} not registered"
        twin = generate_twin(real)
        assert twin.tier == "adversarial"
        assert twin.feature_id == twin_id_for(fid)


def test_ablation_runs_with_synthetic_backtest_fn(tmp_path):
    """Synthetic LOO ablation — verifies the 3 features integrate with
    the runner without modification."""
    import core.feature_foundry.features  # noqa: F401
    import math as _math

    weights = {
        "hyg_lqd_spread": 0.07,
        "dxy_change_20d": 0.04,
        "vvix_or_proxy":  0.05,
    }

    def synthetic_backtest_fn(active: set) -> float:
        return sum(weights[f] for f in active if f in weights)

    out_root = tmp_path / "ablation"
    results = run_ablation(
        feature_ids=WS_C_FEATURE_IDS,
        baseline_run_uuid="ws-c-cross-asset-test",
        backtest_fn=synthetic_backtest_fn,
        out_root=out_root,
    )

    assert set(results.keys()) == set(WS_C_FEATURE_IDS)
    for fid, weight in weights.items():
        assert _math.isclose(results[fid].contribution_sharpe, weight,
                             rel_tol=1e-9)
    assert (out_root / "ws-c-cross-asset-test.json").exists()


def test_model_cards_validate_clean():
    import core.feature_foundry.features  # noqa: F401
    errors = validate_all_model_cards()
    new_errors = [e for e in errors if any(fid in e for fid in WS_C_FEATURE_IDS)]
    assert new_errors == [], (
        "Model card validation errors for new features:\n"
        + "\n".join(new_errors)
    )

