"""
HMMRegimeClassifier — Engine E confidence-aware regime detection.

Replaces nothing. Augments the existing 5-axis threshold detector with a
Gaussian Hidden Markov Model that emits per-bar posterior probabilities
across K macro states (default K=3: benign / stressed / crisis).

Why HMM (over thresholds):
- Thresholds collapse to binary {high, low} per axis. Real regimes have
  duration, transition uncertainty, and continuum of "how confident
  are we right now". HMM exposes posteriors directly.
- Forward-backward gives smoothed probabilities; Viterbi gives the
  argmax path. We use forward (filter) at inference so there is no
  look-ahead.

Feature vector (cross-asset + macro):
  - SPY 5d log-return
  - SPY 20d realized volatility
  - TLT 20d log-return  (rates regime proxy)
  - VIX level (FRED VIXCLS)
  - T10Y2Y yield-curve spread (FRED)
  - BAA-AAA credit spread (FRED, computed from BAA10Y - AAA10Y)
  - DTWEXBGS broad dollar index 63d return (FRED)

Training: one-shot offline run on 2021-2024 produces a pickled model.
Inference: load model + feature snapshot, return posterior probability
distribution over K states.

Determinism: random_state=42 fixed at training time. Pickled model
loads bit-identically.

Mapping HMM-discovered states to named labels (benign/stressed/crisis):
state-mean of "SPY 20d realized vol" feature is the proxy. Lowest-vol
state → benign; mid → stressed; highest → crisis. Validated post-hoc
on the train set.
"""
from __future__ import annotations

import logging
import pickle
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger("HMMRegimeClassifier")

# Default state labels (k=3)
DEFAULT_STATE_LABELS_3 = ("benign", "stressed", "crisis")
DEFAULT_STATE_LABELS_2 = ("benign", "stressed")
DEFAULT_STATE_LABELS_4 = ("benign", "expansion", "stressed", "crisis")

DEFAULT_FEATURES = (
    "spy_ret_5d",
    "spy_vol_20d",
    "tlt_ret_20d",
    "vix_level",
    "yield_curve_spread",
    "credit_spread_baa_aaa",
    "dollar_ret_63d",
)


@dataclass
class HMMTrainingArtifact:
    """Persisted HMM model + metadata. Pickled for production inference."""
    n_states: int
    feature_names: Tuple[str, ...]
    feature_means: np.ndarray  # shape (n_features,) — for z-score at inference
    feature_stds: np.ndarray   # shape (n_features,) — for z-score at inference
    state_label_for_idx: Tuple[str, ...]  # idx -> label after sort by vol
    train_start: str
    train_end: str
    train_log_likelihood: float
    n_train_obs: int
    hmm_pickle: bytes = field(repr=False)


