"""Tests for Workstream-C cross-asset confirmation primitives:

  - hyg_lqd_spread   (HY-IG OAS spread 60d z-score; substitute for HYG/LQD ETF ratio)
  - dxy_change_20d   (DTWEXBGS broad USD index 20d % change)
  - vvix_or_proxy    (30d realized vol of VIXCLS; substitute for CBOE VVIX)

Plus the cross-asset confirmation function at
`engines/engine_e_regime/cross_asset_confirm.py`.

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


# ============================================================
# Cross-asset confirmation function
# ============================================================

def test_confirm_stress_transition_with_two_signals():
    """Transition INTO crisis with 2/3 cross-asset signals confirming → confirm=True."""
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "crisis",
        "prev_state": "benign",
        "transition_probs": {"benign": 0.10, "stressed": 0.30, "crisis": 0.60},
        "confidence": 0.6,
    }
    cross_asset_state = {
        "hyg_lqd_z": 1.5,         # confirmed (>1.0)
        "dxy_change_20d": 0.030,  # confirmed (>0.02)
        "vvix_proxy": 0.5,        # NOT confirmed (assume below 90th pct threshold)
    }
    config = {"vvix_proxy_threshold": 1.0}  # explicit threshold above 0.5
    result = confirm_regime_transition(hmm_signal, cross_asset_state, config)
    assert result["confirm"] is True
    assert result["veto_reason"] is None


def test_veto_when_only_one_signal_confirms():
    """Single cross-asset signal → vetoed, returns insufficient-confirmation reason."""
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "crisis",
        "prev_state": "benign",
        "transition_probs": {"benign": 0.10, "stressed": 0.20, "crisis": 0.70},
        "confidence": 0.7,
    }
    cross_asset_state = {
        "hyg_lqd_z": 1.5,         # confirmed
        "dxy_change_20d": 0.005,  # NOT confirmed
        "vvix_proxy": 0.4,        # NOT confirmed
    }
    config = {"vvix_proxy_threshold": 1.0}
    result = confirm_regime_transition(hmm_signal, cross_asset_state, config)
    assert result["confirm"] is False
    assert result["veto_reason"] == "insufficient cross-asset confirmation"


def test_veto_when_zero_signals_confirm():
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "crisis",
        "prev_state": "benign",
        "transition_probs": {"benign": 0.20, "stressed": 0.30, "crisis": 0.50},
        "confidence": 0.5,
    }
    cross_asset_state = {
        "hyg_lqd_z": 0.5,
        "dxy_change_20d": 0.01,
        "vvix_proxy": 0.3,
    }
    config = {"vvix_proxy_threshold": 1.0}
    result = confirm_regime_transition(hmm_signal, cross_asset_state, config)
    assert result["confirm"] is False
    assert result["veto_reason"] == "insufficient cross-asset confirmation"


def test_confirm_when_all_three_signals_fire():
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "crisis",
        "prev_state": "stressed",
        "transition_probs": {"benign": 0.05, "stressed": 0.20, "crisis": 0.75},
        "confidence": 0.75,
    }
    cross_asset_state = {
        "hyg_lqd_z": 2.0,
        "dxy_change_20d": 0.04,
        "vvix_proxy": 1.5,
    }
    config = {"vvix_proxy_threshold": 1.0}
    result = confirm_regime_transition(hmm_signal, cross_asset_state, config)
    assert result["confirm"] is True
    assert result["veto_reason"] is None


def test_no_confirmation_needed_for_exit_to_calm():
    """Transition OUT of stress → benign returns confirm=True without
    requiring cross-asset confirmation. Don't keep the system risk-off
    just because the macro tape is still ugly."""
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "benign",
        "prev_state": "crisis",
        "transition_probs": {"benign": 0.70, "stressed": 0.20, "crisis": 0.10},
        "confidence": 0.7,
    }
    # All cross-asset signals look ugly — but we're transitioning OUT of stress.
    cross_asset_state = {
        "hyg_lqd_z": 2.0,
        "dxy_change_20d": 0.05,
        "vvix_proxy": 2.0,
    }
    result = confirm_regime_transition(hmm_signal, cross_asset_state)
    assert result["confirm"] is True
    assert result["veto_reason"] is None


def test_no_confirmation_needed_for_no_transition():
    """Same state → confirm=True trivially (no transition to confirm)."""
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "stressed",
        "prev_state": "stressed",
        "transition_probs": {"benign": 0.10, "stressed": 0.80, "crisis": 0.10},
        "confidence": 0.8,
    }
    cross_asset_state = {
        "hyg_lqd_z": 0.5,
        "dxy_change_20d": 0.005,
        "vvix_proxy": 0.6,
    }
    result = confirm_regime_transition(hmm_signal, cross_asset_state)
    assert result["confirm"] is True
    assert result["veto_reason"] is None


def test_config_overrides_thresholds():
    """A stricter HYG threshold of 2.0 turns a 1.5 reading from confirmed
    to not-confirmed, flipping a borderline 2/3 case to a veto."""
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "crisis",
        "prev_state": "benign",
        "transition_probs": {"benign": 0.10, "stressed": 0.30, "crisis": 0.60},
        "confidence": 0.6,
    }
    # 1.5 HYG (confirmed under default 1.0) + 0.025 DXY (confirmed under 0.02)
    # + 0.4 VVIX (not confirmed under 1.0) = 2/3 confirms with defaults.
    cross_asset_state = {
        "hyg_lqd_z": 1.5,
        "dxy_change_20d": 0.025,
        "vvix_proxy": 0.4,
    }

    # Default config → 2/3 confirm
    default = confirm_regime_transition(
        hmm_signal, cross_asset_state, {"vvix_proxy_threshold": 1.0}
    )
    assert default["confirm"] is True

    # Stricter HYG threshold → only 1/3 confirm → veto
    strict = confirm_regime_transition(
        hmm_signal, cross_asset_state,
        {"hyg_lqd_z_threshold": 2.0, "vvix_proxy_threshold": 1.0},
    )
    assert strict["confirm"] is False
    assert strict["veto_reason"] == "insufficient cross-asset confirmation"


def test_handles_none_cross_asset_signals():
    """Pre-2023-07 era: hyg_lqd_z is None (BAML data hasn't started yet).
    None counts as 'not confirmed'. With dxy and vvix both confirmed,
    we still have 2/3 → confirm=True."""
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "crisis",
        "prev_state": "stressed",
        "transition_probs": {"benign": 0.10, "stressed": 0.30, "crisis": 0.60},
        "confidence": 0.6,
    }
    cross_asset_state = {
        "hyg_lqd_z": None,         # data gap
        "dxy_change_20d": 0.030,   # confirmed
        "vvix_proxy": 1.5,         # confirmed
    }
    result = confirm_regime_transition(
        hmm_signal, cross_asset_state, {"vvix_proxy_threshold": 1.0},
    )
    assert result["confirm"] is True


def test_all_none_signals_vetoes():
    """All signals None (no cross-asset data at all) → vetoed.
    Belt-and-suspenders: don't grant confirmation when we have nothing
    to confirm with."""
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "crisis",
        "prev_state": "benign",
        "transition_probs": {"benign": 0.10, "stressed": 0.20, "crisis": 0.70},
        "confidence": 0.7,
    }
    cross_asset_state = {
        "hyg_lqd_z": None,
        "dxy_change_20d": None,
        "vvix_proxy": None,
    }
    result = confirm_regime_transition(hmm_signal, cross_asset_state)
    assert result["confirm"] is False
    assert result["veto_reason"] == "insufficient cross-asset confirmation"


def test_confidence_is_propagated():
    """Output `confidence` field reflects the HMM input confidence (we
    don't currently amplify, just pass through with adjustment for the
    veto path so downstream can read a single number)."""
    from engines.engine_e_regime.cross_asset_confirm import (
        confirm_regime_transition,
    )
    hmm_signal = {
        "state": "crisis",
        "prev_state": "benign",
        "transition_probs": {"benign": 0.10, "stressed": 0.20, "crisis": 0.70},
        "confidence": 0.7,
    }
    cross_asset_state = {
        "hyg_lqd_z": 2.0,
        "dxy_change_20d": 0.04,
        "vvix_proxy": 1.5,
    }
    result = confirm_regime_transition(
        hmm_signal, cross_asset_state, {"vvix_proxy_threshold": 1.0},
    )
    assert "confidence" in result
    assert isinstance(result["confidence"], float)
    assert 0.0 <= result["confidence"] <= 1.0
