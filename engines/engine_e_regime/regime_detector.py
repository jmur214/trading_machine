"""
RegimeDetector — Engine E coordinator.

Holds 5 sub-detectors, 5 hysteresis filters, an advisory engine,
and a history store. Single public method: detect_regime().

Flow per bar:
  1. Call each of 5 sub-detectors → raw (state, confidence, details)
  2. Pass each through its HysteresisFilter → stabilized state
  3. Compute transition_risk and regime_stability
  4. Map to named macro regime with soft probabilities
  5. Query history for duration, flip-frequency, empirical transitions
  6. Call AdvisoryEngine → non-binding hints + coherence warnings
  7. Assemble full output dict (new structured + backward-compat flat keys)
  8. Append to RegimeHistoryStore
"""

import logging
from collections import deque

import numpy as np
import pandas as pd
from typing import Deque, Dict, Optional

from engines.engine_e_regime.regime_config import RegimeConfig
from engines.engine_e_regime.hysteresis import HysteresisFilter
from engines.engine_e_regime.advisory import AdvisoryEngine
from engines.engine_e_regime.regime_history import RegimeHistoryStore
from engines.engine_e_regime.detectors.trend_detector import TrendDetector
from engines.engine_e_regime.detectors.volatility_detector import VolatilityDetector
from engines.engine_e_regime.detectors.correlation_detector import CorrelationDetector
from engines.engine_e_regime.detectors.breadth_detector import BreadthDetector
from engines.engine_e_regime.detectors.forward_stress_detector import ForwardStressDetector

_log = logging.getLogger("RegimeDetector")


# Backward-compat volatility mapping: "shock" → "high" for old consumers
_VOL_COMPAT = {"shock": "high", "low": "low", "normal": "normal", "high": "high"}
# Backward-compat trend mapping: "range" → "neutral" for old consumers
_TREND_COMPAT = {"bull": "bull", "bear": "bear", "range": "neutral"}
_REGIME_INT = {"bull": 1, "bear": -1, "range": 0}


def _hmm_confidence(proba: Dict[str, float]) -> float:
    """Normalized-entropy confidence proxy for HMM output dict.

    Mirrors HMMRegimeClassifier.confidence_from_proba — duplicated here
    so detect_regime can consume the dict without importing the classifier.
    """
    if not proba:
        return 0.0
    p = np.array([v for v in proba.values() if v > 0], dtype=np.float64)
    if len(p) <= 1:
        return 1.0
    n = len(proba)
    if n <= 1:
        return 1.0
    return float(np.clip(1.0 - (-(p * np.log(p)).sum()) / np.log(n), 0.0, 1.0))


