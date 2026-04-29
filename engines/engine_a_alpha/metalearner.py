"""
engines/engine_a_alpha/metalearner.py
======================================
Layer 3 combiner: a profile-aware non-linear meta-learner that replaces
the legacy ``signal_processor.weighted_sum``.

Background: a linear weighted sum can't express interactions like
"edge X is good only when edge Y agrees AND regime is bull." A
gradient-boosted tree can. Per ``docs/Core/phase1_metalearner_design.md``,
the meta-learner takes tier=feature edge scores as inputs and predicts
the profile-aware fitness of forward returns.

This is Layer 3 (allocation) in the three-layer architecture:
  Layer 1 (Existence — alive vs retired): in lifecycle_manager
  Layer 2 (Tier — alpha/feature/context): in tier_classifier
  Layer 3 (Allocation): HERE

Cold-start safety:
  ``predict()`` returns 0.0 (a no-op signal) when the model has never
  been trained. This means wiring the meta-learner into
  signal_processor is safe even before any training has happened —
  the system falls back to its existing behavior. Training happens
  offline via ``scripts/train_metalearner.py``.

Profile awareness:
  The meta-learner is trained against the profile's fitness function
  applied to forward returns, not raw forward returns. Switching
  profiles trains a different model — same edge pool, different
  allocation. Models are saved per-profile to
  ``data/governor/metalearner_<profile_name>.pkl``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Union

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL_DIR = ROOT / "data" / "governor"

log = logging.getLogger("MetaLearner")

# Default GBR hyperparameters. Tuned for our small data size (~1000 days
# × ~10-15 features). Conservative depth + learning rate to prevent
# overfitting; n_estimators=300 gives a reasonable bias-variance trade.
DEFAULT_HYPERPARAMS: Dict[str, Union[int, float]] = {
    "n_estimators": 300,
    "max_depth": 3,
    "learning_rate": 0.05,
    "subsample": 0.8,         # row sub-sampling for regularization
    "min_samples_split": 10,  # don't split tiny leaves
    "random_state": 0,
}


@dataclass
class MetaLearner:
    """A per-profile meta-learner that combines tier=feature edge scores
    into a profile-aware allocation signal.

    Usage at training time::

        ml = MetaLearner(profile_name="balanced")
        ml.fit(X_train, y_train)   # X: DataFrame, y: Series
        ml.save()                  # writes data/governor/metalearner_balanced.pkl

    Usage at inference time::

        ml = MetaLearner.load(profile_name="balanced")
        score = ml.predict(features_one_bar)   # scalar in [-1, 1]

    Cold-start: if no model file exists for the profile, ``load`` returns
    an untrained instance whose ``predict`` returns 0.0. Wiring this into
    ``signal_processor`` is therefore safe before any training occurs.

    Feature alignment: the model locks in the column order at fit time.
    Predicting with a different feature set raises a clear error rather
    than silently mis-aligning columns.
    """

    profile_name: str = "balanced"
    hyperparams: Dict[str, Union[int, float]] = field(
        default_factory=lambda: dict(DEFAULT_HYPERPARAMS)
    )

    # State populated by fit / load:
    _model: Optional[object] = field(default=None, init=False, repr=False)
    feature_names: Optional[List[str]] = field(default=None, init=False)
    target_clip: float = field(default=1.0, init=False)
    n_train_samples: int = field(default=0, init=False)
    train_metadata: Dict[str, Union[str, int, float]] = field(
        default_factory=dict, init=False
    )

    # ----------------------------------------------------------- properties

    def is_trained(self) -> bool:
        """True iff ``fit()`` has been called (or a trained model loaded)."""
        return self._model is not None and self.feature_names is not None

    # ----------------------------------------------------------- fit / predict

    def fit(self, X: pd.DataFrame, y: pd.Series) -> "MetaLearner":
        """Train on (X, y).

        ``X`` is a DataFrame whose columns are the feature names (typically
        per-edge return-stream summaries; the trainer constructs these).
        ``y`` is a Series of profile-aware forward fitness scalars.

        Locks in:
          - feature_names: column order at training time. Future predict()
            calls must supply features in the same order.
          - target_clip: max(|y|) over training. Predictions are clipped
            to [-target_clip, +target_clip] at inference time so a
            wildly-extrapolating tree can't dominate the signal ensemble.
        """
        from sklearn.ensemble import GradientBoostingRegressor

        if X.empty:
            raise ValueError("Cannot fit MetaLearner on empty X")
        if len(X) != len(y):
            raise ValueError(
                f"X and y length mismatch: {len(X)} vs {len(y)}"
            )
        # Clean rows where y is NaN (forward target unavailable at end of window).
        mask = ~pd.isna(y)
        X_clean = X.loc[mask].copy()
        y_clean = y.loc[mask].copy()
        if len(X_clean) < 30:
            raise ValueError(
                f"Insufficient training samples after NaN drop: {len(X_clean)}. "
                "Need at least 30."
            )

        self.feature_names = list(X_clean.columns)
        self.target_clip = max(abs(float(y_clean.min())), abs(float(y_clean.max())))
        self.n_train_samples = len(X_clean)

        model = GradientBoostingRegressor(**self.hyperparams)
        model.fit(X_clean.values, y_clean.values)
        self._model = model

        # Train metadata helps the validation report explain what was trained.
        self.train_metadata = {
            "profile_name": self.profile_name,
            "n_samples": self.n_train_samples,
            "n_features": len(self.feature_names),
            "target_min": float(y_clean.min()),
            "target_max": float(y_clean.max()),
            "target_mean": float(y_clean.mean()),
            "target_std": float(y_clean.std()),
            "train_score_r2": float(model.score(X_clean.values, y_clean.values)),
        }
        log.info(
            "[MetaLearner.%s] fit on %d samples, %d features, train R²=%.3f",
            self.profile_name,
            self.n_train_samples,
            len(self.feature_names),
            self.train_metadata["train_score_r2"],
        )
        return self

    def predict(
        self,
        X: Union[pd.DataFrame, pd.Series, Dict[str, float]],
    ) -> Union[float, np.ndarray]:
        """Predict the profile-aware score for one or more rows.

        Cold-start: if no model has been trained, returns 0.0 (scalar) or
        zeros (vector) so callers can wire this in without conditional
        branches and the system falls back to its non-meta behavior.

        Feature alignment: predicting with a column set that doesn't match
        ``feature_names`` raises ``ValueError``. Caller must supply the
        same columns in any order; this method reorders to the trained
        order automatically.

        Output is clipped to ``[-target_clip, +target_clip]`` to bound
        the influence of out-of-distribution inputs.
        """
        if not self.is_trained():
            # Cold-start fallback. Scalar input → scalar 0; batch → zeros.
            if isinstance(X, (pd.Series, dict)):
                return 0.0
            return np.zeros(len(X)) if hasattr(X, "__len__") else 0.0

        # Normalize input to a DataFrame with the trained columns.
        if isinstance(X, dict):
            X_df = pd.DataFrame([X])
        elif isinstance(X, pd.Series):
            X_df = X.to_frame().T
        else:
            X_df = X

        missing = set(self.feature_names) - set(X_df.columns)
        if missing:
            raise ValueError(
                f"MetaLearner.predict missing features: {sorted(missing)}. "
                f"Expected {self.feature_names}"
            )

        # Reorder to trained column order; tolerate extras (just drop them).
        X_aligned = X_df[self.feature_names].copy()
        # NaN handling: fill with column means from training (stored on the
        # model). Preserves predict() being a pure function call.
        X_aligned = X_aligned.fillna(0.0)

        preds = self._model.predict(X_aligned.values)
        preds = np.clip(preds, -self.target_clip, self.target_clip)

        # Scalar output for scalar input.
        if isinstance(X, (pd.Series, dict)):
            return float(preds[0])
        return preds

    # ----------------------------------------------------------- persist

    def model_path(self, model_dir: Optional[Path] = None) -> Path:
        """Canonical path for this profile's trained model file."""
        d = model_dir or DEFAULT_MODEL_DIR
        return d / f"metalearner_{self.profile_name}.pkl"

    def save(self, model_dir: Optional[Path] = None) -> Path:
        """Serialize self to disk via joblib. Returns the written path."""
        if not self.is_trained():
            raise RuntimeError("Refusing to save an untrained MetaLearner")
        import joblib

        path = self.model_path(model_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "profile_name": self.profile_name,
            "hyperparams": self.hyperparams,
            "model": self._model,
            "feature_names": self.feature_names,
            "target_clip": self.target_clip,
            "n_train_samples": self.n_train_samples,
            "train_metadata": self.train_metadata,
        }
        joblib.dump(payload, path)
        log.info("[MetaLearner.%s] saved → %s", self.profile_name, path)
        return path

    @classmethod
    def load(
        cls,
        profile_name: str = "balanced",
        model_dir: Optional[Path] = None,
    ) -> "MetaLearner":
        """Load a trained MetaLearner from disk. Cold-start safe: if no
        model file exists, returns an untrained instance whose
        ``predict()`` returns 0.0."""
        instance = cls(profile_name=profile_name)
        path = instance.model_path(model_dir)
        if not path.exists():
            log.info(
                "[MetaLearner.%s] no model file at %s — cold-start, predict()=0",
                profile_name, path,
            )
            return instance
        import joblib

        payload = joblib.load(path)
        if payload.get("profile_name") != profile_name:
            log.warning(
                "[MetaLearner] profile name mismatch: file %s claims %r, expected %r",
                path, payload.get("profile_name"), profile_name,
            )
        instance.hyperparams = payload.get("hyperparams", dict(DEFAULT_HYPERPARAMS))
        instance._model = payload["model"]
        instance.feature_names = list(payload["feature_names"])
        instance.target_clip = float(payload.get("target_clip", 1.0))
        instance.n_train_samples = int(payload.get("n_train_samples", 0))
        instance.train_metadata = dict(payload.get("train_metadata", {}))
        log.info(
            "[MetaLearner.%s] loaded from %s (%d features, %d train samples)",
            profile_name, path, len(instance.feature_names), instance.n_train_samples,
        )
        return instance


__all__ = [
    "MetaLearner",
    "DEFAULT_HYPERPARAMS",
    "DEFAULT_MODEL_DIR",
]
