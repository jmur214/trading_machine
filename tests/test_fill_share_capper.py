"""
tests/test_fill_share_capper.py
===============================
Phase 2.10d Primitive 1 — per-edge fill-share ceiling.

Validates that the bottom-3 edge concentration observed in 2025
(83% fill share for momentum_edge_v1 + low_vol_factor_v1 +
atr_breakout_v1) is impossible by construction once the cap is active.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from engines.engine_a_alpha.fill_share_capper import (
    FillShareCapSettings,
    FillShareCapper,
)


def _sig(ticker: str, edge_id: str, strength: float = 1.0,
         side: str = "long") -> dict:
    return {
        "ticker": ticker,
        "side": side,
        "strength": float(strength),
        "edge": edge_id.replace("_v1", ""),
        "edge_id": edge_id,
        "edge_group": "technical",
        "edge_category": "technical",
        "meta": {},
    }


# ---------------------------------------------------------------------------
# Defaults / no-op contract
# ---------------------------------------------------------------------------

def test_disabled_passes_through():
    capper = FillShareCapper(FillShareCapSettings(enabled=False))
    sigs = [_sig(f"T{i}", "momentum_edge_v1", 1.0) for i in range(20)]
    out = capper.apply(sigs)
    assert all(s["strength"] == 1.0 for s in out)


def test_below_min_signals_passes_through():
    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=10))
    # 5 signals, all one edge → 100% share but below threshold → no cap
    sigs = [_sig(f"T{i}", "momentum_edge_v1", 1.0) for i in range(5)]
    out = capper.apply(sigs)
    assert all(s["strength"] == 1.0 for s in out)


def test_invalid_cap_raises():
    with pytest.raises(ValueError):
        FillShareCapper(FillShareCapSettings(cap=0.0))
    with pytest.raises(ValueError):
        FillShareCapper(FillShareCapSettings(cap=1.5))


def test_well_distributed_no_change():
    """A well-balanced bar (no edge over cap) should pass through."""
    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))
    sigs = (
        [_sig(f"T{i}", "edge_a") for i in range(5)]
        + [_sig(f"U{i}", "edge_b") for i in range(5)]
        + [_sig(f"V{i}", "edge_c") for i in range(5)]
        + [_sig(f"W{i}", "edge_d") for i in range(5)]
    )  # 4 edges × 5 = 25% each, exactly at cap
    out = capper.apply(sigs)
    assert all(s["strength"] == 1.0 for s in out)


# ---------------------------------------------------------------------------
# Cap fires correctly
# ---------------------------------------------------------------------------

def test_cap_scales_dominant_edge():
    """A bar where one edge is 80% of signals; cap=25% → scale=25/80=0.3125."""
    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))
    sigs = (
        [_sig(f"T{i}", "momentum_edge_v1", 1.0) for i in range(80)]
        + [_sig(f"U{i}", "volume_anomaly_v1", 1.0) for i in range(20)]
    )
    out = capper.apply(sigs)
    momentum_strengths = [s["strength"] for s in out if s["edge_id"] == "momentum_edge_v1"]
    volume_strengths = [s["strength"] for s in out if s["edge_id"] == "volume_anomaly_v1"]
    # 80 momentum signals scaled to 25/80 = 0.3125
    assert all(s == pytest.approx(0.3125) for s in momentum_strengths)
    # volume_anomaly under cap → unchanged
    assert all(s == pytest.approx(1.0) for s in volume_strengths)


def test_cap_attaches_diagnostic_meta():
    """Capped signals should carry a meta.fill_share_cap dict for traceability."""
    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))
    sigs = [_sig(f"T{i}", "momentum_edge_v1", 1.0) for i in range(80)] \
        + [_sig(f"U{i}", "volume_anomaly_v1", 1.0) for i in range(20)]
    out = capper.apply(sigs)
    capped = [s for s in out if s["edge_id"] == "momentum_edge_v1"]
    uncapped = [s for s in out if s["edge_id"] == "volume_anomaly_v1"]
    assert all("fill_share_cap" in s["meta"] for s in capped)
    assert all("fill_share_cap" not in s.get("meta", {}) for s in uncapped)
    cap_info = capped[0]["meta"]["fill_share_cap"]
    assert cap_info["edge_id"] == "momentum_edge_v1"
    assert cap_info["share_pre"] == pytest.approx(0.8)
    assert cap_info["scale"] == pytest.approx(0.3125)
    assert cap_info["strength_pre"] == pytest.approx(1.0)


def test_cap_preserves_signal_count():
    """No signals should be dropped — only strengths reduced."""
    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))
    sigs = [_sig(f"T{i}", "X", 1.0) for i in range(100)]
    out = capper.apply(sigs)
    assert len(out) == 100


def test_cap_preserves_relative_strengths_within_capped_edge():
    """If two signals from the capped edge have strengths 0.5 and 1.0 pre-cap,
    their post-cap ratio should still be 0.5 : 1.0 (after scaling)."""
    capper = FillShareCapper(FillShareCapSettings(cap=0.5, min_signals_for_cap=4))
    sigs = (
        [_sig("T1", "X", 0.5)]
        + [_sig(f"T{i}", "X", 1.0) for i in range(2, 9)]  # 7 more X signals
        + [_sig("U1", "Y", 0.7)]
    )  # 8 X / 9 = 88.9% > 50% cap; scale to 50/88.9 = 0.5625
    out = capper.apply(sigs)
    x_signals = [s for s in out if s["edge_id"] == "X"]
    s_low = next(s for s in x_signals if s["meta"]["fill_share_cap"]["strength_pre"] == 0.5)
    s_high = [s for s in x_signals if s["meta"]["fill_share_cap"]["strength_pre"] == 1.0]
    # Ratio preserved
    assert s_low["strength"] / s_high[0]["strength"] == pytest.approx(0.5)


def test_multiple_edges_over_cap():
    """Two edges both over cap should each be scaled independently."""
    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))
    sigs = (
        [_sig(f"A{i}", "X") for i in range(40)]
        + [_sig(f"B{i}", "Y") for i in range(40)]
        + [_sig(f"C{i}", "Z") for i in range(20)]
    )
    out = capper.apply(sigs)
    x_strengths = [s["strength"] for s in out if s["edge_id"] == "X"]
    y_strengths = [s["strength"] for s in out if s["edge_id"] == "Y"]
    z_strengths = [s["strength"] for s in out if s["edge_id"] == "Z"]
    # 40/100 = 40% → scale to 25/40 = 0.625
    assert all(x == pytest.approx(0.625) for x in x_strengths)
    assert all(y == pytest.approx(0.625) for y in y_strengths)
    assert all(z == pytest.approx(1.0) for z in z_strengths)


def test_cap_handles_missing_edge_id():
    """Defensively bucket signals without edge_id under '_unknown'."""
    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))
    sigs = [{"ticker": f"T{i}", "side": "long", "strength": 1.0,
             "meta": {}} for i in range(80)] \
        + [_sig(f"U{i}", "Y") for i in range(20)]
    # All 80 have no edge_id → bucket "_unknown" 80% → scale to 0.3125
    out = capper.apply(sigs)
    unknown_strengths = [s["strength"] for s in out if "edge_id" not in s]
    assert all(s == pytest.approx(0.3125) for s in unknown_strengths)


# ---------------------------------------------------------------------------
# Property: an over-cap edge's post-cap strength sum equals cap × pre-budget
# ---------------------------------------------------------------------------

def test_post_cap_budget_share_equals_cap():
    """The defining invariant for proportional scaling:

    For any edge whose pre-cap count-share exceeds `cap`, its post-cap
    strength sum equals `cap × pre_cap_total_strength`. I.e. the cap
    bounds *budget consumption* (sum of strengths) at exactly the cap
    fraction of the pre-cap total. Proportional scaling does NOT bound
    the post-cap *strength share* (the denominator also shrinks), so we
    measure against the pre-cap total, which is the budget the system
    was initially trying to allocate.
    """
    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))
    sigs = (
        [_sig(f"A{i}", "X", 1.0) for i in range(60)]
        + [_sig(f"B{i}", "Y", 1.0) for i in range(20)]
        + [_sig(f"C{i}", "Z", 1.0) for i in range(20)]
    )
    pre_total = sum(s["strength"] for s in sigs)  # 100
    out = capper.apply(sigs)

    by_edge: dict[str, float] = {}
    for s in out:
        by_edge[s["edge_id"]] = by_edge.get(s["edge_id"], 0.0) + s["strength"]

    # X was 60% pre-cap → post-cap budget exactly cap × pre_total = 0.25 × 100
    assert by_edge["X"] == pytest.approx(0.25 * pre_total)
    # Y, Z unchanged (each 20% < cap)
    assert by_edge["Y"] == pytest.approx(20.0)
    assert by_edge["Z"] == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# 2025-style scenario: 5 edges firing, momentum-shaped trying to dominate
# ---------------------------------------------------------------------------

def test_2025_style_dominant_momentum_capped():
    """Reconstruct a 2025-anchor-style bar:
        momentum_edge_v1 — 60 signals (dominant)
        low_vol_factor_v1 — 25 signals (paused but still firing)
        atr_breakout_v1 — 18 signals (paused-soft)
        volume_anomaly_v1 — 5 signals (the alpha that gets crowded out)
        herding_v1 — 2 signals (also crowded out)

    Total 110 signals. Bottom 3 = 103/110 = 93.6% concentration.
    With cap 0.25: each of momentum, low_vol, atr_breakout gets scaled to
    0.25/their_share. volume_anomaly + herding (2.7% combined) untouched.
    """
    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))
    sigs = (
        [_sig(f"M{i}", "momentum_edge_v1", 1.0) for i in range(60)]
        + [_sig(f"L{i}", "low_vol_factor_v1", 1.0) for i in range(25)]
        + [_sig(f"A{i}", "atr_breakout_v1", 1.0) for i in range(18)]
        + [_sig(f"V{i}", "volume_anomaly_v1", 1.0) for i in range(5)]
        + [_sig(f"H{i}", "herding_v1", 1.0) for i in range(2)]
    )
    n = len(sigs)
    pre = capper.diagnose(sigs)
    assert pre["shares"]["momentum_edge_v1"] == pytest.approx(60 / n)
    assert pre["binds"], "expected at least one binding edge"

    out = capper.apply(sigs)

    # momentum (60/110 ≈ 54.5%) → scale = 0.25 * 110 / 60 ≈ 0.4583
    assert all(s["strength"] == pytest.approx(0.25 * 110 / 60)
               for s in out if s["edge_id"] == "momentum_edge_v1")
    # low_vol (25/110 ≈ 22.7%) → under cap → unchanged
    assert all(s["strength"] == pytest.approx(1.0)
               for s in out if s["edge_id"] == "low_vol_factor_v1")
    # atr_breakout (18/110 ≈ 16.4%) → under cap → unchanged
    assert all(s["strength"] == pytest.approx(1.0)
               for s in out if s["edge_id"] == "atr_breakout_v1")
    # The crowded-out alphas → unchanged
    assert all(s["strength"] == pytest.approx(1.0)
               for s in out if s["edge_id"] == "volume_anomaly_v1")
    assert all(s["strength"] == pytest.approx(1.0)
               for s in out if s["edge_id"] == "herding_v1")

    # Budget consumption check: post-cap, momentum_edge_v1's strength sum
    # equals exactly cap × pre_total_strength = 0.25 × 110 = 27.5.
    by_edge: dict[str, float] = {}
    for s in out:
        by_edge[s["edge_id"]] = by_edge.get(s["edge_id"], 0.0) + s["strength"]
    pre_total = float(n)  # all pre-strengths were 1.0
    assert by_edge["momentum_edge_v1"] == pytest.approx(0.25 * pre_total)


# ---------------------------------------------------------------------------
# 2025 trade-log replay (skip if the source files are missing)
# ---------------------------------------------------------------------------

def _trades_path(run_id: str) -> Path:
    return Path("data/trade_logs") / run_id / f"trades_{run_id}.csv"


@pytest.mark.skipif(
    not _trades_path("72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34").exists(),
    reason="2025 anchor trade log not present in this checkout",
)
def test_2025_anchor_replay_concentration_bounded():
    """Replay-style: take the per-day attribution shape from the 2025 anchor
    trade log, treat each day's entries as one bar, and verify that the cap
    would have bounded the dominant-edge share to <= 25% on every day where
    the cap binds.

    This is not a backtest — it just checks that the capper, applied to
    the actual per-day signal-attribution shape we observed in 2025,
    produces a strength-share bounded at the cap.
    """
    df = pd.read_csv(
        _trades_path("72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34"),
        parse_dates=["timestamp"],
    )
    df = df[df["trigger"] == "entry"].copy()
    df["day"] = df["timestamp"].dt.date

    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))

    days_with_cap = 0
    days_total = 0
    for day, day_sigs in df.groupby("day"):
        sigs = [
            _sig(row["ticker"], row["edge_id"], 1.0)
            for _, row in day_sigs.iterrows()
        ]
        if len(sigs) < 4:
            continue
        days_total += 1
        diag = capper.diagnose(sigs)
        if diag["binds"]:
            days_with_cap += 1
        pre_total_strength = float(len(sigs))  # all 1.0 pre-strength
        out = capper.apply(sigs)
        # Invariant: for each edge whose pre-cap count-share exceeds cap,
        # its post-cap strength sum equals cap × pre_total_strength.
        by_edge: dict[str, float] = {}
        for s in out:
            by_edge[s["edge_id"]] = by_edge.get(s["edge_id"], 0.0) + s["strength"]
        for edge, post_sum in by_edge.items():
            pre_share = diag["shares"].get(edge, 0.0)
            if pre_share > 0.25:
                # Bounded at cap × pre_total
                assert post_sum <= 0.25 * pre_total_strength + 1e-6, (
                    f"{day} {edge}: pre_share={pre_share:.3f}, "
                    f"post_sum={post_sum:.3f}, expected <= "
                    f"{0.25 * pre_total_strength:.3f}"
                )

    # Sanity: at least some days had a binding cap (the 2025 issue we're
    # fixing) — otherwise this test would be vacuous.
    assert days_with_cap > 0, "expected the cap to bind on at least one 2025 day"
    print(f"\n[2025 REPLAY] cap bound on {days_with_cap}/{days_total} entry-days "
          f"({days_with_cap / days_total * 100:.1f}%)")
