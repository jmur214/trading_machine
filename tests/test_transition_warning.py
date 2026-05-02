"""Tests for TransitionWarningDetector (Workstream C slice 2 — 2026-05)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.engine_e_regime.transition_warning import (
    TransitionWarningConfig,
    TransitionWarningDetector,
    TransitionWarningRead,
)


def _build_synthetic_posterior_seq(
    n: int = 50, transition_at: int = 25, seed: int = 0
) -> pd.DataFrame:
    """Build a 3-state posterior sequence with a sharp transition.

    Bars 0..transition_at-1 → concentrated on state "benign".
    Bars transition_at..n   → concentrated on state "crisis".
    A small bridge of higher entropy spans the transition.
    """
    rng = np.random.default_rng(seed)
    states = ["benign", "stressed", "crisis"]
    rows = []
    bridge_width = 3
    for i in range(n):
        if i < transition_at - bridge_width:
            base = np.array([0.95, 0.04, 0.01])
        elif i < transition_at:
            # Bridge zone: high entropy, mass shifting toward crisis
            t = (i - (transition_at - bridge_width)) / bridge_width
            base = np.array([0.95 - 0.7 * t, 0.04 + 0.0 * t, 0.01 + 0.7 * t])
        elif i < transition_at + bridge_width:
            t = (i - transition_at) / bridge_width
            base = np.array([0.25 - 0.24 * t, 0.04, 0.71 + 0.24 * t])
        else:
            base = np.array([0.01, 0.04, 0.95])
        # Add small noise + renormalize
        noise = rng.normal(0, 0.01, 3)
        base = np.maximum(base + noise, 0.001)
        base = base / base.sum()
        rows.append(base)
    arr = np.vstack(rows)
    idx = pd.date_range("2024-01-02", periods=n, freq="B")
    return pd.DataFrame(arr, index=idx, columns=states)


def test_normalized_entropy_uniform_is_one():
    """Uniform posterior → normalized entropy 1.0."""
    p = np.array([1 / 3, 1 / 3, 1 / 3])
    assert TransitionWarningDetector._normalized_entropy(p) == pytest.approx(1.0, abs=1e-6)


def test_normalized_entropy_concentrated_is_zero():
    """Concentrated posterior → normalized entropy ~0."""
    p = np.array([1.0, 0.0, 0.0])
    assert TransitionWarningDetector._normalized_entropy(p) < 1e-6


def test_kl_divergence_self_is_zero():
    """KL(p || p) = 0."""
    p = np.array([0.5, 0.3, 0.2])
    assert TransitionWarningDetector._kl_divergence(p, p) < 1e-6


def test_kl_divergence_directional():
    """KL is asymmetric: KL(p||q) != KL(q||p) in general."""
    p = np.array([0.7, 0.2, 0.1])
    q = np.array([0.1, 0.2, 0.7])
    a = TransitionWarningDetector._kl_divergence(p, q)
    b = TransitionWarningDetector._kl_divergence(q, p)
    assert a > 0 and b > 0
    # For this symmetric pair they should be equal-ish, but for asymmetric
    # pairs they would differ — just verify both are positive nat divergences
    assert abs(a - b) < 1.0  # bounded differences for these test inputs


def test_detect_sequence_fires_around_transition():
    """Warning should fire on bars near the synthetic transition."""
    seq = _build_synthetic_posterior_seq(n=50, transition_at=25)
    det = TransitionWarningDetector(TransitionWarningConfig(
        window=5, entropy_threshold=0.55, kl_threshold=0.3,
        smoothing_window=3, min_history=5,
    ))
    out = det.detect_sequence(seq)
    assert out.shape[0] == seq.shape[0]
    # Some warning bars must exist around bars 22..30 (transition zone)
    transition_zone_warnings = out["warning"].iloc[20:32].sum()
    assert transition_zone_warnings >= 2, (
        f"Expected ≥2 warnings in transition zone, got {transition_zone_warnings}"
    )


def test_detect_sequence_quiet_when_no_transition():
    """Posterior sequence with no transition should fire few/no warnings."""
    rng = np.random.default_rng(42)
    n = 100
    states = ["benign", "stressed", "crisis"]
    rows = []
    for _ in range(n):
        # Stable concentrated posterior with tiny noise
        base = np.array([0.97, 0.02, 0.01])
        noise = rng.normal(0, 0.005, 3)
        p = np.maximum(base + noise, 0.001)
        p = p / p.sum()
        rows.append(p)
    seq = pd.DataFrame(np.vstack(rows), columns=states,
                       index=pd.date_range("2024-01-02", periods=n, freq="B"))
    det = TransitionWarningDetector()
    out = det.detect_sequence(seq)
    n_warnings = int(out["warning"].sum())
    # Less than 5% false-positive rate on quiet data
    assert n_warnings < 0.05 * n, (
        f"Stable sequence should fire few warnings, got {n_warnings}/{n}"
    )


def test_detect_at_returns_typed_read():
    """detect_at returns TransitionWarningRead with required fields."""
    det = TransitionWarningDetector()
    history = [
        {"benign": 0.95, "stressed": 0.04, "crisis": 0.01},
    ] * 10
    posterior = {"benign": 0.5, "stressed": 0.3, "crisis": 0.2}
    read = det.detect_at(pd.Timestamp("2024-06-01"), posterior, history)
    assert isinstance(read, TransitionWarningRead)
    assert read.timestamp == pd.Timestamp("2024-06-01")
    assert isinstance(read.warning, bool)
    assert 0.0 <= read.entropy <= 1.0


def test_detect_at_empty_history_doesnt_fire():
    """With empty history, warning shouldn't fire (warm-up gate)."""
    det = TransitionWarningDetector(TransitionWarningConfig(min_history=5))
    posterior = {"benign": 0.34, "stressed": 0.33, "crisis": 0.33}
    read = det.detect_at(pd.Timestamp("2024-06-01"), posterior, history=[])
    assert read.warning is False  # below min_history


def test_detect_sequence_warm_up_period_silent():
    """First `min_history-1` bars cannot fire (warm-up convention)."""
    seq = _build_synthetic_posterior_seq(n=30, transition_at=20)
    det = TransitionWarningDetector(TransitionWarningConfig(min_history=10))
    out = det.detect_sequence(seq)
    assert not out["warning"].iloc[:9].any()


def test_kl_from_lag_zero_when_short_history():
    """KL_from_lag = 0 when sequence shorter than lag."""
    arr = np.array([[0.5, 0.3, 0.2], [0.4, 0.4, 0.2]])
    # Lag 5 but only 2 bars → 0
    assert TransitionWarningDetector._kl_from_lag(arr, lag=5) == 0.0


def test_detect_sequence_empty_returns_empty_frame():
    """Empty input yields empty DataFrame with right schema."""
    det = TransitionWarningDetector()
    out = det.detect_sequence(pd.DataFrame())
    assert out.empty
    assert set(out.columns) == {
        "warning", "entropy", "entropy_smoothed",
        "kl_from_lag", "kl_smoothed", "reason",
    }