class RegimeDetector:
    """5-axis market regime detector with hysteresis, advisory hints,
    and named macro regime mapping.

    Stateful — hysteresis filters and breadth detector track state across bars.
    Call reset() between backtest runs.
    """

    def __init__(self, config: RegimeConfig = None):
        self.cfg = config or RegimeConfig.from_json()

        # Sub-detectors
        self._trend = TrendDetector(self.cfg.trend)
        self._vol = VolatilityDetector(self.cfg.volatility)
        self._corr = CorrelationDetector(self.cfg.correlation)
        self._breadth = BreadthDetector(
            self.cfg.breadth,
            exclude_tickers=set(self.cfg.exclude_from_breadth),
        )
        self._fwd_stress = ForwardStressDetector(self.cfg.forward_stress)

        # Hysteresis filters (one per axis)
        self._filters = {
            "trend": HysteresisFilter(
                confirmation_bars=self.cfg.trend.hysteresis_bars,
            ),
            "volatility": HysteresisFilter(
                confirmation_bars=self.cfg.volatility.hysteresis_bars,
                bypass_states={"shock"},
                bypass_threshold=self.cfg.volatility.crisis_bypass_confidence,
            ),
            "correlation": HysteresisFilter(
                confirmation_bars=self.cfg.correlation.hysteresis_bars,
                bypass_states={"spike"},
                bypass_threshold=self.cfg.correlation.crisis_bypass_confidence,
            ),
            "breadth": HysteresisFilter(
                confirmation_bars=self.cfg.breadth.hysteresis_bars,
            ),
            "forward_stress": HysteresisFilter(
                confirmation_bars=self.cfg.forward_stress.hysteresis_bars,
                bypass_states={"panic"},
                bypass_threshold=self.cfg.forward_stress.crisis_bypass_confidence,
            ),
        }

        # Advisory engine
        self._advisory = AdvisoryEngine(self.cfg.advisory)

        # History store
        self._history = RegimeHistoryStore(
            flip_lookback=self.cfg.advisory.flip_frequency_lookback,
            transition_min_bars=self.cfg.advisory.transition_matrix_min_bars,
        )

        # HMM regime classifier (additive; default disabled).
        # Loaded lazily here at construction to fail fast on bad config.
        self._hmm_clf = None
        self._hmm_feature_panel: Optional[pd.DataFrame] = None
        if getattr(self.cfg, "hmm", None) and self.cfg.hmm.hmm_enabled:
            self._init_hmm()

        # Multi-resolution HMM ensemble (Workstream C slice 2 — 2026-05).
        # Default disabled; surfaces regime_daily / regime_weekly /
        # regime_monthly fields read-only into advisory output.
        self._multires = None
        if (
            getattr(self.cfg, "multires", None)
            and self.cfg.multires.multires_enabled
        ):
            self._init_multires()

        # Transition-warning detector (Workstream C slice 2 — 2026-05).
        # Default disabled; surfaces regime_transition_warning field
        # read-only into advisory output. Maintains a rolling posterior
        # buffer fed by the daily HMM.
        self._tw_detector = None
        self._tw_buffer: Deque[Dict[str, float]] = deque(maxlen=20)
        if (
            getattr(self.cfg, "transition_warning", None)
            and self.cfg.transition_warning.transition_warning_enabled
        ):
            self._init_transition_warning()

    def detect_regime(
        self,
        benchmark_df: pd.DataFrame,
        data_map: Optional[Dict[str, pd.DataFrame]] = None,
        now: Optional[str] = None,
    ) -> dict:
        """Run full 5-axis regime detection for the current bar.

        Args:
            benchmark_df: SPY (or primary benchmark) OHLCV DataFrame.
            data_map: Full ticker data_map (needed for correlation, breadth,
                      forward stress VIX data). Optional — axes degrade gracefully.
            now: Optional timestamp string for the current bar.

        Returns:
            Full regime output dict (see output contract in plan).
        """
        data_map = data_map or {}

        # --- Step 1: Raw detection ---
        trend_raw, trend_conf, trend_details = self._trend.detect(benchmark_df)
        vol_raw, vol_conf, vol_details = self._vol.detect(benchmark_df)
        corr_raw, corr_conf, corr_details = self._corr.detect(data_map)
        breadth_raw, breadth_conf, breadth_details = self._breadth.detect(data_map)
        fwd_raw, fwd_conf, fwd_details = self._fwd_stress.detect(
            benchmark_df, data_map
        )

        # --- Step 2: Hysteresis stabilization ---
        raw = {
            "trend": (trend_raw, trend_conf),
            "volatility": (vol_raw, vol_conf),
            "correlation": (corr_raw, corr_conf),
            "breadth": (breadth_raw, breadth_conf),
            "forward_stress": (fwd_raw, fwd_conf),
        }

        axis_states = {}
        axis_confidences = {}
        for axis, (state, conf) in raw.items():
            stabilized = self._filters[axis].update(state, conf)
            axis_states[axis] = stabilized
            # Use raw confidence if state was confirmed, else dampen
            if stabilized == state:
                axis_confidences[axis] = conf
            else:
                axis_confidences[axis] = conf * 0.7  # dampened during transition

        # --- Step 3: Transition risk and stability ---
        pending_ratios = [
            f.transition_progress
            for f in self._filters.values()
            if f.is_transitioning
        ]

        # SPY-TLT directionality contribution
        spy_tlt_change = corr_details.get("spy_tlt_corr_change", 0.0)
        if spy_tlt_change > self.cfg.correlation.spy_tlt_change_warning_threshold:
            pending_ratios.append(0.5)

        transition_risk = max(pending_ratios) if pending_ratios else 0.0

        avg_confidence = float(np.mean(list(axis_confidences.values())))
        regime_stability = avg_confidence * (1.0 - transition_risk)

        # --- Step 4 & 5: Advisory + macro regime ---
        durations = self._history.axis_durations
        flip_counts = self._history.flip_counts()

        # HMM augmentation (Engine E first slice — 2026-05).
        # Returns posterior P(state | features) over {benign, stressed, crisis}
        # or None if HMM disabled / unavailable.
        hmm_proba = self._predict_hmm(now)

        # Multi-resolution HMM ensemble (Workstream C slice 2 — 2026-05).
        # Returns {"regime_daily": dict|None, "regime_weekly": dict|None,
        # "regime_monthly": dict|None} or None if disabled.
        multires_advisory = self._predict_multires(now)

        # Transition-warning detector (Workstream C slice 2 — 2026-05).
        # Streams the daily HMM posterior through the buffer and detector;
        # returns {"warning": bool, "entropy": float, "kl_from_lag": float,
        # ...} or None if disabled / no posterior available.
        transition_warning_read = self._update_transition_warning(now, hmm_proba)

        macro_regime, advisory = self._advisory.generate(
            axis_states=axis_states,
            axis_confidences=axis_confidences,
            axis_durations=durations,
            flip_counts=flip_counts,
            corr_details=corr_details,
            hmm_proba=hmm_proba,
        )

        # Read-only multi-res + transition-warning fields surfaced into
        # advisory dict. Engine B reads only advisory.risk_scalar today;
        # these new fields are observability for future consumers.
        if multires_advisory is not None:
            advisory.update(multires_advisory)
        if transition_warning_read is not None:
            advisory["regime_transition_warning"] = transition_warning_read

        # --- Step 6: Empirical transition matrix ---
        transition_probs = self._history.get_transition_matrix()

        # --- Step 7: Assemble output ---
        timestamp = now or ""

        output = {
            "timestamp": timestamp,
            # 5-Axis Regime Classification
            "trend_regime": {"state": axis_states["trend"], "confidence": round(axis_confidences["trend"], 3)},
            "volatility_regime": {"state": axis_states["volatility"], "confidence": round(axis_confidences["volatility"], 3)},
            "correlation_regime": {"state": axis_states["correlation"], "confidence": round(axis_confidences["correlation"], 3)},
            "breadth_regime": {"state": axis_states["breadth"], "confidence": round(axis_confidences["breadth"], 3)},
            "forward_stress_regime": {"state": axis_states["forward_stress"], "confidence": round(axis_confidences["forward_stress"], 3)},
            # Composite Signals
            "transition_risk": round(transition_risk, 3),
            "regime_stability": round(regime_stability, 3),
            # Named Macro Regime
            "macro_regime": macro_regime,
            # HMM posterior over named states (None when HMM disabled)
            "hmm_regime": (
                {
                    "probabilities": hmm_proba,
                    "confidence": (
                        round(_hmm_confidence(hmm_proba), 3)
                        if hmm_proba else None
                    ),
                    "argmax": (max(hmm_proba, key=hmm_proba.get)
                               if hmm_proba else None),
                }
                if hmm_proba is not None else None
            ),
            # Advisory (non-binding)
            "advisory": advisory,
            # Detailed Explanations
            "explanation": {
                "trend": trend_details,
                "volatility": vol_details,
                "correlation": corr_details,
                "breadth": breadth_details,
                "forward_stress": fwd_details,
            },
            # Meta
            "meta": {
                "axis_durations": durations,
                "flip_counts_30bar": flip_counts,
                "empirical_transition_probs": transition_probs,
            },
            # BACKWARD COMPATIBILITY
            "regime": f"{_TREND_COMPAT.get(axis_states['trend'], 'neutral')}_{_VOL_COMPAT.get(axis_states['volatility'], 'normal')}_vol",
            "trend": _TREND_COMPAT.get(axis_states["trend"], "neutral"),
            "volatility": _VOL_COMPAT.get(axis_states["volatility"], "normal"),
            "regime_int": _REGIME_INT.get(axis_states["trend"], 0),
            "details": {
                "price": trend_details.get("price", 0.0),
                "sma": trend_details.get("sma200", 0.0),
                "atr": vol_details.get("atr", 0.0),
                "er": trend_details.get("er_60", 0.0),
                "atr_percentile": vol_details.get("atr_percentile", 50.0),
            },
        }

        # --- Step 8: Append to history ---
        history_row = {
            "timestamp": timestamp,
            "trend": axis_states["trend"],
            "volatility": axis_states["volatility"],
            "correlation": axis_states["correlation"],
            "breadth": axis_states["breadth"],
            "forward_stress": axis_states["forward_stress"],
            "macro_regime": macro_regime["label"],
            "trend_confidence": axis_confidences["trend"],
            "volatility_confidence": axis_confidences["volatility"],
            "correlation_confidence": axis_confidences["correlation"],
            "breadth_confidence": axis_confidences["breadth"],
            "forward_stress_confidence": axis_confidences["forward_stress"],
            "transition_risk": transition_risk,
            "regime_stability": regime_stability,
        }
        self._history.append(history_row)

        return output

    @property
    def history(self) -> RegimeHistoryStore:
        """Access the regime history store."""
        return self._history

    def reset(self) -> None:
        """Clear all internal state. Must be called between backtest runs."""
        for f in self._filters.values():
            f.reset()
        self._breadth.reset()
        self._history.reset()
        # Drain transition-warning posterior buffer so a fresh run starts
        # from cold state (no carryover from prior run).
        self._tw_buffer.clear()

    # ------------------------------------------------------------------
    # HMM augmentation (Engine E confidence-aware first slice — 2026-05)
    # ------------------------------------------------------------------
    def _init_hmm(self) -> None:
        """Load the persisted HMM model + lazily build feature panel.

        On_model_missing semantics:
          - "warn" (default): log + leave _hmm_clf=None; advisory unchanged
          - "raise": let exception propagate to caller
        """
        from pathlib import Path
        import os
        from engines.engine_e_regime.hmm_classifier import HMMRegimeClassifier
        from engines.engine_e_regime import macro_features as mf

        cfg = self.cfg.hmm
        # Resolve model path relative to repo root if not absolute
        model_path = Path(cfg.model_path)
        if not model_path.is_absolute():
            repo_root = Path(__file__).resolve().parents[2]
            model_path = repo_root / model_path

        if not model_path.exists():
            msg = f"HMM model not found at {model_path}; HMM augmentation disabled"
            if cfg.on_model_missing == "raise":
                raise FileNotFoundError(msg)
            _log.warning(msg)
            return

        try:
            self._hmm_clf = HMMRegimeClassifier.load(model_path)
        except Exception as exc:
            if cfg.on_model_missing == "raise":
                raise
            _log.warning(f"HMM load failed: {exc}; HMM augmentation disabled")
            return

        # Build feature panel once (covers full historical range).
        # detect_regime() will look up the row at-or-before the current bar.
        try:
            self._hmm_feature_panel = mf.build_feature_panel(include_aux=False)
            _log.info(
                f"HMM model loaded ({self._hmm_clf.n_states} states); "
                f"feature panel rows={len(self._hmm_feature_panel)}"
            )
        except Exception as exc:
            _log.warning(
                f"HMM feature panel build failed: {exc}; HMM augmentation disabled"
            )
            self._hmm_clf = None

    def _predict_hmm(self, now: Optional[str]) -> Optional[Dict[str, float]]:
        """Return HMM posterior P(state | features at `now`).

        None on any error; uniform distribution if features are NaN
        (delegated to HMMRegimeClassifier).
        """
        if self._hmm_clf is None or self._hmm_feature_panel is None:
            return None
        if not now:
            return None

        from engines.engine_e_regime import macro_features as mf
        try:
            row = mf.latest_feature_row(self._hmm_feature_panel, pd.Timestamp(now))
        except Exception:
            return None
        if row is None:
            return None
        try:
            return self._hmm_clf.predict_proba_at(
                row, history_panel=self._hmm_feature_panel
            )
        except Exception as exc:
            _log.debug(f"HMM predict failed at {now}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Multi-resolution HMM (Workstream C slice 2 — 2026-05)
    # ------------------------------------------------------------------
    def _init_multires(self) -> None:
        """Load multi-resolution HMM ensemble (daily/weekly/monthly).

        On any artifact missing, the orchestrator logs and degrades —
        loaded_cadences may be a strict subset of {daily, weekly, monthly}.
        """
        try:
            from engines.engine_e_regime.multires_hmm import (
                MultiResolutionHMM, MultiResHMMArtifacts,
            )
            from pathlib import Path
            cfg = self.cfg.multires
            repo_root = Path(__file__).resolve().parents[2]
            artifacts = MultiResHMMArtifacts(
                daily_path=repo_root / self.cfg.hmm.model_path,
                weekly_path=repo_root / cfg.weekly_model_path,
                monthly_path=repo_root / cfg.monthly_model_path,
            )
            self._multires = MultiResolutionHMM(
                artifacts=artifacts,
                history_window_daily=cfg.history_window_daily,
                history_window_weekly=cfg.history_window_weekly,
                history_window_monthly=cfg.history_window_monthly,
            )
            _log.info(
                f"Multi-resolution HMM loaded; cadences="
                f"{self._multires.loaded_cadences}"
            )
        except Exception as exc:
            _log.warning(f"Multi-resolution HMM init failed: {exc}")
            self._multires = None

    def _predict_multires(self, now: Optional[str]) -> Optional[Dict[str, Optional[dict]]]:
        """Run multi-res classification at `now`. Returns advisory-format dict."""
        if self._multires is None or not now:
            return None
        try:
            ts = pd.Timestamp(now)
            results = self._multires.classify_at(ts)
            return self._multires.to_advisory_dict(results)
        except Exception as exc:
            _log.debug(f"Multi-res predict failed at {now}: {exc}")
            return None

    # ------------------------------------------------------------------
    # Transition-warning detector (Workstream C slice 2 — 2026-05)
    # ------------------------------------------------------------------
    def _init_transition_warning(self) -> None:
        """Initialize the streaming transition-warning detector + buffer."""
        try:
            from engines.engine_e_regime.transition_warning import (
                TransitionWarningDetector,
                TransitionWarningConfig as TwCfgInner,
            )
            cfg = self.cfg.transition_warning
            self._tw_detector = TransitionWarningDetector(
                TwCfgInner(
                    window=cfg.window,
                    entropy_threshold=cfg.entropy_threshold,
                    kl_threshold=cfg.kl_threshold,
                    smoothing_window=cfg.smoothing_window,
                    min_history=cfg.min_history,
                )
            )
            # Resize buffer to honor configured size
            self._tw_buffer = deque(maxlen=cfg.posterior_buffer_size)
            _log.info("TransitionWarningDetector initialized")
        except Exception as exc:
            _log.warning(f"TransitionWarningDetector init failed: {exc}")
            self._tw_detector = None

    def _update_transition_warning(
        self, now: Optional[str], hmm_proba: Optional[Dict[str, float]],
    ) -> Optional[dict]:
        """Push new posterior into buffer + return current bar's warning read."""
        if self._tw_detector is None:
            return None
        if hmm_proba is None or not now:
            return None
        try:
            ts = pd.Timestamp(now)
            history = list(self._tw_buffer)
            read = self._tw_detector.detect_at(
                timestamp=ts, posterior=hmm_proba, history=history,
            )
            # Append AFTER detection so detect_at sees `history` ending at t-1.
            self._tw_buffer.append(dict(hmm_proba))
            return read.to_dict()
        except Exception as exc:
            _log.debug(f"TransitionWarning update failed at {now}: {exc}")
            return None
