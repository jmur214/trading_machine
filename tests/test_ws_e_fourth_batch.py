"""Tests for Workstream-E fourth batch — five regime / trend / range /
seasonality primitives:

  - dispersion_60d            (cross-sectional std of 60d returns)
  - correlation_average_60d   (avg pairwise corr across universe)
  - moving_avg_distance_50d   (log distance from 50d MA)
  - high_minus_low_60d        (60d Hi-Lo / mean, range vol)
  - weekday_dummy             (calendar weekday 1..5)

Same synthetic-fixture pattern as prior batches — re-registers
LocalOHLCV against `tmp_path` so the real `data/` directory is never
read.
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
from core.feature_foundry.features.dispersion_60d import clear_dispersion_cache
from core.feature_foundry.features.correlation_average_60d import (
    clear_correlation_cache,
)


FOURTH_BATCH_IDS = [
    "dispersion_60d",
    "correlation_average_60d",
    "moving_avg_distance_50d",
    "high_minus_low_60d",
    "weekday_dummy",
]


@pytest.fixture(autouse=True)
def _ensure_fourth_batch_registered():
    import importlib
    from core.feature_foundry.features import (
        dispersion_60d, correlation_average_60d, moving_avg_distance_50d,
        high_minus_low_60d, weekday_dummy,
    )
    reg = get_feature_registry()
    registered_ids = {f.feature_id for f in reg.list_features()}
    for mod, fid in (
        (dispersion_60d, "dispersion_60d"),
        (correlation_average_60d, "correlation_average_60d"),
        (moving_avg_distance_50d, "moving_avg_distance_50d"),
        (high_minus_low_60d, "high_minus_low_60d"),
        (weekday_dummy, "weekday_dummy"),
    ):
        if fid not in registered_ids:
            importlib.reload(mod)
    clear_dispersion_cache()
    clear_correlation_cache()
    yield
    clear_dispersion_cache()
    clear_correlation_cache()


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
def universe_six(tmp_path):
    """Six tickers, 200 trading days each, deterministic seed. Mix of
    drifting and flat names so dispersion / correlation are well-defined
    and non-degenerate."""
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=200)
    rng = np.random.default_rng(11)
    series = {}
    drifts = [0.0002, 0.0006, -0.0001, 0.0003, 0.0009, 0.0]
    for i, drift in enumerate(drifts):
        ret = rng.normal(drift, 0.01, len(dates))
        s = 100 * np.exp(np.cumsum(ret))
        ticker = f"T{i}"
        series[ticker] = s
        _write_synthetic_csv(data_root / f"{ticker}_1d.csv", dates, s)
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    yield {"data_root": data_root, "dates": dates, "series": series}
    clear_close_cache()


@pytest.fixture
def universe_two_tickers(tmp_path):
    """Only 2 tickers with sufficient history — too few for the cross-
    sectional features (need >=5 for dispersion, >=3 for correlation)."""
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=200)
    closes = np.linspace(100, 120, len(dates))
    _write_synthetic_csv(data_root / "AA_1d.csv", dates, closes)
    _write_synthetic_csv(data_root / "BB_1d.csv", dates, closes * 1.02)
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    yield {"data_root": data_root, "dates": dates}
    clear_close_cache()


# ---- Registration ---- #

def test_all_five_features_registered():
    import core.feature_foundry.features  # noqa: F401
    reg = get_feature_registry()
    ids = {f.feature_id for f in reg.list_features() if f.tier != "adversarial"}
    assert set(FOURTH_BATCH_IDS).issubset(ids)


# ---- dispersion_60d ---- #

def test_dispersion_matches_closed_form(universe_six):
    from core.feature_foundry.features.dispersion_60d import dispersion_60d
    dt = universe_six["dates"][-1].date()
    val = dispersion_60d("T0", dt)
    assert val is not None
    rets = []
    for s in universe_six["series"].values():
        rets.append(s[-1] / s[-61] - 1.0)
    expected = float(np.std(np.asarray(rets), ddof=1))
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_dispersion_is_ticker_independent(universe_six):
    """Same value for every ticker on the same date."""
    from core.feature_foundry.features.dispersion_60d import dispersion_60d
    dt = universe_six["dates"][-1].date()
    vals = {t: dispersion_60d(t, dt) for t in universe_six["series"]}
    unique = {v for v in vals.values() if v is not None}
    assert len(unique) == 1


def test_dispersion_none_when_too_few_tickers(universe_two_tickers):
    from core.feature_foundry.features.dispersion_60d import dispersion_60d
    dt = universe_two_tickers["dates"][-1].date()
    assert dispersion_60d("AA", dt) is None


def test_dispersion_none_when_short_history(tmp_path):
    """Universe with only 30 days — under the 61-close requirement."""
    from core.feature_foundry.features.dispersion_60d import dispersion_60d
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=30)
    for t in ("A", "B", "C", "D", "E", "F"):
        _write_synthetic_csv(
            data_root / f"{t}_1d.csv", dates,
            np.linspace(100, 110, len(dates)),
        )
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    clear_dispersion_cache()
    try:
        assert dispersion_60d("A", dates[-1].date()) is None
    finally:
        clear_close_cache()
        clear_dispersion_cache()


# ---- correlation_average_60d ---- #

def test_correlation_average_in_unit_interval(universe_six):
    """Mean of correlation coefficients must be in [-1, 1]."""
    from core.feature_foundry.features.correlation_average_60d import (
        correlation_average_60d,
    )
    dt = universe_six["dates"][-1].date()
    val = correlation_average_60d("T0", dt)
    assert val is not None
    assert -1.0 <= val <= 1.0


def test_correlation_average_ticker_independent(universe_six):
    from core.feature_foundry.features.correlation_average_60d import (
        correlation_average_60d,
    )
    dt = universe_six["dates"][-1].date()
    vals = {t: correlation_average_60d(t, dt) for t in universe_six["series"]}
    unique = {v for v in vals.values() if v is not None}
    assert len(unique) == 1


def test_correlation_average_perfect_when_all_identical(tmp_path):
    """If all tickers carry identical close series, mean correlation is 1."""
    from core.feature_foundry.features.correlation_average_60d import (
        correlation_average_60d,
    )
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=120)
    rng = np.random.default_rng(0)
    closes = 100 * np.exp(np.cumsum(rng.normal(0.0005, 0.01, len(dates))))
    for t in ("A", "B", "C", "D"):
        _write_synthetic_csv(data_root / f"{t}_1d.csv", dates, closes)
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    clear_correlation_cache()
    try:
        val = correlation_average_60d("A", dates[-1].date())
        assert val is not None
        assert math.isclose(val, 1.0, abs_tol=1e-9)
    finally:
        clear_close_cache()
        clear_correlation_cache()


def test_correlation_average_none_when_too_few_tickers(universe_two_tickers):
    from core.feature_foundry.features.correlation_average_60d import (
        correlation_average_60d,
    )
    dt = universe_two_tickers["dates"][-1].date()
    assert correlation_average_60d("AA", dt) is None


# ---- moving_avg_distance_50d ---- #

def test_moving_avg_distance_zero_on_flat_price(tmp_path):
    """Constant price → distance from 50d MA is exactly 0."""
    from core.feature_foundry.features.moving_avg_distance_50d import (
        moving_avg_distance_50d,
    )
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=80)
    closes = np.full(len(dates), 100.0)
    _write_synthetic_csv(data_root / "FLAT_1d.csv", dates, closes)
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    try:
        val = moving_avg_distance_50d("FLAT", dates[-1].date())
        assert val is not None
        assert math.isclose(val, 0.0, abs_tol=1e-12)
    finally:
        clear_close_cache()


def test_moving_avg_distance_positive_on_uptrend(tmp_path):
    """Monotonically rising series — close is always above its 50d MA."""
    from core.feature_foundry.features.moving_avg_distance_50d import (
        moving_avg_distance_50d,
    )
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=80)
    closes = np.linspace(100.0, 200.0, len(dates))
    _write_synthetic_csv(data_root / "UP_1d.csv", dates, closes)
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    try:
        val = moving_avg_distance_50d("UP", dates[-1].date())
        assert val is not None
        assert val > 0
    finally:
        clear_close_cache()


def test_moving_avg_distance_matches_closed_form(universe_six):
    from core.feature_foundry.features.moving_avg_distance_50d import (
        moving_avg_distance_50d,
    )
    dt = universe_six["dates"][-1].date()
    val = moving_avg_distance_50d("T0", dt)
    assert val is not None
    s = universe_six["series"]["T0"]
    expected = math.log(s[-1] / s[-50:].mean())
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_moving_avg_distance_none_when_short_history(tmp_path):
    from core.feature_foundry.features.moving_avg_distance_50d import (
        moving_avg_distance_50d,
    )
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=30)
    _write_synthetic_csv(
        data_root / "X_1d.csv", dates, np.linspace(100, 110, len(dates)),
    )
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    try:
        assert moving_avg_distance_50d("X", dates[-1].date()) is None
    finally:
        clear_close_cache()


# ---- high_minus_low_60d ---- #

def test_high_minus_low_zero_on_flat(tmp_path):
    """Constant price → range/mean is 0."""
    from core.feature_foundry.features.high_minus_low_60d import high_minus_low_60d
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=80)
    closes = np.full(len(dates), 50.0)
    _write_synthetic_csv(data_root / "FLAT_1d.csv", dates, closes)
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    try:
        val = high_minus_low_60d("FLAT", dates[-1].date())
        assert val is not None
        assert math.isclose(val, 0.0, abs_tol=1e-12)
    finally:
        clear_close_cache()


def test_high_minus_low_matches_closed_form(universe_six):
    from core.feature_foundry.features.high_minus_low_60d import high_minus_low_60d
    dt = universe_six["dates"][-1].date()
    val = high_minus_low_60d("T0", dt)
    assert val is not None
    window = universe_six["series"]["T0"][-60:]
    expected = (window.max() - window.min()) / window.mean()
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_high_minus_low_non_negative_across_universe(universe_six):
    from core.feature_foundry.features.high_minus_low_60d import high_minus_low_60d
    dt = universe_six["dates"][-1].date()
    for t in universe_six["series"]:
        val = high_minus_low_60d(t, dt)
        assert val is not None and val >= 0.0


def test_high_minus_low_none_when_short_history(tmp_path):
    from core.feature_foundry.features.high_minus_low_60d import high_minus_low_60d
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=30)
    _write_synthetic_csv(
        data_root / "X_1d.csv", dates, np.linspace(100, 110, len(dates)),
    )
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    try:
        assert high_minus_low_60d("X", dates[-1].date()) is None
    finally:
        clear_close_cache()


# ---- weekday_dummy ---- #

def test_weekday_dummy_monday_through_friday():
    from core.feature_foundry.features.weekday_dummy import weekday_dummy
    # 2025-06-02 is a Monday.
    expected = {
        date(2025, 6, 2): 1.0,
        date(2025, 6, 3): 2.0,
        date(2025, 6, 4): 3.0,
        date(2025, 6, 5): 4.0,
        date(2025, 6, 6): 5.0,
    }
    for d, want in expected.items():
        assert weekday_dummy("AAPL", d) == want


def test_weekday_dummy_weekend_returns_none():
    from core.feature_foundry.features.weekday_dummy import weekday_dummy
    # 2025-06-07 is Saturday, 2025-06-08 is Sunday.
    assert weekday_dummy("AAPL", date(2025, 6, 7)) is None
    assert weekday_dummy("AAPL", date(2025, 6, 8)) is None


def test_weekday_dummy_ticker_independent():
    from core.feature_foundry.features.weekday_dummy import weekday_dummy
    d = date(2025, 6, 4)  # Wed
    for t in ("AAPL", "JPM", "ZZZZ"):
        assert weekday_dummy(t, d) == 3.0


# ---- Substrate integration: twin + ablation + cards ---- #

def test_adversarial_twins_can_be_generated_for_all_five(universe_six):
    """Substrate compatibility — twin generator must accept all 5 new
    features without modification."""
    import core.feature_foundry.features  # noqa: F401
    from core.feature_foundry.adversarial import twin_id_for
    reg = get_feature_registry()
    for fid in FOURTH_BATCH_IDS:
        real = reg.get(fid)
        assert real is not None, f"feature {fid!r} not registered"
        twin = generate_twin(real)
        assert twin.tier == "adversarial"
        assert twin.feature_id == twin_id_for(fid)


def test_twin_determinism_for_calendar_feature():
    """weekday_dummy is pure-calendar — twin must still be deterministic
    across calls."""
    import core.feature_foundry.features  # noqa: F401
    from core.feature_foundry.adversarial import twin_id_for
    reg = get_feature_registry()
    real = reg.get("weekday_dummy")
    if reg.get(twin_id_for("weekday_dummy")) is None:
        generate_twin(real)
    twin = reg.get(twin_id_for("weekday_dummy"))
    d = date(2024, 6, 19)  # Wed
    v1 = twin("AAPL", d)
    v2 = twin("AAPL", d)
    assert v1 == v2


def test_ablation_runs_with_synthetic_backtest_fn(tmp_path):
    """Synthetic LOO ablation — verifies the 5 features integrate with
    the runner without modification."""
    import core.feature_foundry.features  # noqa: F401

    weights = {
        "dispersion_60d":            0.05,
        "correlation_average_60d":   0.07,
        "moving_avg_distance_50d":   0.03,
        "high_minus_low_60d":        0.04,
        "weekday_dummy":             0.01,
    }

    def synthetic_backtest_fn(active: set) -> float:
        return sum(weights[f] for f in active if f in weights)

    out_root = tmp_path / "ablation"
    results = run_ablation(
        feature_ids=FOURTH_BATCH_IDS,
        baseline_run_uuid="ws-e-fourth-batch-test",
        backtest_fn=synthetic_backtest_fn,
        out_root=out_root,
    )

    assert set(results.keys()) == set(FOURTH_BATCH_IDS)
    for fid, weight in weights.items():
        assert math.isclose(results[fid].contribution_sharpe, weight,
                            rel_tol=1e-9)
    assert (out_root / "ws-e-fourth-batch-test.json").exists()


def test_model_cards_validate_clean():
    import core.feature_foundry.features  # noqa: F401
    errors = validate_all_model_cards()
    new_errors = [e for e in errors if any(fid in e for fid in FOURTH_BATCH_IDS)]
    assert new_errors == [], (
        "Model card validation errors for new features:\n"
        + "\n".join(new_errors)
    )
