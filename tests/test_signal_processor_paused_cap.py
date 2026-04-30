"""
tests/test_signal_processor_paused_cap.py
=========================================
Phase 2.10d Primitive 2 — soft-pause weight ceiling.

Bug being closed: an edge with status=paused enters SignalProcessor with
its initial weight already capped at 0.5 by mode_controller. But
regime_gate then multiplies the weight in the per-bar processing path.
A regime_gate value of 1.0 in stressed/crisis regimes does nothing on
the cap (good); but the bug shape generalizes — any future amplifier
in the per-bar weight chain (learned_affinity, governor adjustment) can
push a paused edge's effective weight back toward full and cancel the
soft-pause's intended suppression.

Empirical case: low_vol_factor_v1 (status=paused, mode_controller initial
weight 0.5) fired 1,613 times in the 2025 OOS run. The fix in
SignalProcessor enforces an absolute ceiling: a paused edge can never
have effective weight > paused_max_weight regardless of any downstream
multiplier.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from engines.engine_a_alpha.signal_processor import (
    EnsembleSettings,
    HygieneSettings,
    RegimeSettings,
    SignalProcessor,
)


def _make_df(n: int = 100) -> pd.DataFrame:
    prices = 100 + np.cumsum(np.random.default_rng(0).normal(0, 0.5, n))
    return pd.DataFrame({
        "Close": prices,
        "High": prices * 1.01,
        "Low": prices * 0.99,
        "Volume": np.ones(n) * 1e6,
    })


def _make_processor(
    edge_weights: dict,
    regime_gates: dict | None = None,
    paused_edge_ids: set | None = None,
    paused_max_weight: float = 0.5,
) -> SignalProcessor:
    return SignalProcessor(
        regime=RegimeSettings(enable_trend=False, enable_vol=False),
        hygiene=HygieneSettings(min_history=1, clamp=1.5),
        ensemble=EnsembleSettings(enable_shrink=False),
        edge_weights=edge_weights,
        regime_gates=regime_gates or {},
        paused_edge_ids=paused_edge_ids,
        paused_max_weight=paused_max_weight,
    )


def _advisory(regime_summary: str) -> dict:
    return {"advisory": {"regime_summary": regime_summary, "risk_scalar": 1.0}}


# ---------------------------------------------------------------------------
# Default behavior: no paused set → backwards-compatible, no clamp
# ---------------------------------------------------------------------------

def test_no_paused_set_does_not_clamp():
    """Pre-fix-equivalent path: when paused_edge_ids is empty, weights pass
    through unchanged. Required for the no-op-by-default contract."""
    proc = _make_processor(
        {"edge_a": 1.5},
        paused_edge_ids=set(),
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.5}}
    result = proc.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                          regime_meta=_advisory("benign"))
    detail = result["AAPL"]["edges_detail"][0]
    assert detail["weight"] == pytest.approx(1.5)


def test_unpaused_edge_with_high_weight_not_clamped():
    """An edge NOT in paused_edge_ids retains its full weight even with the
    cap enabled — the cap is paused-only."""
    proc = _make_processor(
        {"edge_a": 1.0, "edge_b": 1.0},
        paused_edge_ids={"edge_a"},
        paused_max_weight=0.5,
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"edge_a": 0.5, "edge_b": 0.5}}
    result = proc.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                          regime_meta=_advisory("benign"))
    detail = {d["edge"]: d for d in result["AAPL"]["edges_detail"]}
    # edge_a paused → clamped to 0.5; edge_b unpaused → 1.0 unchanged
    assert detail["edge_a"]["weight"] == pytest.approx(0.5)
    assert detail["edge_b"]["weight"] == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Core fix: regime_gate amplification cannot leak past the cap
# ---------------------------------------------------------------------------

def test_paused_cap_clamps_above_ceiling():
    """Direct ceiling test: paused edge with base weight 0.5, gate 2.0 in
    stressed (synthetic amplifier) → effective should clamp to 0.5, not 1.0."""
    proc = _make_processor(
        {"low_vol_factor_v1": 0.5},
        regime_gates={"low_vol_factor_v1": {"benign": 0.15, "stressed": 2.0}},
        paused_edge_ids={"low_vol_factor_v1"},
        paused_max_weight=0.5,
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"low_vol_factor_v1": 0.5}}
    result = proc.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                          regime_meta=_advisory("stressed"))
    detail = result["AAPL"]["edges_detail"][0]
    # 0.5 * 2.0 = 1.0 → clamp → 0.5
    assert detail["weight"] == pytest.approx(0.5)


def test_paused_cap_does_not_inflate_low_weights():
    """The ceiling is one-sided. A paused edge with effective weight below
    the cap (e.g. benign regime suppressing it to 0.075) is NOT lifted."""
    proc = _make_processor(
        {"low_vol_factor_v1": 0.5},
        regime_gates={"low_vol_factor_v1": {"benign": 0.15, "stressed": 1.0}},
        paused_edge_ids={"low_vol_factor_v1"},
        paused_max_weight=0.5,
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"low_vol_factor_v1": 0.5}}
    result = proc.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                          regime_meta=_advisory("benign"))
    detail = result["AAPL"]["edges_detail"][0]
    # 0.5 * 0.15 = 0.075 → unchanged
    assert detail["weight"] == pytest.approx(0.075)


# ---------------------------------------------------------------------------
# 2025 reconstruction: low_vol_factor_v1 leak case
# ---------------------------------------------------------------------------

def test_2025_low_vol_factor_leak_closed():
    """Reconstruct the 2025 leak: low_vol_factor_v1 status=paused, initial
    weight 0.5 (post-mode_controller cap), regime_gate {benign:0.15,
    stressed:1.0, crisis:1.0}. In stressed regimes, gate releases the edge
    back to 0.5 — which is the soft-pause cap. The fix ensures effective
    weight never exceeds the cap.

    The OLD shape (pre-fix) of the bug: in code paths that multiply weight
    above 0.5 (any of: governor weight, learned_affinity, future
    amplifier), nothing prevented the paused edge from running at full
    weight. The cap closes that surface.
    """
    # Deliberately stack multiple amplifiers that pre-fix would have lifted
    # this above the 0.5 ceiling.
    proc = _make_processor(
        {"low_vol_factor_v1": 0.5},
        regime_gates={"low_vol_factor_v1": {"benign": 0.15, "stressed": 1.5,
                                             "crisis": 2.0}},
        paused_edge_ids={"low_vol_factor_v1"},
        paused_max_weight=0.5,
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"low_vol_factor_v1": 0.5}}

    # In each non-benign regime, gate amplifies the base weight past the cap.
    # The cap should always bind.
    for regime in ("stressed", "crisis"):
        result = proc.process(
            data_map, pd.Timestamp("2024-01-01"), raw_scores,
            regime_meta=_advisory(regime),
        )
        detail = result["AAPL"]["edges_detail"][0]
        assert detail["weight"] <= 0.5 + 1e-9, (
            f"{regime}: paused edge effective weight {detail['weight']} "
            f"exceeded soft-pause ceiling 0.5"
        )


def test_paused_cap_invariant_across_all_regimes():
    """Property test: for any regime label, a paused edge's effective weight
    must be <= paused_max_weight."""
    rng = np.random.default_rng(42)
    proc = _make_processor(
        {"e": 1.0},
        # Adversarial gate: every regime label amplifies past the cap
        regime_gates={"e": {r: 5.0 for r in ("benign", "stressed", "crisis")}},
        paused_edge_ids={"e"},
        paused_max_weight=0.5,
    )
    data_map = {"AAPL": _make_df()}
    for _ in range(20):
        raw = float(rng.uniform(-1, 1))
        regime = rng.choice(["benign", "stressed", "crisis"])
        result = proc.process(
            data_map, pd.Timestamp("2024-01-01"),
            {"AAPL": {"e": raw}},
            regime_meta=_advisory(regime),
        )
        if "AAPL" not in result:
            continue
        w = result["AAPL"]["edges_detail"][0]["weight"]
        assert w <= 0.5 + 1e-9, f"regime={regime} raw={raw}: w={w} > cap"


# ---------------------------------------------------------------------------
# Cap value is configurable per call
# ---------------------------------------------------------------------------

def test_paused_max_weight_is_configurable():
    """A future tighter ceiling (e.g. 0.1) should be honored verbatim."""
    proc = _make_processor(
        {"e": 1.0},
        regime_gates={"e": {"benign": 1.0}},
        paused_edge_ids={"e"},
        paused_max_weight=0.1,
    )
    data_map = {"AAPL": _make_df()}
    raw_scores = {"AAPL": {"e": 0.5}}
    result = proc.process(data_map, pd.Timestamp("2024-01-01"), raw_scores,
                          regime_meta=_advisory("benign"))
    detail = result["AAPL"]["edges_detail"][0]
    assert detail["weight"] == pytest.approx(0.1)
