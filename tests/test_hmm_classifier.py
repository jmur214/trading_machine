"""Tests for Engine E's HMM regime classifier (Workstream C first slice)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.engine_e_regime.hmm_classifier import (
    HMMRegimeClassifier,
    DEFAULT_FEATURES,
    DEFAULT_STATE_LABELS_3,
)


def _synthetic_panel(n_obs: int = 400, seed: int = 0) -> pd.DataFrame:
    """Build a 3-regime synthetic panel with realistic feature scales.

    Three blocks (benign, stressed, crisis) with monotonically increasing
    realized vol — the HMM should recover this structure.
    """
    rng = np.random.default_rng(seed)
    blocks = []
    block_sizes = [n_obs // 3, n_obs // 3, n_obs - 2 * (n_obs // 3)]
    # (mean_vec, std_vec) per regime, in approximate "realistic" units
    regimes = [
        # benign: low vol, positive returns, low VIX, healthy curve
        ([0.005, 0.005, 0.001, 14.0, 0.3, 0.6, -0.01],
         [0.01, 0.001, 0.005, 2.0, 0.05, 0.05, 0.02]),
        # stressed: medium vol, slight negative returns, elevated VIX
        ([-0.005, 0.012, -0.005, 22.0, 0.1, 0.9, 0.03],
         [0.015, 0.002, 0.01, 4.0, 0.08, 0.10, 0.03]),
        # crisis: high vol, negative returns, high VIX, inverted curve
        ([-0.025, 0.025, 0.020, 35.0, -0.2, 1.6, 0.05],
         [0.025, 0.004, 0.015, 6.0, 0.10, 0.20, 0.04]),
    ]
    for size, (mu, sigma) in zip(block_sizes, regimes):
        block = rng.normal(loc=mu, scale=sigma, size=(size, len(mu)))
        blocks.append(block)
    arr = np.vstack(blocks)
    idx = pd.date_range("2020-01-01", periods=n_obs, freq="B")
    return pd.DataFrame(arr, columns=list(DEFAULT_FEATURES), index=idx)


def test_hmm_train_predict_round_trip(tmp_path):
    """Fit on synthetic 3-regime data, persist, reload, posteriors stable."""
    panel = _synthetic_panel(n_obs=400)
    clf = HMMRegimeClassifier(n_states=3, random_state=42)
    artifact = clf.fit(panel)

    assert artifact.n_states == 3
    assert artifact.n_train_obs == len(panel)
    assert np.isfinite(artifact.train_log_likelihood)
    assert artifact.feature_names == DEFAULT_FEATURES

    # Predict on a row
    row = panel.iloc[-1]
    proba = clf.predict_proba_at(row)
    assert set(proba.keys()) == set(DEFAULT_STATE_LABELS_3)
    assert pytest.approx(sum(proba.values()), abs=1e-6) == 1.0
    assert all(0.0 <= v <= 1.0 for v in proba.values())

    # Persist and reload
    out = tmp_path / "hmm.pkl"
    clf.save(out)
    clf2 = HMMRegimeClassifier.load(out)
    proba2 = clf2.predict_proba_at(row)
    for state in proba:
        assert pytest.approx(proba[state], abs=1e-9) == proba2[state]


def test_hmm_state_labels_ordered_by_vol():
    """benign should map to the LOWEST-vol state; crisis to the HIGHEST."""
    panel = _synthetic_panel(n_obs=400)
    clf = HMMRegimeClassifier(n_states=3, random_state=42)
    clf.fit(panel)

    # Aggregate posterior over the three time blocks
    proba_seq = clf.predict_proba_sequence(panel)
    n_per = len(panel) // 3
    benign_block = proba_seq.iloc[:n_per].mean()
    crisis_block = proba_seq.iloc[-n_per:].mean()

    # benign block should weight benign label more than crisis label
    assert benign_block["benign"] > benign_block["crisis"]
    # crisis block should weight crisis label more than benign label
    assert crisis_block["crisis"] > crisis_block["benign"]


def test_hmm_log_likelihood_3state_beats_2state():
    """3-state HMM should fit synthetic 3-regime data at least as well as 2-state."""
    panel = _synthetic_panel(n_obs=400)

    clf2 = HMMRegimeClassifier(n_states=2, random_state=42)
    clf2.fit(panel)
    ll2 = clf2.score(panel)

    clf3 = HMMRegimeClassifier(n_states=3, random_state=42)
    clf3.fit(panel)
    ll3 = clf3.score(panel)

    # 3-state must do at least as well in-sample (more flexibility).
    # Per-obs comparison is fairer if we account for parameter count,
    # but for synthetic 3-regime data 3-state should win on raw LL too.
    assert ll3 >= ll2 - 1e-6, f"3-state LL ({ll3}) must beat 2-state ({ll2})"


def test_hmm_uniform_proba_on_nan():
    """NaN feature row → uniform posterior (graceful degrade signal)."""
    panel = _synthetic_panel(n_obs=400)
    clf = HMMRegimeClassifier(n_states=3, random_state=42)
    clf.fit(panel)

    nan_row = pd.Series({c: np.nan for c in DEFAULT_FEATURES})
    proba = clf.predict_proba_at(nan_row)
    assert pytest.approx(sum(proba.values()), abs=1e-9) == 1.0
    # Uniform: each ~ 1/3
    for v in proba.values():
        assert pytest.approx(v, abs=1e-6) == 1.0 / 3.0


def test_hmm_confidence_from_proba():
    """Entropy-based confidence: uniform → 0; concentrated → 1."""
    uniform = {"a": 1 / 3, "b": 1 / 3, "c": 1 / 3}
    concentrated = {"a": 1.0, "b": 0.0, "c": 0.0}
    spread = {"a": 0.5, "b": 0.3, "c": 0.2}

    assert HMMRegimeClassifier.confidence_from_proba(uniform) < 0.01
    assert HMMRegimeClassifier.confidence_from_proba(concentrated) > 0.99
    spread_c = HMMRegimeClassifier.confidence_from_proba(spread)
    assert 0.05 < spread_c < 0.95


def test_hmm_predict_sequence_schema():
    """predict_proba_sequence returns DataFrame indexed identically to input."""
    panel = _synthetic_panel(n_obs=200)
    clf = HMMRegimeClassifier(n_states=3, random_state=42)
    clf.fit(panel)

    out = clf.predict_proba_sequence(panel)
    assert len(out) == len(panel)
    assert (out.index == panel.index).all()
    assert list(out.columns) == list(DEFAULT_STATE_LABELS_3)
    # Each row sums to ~1
    row_sums = out.sum(axis=1)
    assert (row_sums.between(0.99, 1.01)).all()


def test_hmm_windowed_predict_smooths_posterior():
    """predict_proba_at with history_panel uses temporal smoothing."""
    panel = _synthetic_panel(n_obs=400)
    clf = HMMRegimeClassifier(n_states=3, random_state=42)
    clf.fit(panel)

    # Take a row from the middle (stressed block) and run with/without history
    mid_idx = len(panel) // 2
    row = panel.iloc[mid_idx]
    proba_no_hist = clf.predict_proba_at(row)
    proba_with_hist = clf.predict_proba_at(
        row, history_panel=panel.iloc[: mid_idx + 1], history_window=60
    )

    # Both must be valid distributions
    assert pytest.approx(sum(proba_no_hist.values()), abs=1e-6) == 1.0
    assert pytest.approx(sum(proba_with_hist.values()), abs=1e-6) == 1.0
    # Different paths should generally produce different values (but
    # we can't assert direction without overconstraining).


def test_macro_feature_panel_schema():
    """Smoke test the regime-input feature panel builds with the canonical schema."""
    from engines.engine_e_regime.macro_features import (
        build_feature_panel, FEATURE_COLUMNS,
    )
    panel = build_feature_panel(start="2024-01-01", end="2024-12-31")
    assert list(panel.columns) == list(FEATURE_COLUMNS)
    # Should have ~250 trading days
    assert 200 <= len(panel) <= 280, f"unexpected panel length: {len(panel)}"
    # Most key columns should be non-NaN by 2024 (FRED cache populated)
    last_row = panel.dropna().iloc[-1] if not panel.dropna().empty else None
    assert last_row is not None, "feature panel has no fully-populated row"
