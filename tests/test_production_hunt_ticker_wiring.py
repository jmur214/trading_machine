"""tests/test_production_hunt_ticker_wiring.py
================================================
Regression tests for T-2026-05-12-054.

Pre-T-054, the production `DiscoveryEngine.hunt()` called
`compute_all_features` WITHOUT `ticker=`. Because
`compute_all_features` is ticker-optional and skips the Foundry pass
when ticker is None, every foundry_feature gene in the GA emission
referenced a column that never existed → silent dead-letter.

These tests pin the fix:

1. `test_production_hunt_passes_ticker_to_compute_all_features` —
   spies on `FeatureEngineer.compute_all_features` and asserts every
   call from `hunt()` carries a non-None `ticker` argument.
2. `test_foundry_feature_columns_populated_post_fix` — runs `hunt()`
   on synthetic data and verifies the produced feature DataFrame
   contains `Foundry_*` columns. Pre-fix this would have been zero.
3. `test_pre_fix_repro_documented` — golden-file check that the
   pre-fix diagnostic JSON exists with the expected dead-letter
   evidence.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

import numpy as np
import pandas as pd

from engines.engine_d_discovery.discovery import DiscoveryEngine
from engines.engine_d_discovery.feature_engineering import FeatureEngineer

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _synthetic_data_map(n_tickers: int = 3, n_bars: int = 300) -> dict:
    rng = np.random.default_rng(0)
    dates = pd.date_range("2024-01-02", periods=n_bars, freq="B")
    out = {}
    for i in range(n_tickers):
        px = 100 + rng.normal(0, 1, size=n_bars).cumsum()
        out[f"T{i:03d}"] = pd.DataFrame(
            {
                "Open": px, "High": px + 0.5, "Low": px - 0.5,
                "Close": px, "Volume": rng.integers(1e5, 1e7, size=n_bars),
            },
            index=dates,
        )
    return out


def test_production_hunt_passes_ticker_to_compute_all_features():
    """Every `compute_all_features` call from `hunt()` must carry `ticker=`."""
    calls: List[dict] = []
    orig = FeatureEngineer.compute_all_features

    def spy(self, ohlc_df, fund_df, **kw):
        calls.append({
            "has_ticker_kw": "ticker" in kw,
            "ticker_value": kw.get("ticker"),
        })
        return orig(self, ohlc_df, fund_df, **kw)

    FeatureEngineer.compute_all_features = spy
    try:
        de = DiscoveryEngine()
        de.hunt(data_map=_synthetic_data_map(n_tickers=3))
    finally:
        FeatureEngineer.compute_all_features = orig

    assert len(calls) >= 3, f"expected >=3 compute_all_features calls, got {len(calls)}"
    for i, c in enumerate(calls):
        assert c["has_ticker_kw"], (
            f"call {i} missing `ticker` kwarg — regresses T-054 fix"
        )
        assert c["ticker_value"] is not None, (
            f"call {i} passed ticker=None — Foundry pass would be skipped"
        )
        assert isinstance(c["ticker_value"], str), (
            f"call {i} ticker is not a string: {c['ticker_value']!r}"
        )


def test_foundry_feature_columns_populated_post_fix():
    """After the fix, `hunt()` produces feature DataFrames with `Foundry_*` columns."""
    seen_columns: List[List[str]] = []
    orig = FeatureEngineer.compute_all_features

    def spy(self, ohlc_df, fund_df, **kw):
        result = orig(self, ohlc_df, fund_df, **kw)
        seen_columns.append(list(result.columns))
        return result

    FeatureEngineer.compute_all_features = spy
    try:
        de = DiscoveryEngine()
        de.hunt(data_map=_synthetic_data_map(n_tickers=2))
    finally:
        FeatureEngineer.compute_all_features = orig

    assert seen_columns, "no compute_all_features calls observed"
    for i, cols in enumerate(seen_columns):
        foundry = [c for c in cols if c.startswith("Foundry_")]
        assert len(foundry) > 0, (
            f"call {i} produced 0 Foundry_* columns post-fix — "
            f"Foundry pass not being exercised. Got columns: {cols[:20]}"
        )


def test_pre_fix_repro_documented():
    """The pre-fix diagnostic JSON exists and confirms the dead-letter pattern."""
    p = PROJECT_ROOT / "docs" / "Audit" / "production_hunt_ticker_wiring_prefix_2026_05_12.json"
    assert p.exists(), f"pre-fix diagnostic missing at {p}"
    data = json.loads(p.read_text())
    assert data["phase"] == "pre-fix"
    assert data["production_hunt_passes_ticker"] is False, (
        "pre-fix diagnostic should record production_hunt_passes_ticker=False"
    )
    assert data["foundry_cols_no_ticker"] == 0, (
        "pre-fix diagnostic should record 0 foundry cols when ticker omitted"
    )
    assert data["foundry_cols_with_ticker"] > 0, (
        "pre-fix diagnostic should record >0 foundry cols when ticker passed"
    )


def test_compute_all_features_signature_unchanged():
    """Defensive: `compute_all_features` still treats `ticker` as optional
    so other call-sites that don't yet pass it (e.g. `rule_based_edge.py`)
    don't break. The fix is at the call-site, NOT at the signature."""
    import inspect

    sig = inspect.signature(FeatureEngineer.compute_all_features)
    ticker_param = sig.parameters.get("ticker")
    assert ticker_param is not None, "ticker parameter removed from signature"
    assert ticker_param.default is None, (
        "ticker default changed from None — would break optional callers"
    )


def test_foundry_pass_skipped_when_ticker_none():
    """Belt-and-suspenders: confirm the documented contract that
    `compute_all_features(..., ticker=None)` skips the Foundry pass."""
    fe = FeatureEngineer()
    data = _synthetic_data_map(n_tickers=1)["T000"]
    no_ticker = fe.compute_all_features(data, pd.DataFrame())
    with_ticker = fe.compute_all_features(data, pd.DataFrame(), ticker="T000")
    foundry_off = [c for c in no_ticker.columns if c.startswith("Foundry_")]
    foundry_on = [c for c in with_ticker.columns if c.startswith("Foundry_")]
    assert len(foundry_off) == 0, (
        f"ticker=None should skip Foundry, got {len(foundry_off)} cols"
    )
    assert len(foundry_on) > 0, (
        "ticker=<str> should populate Foundry cols"
    )
