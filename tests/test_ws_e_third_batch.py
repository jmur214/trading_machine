"""Tests for Workstream-E third batch — five calendar / event-driven /
pairs primitives:

  - days_to_quarter_end       (calendar days to next Mar/Jun/Sep/Dec end)
  - month_of_year_dummy       (calendar month as float 1..12)
  - pair_zscore_60d           (60d z-score of log price ratio for 5 pairs)
  - earnings_proximity_5d     (graded 0..1 score from next earnings date)
  - vix_change_5d             (5-business-day percent change in VIX)

Uses the same synthetic-fixture pattern as the first/second batches —
re-registers source plugins against `tmp_path` so the real `data/`
directory is never touched.
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
from core.feature_foundry.sources.earnings_calendar import (
    EarningsCalendar,
    clear_earnings_cache,
)
from core.feature_foundry.sources.fred_macro import (
    FREDMacro,
    clear_series_cache,
)


THIRD_BATCH_IDS = [
    "days_to_quarter_end",
    "month_of_year_dummy",
    "pair_zscore_60d",
    "earnings_proximity_5d",
    "vix_change_5d",
]


@pytest.fixture(autouse=True)
def _ensure_third_batch_registered():
    import importlib
    from core.feature_foundry.features import (
        days_to_quarter_end, month_of_year_dummy, pair_zscore_60d,
        earnings_proximity_5d, vix_change_5d,
    )
    reg = get_feature_registry()
    registered_ids = {f.feature_id for f in reg.list_features()}
    for mod, fid in (
        (days_to_quarter_end, "days_to_quarter_end"),
        (month_of_year_dummy, "month_of_year_dummy"),
        (pair_zscore_60d, "pair_zscore_60d"),
        (earnings_proximity_5d, "earnings_proximity_5d"),
        (vix_change_5d, "vix_change_5d"),
    ):
        if fid not in registered_ids:
            importlib.reload(mod)
    yield


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
def pair_universe(tmp_path):
    """Two pair-mapped tickers (JPM, BAC) + a non-pair ticker (AAPL).
    JPM drifts up, BAC drifts up faster — log ratio increasingly
    negative (JPM cheap relative to BAC), so z-score should be
    measurably non-zero on the last day."""
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=120)
    rng = np.random.default_rng(7)

    jpm_ret = rng.normal(0.0003, 0.01, len(dates))
    jpm = 100 * np.exp(np.cumsum(jpm_ret))
    bac_ret = rng.normal(0.0009, 0.01, len(dates))   # outperforms JPM
    bac = 100 * np.exp(np.cumsum(bac_ret))
    aapl_ret = rng.normal(0.0005, 0.012, len(dates))
    aapl = 100 * np.exp(np.cumsum(aapl_ret))

    _write_synthetic_csv(data_root / "JPM_1d.csv", dates, jpm)
    _write_synthetic_csv(data_root / "BAC_1d.csv", dates, bac)
    _write_synthetic_csv(data_root / "AAPL_1d.csv", dates, aapl)

    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    yield {"data_root": data_root, "dates": dates,
           "jpm": jpm, "bac": bac, "aapl": aapl}
    clear_close_cache()


@pytest.fixture
def earnings_universe(tmp_path):
    """Synthetic earnings parquet for AAPL with known announcement
    dates so we can verify proximity scoring."""
    data_root = tmp_path / "earnings"
    data_root.mkdir()

    # Announcement dates — known absolute dates we'll probe against
    announcements = pd.to_datetime([
        "2024-04-15", "2024-07-15", "2024-10-15", "2025-01-15",
    ])
    df = pd.DataFrame({
        "symbol": ["AAPL"] * len(announcements),
        "eps_actual": [1.0, 1.1, 1.2, 1.3],
        "eps_estimate": [0.9, 1.0, 1.1, 1.2],
        "eps_surprise_pct": [0.1, 0.1, 0.1, 0.1],
    }, index=announcements)
    df.index.name = "announcement_date"
    df.to_parquet(data_root / "AAPL_calendar.parquet")

    src = EarningsCalendar(data_root=data_root)
    get_source_registry().register(src)
    clear_earnings_cache()
    yield {"data_root": data_root, "announcements": announcements}
    clear_earnings_cache()


@pytest.fixture
def vix_universe(tmp_path):
    """Synthetic VIXCLS series with deterministic level so we can verify
    5-day pct-change calculation."""
    data_root = tmp_path / "macro"
    data_root.mkdir()

    dates = pd.bdate_range(start="2024-01-02", periods=30)
    # Linear ramp 15 -> 30 — 5-day pct change is deterministic
    vix = np.linspace(15.0, 30.0, len(dates))
    df = pd.DataFrame({"value": vix}, index=pd.DatetimeIndex(dates, name="date"))
    df.to_parquet(data_root / "VIXCLS.parquet")

    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    yield {"data_root": data_root, "dates": dates, "vix": vix}
    clear_series_cache()


# ---- Registration ---- #

def test_all_five_features_registered():
    import core.feature_foundry.features  # noqa: F401
    reg = get_feature_registry()
    ids = {f.feature_id for f in reg.list_features() if f.tier != "adversarial"}
    assert set(THIRD_BATCH_IDS).issubset(ids)


# ---- days_to_quarter_end ---- #

def test_days_to_quarter_end_zero_on_quarter_end():
    from core.feature_foundry.features.days_to_quarter_end import days_to_quarter_end
    for d in (date(2025, 3, 31), date(2025, 6, 30),
              date(2025, 9, 30), date(2025, 12, 31)):
        assert days_to_quarter_end("AAPL", d) == 0.0


def test_days_to_quarter_end_decreases_through_quarter():
    from core.feature_foundry.features.days_to_quarter_end import days_to_quarter_end
    # Through Q1 2025 — values must decrease monotonically
    a = days_to_quarter_end("AAPL", date(2025, 1, 1))
    b = days_to_quarter_end("AAPL", date(2025, 2, 15))
    c = days_to_quarter_end("AAPL", date(2025, 3, 30))
    assert a > b > c
    assert a == 89.0  # 2025-01-01 → 2025-03-31 = 89 days
    assert c == 1.0


def test_days_to_quarter_end_resets_after_quarter_end():
    """April 1 → next quarter-end is June 30 = 90 days."""
    from core.feature_foundry.features.days_to_quarter_end import days_to_quarter_end
    val = days_to_quarter_end("AAPL", date(2025, 4, 1))
    assert val == 90.0


def test_days_to_quarter_end_year_boundary():
    """Dec 31 = 0; Jan 1 next year = 89 days."""
    from core.feature_foundry.features.days_to_quarter_end import days_to_quarter_end
    assert days_to_quarter_end("AAPL", date(2025, 12, 31)) == 0.0
    assert days_to_quarter_end("AAPL", date(2026, 1, 1)) == 89.0


# ---- month_of_year_dummy ---- #

def test_month_of_year_dummy_returns_correct_month():
    from core.feature_foundry.features.month_of_year_dummy import month_of_year_dummy
    for m in range(1, 13):
        assert month_of_year_dummy("AAPL", date(2025, m, 15)) == float(m)


def test_month_of_year_dummy_ticker_independent():
    """Same value across tickers on the same date."""
    from core.feature_foundry.features.month_of_year_dummy import month_of_year_dummy
    d = date(2025, 6, 15)
    for t in ("AAPL", "JPM", "ZZZZ"):
        assert month_of_year_dummy(t, d) == 6.0


# ---- pair_zscore_60d ---- #

def test_pair_zscore_returns_none_for_unmapped_ticker(pair_universe):
    from core.feature_foundry.features.pair_zscore_60d import pair_zscore_60d
    dt = pair_universe["dates"][-1].date()
    assert pair_zscore_60d("AAPL", dt) is None
    assert pair_zscore_60d("ZZZZ_NOT_REAL", dt) is None


def test_pair_zscore_matches_closed_form(pair_universe):
    """Manual recomputation of the 60d z-score on the synthetic data."""
    from core.feature_foundry.features.pair_zscore_60d import pair_zscore_60d
    dt = pair_universe["dates"][-1].date()
    val = pair_zscore_60d("JPM", dt)
    assert val is not None
    a = pair_universe["jpm"][-60:]
    b = pair_universe["bac"][-60:]
    ratio = np.log(a) - np.log(b)
    expected = (ratio[-1] - ratio.mean()) / ratio.std(ddof=1)
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_pair_zscore_signs_match_for_both_legs(pair_universe):
    """JPM(self)/BAC(partner) and BAC(self)/JPM(partner) z-scores are
    sign-flipped because log(a/b) = -log(b/a)."""
    from core.feature_foundry.features.pair_zscore_60d import pair_zscore_60d
    dt = pair_universe["dates"][-1].date()
    z_jpm = pair_zscore_60d("JPM", dt)
    z_bac = pair_zscore_60d("BAC", dt)
    assert z_jpm is not None and z_bac is not None
    assert math.isclose(z_jpm, -z_bac, rel_tol=1e-9)


def test_pair_zscore_none_when_short_history(tmp_path):
    """Synthetic universe with only 30 days — under the 60d window."""
    from core.feature_foundry.features.pair_zscore_60d import pair_zscore_60d
    data_root = tmp_path / "processed"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=30)
    closes = np.linspace(100, 110, len(dates))
    _write_synthetic_csv(data_root / "JPM_1d.csv", dates, closes)
    _write_synthetic_csv(data_root / "BAC_1d.csv", dates, closes * 1.01)
    src = LocalOHLCV(data_root=data_root)
    get_source_registry().register(src)
    clear_close_cache()
    try:
        assert pair_zscore_60d("JPM", dates[-1].date()) is None
    finally:
        clear_close_cache()


# ---- earnings_proximity_5d ---- #

def test_earnings_proximity_one_on_announcement_day(earnings_universe):
    """On the announcement date itself, score is exactly 1.0."""
    from core.feature_foundry.features.earnings_proximity_5d import earnings_proximity_5d
    val = earnings_proximity_5d("AAPL", date(2024, 4, 15))
    assert val is not None
    assert math.isclose(val, 1.0, abs_tol=1e-9)


def test_earnings_proximity_decays_to_zero(earnings_universe):
    """6+ business days before the next announcement, score is 0."""
    from core.feature_foundry.features.earnings_proximity_5d import earnings_proximity_5d
    # 2024-04-15 is a Monday. 6 business days before = 2024-04-05 (Friday).
    val_far = earnings_proximity_5d("AAPL", date(2024, 4, 5))
    assert val_far == 0.0


def test_earnings_proximity_ladder(earnings_universe):
    """Score steps: 5 days out → 0.0, 4 → 0.2, 3 → 0.4, 2 → 0.6, 1 → 0.8,
    0 → 1.0."""
    from core.feature_foundry.features.earnings_proximity_5d import earnings_proximity_5d
    # Monday 2024-04-15 announcement; the prior 5 business days:
    #   T-1 = Fri 2024-04-12  (1 bday) → 0.8
    #   T-2 = Thu 2024-04-11           → 0.6
    #   T-3 = Wed 2024-04-10           → 0.4
    #   T-4 = Tue 2024-04-09           → 0.2
    #   T-5 = Mon 2024-04-08           → 0.0
    expected = {
        date(2024, 4, 12): 0.8,
        date(2024, 4, 11): 0.6,
        date(2024, 4, 10): 0.4,
        date(2024, 4,  9): 0.2,
        date(2024, 4,  8): 0.0,
    }
    for d, want in expected.items():
        val = earnings_proximity_5d("AAPL", d)
        assert val is not None
        assert math.isclose(val, want, abs_tol=1e-9), (
            f"date {d}: expected {want}, got {val}"
        )


def test_earnings_proximity_none_for_unknown_ticker(earnings_universe):
    from core.feature_foundry.features.earnings_proximity_5d import earnings_proximity_5d
    assert earnings_proximity_5d("ZZZZ_NOT_REAL", date(2024, 4, 10)) is None


def test_earnings_proximity_none_after_last_cached(earnings_universe):
    """No future announcement after the last cached one → None."""
    from core.feature_foundry.features.earnings_proximity_5d import earnings_proximity_5d
    val = earnings_proximity_5d("AAPL", date(2026, 1, 1))
    assert val is None


# ---- vix_change_5d ---- #

def test_vix_change_5d_matches_closed_form(vix_universe):
    """Linear ramp 15 -> 30 over 30 bdays. 5-day pct change at the end:
    vix[-1] / vix[-6] - 1."""
    from core.feature_foundry.features.vix_change_5d import vix_change_5d
    dt = vix_universe["dates"][-1].date()
    val = vix_change_5d("AAPL", dt)
    assert val is not None
    vix = vix_universe["vix"]
    expected = vix[-1] / vix[-6] - 1.0
    assert math.isclose(val, expected, rel_tol=1e-9)


def test_vix_change_5d_ticker_independent(vix_universe):
    """Same value for any ticker (VIX is broadcast)."""
    from core.feature_foundry.features.vix_change_5d import vix_change_5d
    dt = vix_universe["dates"][-1].date()
    a = vix_change_5d("AAPL", dt)
    b = vix_change_5d("JPM", dt)
    c = vix_change_5d("ZZZZ", dt)
    assert a is not None and b is not None and c is not None
    assert a == b == c


def test_vix_change_5d_positive_on_rising_ramp(vix_universe):
    """Linear up ramp → positive pct change."""
    from core.feature_foundry.features.vix_change_5d import vix_change_5d
    dt = vix_universe["dates"][-1].date()
    val = vix_change_5d("AAPL", dt)
    assert val > 0


def test_vix_change_5d_none_when_short_history(tmp_path):
    """VIX series with only 3 points — under the 6-point requirement."""
    from core.feature_foundry.features.vix_change_5d import vix_change_5d
    data_root = tmp_path / "macro"
    data_root.mkdir()
    dates = pd.bdate_range(start="2024-01-02", periods=3)
    df = pd.DataFrame({"value": [15.0, 16.0, 17.0]},
                     index=pd.DatetimeIndex(dates, name="date"))
    df.to_parquet(data_root / "VIXCLS.parquet")
    src = FREDMacro(data_root=data_root)
    get_source_registry().register(src)
    clear_series_cache()
    try:
        assert vix_change_5d("AAPL", dates[-1].date()) is None
    finally:
        clear_series_cache()


# ---- Substrate integration: twin + ablation + cards ---- #

def test_adversarial_twins_can_be_generated_for_all_five(
    pair_universe, earnings_universe, vix_universe,
):
    """Substrate compatibility — twin generator must accept all 5 new
    features without modification."""
    import core.feature_foundry.features  # noqa: F401
    from core.feature_foundry.adversarial import twin_id_for
    reg = get_feature_registry()
    for fid in THIRD_BATCH_IDS:
        real = reg.get(fid)
        assert real is not None, f"feature {fid!r} not registered"
        twin = generate_twin(real)
        assert twin.tier == "adversarial"
        assert twin.feature_id == twin_id_for(fid)


def test_twin_determinism_for_calendar_feature():
    """days_to_quarter_end is pure-calendar — twin must still be
    deterministic across calls."""
    import core.feature_foundry.features  # noqa: F401
    from core.feature_foundry.adversarial import twin_id_for
    reg = get_feature_registry()
    real = reg.get("days_to_quarter_end")
    if reg.get(twin_id_for("days_to_quarter_end")) is None:
        generate_twin(real)
    twin = reg.get(twin_id_for("days_to_quarter_end"))
    d = date(2024, 6, 15)
    v1 = twin("AAPL", d)
    v2 = twin("AAPL", d)
    assert v1 == v2


def test_ablation_runs_with_synthetic_backtest_fn(tmp_path):
    """Synthetic LOO ablation — verifies the 5 features integrate with
    the runner without modification."""
    import core.feature_foundry.features  # noqa: F401

    weights = {
        "days_to_quarter_end":   0.04,
        "month_of_year_dummy":   0.02,
        "pair_zscore_60d":       0.08,
        "earnings_proximity_5d": 0.06,
        "vix_change_5d":         0.05,
    }

    def synthetic_backtest_fn(active: set) -> float:
        return sum(weights[f] for f in active if f in weights)

    out_root = tmp_path / "ablation"
    results = run_ablation(
        feature_ids=THIRD_BATCH_IDS,
        baseline_run_uuid="ws-e-third-batch-test",
        backtest_fn=synthetic_backtest_fn,
        out_root=out_root,
    )

    assert set(results.keys()) == set(THIRD_BATCH_IDS)
    for fid, weight in weights.items():
        assert math.isclose(results[fid].contribution_sharpe, weight,
                            rel_tol=1e-9)
    assert (out_root / "ws-e-third-batch-test.json").exists()


def test_model_cards_validate_clean():
    import core.feature_foundry.features  # noqa: F401
    errors = validate_all_model_cards()
    new_errors = [e for e in errors if any(fid in e for fid in THIRD_BATCH_IDS)]
    assert new_errors == [], (
        "Model card validation errors for new features:\n"
        + "\n".join(new_errors)
    )
