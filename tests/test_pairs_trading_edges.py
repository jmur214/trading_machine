"""Tests for engines/engine_a_alpha/edges/pairs_trading_v1.py.

Covers acceptance criterion 3 of T-2026-05-09-017:
  - long-X / short-Y entry when z_t below -z_entry  (and the symmetric reverse)
  - exit (flatten) when |z_t| <= z_exit
  - stop (flatten) when |z_t| >= z_stop
  - all registered pair specs are at status='paused' tier='feature'
  - missing leg in data_map → no crash, abstain everywhere
  - mis-configured spec (empty ticker_x/ticker_y) → abstain
  - degenerate spread (zero std over the lookback) → abstain

Synthetic data is constructed with fixed seeds so the spread sequence
is exactly known up to numerical precision; threshold logic can be
asserted bit-stably.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engines.engine_a_alpha.edges.pairs_trading_v1 import (
    MANIFEST_PATH,
    PairsTradingEdge,
    SHARED_DEFAULTS,
)


# ---------------------------------------------------------------------------
# Synthetic-data helpers — log-Y = log-X + spread, with spread crafted
# to land at a chosen z-score on the final bar.
# ---------------------------------------------------------------------------

def _build_pair_dataframes(
    spread_series: np.ndarray,
    *,
    ticker_x: str = "TX",
    ticker_y: str = "TY",
    base_price_x: float = 100.0,
    seed: int = 7,
) -> dict[str, pd.DataFrame]:
    """Build a dict of {ticker: DataFrame} for two synthetic price series
    where log_Y - log_X equals exactly the supplied spread sequence.

    We synthesize log_X as a smooth random walk (deterministic seed) and
    set log_Y = log_X + spread. Both DataFrames carry only Close (the
    fields the edge consumes); other columns are present but irrelevant.
    """
    rng = np.random.default_rng(seed)
    n = len(spread_series)
    x_increments = rng.normal(loc=0.0, scale=0.005, size=n)
    log_x = np.log(base_price_x) + np.cumsum(x_increments)
    log_y = log_x + np.asarray(spread_series, dtype=float)
    dates = pd.bdate_range("2020-01-02", periods=n)

    df_x = pd.DataFrame({"Close": np.exp(log_x)}, index=dates)
    df_y = pd.DataFrame({"Close": np.exp(log_y)}, index=dates)
    return {ticker_x: df_x, ticker_y: df_y}


def _craft_spread_with_terminal_z(
    target_z: float,
    *,
    n: int = 80,
    mean: float = 0.0,
    std: float = 0.01,
    seed: int = 11,
) -> np.ndarray:
    """Return a length-n spread series with sample mean=mean, sample
    std=std, and the terminal value placed exactly at z = target_z
    standard deviations from the mean.

    We achieve this by drawing n-1 random spreads and solving the
    final value to enforce the sample-mean and sample-std identities.
    Then we replace the final value with mean + target_z * std (which
    perturbs sample stats, but the perturbation is small for n large).
    """
    rng = np.random.default_rng(seed)
    body = rng.normal(loc=mean, scale=std, size=n - 1)
    body = (body - body.mean()) * (std / max(body.std(ddof=1), 1e-12)) + mean
    spread = np.append(body, mean + target_z * std)
    return spread


def _z_of_terminal_spread(spread: np.ndarray) -> float:
    """Re-compute the z-score the edge would see for a given log_y -
    β·log_x sequence (β=1 in these tests, so spread *is* log_y - log_x)."""
    mu = float(np.mean(spread))
    sd = float(np.std(spread, ddof=1))
    if sd == 0.0:
        return float("nan")
    return float((spread[-1] - mu) / sd)


# ---------------------------------------------------------------------------
# Behavior tests
# ---------------------------------------------------------------------------

def test_spread_zscore_entry_long_short_when_below_threshold():
    """When z_t is well below -z_entry, the edge should emit:
    Y = +long_score (Y is cheap on the spread, buy it)
    X = -long_score (short the rich leg)"""
    spread = _craft_spread_with_terminal_z(target_z=-3.0, n=80)
    data_map = _build_pair_dataframes(spread)
    z = _z_of_terminal_spread(spread)
    assert z < -2.0  # sanity check on craft

    edge = PairsTradingEdge(params={
        "ticker_x": "TX",
        "ticker_y": "TY",
        "beta": 1.0,
        "lookback_days": 80,
        "z_entry": 2.0,
        "z_exit": 0.5,
        "z_stop": 4.0,
    })
    out = edge.compute_signals(data_map, data_map["TX"].index[-1])
    assert out["TY"] == pytest.approx(1.0)
    assert out["TX"] == pytest.approx(-1.0)


def test_spread_zscore_entry_short_long_when_above_threshold():
    """Symmetric reverse: z_t well above +z_entry → Y is rich, short Y / long X."""
    spread = _craft_spread_with_terminal_z(target_z=+3.0, n=80)
    data_map = _build_pair_dataframes(spread)

    edge = PairsTradingEdge(params={
        "ticker_x": "TX",
        "ticker_y": "TY",
        "beta": 1.0,
        "lookback_days": 80,
    })
    out = edge.compute_signals(data_map, data_map["TX"].index[-1])
    assert out["TY"] == pytest.approx(-1.0)
    assert out["TX"] == pytest.approx(1.0)


def test_spread_zscore_exit_when_meanreverted():
    """When |z_t| <= z_exit (mean-reverted), edge abstains on both legs."""
    spread = _craft_spread_with_terminal_z(target_z=0.2, n=80)
    data_map = _build_pair_dataframes(spread)

    edge = PairsTradingEdge(params={
        "ticker_x": "TX",
        "ticker_y": "TY",
        "beta": 1.0,
        "lookback_days": 80,
    })
    out = edge.compute_signals(data_map, data_map["TX"].index[-1])
    assert out["TY"] == 0.0
    assert out["TX"] == 0.0


def test_stop_loss_when_spread_breaks():
    """When |z_t| >= z_stop, edge flattens — DOES NOT enter even
    though |z| > z_entry. Stop overrides entry."""
    spread = _craft_spread_with_terminal_z(target_z=-5.0, n=80)
    data_map = _build_pair_dataframes(spread)

    edge = PairsTradingEdge(params={
        "ticker_x": "TX",
        "ticker_y": "TY",
        "beta": 1.0,
        "lookback_days": 80,
        "z_entry": 2.0,
        "z_stop": 4.0,
    })
    out = edge.compute_signals(data_map, data_map["TX"].index[-1])
    assert out["TX"] == 0.0
    assert out["TY"] == 0.0


def test_neutral_band_between_exit_and_entry_abstains():
    """Stateless v1: between |z_exit| and |z_entry|, no signal.
    Stateful hysteresis (hold-while-in-trade) is a documented follow-up."""
    spread = _craft_spread_with_terminal_z(target_z=1.0, n=80)
    data_map = _build_pair_dataframes(spread)

    edge = PairsTradingEdge(params={
        "ticker_x": "TX",
        "ticker_y": "TY",
        "beta": 1.0,
        "lookback_days": 80,
    })
    out = edge.compute_signals(data_map, data_map["TX"].index[-1])
    assert out["TY"] == 0.0
    assert out["TX"] == 0.0


def test_pairs_handle_missing_ticker_gracefully():
    """If one leg is absent from data_map, the edge MUST NOT crash
    and MUST emit zero for every ticker present (you can't half-trade
    a pair)."""
    # Only TY present — TX is missing.
    df_y = pd.DataFrame(
        {"Close": np.linspace(100, 110, 80)},
        index=pd.bdate_range("2020-01-02", periods=80),
    )
    df_other = pd.DataFrame(
        {"Close": np.linspace(50, 55, 80)},
        index=pd.bdate_range("2020-01-02", periods=80),
    )
    data_map = {"TY": df_y, "OTHER": df_other}

    edge = PairsTradingEdge(params={
        "ticker_x": "TX",
        "ticker_y": "TY",
        "beta": 1.0,
        "lookback_days": 60,
    })
    out = edge.compute_signals(data_map, df_y.index[-1])
    assert out == {"TY": 0.0, "OTHER": 0.0}


def test_misconfigured_spec_abstains():
    """Empty ticker_x/ticker_y in params → abstain on the entire data_map."""
    df = pd.DataFrame(
        {"Close": np.linspace(100, 110, 80)},
        index=pd.bdate_range("2020-01-02", periods=80),
    )
    data_map = {"AAA": df, "BBB": df.copy()}

    edge = PairsTradingEdge(params={"ticker_x": "", "ticker_y": ""})
    out = edge.compute_signals(data_map, df.index[-1])
    assert out == {"AAA": 0.0, "BBB": 0.0}


def test_degenerate_spread_zero_std_abstains():
    """If the spread is constant over the lookback window (e.g.,
    perfectly co-moving log series), std=0 and z is undefined.
    The edge must abstain rather than divide by zero."""
    # log_y = log_x + 0.1 for every bar → spread is exactly 0.1 always.
    n = 80
    log_x = np.linspace(np.log(100), np.log(110), n)
    log_y = log_x + 0.1
    dates = pd.bdate_range("2020-01-02", periods=n)
    data_map = {
        "TX": pd.DataFrame({"Close": np.exp(log_x)}, index=dates),
        "TY": pd.DataFrame({"Close": np.exp(log_y)}, index=dates),
    }
    edge = PairsTradingEdge(params={
        "ticker_x": "TX",
        "ticker_y": "TY",
        "beta": 1.0,
        "lookback_days": 80,
    })
    out = edge.compute_signals(data_map, dates[-1])
    assert out["TX"] == 0.0
    assert out["TY"] == 0.0


def test_insufficient_history_abstains():
    """Fewer aligned bars than lookback_days → abstain."""
    # Only 30 aligned bars, but lookback=60 → abstain.
    n = 30
    dates = pd.bdate_range("2020-01-02", periods=n)
    log_x = np.linspace(np.log(100), np.log(105), n)
    log_y = log_x + 0.05
    data_map = {
        "TX": pd.DataFrame({"Close": np.exp(log_x)}, index=dates),
        "TY": pd.DataFrame({"Close": np.exp(log_y)}, index=dates),
    }
    edge = PairsTradingEdge(params={
        "ticker_x": "TX",
        "ticker_y": "TY",
        "beta": 1.0,
        "lookback_days": 60,
    })
    out = edge.compute_signals(data_map, dates[-1])
    assert out["TX"] == 0.0
    assert out["TY"] == 0.0


def test_beta_alters_z_score():
    """Asserts β actually enters the spread computation: the internal
    `_zscore_now(log_x, log_y, beta)` returns different z-scores for
    different β values on the same input series. (Output signal might
    happen to coincide if both z's fall in the same band, but the
    z's themselves must differ.)"""
    rng = np.random.default_rng(42)
    n = 100
    log_x = np.cumsum(rng.normal(0, 0.01, n)) + np.log(100)
    spread_clean = rng.normal(0, 0.005, n)
    # log_y is built with a "true" β=2 relationship.
    log_y = 2.0 * log_x + spread_clean

    edge = PairsTradingEdge()
    z_correct = edge._zscore_now(log_x, log_y, beta=2.0)
    z_wrong = edge._zscore_now(log_x, log_y, beta=1.0)
    assert z_correct is not None and z_wrong is not None
    # The two z-scores must differ — proof β is participating.
    assert abs(z_correct - z_wrong) > 0.01, (
        f"β param did not affect z-score: z(β=2)={z_correct}, z(β=1)={z_wrong}"
    )


# ---------------------------------------------------------------------------
# Registration tests
# ---------------------------------------------------------------------------

def test_all_pairs_register_at_paused_feature():
    """Every auto-registered pair edge must be at status='paused'
    tier='feature'. No promotion to active at import time."""
    # Importing the module triggers registration as a side effect.
    from engines.engine_a_alpha.edges import pairs_trading_v1  # noqa: F401
    from engines.engine_a_alpha.edge_registry import EdgeRegistry

    reg = EdgeRegistry()
    pair_specs = [s for s in reg.get_all_specs() if s.category == "pairs_trading"]
    assert len(pair_specs) >= 1, (
        "At least one pair edge should auto-register from the cointegration "
        "screen manifest. If the manifest is missing, the screen wasn't run."
    )
    for s in pair_specs:
        assert s.status == "paused", f"{s.edge_id} status={s.status}, expected 'paused'"
        assert s.tier == "feature", f"{s.edge_id} tier={s.tier}, expected 'feature'"
        assert s.module == "engines.engine_a_alpha.edges.pairs_trading_v1"
        assert s.params.get("ticker_x"), f"{s.edge_id} missing ticker_x in params"
        assert s.params.get("ticker_y"), f"{s.edge_id} missing ticker_y in params"
        assert isinstance(s.params.get("beta"), (int, float)), (
            f"{s.edge_id} missing or non-numeric beta in params"
        )


def test_module_loads_without_manifest():
    """If the manifest is missing (fresh checkout), the module must
    still import without raising — no pair edges register, but no crash."""
    # We can't actually delete the manifest here without polluting
    # other tests. Instead, verify the loader handles the missing-file
    # case directly.
    from engines.engine_a_alpha.edges.pairs_trading_v1 import _load_survivor_specs

    # Call the loader with a nonexistent manifest path by monkey-patching.
    import engines.engine_a_alpha.edges.pairs_trading_v1 as mod
    original = mod.MANIFEST_PATH
    try:
        mod.MANIFEST_PATH = Path("/tmp/this_file_does_not_exist_for_sure.json")
        result = _load_survivor_specs()
        assert result == []
    finally:
        mod.MANIFEST_PATH = original


def test_shared_defaults_have_required_keys():
    """The shared-defaults dict must define all the keys the edge
    expects. Catches drift between the constants block and
    `compute_signals`."""
    required = {
        "ticker_x", "ticker_y", "beta", "pair_id",
        "lookback_days", "z_entry", "z_exit", "z_stop", "min_history_bars",
        "long_score", "short_score",
    }
    assert required.issubset(set(SHARED_DEFAULTS.keys())), (
        f"Missing required keys in SHARED_DEFAULTS: {required - set(SHARED_DEFAULTS.keys())}"
    )


def test_manifest_is_valid_json_and_versioned():
    """The cointegration screen output must be valid JSON with the
    keys the edge module reads."""
    if not MANIFEST_PATH.exists():
        pytest.skip("Manifest not present in this checkout")
    payload = json.loads(MANIFEST_PATH.read_text())
    assert "candidates" in payload
    assert "task_id" in payload
    assert payload["task_id"] == "T-2026-05-09-017"
    for cand in payload["candidates"]:
        assert "ticker_x" in cand
        assert "ticker_y" in cand
        assert "survives" in cand
        if cand["survives"]:
            assert "beta" in cand
            assert isinstance(cand["beta"], (int, float))