class HMMRegimeClassifier:
    """3-state Gaussian HMM regime classifier.

    Parameters
    ----------
    n_states : int
        Number of hidden states. Default 3 (benign/stressed/crisis).
    feature_names : tuple of str
        Ordered feature column names.
    state_labels : tuple of str | None
        Human-readable labels assigned in order of ascending realized
        vol of the SPY-vol feature. None → use defaults for n_states.
    random_state : int
        Determinism seed for EM.
    """

    def __init__(
        self,
        n_states: int = 3,
        feature_names: Tuple[str, ...] = DEFAULT_FEATURES,
        state_labels: Optional[Tuple[str, ...]] = None,
        random_state: int = 42,
    ):
        if state_labels is None:
            if n_states == 2:
                state_labels = DEFAULT_STATE_LABELS_2
            elif n_states == 3:
                state_labels = DEFAULT_STATE_LABELS_3
            elif n_states == 4:
                state_labels = DEFAULT_STATE_LABELS_4
            else:
                state_labels = tuple(f"state_{i}" for i in range(n_states))
        if len(state_labels) != n_states:
            raise ValueError(
                f"state_labels length ({len(state_labels)}) must match "
                f"n_states ({n_states})"
            )

        self.n_states = n_states
        self.feature_names = tuple(feature_names)
        self.state_labels = tuple(state_labels)
        self.random_state = random_state

        # Filled in by fit() / load()
        self._hmm = None
        self._feature_means: Optional[np.ndarray] = None
        self._feature_stds: Optional[np.ndarray] = None
        self._state_label_for_idx: Optional[Tuple[str, ...]] = None
        self._is_fitted: bool = False

    # ---------------------------------------------------------------
    # Fit
    # ---------------------------------------------------------------
    def fit(
        self,
        X_df: pd.DataFrame,
        train_start: Optional[str] = None,
        train_end: Optional[str] = None,
    ) -> HMMTrainingArtifact:
        """Fit Gaussian HMM on a feature DataFrame.

        Args:
            X_df: DataFrame indexed by date, with columns matching
                  self.feature_names. NaN rows dropped before fit.
            train_start / train_end: Optional date bounds; rows outside
                  are dropped before fit.

        Returns:
            HMMTrainingArtifact (pickleable for production).
        """
        from hmmlearn.hmm import GaussianHMM

        df = X_df.copy()
        if train_start is not None:
            df = df[df.index >= pd.Timestamp(train_start)]
        if train_end is not None:
            df = df[df.index <= pd.Timestamp(train_end)]

        # Subset to declared features and drop NaN rows
        missing = [c for c in self.feature_names if c not in df.columns]
        if missing:
            raise ValueError(
                f"Training frame missing required features: {missing}"
            )
        df = df[list(self.feature_names)].dropna()
        if len(df) < 100:
            raise ValueError(
                f"Insufficient training data ({len(df)} rows) — need >=100"
            )

        # Z-score normalize (HMM Gaussian emissions are scale-sensitive)
        means = df.mean(axis=0).values.astype(np.float64)
        stds = df.std(axis=0, ddof=0).values.astype(np.float64)
        stds = np.where(stds < 1e-9, 1.0, stds)  # avoid div0
        X = ((df.values - means) / stds).astype(np.float64)

        # Fit HMM with multiple random restarts for robustness
        best_score = -np.inf
        best_model = None
        for seed_offset in range(5):
            try:
                model = GaussianHMM(
                    n_components=self.n_states,
                    covariance_type="full",
                    n_iter=200,
                    tol=1e-4,
                    random_state=self.random_state + seed_offset,
                    init_params="stmc",
                    params="stmc",
                )
                model.fit(X)
                score = model.score(X)
                if score > best_score and np.isfinite(score):
                    best_score = score
                    best_model = model
            except Exception as exc:
                log.warning(f"HMM fit attempt {seed_offset} failed: {exc}")

        if best_model is None:
            raise RuntimeError("All HMM fit restarts failed")

        # Map state index -> label by ascending vol-feature mean.
        # spy_vol_20d feature index in z-scored space: state with highest
        # mean for this feature is "crisis"; lowest is "benign".
        vol_feat_idx = self.feature_names.index("spy_vol_20d") \
            if "spy_vol_20d" in self.feature_names else 0
        # In z-scored space, state means are model.means_ (n_states, n_features)
        state_vol_means = best_model.means_[:, vol_feat_idx]
        order = np.argsort(state_vol_means)  # ascending → benign to crisis

        # State idx -> label: position 0 in sorted order = self.state_labels[0]
        idx_to_label = [None] * self.n_states
        for sorted_pos, state_idx in enumerate(order):
            idx_to_label[state_idx] = self.state_labels[sorted_pos]
        idx_to_label_t = tuple(idx_to_label)

        # Persist on instance
        self._hmm = best_model
        self._feature_means = means
        self._feature_stds = stds
        self._state_label_for_idx = idx_to_label_t
        self._is_fitted = True

        return HMMTrainingArtifact(
            n_states=self.n_states,
            feature_names=self.feature_names,
            feature_means=means,
            feature_stds=stds,
            state_label_for_idx=idx_to_label_t,
            train_start=str(df.index.min().date()),
            train_end=str(df.index.max().date()),
            train_log_likelihood=float(best_score),
            n_train_obs=int(len(df)),
            hmm_pickle=pickle.dumps(best_model),
        )

    # ---------------------------------------------------------------
    # Inference
    # ---------------------------------------------------------------
    def predict_proba_at(
        self,
        x_row: pd.Series,
        history_panel: Optional[pd.DataFrame] = None,
        history_window: int = 60,
    ) -> Dict[str, float]:
        """Posterior P(state | features at row) — temporally smoothed.

        For per-bar use during backtest. When `history_panel` is provided,
        runs predict_proba on the trailing `history_window` rows ending
        at x_row's index (no look-ahead), returns the last row's posterior.
        This is the filtered (causal) posterior conditioned on recent
        observations.

        When `history_panel` is None, falls back to single-row emission
        probabilities (no temporal smoothing — mostly used in tests).

        Args:
            x_row: pandas Series with self.feature_names as index, indexed
                   by the as-of timestamp.
            history_panel: Optional DataFrame ending at-or-before x_row.name.
            history_window: Trailing bars to include in the smoothing window.

        Returns:
            {state_label: probability} dict summing to ~1.0.
            Returns uniform distribution if all features NaN.
        """
        if not self._is_fitted:
            raise RuntimeError("HMMRegimeClassifier not fitted/loaded")

        # If history is provided, smooth over the trailing window.
        if history_panel is not None and not history_panel.empty:
            try:
                ts = pd.Timestamp(x_row.name) if x_row.name is not None else None
            except Exception:
                ts = None
            if ts is not None:
                window = history_panel.loc[:ts][list(self.feature_names)]
                window = window.dropna().tail(history_window)
                if len(window) >= 5:
                    Z = (window.values - self._feature_means) / self._feature_stds
                    try:
                        proba_seq = self._hmm.predict_proba(Z)
                        proba = proba_seq[-1]
                        return {
                            self._state_label_for_idx[i]: float(proba[i])
                            for i in range(self.n_states)
                        }
                    except Exception as exc:
                        log.debug(f"HMM windowed predict failed: {exc}")
                        # fall through to single-row path

        # Fallback: single-row emission probabilities (no temporal info)
        try:
            vals = np.array(
                [float(x_row[c]) for c in self.feature_names],
                dtype=np.float64,
            )
        except (KeyError, TypeError, ValueError):
            return self._uniform_proba()
        if not np.all(np.isfinite(vals)):
            return self._uniform_proba()

        z = (vals - self._feature_means) / self._feature_stds
        proba = self._hmm.predict_proba(z.reshape(1, -1))[0]

        return {
            self._state_label_for_idx[i]: float(proba[i])
            for i in range(self.n_states)
        }

    def predict_proba_sequence(
        self, X_df: pd.DataFrame
    ) -> pd.DataFrame:
        """Posterior P(state | x_{1..T}) for a full feature sequence.

        Uses forward-backward (predict_proba). For online/causal use, see
        predict_proba_filtered. Returned DataFrame is indexed identically
        to X_df with columns = state_labels (ordered).
        """
        if not self._is_fitted:
            raise RuntimeError("HMMRegimeClassifier not fitted/loaded")

        df = X_df[list(self.feature_names)].copy()
        # Drop NaN rows; we'll reindex to X_df at the end (NaN rows
        # become uniform).
        valid = df.dropna()
        if len(valid) == 0:
            cols = list(self._state_label_for_idx)
            return pd.DataFrame(
                np.full((len(X_df), self.n_states), 1.0 / self.n_states),
                index=X_df.index,
                columns=cols,
            )

        Z = (valid.values - self._feature_means) / self._feature_stds
        proba = self._hmm.predict_proba(Z)  # shape (T, n_states)

        # Re-order columns by state_label
        cols = list(self._state_label_for_idx)
        result_valid = pd.DataFrame(proba, index=valid.index)
        # rename columns from state index -> label
        result_valid.columns = [self._state_label_for_idx[i] for i in range(self.n_states)]
        # Reorder to canonical label order if desired
        result_valid = result_valid[list(self.state_labels)]

        # Reindex to full X_df, NaN rows get uniform
        full = result_valid.reindex(X_df.index)
        full = full.fillna(1.0 / self.n_states)
        return full

    def score(self, X_df: pd.DataFrame) -> float:
        """Log-likelihood of X_df under the fitted model.

        Drops NaN rows before scoring. Returns -inf on empty.
        """
        if not self._is_fitted:
            raise RuntimeError("HMMRegimeClassifier not fitted/loaded")
        df = X_df[list(self.feature_names)].dropna()
        if len(df) == 0:
            return float("-inf")
        Z = (df.values - self._feature_means) / self._feature_stds
        return float(self._hmm.score(Z))

    def _uniform_proba(self) -> Dict[str, float]:
        """Return uniform probability dict — signals max uncertainty."""
        u = 1.0 / self.n_states
        return {label: u for label in self.state_labels}

    # ---------------------------------------------------------------
    # Confidence helpers
    # ---------------------------------------------------------------
    @staticmethod
    def confidence_from_proba(proba: Dict[str, float]) -> float:
        """Map a posterior dict to a [0, 1] confidence scalar.

        confidence = 1 - normalized_entropy
        - Uniform distribution → 0.0 (max uncertainty)
        - Concentrated on one state → 1.0 (max certainty)
        """
        if not proba:
            return 0.0
        p = np.array(list(proba.values()), dtype=np.float64)
        p = p[p > 0]  # drop zero-probability states (log undefined)
        if len(p) <= 1:
            return 1.0
        n = len(proba)
        if n <= 1:
            return 1.0
        max_entropy = np.log(n)
        entropy = -np.sum(p * np.log(p))
        return float(np.clip(1.0 - entropy / max_entropy, 0.0, 1.0))

    # ---------------------------------------------------------------
    # Persistence
    # ---------------------------------------------------------------
    def save(self, path: str | Path) -> None:
        """Pickle full state to disk."""
        if not self._is_fitted:
            raise RuntimeError("Cannot save unfitted HMMRegimeClassifier")
        artifact = HMMTrainingArtifact(
            n_states=self.n_states,
            feature_names=self.feature_names,
            feature_means=self._feature_means,
            feature_stds=self._feature_stds,
            state_label_for_idx=self._state_label_for_idx,
            train_start="",  # caller can re-set on artifact before save
            train_end="",
            train_log_likelihood=0.0,
            n_train_obs=0,
            hmm_pickle=pickle.dumps(self._hmm),
        )
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(artifact, f)

    @classmethod
    def load(cls, path: str | Path) -> "HMMRegimeClassifier":
        """Load pickled model from disk."""
        with open(path, "rb") as f:
            artifact: HMMTrainingArtifact = pickle.load(f)

        # Rebuild instance with same n_states / labels / feature names
        n_states = artifact.n_states
        labels = artifact.state_label_for_idx
        # Detect canonical label set by sorted_pos -> which label was at
        # each ascending-vol position
        # Simpler: assume user passed state_labels matching defaults
        canonical = sorted(set(labels), key=labels.index)
        # That's the labels in order of original sort. But we need
        # canonical (benign, stressed, crisis) order — recover from defaults.
        if n_states == 3:
            canonical_t = DEFAULT_STATE_LABELS_3
        elif n_states == 2:
            canonical_t = DEFAULT_STATE_LABELS_2
        elif n_states == 4:
            canonical_t = DEFAULT_STATE_LABELS_4
        else:
            canonical_t = tuple(canonical)

        inst = cls(
            n_states=n_states,
            feature_names=artifact.feature_names,
            state_labels=canonical_t,
        )
        inst._hmm = pickle.loads(artifact.hmm_pickle)
        inst._feature_means = artifact.feature_means
        inst._feature_stds = artifact.feature_stds
        inst._state_label_for_idx = artifact.state_label_for_idx
        inst._is_fitted = True
        inst._artifact_metadata = {
            "train_start": artifact.train_start,
            "train_end": artifact.train_end,
            "train_log_likelihood": artifact.train_log_likelihood,
            "n_train_obs": artifact.n_train_obs,
        }
        return inst
