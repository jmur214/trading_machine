"""Tests for E-rebuild phase-1 extensions to macro_features.

Covers the new feature flags (`include_hyg_ig`, `include_leading_rs`) and
verifies the new features have expected shape, NaN behavior, and ordering.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from engines.engine_e_regime.macro_features import (
    FEATURE_COLUMNS,
    HYG_IG_FEATURES,
    LEADING_RS_FEATURES,
    build_feature_panel,
)


REPO = Path(__file__).resolve().parents[1]


def _required_cache_present() -> bool:
    """Skip the feature tests when local macro cache hasn't been fetched."""
    needed = [
        "BAMLH0A0HYM2.parquet", "BAMLC0A0CM.parquet",
        "HG_F.parquet", "GC_F.parquet", "XLP.parquet", "XLY.parquet",
        "VIXCLS.parquet", "BAA10Y.parquet", "AAA10Y.parquet",
        "T10Y2Y.parquet", "DTWEXBGS.parquet",
    ]
    macro_dir = REPO / "data" / "macro"
    return all((macro_dir / n).exists() for n in needed)


def test_hyg_ig_features_constant_is_a_list_with_expected_member():
    assert isinstance(HYG_IG_FEATURES, list)
    assert "hyg_ig_oas" in HYG_IG_FEATURES


def test_leading_rs_features_constant_has_expected_members():
    assert isinstance(LEADING_RS_FEATURES, list)
    assert "copper_gold_ratio" in LEADING_RS_FEATURES
    assert "xlp_xly_ratio" in LEADING_RS_FEATURES


def test_default_panel_does_not_include_phase1_features():
    """Phase-1 features must remain opt-in. Default 7-feature HMM unchanged."""
    if not _required_cache_present():
        pytest.skip("macro cache not populated — run fetch scripts to enable")
    panel = build_feature_panel(start="2024-01-01", end="2024-06-30")
    assert "hyg_ig_oas" not in panel.columns
    assert "copper_gold_ratio" not in panel.columns
    assert "xlp_xly_ratio" not in panel.columns
    assert list(panel.columns) == FEATURE_COLUMNS


def test_panel_with_hyg_ig_flag_appends_feature_in_order():
    if not _required_cache_present():
        pytest.skip("macro cache not populated")
    panel = build_feature_panel(
        start="2024-01-01", end="2024-06-30", include_hyg_ig=True,
    )
    assert "hyg_ig_oas" in panel.columns
    expected = list(FEATURE_COLUMNS) + ["hyg_ig_oas"]
    assert list(panel.columns) == expected
    # hyg_ig_oas should be a positive credit spread (HY > IG); over a benign
    # 6-month window in early 2024 it should never go negative.
    s = panel["hyg_ig_oas"].dropna()
    assert (s > 0).all(), "HY OAS minus IG OAS should be > 0 across history"


def test_panel_with_leading_rs_flag_appends_two_features_in_order():
    if not _required_cache_present():
        pytest.skip("macro cache not populated")
    panel = build_feature_panel(
        start="2024-01-01", end="2024-12-31", include_leading_rs=True,
    )
    assert "copper_gold_ratio" in panel.columns
    assert "xlp_xly_ratio" in panel.columns
    expected = list(FEATURE_COLUMNS) + ["copper_gold_ratio", "xlp_xly_ratio"]
    assert list(panel.columns) == expected
    # Both features are 63d log-changes — first 63 rows should be NaN.
    cg = panel["copper_gold_ratio"]
    rs = panel["xlp_xly_ratio"]
    # After the warm-up the features should be finite floats centered near zero.
    assert cg.dropna().abs().median() < 0.5, \
        "63d log-change should not have order-of-1 magnitudes routinely"
    assert rs.dropna().abs().median() < 0.5


def test_panel_with_all_phase1_flags_returns_correct_column_count():
    if not _required_cache_present():
        pytest.skip("macro cache not populated")
    panel = build_feature_panel(
        start="2024-01-01", end="2024-12-31",
        include_hyg_ig=True, include_leading_rs=True,
    )
    expected_cols = (
        list(FEATURE_COLUMNS) + HYG_IG_FEATURES + LEADING_RS_FEATURES
    )
    assert list(panel.columns) == expected_cols
    assert len(panel.columns) == len(FEATURE_COLUMNS) + 3


def test_phase1_features_no_lookahead_at_end():
    """The forward-fill pattern in build_feature_panel should NOT bring in
    future data — the last day's hyg_ig_oas should be derivable from data
    available on or before that date."""
    if not _required_cache_present():
        pytest.skip("macro cache not populated")
    panel_short = build_feature_panel(
        start="2024-01-01", end="2024-03-31", include_hyg_ig=True,
    )
    panel_long = build_feature_panel(
        start="2024-01-01", end="2024-12-31", include_hyg_ig=True,
    )
    # Values for shared dates should match exactly — no contamination from
    # future observations the longer panel sees.
    common = panel_short.index.intersection(panel_long.index)
    for col in ("hyg_ig_oas",):
        a = panel_short.loc[common, col].dropna()
        b = panel_long.loc[common[: len(a)], col].dropna()
        # Use full alignment — both series should be identical on overlap.
        aligned = pd.concat([a.rename("a"), b.rename("b")], axis=1, join="inner")
        # Tolerate tiny float roundtrip noise from parquet.
        np.testing.assert_allclose(
            aligned["a"].values, aligned["b"].values, rtol=1e-9, atol=1e-9,
        )


def test_resample_handles_phase1_levels_without_double_summing():
    """Verify _LEVEL_COLUMNS includes the phase-1 features so weekly/monthly
    resample takes 'last' (not 'sum'). A phase-1 column accidentally treated
    as a return would compound across days and produce wrong magnitudes."""
    if not _required_cache_present():
        pytest.skip("macro cache not populated")
    from engines.engine_e_regime.macro_features import (
        _LEVEL_COLUMNS, resample_feature_panel,
    )
    assert "hyg_ig_oas" in _LEVEL_COLUMNS
    assert "copper_gold_ratio" in _LEVEL_COLUMNS
    assert "xlp_xly_ratio" in _LEVEL_COLUMNS

    panel = build_feature_panel(
        start="2024-01-01", end="2024-06-30",
        include_hyg_ig=True, include_leading_rs=True,
    )
    weekly = resample_feature_panel(panel, "W")
    # Magnitude check: weekly hyg_ig_oas should be in the same range as
    # daily (level data, taken as last).
    daily_range = panel["hyg_ig_oas"].dropna()
    weekly_range = weekly["hyg_ig_oas"].dropna()
    assert daily_range.max() * 0.95 <= weekly_range.max() <= daily_range.max() * 1.05
    assert daily_range.min() * 0.95 <= weekly_range.min() <= daily_range.min() * 1.05
