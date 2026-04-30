# engines/engine_a_alpha/signal_processor.py
"""
SignalProcessor
---------------

- Normalizes each edge's raw score to [-1, +1] with robust clamping
- Applies regime gates (trend/volatility) per ticker
- Applies ensemble shrinkage
- Enforces hygiene (min history, NaN/inf drop, de-dup optionally)

Output schema per ticker:
{
  'aggregate_score': float in [-1, +1],
  'regimes': {'trend': bool, 'vol_ok': bool},
  'edges_detail': [{'edge','raw','norm','weight'}]
}
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

import numpy as np
import pandas as pd

from engines.engine_f_governance.regime_tracker import EDGE_CATEGORY_MAP


# ----------------------------- Settings ----------------------------- #

@dataclass
class RegimeSettings:
    enable_trend: bool = True
    trend_fast: int = 20
    trend_slow: int = 50
    enable_vol: bool = True
    vol_lookback: int = 20
    vol_z_max: float = 2.5
    shrink_off: float = 0.3  # multiply score by this when regime not OK


@dataclass
class HygieneSettings:
    min_history: int = 60
    dedupe_last_n: int = 1
    clamp: float = 1.5  # clamp raw score to +/- this before normalization
    # NOTE: All edges produce scores in [-1, +1]. clamp must match this range
    # so tanh(raw/clamp) gives meaningful spread. clamp=6.0 compressed everything
    # to ~[-0.16, +0.16], causing single-edge positive signals to die at threshold.


@dataclass
class EnsembleSettings:
    enable_shrink: bool = True
    shrink_lambda: float = 0.35  # ridge-like shrinkage
    combine: str = "weighted_mean"  # 'weighted_mean' only for now


@dataclass
class MetaLearnerSettings:
    """Layer 3 (allocation) meta-learner integration.

    The meta-learner combines tier=feature edge scores into a profile-aware
    contribution that ADDS to the legacy weighted_sum over tier=alpha edges.
    This is the Phase 1 architecture from
    docs/Core/phase1_metalearner_design.md.

    Default OFF for safety: when `enabled=False`, behavior is identical to
    the legacy linear weighted_sum. Cold-start safe: if `enabled=True` but
    no trained model exists for the active profile, MetaLearner.predict
    returns 0.0 and the system falls back to legacy behavior automatically
    (no exceptions in the hot path).

    The contribution_weight scales how much the meta-learner's prediction
    is added to the linear sum. Start small (0.1) so a noisy model can't
    dominate the signal; raise after validation evidence accumulates.
    """
    enabled: bool = False
    profile_name: str = "balanced"
    contribution_weight: float = 0.1


# ----------------------------- Processor ----------------------------- #

EDGE_AFFINITY_MAP = {
    "momentum": "momentum",
    "atr_breakout": "momentum",
    "atr_breakout_v1": "momentum",
    "xsec_momentum": "momentum",
    "mean_reversion": "mean_reversion",
    "rsi_bounce": "mean_reversion",
    "bollinger_reversion": "mean_reversion",
    "trend_following": "trend_following",
    "fundamental": "fundamental",
    "fundamental_ratio": "fundamental",
    "fundamental_value": "fundamental",
    "news_sentiment_edge": "fundamental",
    "news_sentiment_boost": "fundamental",
}


class SignalProcessor:
    def __init__(
        self,
        regime: RegimeSettings,
        hygiene: HygieneSettings,
        ensemble: EnsembleSettings,
        edge_weights: Dict[str, float],
        regime_gates: Optional[Dict[str, Dict[str, float]]] = None,
        debug: bool = False,
        metalearner_settings: Optional[MetaLearnerSettings] = None,
        edge_tiers: Optional[Dict[str, str]] = None,
        paused_edge_ids: Optional[Set[str]] = None,
        paused_max_weight: float = 0.5,
    ):
        self.regime = regime
        self.hygiene = hygiene
        self.ensemble = ensemble
        self.edge_weights = dict(edge_weights or {})
        self.regime_gates = dict(regime_gates or {})
        self.debug = bool(debug)
        # Phase 2.10d Primitive 2 — soft-pause weight ceiling.
        # Edges in `paused_edge_ids` (lifecycle status=paused) have their
        # effective per-bar weight capped at `paused_max_weight` AFTER all
        # multiplicative adjustments (regime_gate, learned_affinity). The
        # cap in mode_controller only bounds the *initial* weight; without
        # this ceiling, regime_gates with values > base/cap can re-amplify
        # a paused edge back toward full weight. Empirically observed:
        # low_vol_factor_v1 (status=paused, soft-paused initial weight 0.5)
        # fired 1,613 times in 2025 because its regime_gate releases it in
        # stressed regimes (gate[stressed]=1.0 cancels the benign-regime
        # 0.15 suppression). The cap closes that leak.
        self.paused_edge_ids: Set[str] = set(paused_edge_ids or set())
        self.paused_max_weight: float = float(paused_max_weight)
        # Layer 3 meta-learner integration. Default OFF — when disabled,
        # behavior is identical to the legacy linear weighted_sum so this
        # change is a strict no-op for existing backtests.
        self.ml_settings = metalearner_settings or MetaLearnerSettings()
        # Per-edge tier classification from EdgeRegistry (Layer 2).
        # Maps edge_id -> "alpha" | "feature" | "context". Edges not in
        # this dict default to "alpha" (legacy linear-sum behavior) so a
        # caller that doesn't pass tiers gets the pre-Phase-1 contract.
        self.edge_tiers = dict(edge_tiers or {})
        # Lazy-loaded MetaLearner — only loaded if enabled. Cold-start safe:
        # if no model file exists for the active profile, the loaded
        # instance's predict() returns 0.0 and behavior falls back to legacy.
        self._metalearner = None
        if self.ml_settings.enabled:
            self._metalearner = self._try_load_metalearner()
        if self.debug:
            print(f"[SIGNAL_PROCESSOR] Init with Regime: {self.regime}")
            print(f"[SIGNAL_PROCESSOR] MetaLearner: enabled={self.ml_settings.enabled}, "
                  f"profile={self.ml_settings.profile_name}, "
                  f"trained={self._metalearner.is_trained() if self._metalearner else False}")

    def _try_load_metalearner(self):
        """Load the trained MetaLearner for the active profile. Cold-start
        safe — if no model file exists, returns an untrained instance whose
        predict() returns 0.0 (no impact on signal output)."""
        try:
            from engines.engine_a_alpha.metalearner import MetaLearner
            return MetaLearner.load(profile_name=self.ml_settings.profile_name)
        except Exception as e:
            # Any unexpected error (corrupt model file, sklearn version
            # mismatch, etc.) → fall back to legacy. Better to silently
            # use the linear sum than crash the backtest.
            if self.debug:
                print(f"[SIGNAL_PROCESSOR] MetaLearner load failed: {type(e).__name__}: {e}")
            return None

    def _metalearner_contribution(
        self,
        edge_map: Dict[str, float],
    ) -> float:
        """Run the meta-learner over the current bar's tier=feature edge
        scores and return its scalar contribution.

        Returns 0.0 (no contribution) if:
          - meta-learner disabled
          - no model loaded / cold-start
          - feature mismatch that the alignment guard can't recover from
          - any unexpected error

        Sparse-input handling: at training time, every bar is a row with
        all N trained-feature columns (zeros for non-firing edges). At
        inference, only edges that fired this bar appear in `edge_map`.
        We fill any trained feature absent from the current bar with 0.0
        — this matches the trainer's NaN→0 behavior in
        ``build_features_from_raw_scores``.
        """
        if not self.ml_settings.enabled or self._metalearner is None:
            return 0.0
        if not self._metalearner.is_trained():
            return 0.0

        trained_features = self._metalearner.feature_names or []
        if not trained_features:
            return 0.0

        # Build feature dict from tier=feature edges in the current bar's scores.
        # Start by zero-filling every trained feature, then fill in current-bar
        # values for the edges that fired this bar AND are tier=feature.
        feature_inputs: Dict[str, float] = {f: 0.0 for f in trained_features}
        any_present = False
        for edge_name, raw in edge_map.items():
            if raw is None:
                continue
            tier = self.edge_tiers.get(edge_name, "alpha")
            if tier != "feature":
                continue
            if edge_name not in feature_inputs:
                # Edge wasn't in the training set — model can't use it.
                # Drop silently rather than reject.
                continue
            try:
                feature_inputs[edge_name] = float(raw)
                any_present = True
            except Exception:
                continue
        if not any_present:
            # No trained feature edges fired on this bar — model has nothing
            # to differentiate this bar from the all-zero baseline. Skip.
            return 0.0
        try:
            ml_score = self._metalearner.predict(feature_inputs)
            # Normalize the prediction to [-1, 1] before applying
            # contribution_weight. Without this, the meta-learner's raw
            # output can be much wider than the [-1, 1] aggregate score
            # range (the training target — profile-aware fitness — can
            # be in [-30, +30] for some profiles), letting the model
            # dominate the linear sum even at small contribution_weight.
            # target_clip is set at fit time to max(|y_train|).
            target_clip = max(self._metalearner.target_clip, 1e-6)
            ml_norm = float(ml_score) / target_clip
            ml_norm = max(-1.0, min(1.0, ml_norm))
            return ml_norm * float(self.ml_settings.contribution_weight)
        except Exception as e:
            # Defensive: any unexpected predict error → fall back to legacy.
            if self.debug:
                print(f"[SIGNAL_PROCESSOR] MetaLearner predict failed "
                      f"({type(e).__name__}): {e} — falling back to linear baseline")
            return 0.0

    # ---- helpers ---- #

    def _enough_history(self, df: pd.DataFrame) -> bool:
        return df is not None and len(df.index) >= int(self.hygiene.min_history)

    @staticmethod
    def _safe_close(df: pd.DataFrame) -> pd.Series:
        s = pd.to_numeric(df.get("Close", pd.Series(dtype=float)), errors="coerce")
        return s.dropna()

    def _trend_ok(self, df: pd.DataFrame) -> bool:
        if not self.regime.enable_trend:
            return True
        px = self._safe_close(df)
        if px.shape[0] < max(self.regime.trend_fast, self.regime.trend_slow):
            return False
        fast = px.rolling(self.regime.trend_fast).mean()
        slow = px.rolling(self.regime.trend_slow).mean()
        return bool(fast.iloc[-1] > slow.iloc[-1])

    def _vol_ok(self, df: pd.DataFrame) -> bool:
        if not self.regime.enable_vol:
            return True
        px = self._safe_close(df)
        if px.shape[0] < self.regime.vol_lookback + 5:
            return False
        ret = px.pct_change().dropna()
        vol = ret.rolling(self.regime.vol_lookback).std().dropna()
        if vol.empty:
            return False
        z = (vol - vol.mean()) / (vol.std() + 1e-12)
        return bool(abs(z.iloc[-1]) <= self.regime.vol_z_max)

    @staticmethod
    def _normalize_score(raw: float, clamp: float) -> float:
        # clamp extreme raw scores to control outliers, then squash to [-1,1]
        r = max(-clamp, min(clamp, float(raw)))
        # tanh-like squashing (scaled)
        return float(np.tanh(r / clamp))

    # ---- public ---- #

    def process(
        self,
        data_map: Dict[str, pd.DataFrame],
        now: pd.Timestamp,
        raw_scores: Dict[str, Dict[str, float]],
        regime_meta: Dict[str, any] = None,
    ) -> Dict[str, dict]:
        """
        Returns a dict per ticker with normalized & aggregated score and details.
        """
        out: Dict[str, dict] = {}

        for ticker, edge_map in raw_scores.items():
            df = data_map.get(ticker)
            if df is None or df.empty or not self._enough_history(df):
                continue

            trend_ok = self._trend_ok(df)
            vol_ok = self._vol_ok(df)
            regimes = {"trend": trend_ok, "vol_ok": vol_ok}

            details: List[dict] = []
            weighted_sum = 0.0
            weight_total = 0.0

            for edge_name, raw in edge_map.items():
                if raw is None:
                    continue
                # hygiene: numeric
                try:
                    raw_f = float(raw)
                except Exception:
                    continue
                if np.isnan(raw_f) or np.isinf(raw_f):
                    continue

                norm = self._normalize_score(raw_f, self.hygiene.clamp)

                # regime shrink if any regime off (Micro-Regime per ticker)
                if not (trend_ok and vol_ok):
                    old_norm = norm
                    norm *= float(self.regime.shrink_off)
                    if self.debug:
                        print(f"[REGIME] {ticker} {now} Micro-Regime blocked (Trend={trend_ok} Vol={vol_ok}). Shrinking {old_norm:.3f} -> {norm:.3f}")

                # --- Macro Regime Scaling (Engine E Advisory) ---
                # Strategy: use risk_scalar as a brake in stressed/crisis regimes.
                # Edge affinity boost is deferred until edges have proven regime-
                # conditional profitability via Governance (F). With 26% win rate,
                # amplifying losing edges is counterproductive.
                advisory = regime_meta.get("advisory") if regime_meta else None
                if advisory:
                    regime_summary = advisory.get("regime_summary", "benign")
                    if regime_summary in ("stressed", "crisis"):
                        risk_scalar = float(advisory.get("risk_scalar", 1.0))
                        old_norm = norm
                        norm *= risk_scalar
                        if self.debug:
                            print(f"[REGIME] {ticker} {now} Engine E brake: summary={regime_summary} risk_scalar={risk_scalar:.2f} norm {old_norm:.3f} -> {norm:.3f}")
                elif regime_meta:
                    # Fallback: legacy binary cuts when advisory not available
                    market_trend = regime_meta.get("trend", "unknown")
                    market_vol = regime_meta.get("volatility", "unknown")
                    if market_trend == "bear" and norm > 0:
                        norm *= 0.5
                    if market_vol == "high":
                        norm *= 0.75

                # --- Learned Edge Affinity (from Governor regime tracker) ---
                if advisory:
                    learned_affinity = advisory.get("learned_edge_affinity", {})
                    if learned_affinity:
                        edge_lower = edge_name.lower()
                        edge_cat = "fundamental"  # default
                        for pattern, category in EDGE_CATEGORY_MAP.items():
                            if pattern in edge_lower:
                                edge_cat = category
                                break
                        affinity_mult = float(np.clip(learned_affinity.get(edge_cat, 1.0), 0.3, 1.5))
                        if affinity_mult != 1.0:
                            old_norm = norm
                            norm *= affinity_mult
                            if self.debug:
                                print(f"[AFFINITY] {ticker} {now} edge={edge_name} cat={edge_cat} mult={affinity_mult:.2f} norm {old_norm:.3f} -> {norm:.3f}")

                # --- Directional Regime Bias ---
                # DISABLED: Regime detection misclassifies 2023-2024 bull markets
                # as "cautious_decline", causing suppression of longs in bull markets.
                # Until regime detection reliably distinguishes bull/bear, directional
                # suppression does more harm than good.

                w = float(self.edge_weights.get(edge_name, 1.0))
                # Regime gate: per-edge conditional weighting from EdgeSpec.regime_gate.
                # Multiplies w by the gate value for the current regime_summary.
                # Default 1.0 if regime not in gate (unconditional pass-through).
                gate = self.regime_gates.get(edge_name)
                if gate:
                    advisory = regime_meta.get("advisory") if regime_meta else None
                    current_regime = (advisory.get("regime_summary", "benign")
                                      if advisory else "benign")
                    w *= float(gate.get(current_regime, 1.0))

                # Phase 2.10d Primitive 2 — soft-pause hard ceiling.
                # Applied AFTER all weight multipliers (initial cap, regime_gate)
                # so no downstream amplifier can leak a paused edge past its
                # soft-pause budget. Only fires for edges with status=paused.
                if edge_name in self.paused_edge_ids and w > self.paused_max_weight:
                    if self.debug:
                        print(f"[PAUSED_CAP] {edge_name} weight {w:.3f} clamped "
                              f"to soft-pause ceiling {self.paused_max_weight:.3f}")
                    w = self.paused_max_weight

                details.append({"edge": edge_name, "raw": raw_f, "norm": norm, "weight": w})
                weighted_sum += (norm * w)
                # Only count edges with actual signal in denominator —
                # edges with norm ≈ 0 (no opinion or regime-suppressed) abstain.
                if abs(norm) > 1e-6:
                    weight_total += abs(w)

            if weight_total <= 0.0:
                continue

            agg = weighted_sum / weight_total
            # ensemble shrinkage (ridge-style)
            if self.ensemble.enable_shrink:
                agg = agg * (1.0 - self.ensemble.shrink_lambda)

            # ----------------- Layer 3: meta-learner contribution -----------------
            # Adds a profile-aware non-linear term over tier=feature edges.
            # When disabled or untrained, returns 0 → behavior matches legacy
            # linear weighted_sum exactly. See MetaLearnerSettings docstring.
            ml_contribution = self._metalearner_contribution(edge_map)
            if ml_contribution != 0.0:
                if self.debug:
                    print(f"[METALEARNER] {ticker} {now} agg={agg:.4f} + "
                          f"ml={ml_contribution:.4f} = {agg + ml_contribution:.4f}")
                agg = agg + ml_contribution

            # clamp to [-1, 1] (numerical safety)
            agg = max(-1.0, min(1.0, float(agg)))

            out[ticker] = {
                "aggregate_score": agg,
                "regimes": regimes,
                "edges_detail": details,
                "ml_contribution": float(ml_contribution),
            }

        return out