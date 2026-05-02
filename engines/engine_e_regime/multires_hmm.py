"""
MultiResolutionHMM — runs daily / weekly / monthly HMM regime classifiers
in parallel, each on its own resampled feature panel.

This is Workstream C, slice 2 (2026-05). The first slice shipped a single
daily HMM. This module adds two slower-cadence classifiers running side-by-
side. Different downstream consumers can read whichever resolution suits
their rebalance cadence:

  - daily   → core sleeve (per-bar advisory damping)
  - weekly  → tactical regime read (less noise per classification)
  - monthly → strategic / Path C compounder (annual rebalance cares about
              months, not days)

The three classifiers are independently trained — they do NOT share state
or labels at runtime. Each maps {benign, stressed, crisis} via the same
ascending-vol convention as the daily HMMRegimeClassifier (state idx
ordered by mean of `spy_vol_20d` in z-score space).

Tradeoff (validated empirically; see ws_c_multires_transitions audit doc):
  - Slower-cadence classifiers have HIGHER per-classification confidence
    (less noise in their input features) but LOWER temporal precision.
  - A weekly classifier cannot detect an intra-week regime flip; a monthly
    classifier averages over an entire month of price action.

Determinism: each underlying HMM uses random_state=42 (fixed), and the
resample step is deterministic given the daily input.

Engine B integration: NONE direct. The orchestrator surfaces three regime
labels through Engine E's advisory output dict; Engine B reads only what
it already reads (advisory.risk_scalar). New fields are read-only,
diagnostic-only by default. Future consumers can opt in.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd

from engines.engine_e_regime.hmm_classifier import HMMRegimeClassifier
from engines.engine_e_regime import macro_features as mf

log = logging.getLogger("MultiResolutionHMM")

# Cadence keys used throughout (must match advisory output field suffixes).
CADENCES: Tuple[str, ...] = ("daily", "weekly", "monthly")


@dataclass
class CadenceResult:
    """Per-cadence regime read at a single point in time."""
    cadence: str
    proba: Dict[str, float]
    argmax: str
    confidence: float  # 1 - normalized entropy
    bar_timestamp: pd.Timestamp  # the resampled-bar index this read was taken from

    def to_dict(self) -> dict:
        return {
            "cadence": self.cadence,
            "label": self.argmax,
            "probabilities": {k: round(v, 4) for k, v in self.proba.items()},
            "confidence": round(self.confidence, 4),
            "bar_timestamp": str(self.bar_timestamp.date())
            if not pd.isna(self.bar_timestamp)
            else None,
        }


@dataclass
class MultiResHMMArtifacts:
    """Paths to the three persisted HMM models for this multi-res ensemble."""
    daily_path: Path
    weekly_path: Path
    monthly_path: Path

    @classmethod
    def default(cls, repo_root: Optional[Path] = None) -> "MultiResHMMArtifacts":
        root = repo_root or Path(__file__).resolve().parents[2]
        models = root / "engines" / "engine_e_regime" / "models"
        return cls(
            daily_path=models / "hmm_3state_v1.pkl",
            weekly_path=models / "hmm_weekly_v1.pkl",
            monthly_path=models / "hmm_monthly_v1.pkl",
        )


class MultiResolutionHMM:
    """Orchestrator for daily / weekly / monthly HMM classifiers.

    Loads three pre-trained HMMRegimeClassifier artifacts and exposes a
    single `classify_at(timestamp)` method that runs all three in parallel.

    The daily, weekly, monthly feature panels are built once at construction
    and reused across calls — no I/O on the hot path.

    On any one cadence's missing artifact: that cadence is skipped (returns
    None for that key in the result dict). Other cadences continue to work.
    This degrades gracefully on partial-deployment scenarios.
    """

    def __init__(
        self,
        artifacts: Optional[MultiResHMMArtifacts] = None,
        feature_start: str = "2018-01-01",
        feature_end: Optional[str] = None,
        history_window_daily: int = 60,
        history_window_weekly: int = 26,   # ~6 months of weekly bars
        history_window_monthly: int = 12,  # ~1 year of monthly bars
    ):
        self.artifacts = artifacts or MultiResHMMArtifacts.default()
        self.history_window = {
            "daily": history_window_daily,
            "weekly": history_window_weekly,
            "monthly": history_window_monthly,
        }

        # Lazy-load classifiers. Each may be None if its pickle is missing.
        self._classifiers: Dict[str, Optional[HMMRegimeClassifier]] = {
            "daily": None,
            "weekly": None,
            "monthly": None,
        }
        self._panels: Dict[str, Optional[pd.DataFrame]] = {
            "daily": None,
            "weekly": None,
            "monthly": None,
        }

        for cad, path in (
            ("daily", self.artifacts.daily_path),
            ("weekly", self.artifacts.weekly_path),
            ("monthly", self.artifacts.monthly_path),
        ):
            try:
                if path.exists():
                    self._classifiers[cad] = HMMRegimeClassifier.load(path)
                else:
                    log.warning(
                        f"MultiResHMM: {cad} artifact missing at {path}; "
                        f"this cadence will be skipped"
                    )
            except Exception as exc:
                log.warning(f"MultiResHMM: failed to load {cad} from {path}: {exc}")

        # Build feature panels
        try:
            panels = mf.build_multires_panels(
                start=feature_start, end=feature_end, include_aux=False
            )
            self._panels = panels
        except Exception as exc:
            log.warning(f"MultiResHMM: feature panel build failed: {exc}")

    # ------------------------------------------------------------------
    # Inference
    # ------------------------------------------------------------------
    def classify_at(self, timestamp: pd.Timestamp) -> Dict[str, Optional[CadenceResult]]:
        """Classify the regime at `timestamp` across all three resolutions.

        Returns:
            {"daily": CadenceResult|None, "weekly": ..., "monthly": ...}
            None for any cadence whose classifier or panel is unavailable.
        """
        ts = pd.Timestamp(timestamp)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)

        out: Dict[str, Optional[CadenceResult]] = {}
        for cad in CADENCES:
            clf = self._classifiers[cad]
            panel = self._panels.get(cad)
            if clf is None or panel is None or panel.empty:
                out[cad] = None
                continue

            row = mf.latest_feature_row(panel, ts)
            if row is None:
                out[cad] = None
                continue
            try:
                proba = clf.predict_proba_at(
                    row,
                    history_panel=panel,
                    history_window=self.history_window[cad],
                )
            except Exception as exc:
                log.debug(f"MultiResHMM: {cad} predict failed at {ts}: {exc}")
                out[cad] = None
                continue
            argmax = max(proba, key=proba.get)
            conf = HMMRegimeClassifier.confidence_from_proba(proba)
            out[cad] = CadenceResult(
                cadence=cad,
                proba=proba,
                argmax=argmax,
                confidence=conf,
                bar_timestamp=row.name,
            )
        return out

    def to_advisory_dict(
        self, results: Dict[str, Optional[CadenceResult]]
    ) -> Dict[str, Optional[dict]]:
        """Serialize classify_at output to the advisory output schema.

        Schema:
            {
              "regime_daily":   {"label", "probabilities", "confidence", "bar_timestamp"} | None,
              "regime_weekly":  {...} | None,
              "regime_monthly": {...} | None,
            }
        """
        out: Dict[str, Optional[dict]] = {}
        for cad in CADENCES:
            r = results.get(cad)
            out[f"regime_{cad}"] = r.to_dict() if r is not None else None
        return out

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------
    @property
    def loaded_cadences(self) -> Tuple[str, ...]:
        """Tuple of cadence names whose classifiers loaded successfully."""
        return tuple(c for c in CADENCES if self._classifiers[c] is not None)

    def panel(self, cadence: str) -> Optional[pd.DataFrame]:
        """Expose a panel for testing / backtest scripts."""
        return self._panels.get(cadence)

    def classifier(self, cadence: str) -> Optional[HMMRegimeClassifier]:
        """Expose the underlying classifier for the given cadence."""
        return self._classifiers.get(cadence)
