"""
TransitionWarningDetector — fires when an HMM regime is *transitioning*,
not just when a transition has already happened.

This is Workstream C, slice 2 (2026-05). The detector consumes the
posterior probability stream from any HMMRegimeClassifier (typically the
daily classifier — coarser cadences would react too slowly to fire 48hr
ahead) and emits a binary warning + diagnostic metrics per bar.

Mechanism
---------
Two signals computed per bar over a trailing window of length K (default 5):

  1. Rolling K-day posterior ENTROPY — high entropy means the model is
     uncertain across multiple states. Persistent uncertainty often
     precedes an actual mode flip.
  2. KL DIVERGENCE between the posterior at bar t and the posterior at
     bar t-K — a sustained shift in probability mass between states.

A warning fires when either signal crosses its threshold (OR semantics).
Both signals are clipped to a 1-bar history so the per-bar output is
recoverable from the streaming buffer alone — important for live use.

Acceptance criterion (per Workstream C deliverable list):
  ≥48 hours ahead of regime changes in ≥80% of historical cases.

Historical anchor events (from `docs/Progress_Summaries/Other-dev-opinion/
05-1-26_1-percent.md` and `engine_e_hmm_first_slice_2026_05.md`):
  - March 2020 (COVID crash) — argmax flip benign → crisis ~2020-02-24
  - October 2022 (rate selloff) — argmax flip benign → stressed/crisis
  - April 2025 (market_turmoil) — argmax flip benign → crisis ~2025-04-02

The detector is stateless across calls in production (each call passes a
window of posteriors). For backtest mode, see `scripts/
backtest_transition_warning.py` which streams a full posterior sequence
through the detector.

Engine B integration: NONE direct. The detector outputs are surfaced via
`advisory.regime_transition_warning` as a read-only diagnostic field.
Engine B may consume in a future slice; for now this is observability.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

log = logging.getLogger("TransitionWarningDetector")


@dataclass(frozen=True)
class TransitionWarningConfig:
    """Hyperparameters for the transition-warning detector."""
    window: int = 5  # K — trailing bars used for entropy + KL
    entropy_threshold: float = 0.55  # normalized entropy ([0, 1]) above which warning fires
    kl_threshold: float = 0.30  # KL(p_t || p_{t-K}) in nats above which warning fires
    smoothing_window: int = 3  # rolling-mean smoothing on the per-bar entropy/KL series
    min_history: int = 5  # minimum bars before any warning can fire (warm-up)


@dataclass(frozen=True)
class TransitionWarningRead:
    """Per-bar transition-warning diagnostic + binary fire."""
    timestamp: pd.Timestamp
    warning: bool
    entropy: float        # raw normalized entropy at this bar
    entropy_smoothed: float
    kl_from_lag: float    # KL(p_t || p_{t-K}) — 0 if insufficient history
    kl_smoothed: float
    reason: Tuple[str, ...]  # which signal(s) triggered the warning

    def to_dict(self) -> dict:
        return {
            "timestamp": str(self.timestamp.date()) if not pd.isna(self.timestamp) else None,
            "warning": bool(self.warning),
            "entropy": round(float(self.entropy), 4),
            "entropy_smoothed": round(float(self.entropy_smoothed), 4),
            "kl_from_lag": round(float(self.kl_from_lag), 4),
            "kl_smoothed": round(float(self.kl_smoothed), 4),
            "reason": list(self.reason),
        }


class TransitionWarningDetector:
    """Streaming + batch transition warning detector.

    Two interfaces:
      - `detect_at(ts, posterior, history)` — single-bar inference suitable
        for live use (RegimeDetector calls per bar).
      - `detect_sequence(posterior_seq)` — batch over a full posterior
        sequence; used by the backtest validator.
    """

    def __init__(self, config: Optional[TransitionWarningConfig] = None):
        self.cfg = config or TransitionWarningConfig()

    # ------------------------------------------------------------------
    # Per-bar
    # ------------------------------------------------------------------
    def detect_at(
        self,
        timestamp: pd.Timestamp,
        posterior: Dict[str, float],
        history: Sequence[Dict[str, float]],
    ) -> TransitionWarningRead:
        """Detect transition warning at a single bar.

        Args:
            timestamp: Bar timestamp.
            posterior: Current bar's HMM posterior {state: prob}.
            history: Recent posteriors in chronological order, MOST RECENT
                LAST (i.e. history[-1] is the immediately-preceding bar's
                posterior). Length should be >= self.cfg.window for KL to
                fire; entropy fires on any length.

        Returns:
            TransitionWarningRead with per-bar diagnostics + warning bool.
        """
        history_list = list(history) + [posterior]
        seq = self._posterior_seq_to_array(history_list)
        if seq.size == 0:
            return TransitionWarningRead(
                timestamp=timestamp, warning=False, entropy=0.0,
                entropy_smoothed=0.0, kl_from_lag=0.0, kl_smoothed=0.0,
                reason=tuple(),
            )

        # Entropy at current bar
        entropy_now = self._normalized_entropy(seq[-1])
        # Smoothed entropy (rolling mean over smoothing_window bars)
        sm = max(1, self.cfg.smoothing_window)
        entropy_history = np.array([self._normalized_entropy(seq[i]) for i in range(len(seq))])
        entropy_smoothed = float(np.mean(entropy_history[-sm:]))

        # KL from posterior at t - window vs current
        kl_now = self._kl_from_lag(seq, lag=self.cfg.window)
        kl_history = np.array([
            self._kl_from_lag(seq[: i + 1], lag=self.cfg.window)
            for i in range(len(seq))
        ])
        kl_smoothed = float(np.mean(kl_history[-sm:]))

        warning = False
        reasons: List[str] = []
        if len(history_list) >= self.cfg.min_history:
            if entropy_smoothed >= self.cfg.entropy_threshold:
                warning = True
                reasons.append(
                    f"entropy_smoothed={entropy_smoothed:.3f}>={self.cfg.entropy_threshold}"
                )
            if kl_smoothed >= self.cfg.kl_threshold:
                warning = True
                reasons.append(
                    f"kl_smoothed={kl_smoothed:.3f}>={self.cfg.kl_threshold}"
                )

        return TransitionWarningRead(
            timestamp=timestamp,
            warning=warning,
            entropy=float(entropy_now),
            entropy_smoothed=entropy_smoothed,
            kl_from_lag=float(kl_now),
            kl_smoothed=kl_smoothed,
            reason=tuple(reasons),
        )

    # ------------------------------------------------------------------
    # Batch
    # ------------------------------------------------------------------
    def detect_sequence(
        self, posterior_seq: pd.DataFrame
    ) -> pd.DataFrame:
        """Stream the detector through a full posterior sequence.

        Args:
            posterior_seq: DataFrame indexed by bar timestamp, columns = state
                labels (e.g. {benign, stressed, crisis}). Each row sums to 1.

        Returns:
            DataFrame with same index, columns:
              [warning, entropy, entropy_smoothed, kl_from_lag, kl_smoothed, reason]
        """
        if posterior_seq is None or posterior_seq.empty:
            return pd.DataFrame(
                columns=["warning", "entropy", "entropy_smoothed",
                         "kl_from_lag", "kl_smoothed", "reason"],
            )

        states = list(posterior_seq.columns)
        arr = posterior_seq.values  # (T, K)
        T = arr.shape[0]
        K = self.cfg.window
        sm = max(1, self.cfg.smoothing_window)

        # Per-bar entropy
        entropy_per_bar = np.array([self._normalized_entropy(arr[i]) for i in range(T)])
        # Per-bar KL from lag-K
        kl_per_bar = np.zeros(T, dtype=np.float64)
        for i in range(T):
            if i < K:
                kl_per_bar[i] = 0.0
            else:
                kl_per_bar[i] = self._kl_divergence(arr[i], arr[i - K])

        # Rolling-mean smoothing
        ent_smoothed = pd.Series(entropy_per_bar).rolling(sm, min_periods=1).mean().values
        kl_smoothed = pd.Series(kl_per_bar).rolling(sm, min_periods=1).mean().values

        warnings: List[bool] = []
        reasons: List[str] = []
        for i in range(T):
            if i < self.cfg.min_history - 1:  # warm-up
                warnings.append(False)
                reasons.append("")
                continue
            r: List[str] = []
            fire = False
            if ent_smoothed[i] >= self.cfg.entropy_threshold:
                fire = True
                r.append(
                    f"entropy_smoothed={ent_smoothed[i]:.3f}>={self.cfg.entropy_threshold}"
                )
            if kl_smoothed[i] >= self.cfg.kl_threshold:
                fire = True
                r.append(
                    f"kl_smoothed={kl_smoothed[i]:.3f}>={self.cfg.kl_threshold}"
                )
            warnings.append(fire)
            reasons.append("|".join(r))

        out = pd.DataFrame(
            {
                "warning": warnings,
                "entropy": entropy_per_bar,
                "entropy_smoothed": ent_smoothed,
                "kl_from_lag": kl_per_bar,
                "kl_smoothed": kl_smoothed,
                "reason": reasons,
            },
            index=posterior_seq.index,
        )
        return out

    # ------------------------------------------------------------------
    # Statistics helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalized_entropy(p: np.ndarray) -> float:
        """Shannon entropy in nats / log(K) — normalized to [0, 1]."""
        p = np.asarray(p, dtype=np.float64)
        if p.size == 0:
            return 0.0
        p = p[p > 0]
        if p.size == 0 or p.size == 1:
            return 0.0
        K = len(p)
        ent = -float(np.sum(p * np.log(p)))
        return float(np.clip(ent / np.log(K), 0.0, 1.0)) if K > 1 else 0.0

    @staticmethod
    def _kl_divergence(p: np.ndarray, q: np.ndarray, eps: float = 1e-9) -> float:
        """KL(p || q) in nats. Symmetrized? No — directional, p observed at t.

        Both p and q assumed to be probability vectors of equal length.
        """
        p = np.asarray(p, dtype=np.float64) + eps
        q = np.asarray(q, dtype=np.float64) + eps
        # Renormalize after eps add
        p = p / p.sum()
        q = q / q.sum()
        return float(np.sum(p * np.log(p / q)))

    @classmethod
    def _kl_from_lag(cls, seq: np.ndarray, lag: int) -> float:
        """KL(seq[-1] || seq[-1 - lag]). Returns 0 if insufficient history."""
        if seq.shape[0] <= lag:
            return 0.0
        return cls._kl_divergence(seq[-1], seq[-1 - lag])

    @staticmethod
    def _posterior_seq_to_array(history: Sequence[Dict[str, float]]) -> np.ndarray:
        """Convert a list of posterior dicts into an (N, K) array.

        State key order is taken from the first non-empty dict; later dicts
        with different keys are skipped (or zero-filled to align).
        """
        if not history:
            return np.zeros((0, 0), dtype=np.float64)
        first = next((h for h in history if h), None)
        if first is None:
            return np.zeros((0, 0), dtype=np.float64)
        keys = list(first.keys())
        rows = []
        for h in history:
            if not h:
                rows.append(np.zeros(len(keys), dtype=np.float64))
            else:
                rows.append(np.array([h.get(k, 0.0) for k in keys], dtype=np.float64))
        return np.vstack(rows)
