"""
tests/test_metalearner.py
==========================
Tests for ``engines/engine_a_alpha/metalearner.py`` — the Layer 3
profile-aware combiner.

Coverage:
  - Cold-start fallback (untrained predict returns 0.0 — safe to wire
    into signal_processor before any training)
  - fit/predict happy path (recovers a known relationship)
  - Feature alignment: predict with wrong columns raises; reordering
    the same columns succeeds
  - save/load round-trip preserves predictions exactly
  - target_clip bounds out-of-distribution predictions
  - Profile-flip: same X, different y (different profile) produces
    different model weights
  - Insufficient training data raises a clear error
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.metalearner import (
    DEFAULT_HYPERPARAMS,
    MetaLearner,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _synthetic_features(n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame({
        "edge_a": rng.normal(0.0, 0.01, n),
        "edge_b": rng.normal(0.0, 0.01, n),
        "edge_c": rng.normal(0.0, 0.005, n),
    })


def _target_from_features(
    X: pd.DataFrame,
    weights: dict | None = None,
    noise_std: float = 0.001,
    seed: int = 1,
) -> pd.Series:
    """y = w_a*edge_a + w_b*edge_b + w_c*edge_c + noise."""
    weights = weights or {"edge_a": 0.5, "edge_b": 0.3, "edge_c": -0.2}
    rng = np.random.default_rng(seed)
    base = sum(w * X[k] for k, w in weights.items())
    return pd.Series(base + rng.normal(0.0, noise_std, len(X)), index=X.index)


# ---------------------------------------------------------------------------
# Cold-start safety
# ---------------------------------------------------------------------------

def test_cold_start_predict_returns_zero_for_dict():
    """Untrained MetaLearner must NOT crash; it returns 0 so callers
    can wire it into signal_processor before any training."""
    ml = MetaLearner(profile_name="balanced")
    assert not ml.is_trained()
    result = ml.predict({"edge_a": 0.1, "edge_b": -0.05})
    assert result == 0.0


def test_cold_start_predict_returns_zeros_for_dataframe():
    ml = MetaLearner(profile_name="balanced")
    X = _synthetic_features(n=10)
    out = ml.predict(X)
    assert isinstance(out, np.ndarray)
    assert (out == 0.0).all()
    assert len(out) == 10


def test_load_missing_file_returns_cold_start_instance(tmp_path):
    """No model file → load returns an untrained instance, not a crash."""
    ml = MetaLearner.load(profile_name="balanced", model_dir=tmp_path)
    assert isinstance(ml, MetaLearner)
    assert not ml.is_trained()
    assert ml.predict({"edge_a": 0.1}) == 0.0


# ---------------------------------------------------------------------------
# fit / predict happy path
# ---------------------------------------------------------------------------

def test_fit_recovers_known_linear_relationship():
    X = _synthetic_features(n=300, seed=10)
    y = _target_from_features(X, noise_std=0.0001, seed=11)  # very low noise
    ml = MetaLearner(profile_name="test")
    ml.fit(X, y)

    assert ml.is_trained()
    assert ml.feature_names == ["edge_a", "edge_b", "edge_c"]
    # Train R² should be very high given low noise
    assert ml.train_metadata["train_score_r2"] > 0.7

    # Predictions on training data should correlate strongly with target
    preds = ml.predict(X)
    corr = float(np.corrcoef(preds, y.values)[0, 1])
    assert corr > 0.7


def test_fit_returns_self_for_chaining():
    X = _synthetic_features(n=100)
    y = _target_from_features(X)
    ml = MetaLearner(profile_name="test")
    result = ml.fit(X, y)
    assert result is ml


def test_predict_scalar_for_scalar_input():
    """predict(dict) → float; predict(Series) → float; predict(DataFrame) → ndarray."""
    X = _synthetic_features(n=200)
    y = _target_from_features(X)
    ml = MetaLearner().fit(X, y)

    one_dict = ml.predict({"edge_a": 0.005, "edge_b": 0.003, "edge_c": -0.002})
    assert isinstance(one_dict, float)

    one_series = ml.predict(X.iloc[0])
    assert isinstance(one_series, float)

    batch = ml.predict(X.head(5))
    assert isinstance(batch, np.ndarray)
    assert len(batch) == 5


# ---------------------------------------------------------------------------
# Feature alignment
# ---------------------------------------------------------------------------

def test_predict_missing_features_raises():
    X = _synthetic_features(n=100)
    y = _target_from_features(X)
    ml = MetaLearner().fit(X, y)
    bad = pd.DataFrame({"edge_a": [0.0]})  # missing edge_b, edge_c
    with pytest.raises(ValueError, match="missing features"):
        ml.predict(bad)


def test_predict_with_extra_columns_ignored():
    """Extra columns in predict input are dropped; the trained order
    is used."""
    X = _synthetic_features(n=100)
    y = _target_from_features(X)
    ml = MetaLearner().fit(X, y)

    X_extra = X.copy()
    X_extra["edge_unused"] = 0.999  # extra column
    preds = ml.predict(X_extra.head(3))
    # Should produce sane finite predictions, ignoring edge_unused
    assert all(np.isfinite(preds))


def test_predict_reorders_columns_to_trained_order():
    X = _synthetic_features(n=100)
    y = _target_from_features(X)
    ml = MetaLearner().fit(X, y)

    # Same columns, reverse order
    X_reordered = X[["edge_c", "edge_b", "edge_a"]].head(5)
    preds_reordered = ml.predict(X_reordered)

    # Should match predictions on the original column order
    preds_original = ml.predict(X.head(5))
    np.testing.assert_array_almost_equal(preds_reordered, preds_original)


# ---------------------------------------------------------------------------
# save / load round-trip
# ---------------------------------------------------------------------------

def test_save_load_roundtrip_preserves_predictions(tmp_path):
    X = _synthetic_features(n=200)
    y = _target_from_features(X)
    ml = MetaLearner(profile_name="rt").fit(X, y)
    saved_path = ml.save(model_dir=tmp_path)
    assert saved_path.exists()

    loaded = MetaLearner.load(profile_name="rt", model_dir=tmp_path)
    assert loaded.is_trained()
    assert loaded.feature_names == ml.feature_names

    preds_before = ml.predict(X.head(20))
    preds_after = loaded.predict(X.head(20))
    np.testing.assert_array_almost_equal(preds_after, preds_before)


def test_save_untrained_raises(tmp_path):
    ml = MetaLearner(profile_name="empty")
    with pytest.raises(RuntimeError, match="untrained"):
        ml.save(model_dir=tmp_path)


def test_save_includes_profile_name_in_filename(tmp_path):
    X = _synthetic_features(n=100)
    y = _target_from_features(X)
    ml1 = MetaLearner(profile_name="retiree").fit(X, y)
    ml2 = MetaLearner(profile_name="growth").fit(X, y)
    p1 = ml1.save(model_dir=tmp_path)
    p2 = ml2.save(model_dir=tmp_path)

    assert "retiree" in str(p1)
    assert "growth" in str(p2)
    assert p1 != p2


# ---------------------------------------------------------------------------
# Output bounds (target_clip)
# ---------------------------------------------------------------------------

def test_predict_clipped_to_target_range_on_extreme_input():
    """An out-of-distribution feature vector shouldn't produce a
    prediction wildly outside the training target range."""
    X = _synthetic_features(n=200)
    y = _target_from_features(X)
    ml = MetaLearner().fit(X, y)

    # Feature value 100x beyond training distribution
    extreme = {col: 1.0 for col in ml.feature_names}
    pred = ml.predict(extreme)
    assert abs(pred) <= ml.target_clip, (
        f"Prediction {pred} exceeds target_clip {ml.target_clip}"
    )


# ---------------------------------------------------------------------------
# Profile awareness
# ---------------------------------------------------------------------------

def test_different_targets_produce_different_models():
    """Same X, different y (e.g. different profile fitness) → different
    fitted models. This verifies that the meta-learner truly is
    profile-aware: training against `retiree` fitness vs `growth`
    fitness produces distinct allocation models."""
    X = _synthetic_features(n=300)
    y_retiree = _target_from_features(X, weights={"edge_a": 0.7, "edge_b": 0.3, "edge_c": -0.1})
    y_growth = _target_from_features(X, weights={"edge_a": -0.2, "edge_b": 0.5, "edge_c": 0.7})

    ml_r = MetaLearner(profile_name="retiree").fit(X, y_retiree)
    ml_g = MetaLearner(profile_name="growth").fit(X, y_growth)

    preds_r = ml_r.predict(X.head(20))
    preds_g = ml_g.predict(X.head(20))

    # Predictions should differ — same X, different y → different model
    assert not np.allclose(preds_r, preds_g)


# ---------------------------------------------------------------------------
# Validation of training inputs
# ---------------------------------------------------------------------------

def test_fit_empty_X_raises():
    ml = MetaLearner()
    with pytest.raises(ValueError, match="empty X"):
        ml.fit(pd.DataFrame(columns=["edge_a"]), pd.Series([], dtype=float))


def test_fit_length_mismatch_raises():
    ml = MetaLearner()
    X = _synthetic_features(n=100)
    y = pd.Series([0.0] * 50)  # length 50, X has 100
    with pytest.raises(ValueError, match="length mismatch"):
        ml.fit(X, y)


def test_fit_too_few_samples_raises():
    """After NaN drop, fewer than 30 rows → fit refuses (training noise floor)."""
    X = _synthetic_features(n=20)  # below the 30-sample minimum
    y = _target_from_features(X)
    ml = MetaLearner()
    with pytest.raises(ValueError, match="Insufficient training samples"):
        ml.fit(X, y)


def test_fit_drops_nan_targets_silently():
    """NaN in y (e.g. forward target undefined at end of window) gets dropped."""
    X = _synthetic_features(n=100)
    y = _target_from_features(X)
    y.iloc[-10:] = np.nan  # last 10 forward targets unavailable
    ml = MetaLearner()
    ml.fit(X, y)
    # n_train_samples should reflect the drop
    assert ml.n_train_samples == 90


# ---------------------------------------------------------------------------
# Hyperparameter customization
# ---------------------------------------------------------------------------

def test_default_hyperparams_locked_in():
    """Adding/removing a default hyperparam is a real behavior change."""
    expected = {"n_estimators", "max_depth", "learning_rate",
                "subsample", "min_samples_split", "random_state"}
    assert set(DEFAULT_HYPERPARAMS.keys()) == expected


def test_custom_hyperparams_propagate_to_model():
    X = _synthetic_features(n=200)
    y = _target_from_features(X)
    ml = MetaLearner(hyperparams={"n_estimators": 50, "max_depth": 2,
                                   "learning_rate": 0.1, "random_state": 0})
    ml.fit(X, y)
    # Sklearn GBR exposes n_estimators on the fitted model
    assert ml._model.n_estimators == 50
    assert ml._model.max_depth == 2
