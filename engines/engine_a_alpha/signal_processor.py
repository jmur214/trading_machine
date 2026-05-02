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
from typing import Any, Dict, List, Optional, Set

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
class PortfolioOptimizerSettings:
    """Cross-ticker portfolio construction layer.

    After per-ticker aggregation produces ``aggregate_score`` (per-edge
    weighted_sum within each ticker), an optional cross-ticker step
    re-shapes the score magnitudes via a real portfolio optimizer
    (Engine C). The sign of each ``aggregate_score`` is preserved (long
    vs short direction stays as Engine A produced it); only the
    *magnitude* is replaced with the portfolio-weight share.

    method = "weighted_sum"  → no-op, behavior identical to legacy
                               (this is the default; existing backtests
                               are unaffected)
    method = "hrp"           → HRP-as-replacement (slice 1 — FALSIFIED).
                               Preserved for cell D verification only.
                               Strips ensemble conviction from
                               aggregate_score and replaces with HRP-weight
                               × N. Sharpe regression -0.63 vs weighted_sum
                               on prod-109 2025 OOS. Do not deploy.
    method = "hrp_composed"  → HRP slice 2 (compose-not-replace). Preserves
                               aggregate_score (Engine A's edge-ensemble
                               conviction) and ALSO emits per-ticker
                               ``optimizer_weight`` into the per-ticker
                               info dict. AlphaEngine.generate_signals
                               threads optimizer_weight into signal.meta;
                               Engine B multiplies it into the ATR-risk
                               sizing path. The two are composed
                               multiplicatively rather than HRP overwriting
                               conviction.

    The turnover gate is consulted *after* HRP produces weights — if
    expected alpha lift < expected transaction cost, the previously-
    committed weight vector is reused instead, suppressing churn. Active
    for both ``hrp`` and ``hrp_composed`` methods.

    Default OFF for safety: when ``method == "weighted_sum"``, all HRP
    machinery is bypassed, including turnover state. This is a strict
    no-op for callers that don't opt in.
    """
    method: str = "weighted_sum"  # "weighted_sum" | "hrp" | "hrp_composed"
    cov_lookback: int = 60
    min_history: int = 30
    use_ledoit_wolf: bool = True
    linkage_method: str = "single"
    turnover_enabled: bool = True
    turnover_flat_cost_bps: float = 10.0
    turnover_min_check: float = 0.01


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

    Phase 2.11 — per-ticker mode. When ``per_ticker=True``, the
    contribution function looks up a ticker-specific model from
    ``data/governor/per_ticker_metalearners/{ticker}.pkl`` first, falls
    back to the portfolio model when the ticker-specific file is missing
    (cold start for new tickers). Default False so existing backtests
    are unaffected.
    """
    enabled: bool = False
    profile_name: str = "balanced"
    contribution_weight: float = 0.1
    per_ticker: bool = False
    per_ticker_model_dir: str = "data/governor/per_ticker_metalearners"


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
        portfolio_optimizer_settings: Optional["PortfolioOptimizerSettings"] = None,
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

        # Phase 2.11 per-ticker mode — lazy-loaded ticker-keyed model cache.
        # Populated on first request per ticker; misses fall back to the
        # portfolio model. None when per_ticker is disabled.
        self._per_ticker_models: Optional[Dict[str, Any]] = None
        self._per_ticker_misses: Set[str] = set()
        if self.ml_settings.enabled and self.ml_settings.per_ticker:
            self._per_ticker_models = {}

        # Engine C portfolio optimizer (Workstream B, 2026-05). Default
        # method "weighted_sum" is a strict no-op — the per-ticker
        # aggregate scores pass through unchanged. method="hrp" delegates
        # cross-ticker re-shaping to Engine C's HRP optimizer with a
        # turnover-cost gate.
        self.po_settings = portfolio_optimizer_settings or PortfolioOptimizerSettings()
        self._hrp = None
        self._turnover = None
        if self.po_settings.method in ("hrp", "hrp_composed"):
            from engines.engine_c_portfolio.optimizers import HRPOptimizer, TurnoverPenalty
            from engines.engine_c_portfolio.optimizers.hrp import HRPConfig
            from engines.engine_c_portfolio.optimizers.turnover import TurnoverConfig
            self._hrp = HRPOptimizer(HRPConfig(
                cov_lookback=self.po_settings.cov_lookback,
                min_history=self.po_settings.min_history,
                use_ledoit_wolf=self.po_settings.use_ledoit_wolf,
                linkage_method=self.po_settings.linkage_method,
            ))
            self._turnover = TurnoverPenalty(TurnoverConfig(
                enabled=self.po_settings.turnover_enabled,
                flat_cost_bps=self.po_settings.turnover_flat_cost_bps,
                min_turnover_to_check=self.po_settings.turnover_min_check,
            ))

        if self.debug:
            print(f"[SIGNAL_PROCESSOR] Init with Regime: {self.regime}")
            print(f"[SIGNAL_PROCESSOR] MetaLearner: enabled={self.ml_settings.enabled}, "
                  f"profile={self.ml_settings.profile_name}, "
                  f"per_ticker={self.ml_settings.per_ticker}, "
                  f"trained={self._metalearner.is_trained() if self._metalearner else False}")
            print(f"[SIGNAL_PROCESSOR] PortfolioOptimizer: method={self.po_settings.method}")

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

    def _try_load_per_ticker_metalearner(self, ticker: str):
        """Phase 2.11 — load the ticker-specific MetaLearner from
        ``data/governor/per_ticker_metalearners/{ticker}.pkl``.

        Returns a trained MetaLearner instance, or None if the file is
        missing / corrupt. Cached on the instance so we hit disk at most
        once per ticker per backtest run.
        """
        if self._per_ticker_models is None:
            return None
        cached = self._per_ticker_models.get(ticker)
        if cached is not None:
            return cached
        if ticker in self._per_ticker_misses:
            # Don't re-attempt loads we've already established fail
            return None
        try:
            from pathlib import Path
            import joblib
            from engines.engine_a_alpha.metalearner import MetaLearner

            path = Path(self.ml_settings.per_ticker_model_dir) / f"{ticker}.pkl"
            if not path.exists():
                self._per_ticker_misses.add(ticker)
                if self.debug:
                    print(f"[SIGNAL_PROCESSOR] per-ticker model miss for {ticker} "
                          f"({path}) — falling back to portfolio model")
                return None
            payload = joblib.load(path)
            instance = MetaLearner(
                profile_name=payload.get("profile_name", self.ml_settings.profile_name),
            )
            instance.hyperparams = payload.get("hyperparams", instance.hyperparams)
            instance._model = payload["model"]
            instance.feature_names = list(payload["feature_names"])
            instance.target_clip = float(payload.get("target_clip", 1.0))
            instance.n_train_samples = int(payload.get("n_train_samples", 0))
            instance.train_metadata = dict(payload.get("train_metadata", {}))
            self._per_ticker_models[ticker] = instance
            if self.debug:
                print(f"[SIGNAL_PROCESSOR] loaded per-ticker model {ticker} "
                      f"({len(instance.feature_names)} features, "
                      f"{instance.n_train_samples} train samples)")
            return instance
        except Exception as e:
            self._per_ticker_misses.add(ticker)
            if self.debug:
                print(f"[SIGNAL_PROCESSOR] per-ticker load failed for {ticker}: "
                      f"{type(e).__name__}: {e}")
            return None

    def _metalearner_contribution(
        self,
        edge_map: Dict[str, float],
        ticker: Optional[str] = None,
    ) -> float:
        """Run the meta-learner over the current bar's tier=feature edge
        scores and return its scalar contribution.

        Returns 0.0 (no contribution) if:
          - meta-learner disabled
          - no model loaded / cold-start
          - feature mismatch that the alignment guard can't recover from
          - any unexpected error

        Phase 2.11 per-ticker mode: when ``ml_settings.per_ticker`` is
        True AND a `ticker` is supplied AND a per-ticker model exists,
        the per-ticker model is used. Otherwise falls back to the
        portfolio model. This means disabling per-ticker (or training
        only a subset of tickers) is safe — every miss falls back to
        the portfolio model.

        Sparse-input handling: at training time, every bar is a row with
        all N trained-feature columns (zeros for non-firing edges). At
        inference, only edges that fired this bar appear in `edge_map`.
        We fill any trained feature absent from the current bar with 0.0
        — this matches the trainer's NaN→0 behavior in
        ``build_features_from_raw_scores``.
        """
        if not self.ml_settings.enabled:
            return 0.0

        # Pick model: per-ticker first if enabled and the ticker has one,
        # else fall back to the portfolio model.
        active_model = None
        if self.ml_settings.per_ticker and ticker:
            active_model = self._try_load_per_ticker_metalearner(ticker)
        if active_model is None:
            active_model = self._metalearner
        if active_model is None or not active_model.is_trained():
            return 0.0

        trained_features = active_model.feature_names or []
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
            ml_score = active_model.predict(feature_inputs)
            # Normalize the prediction to [-1, 1] before applying
            # contribution_weight. Without this, the meta-learner's raw
            # output can be much wider than the [-1, 1] aggregate score
            # range (the training target — profile-aware fitness — can
            # be in [-30, +30] for some profiles), letting the model
            # dominate the linear sum even at small contribution_weight.
            # target_clip is set at fit time to max(|y_train|).
            target_clip = max(active_model.target_clip, 1e-6)
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
            # `ticker` is plumbed so per-ticker mode can pick the
            # ticker-specific model with portfolio fallback.
            ml_contribution = self._metalearner_contribution(edge_map, ticker=ticker)
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

        # Engine C portfolio-optimizer hook (Workstream B). When method
        # is "weighted_sum" (default), this is a no-op. When "hrp", it
        # re-shapes per-ticker score magnitudes so they reflect HRP
        # weight share across the active universe.
        if self.po_settings.method != "weighted_sum" and self._hrp is not None:
            out = self._apply_portfolio_optimizer(out, data_map)

        return out

    def _apply_portfolio_optimizer(
        self,
        out: Dict[str, dict],
        data_map: Dict[str, pd.DataFrame],
    ) -> Dict[str, dict]:
        """Cross-ticker reshape via HRP.

        Two methods:
        - ``method == "hrp"`` (slice 1, FALSIFIED, retained for D-cell
          verification): replaces aggregate_score magnitude with
          HRP-weight × N. Strips edge-ensemble conviction; produces
          -0.63 Sharpe regression vs weighted_sum.
        - ``method == "hrp_composed"`` (slice 3): preserves aggregate_score
          (sign + magnitude) and emits per-ticker ``optimizer_weight``
          (= HRP-weight × N, lower-clamped at 0; mean is exactly 1.0
          across the firing set so the multiplier redistributes size
          rather than reducing it). AlphaEngine threads optimizer_weight
          into signal.meta; Engine B multiplies it into ATR-risk sizing.
          Composes conviction with HRP rather than replacing it. Slice 2
          additionally clamped at 1.0 — that made the multiplier a strict
          reducer (above-mean clamped down, below-mean attenuated; net
          every position ≤ baseline). Slice 3 removes that upper clamp.

        Tickers with aggregate_score ≈ 0 are excluded from HRP and pass
        through unchanged. The turnover gate decides whether to commit
        new weights or reuse the previously-committed vector (active
        for both methods).
        """
        active = [
            t for t, info in out.items()
            if abs(float(info.get("aggregate_score", 0.0))) > 1e-6
        ]
        if len(active) < 2:
            return out

        returns_df = self._build_returns_panel(active, data_map)
        if returns_df is None or returns_df.empty:
            return out

        active = [t for t in active if t in returns_df.columns]
        if len(active) < 2:
            return out

        proposed = self._hrp.optimize(returns_df, active_tickers=active)
        if proposed.empty or not np.isfinite(proposed.values).all():
            return out

        mu = pd.Series(
            {t: float(out[t]["aggregate_score"]) for t in proposed.index}
        )
        committed = self._turnover.evaluate(proposed, mu)

        n = len(committed)
        if n == 0:
            return out
        scale = float(n)
        is_composed = (self.po_settings.method == "hrp_composed")

        for t, w in committed.items():
            if t not in out:
                continue
            raw_magnitude = float(w) * scale
            out[t]["hrp_weight"] = float(w)

            if is_composed:
                # Slice 3 — redistribution, not reduction.
                # `committed` sums to 1.0 by HRP construction, so committed × N
                # has mean exactly 1.0 across the firing set. Keeping only the
                # lower clamp at 0 lets above-mean tickers amplify (>1.0) and
                # below-mean tickers attenuate (<1.0). The slice-2 upper clamp
                # at 1.0 made every position size-at-or-below baseline — a
                # strict reducer, never a redistributor. Engine B's
                # max_gross_exposure cap clips any pathological amplification.
                out[t]["optimizer_weight"] = max(0.0, raw_magnitude)
            else:
                # Slice-1 replacement (kept for D-cell verification only).
                # aggregate_score is conventionally in [-1, 1]; keep the
                # original clamp on this code path so slice-1 reproductions
                # remain bit-identical to the falsified design.
                magnitude = max(0.0, min(1.0, raw_magnitude))
                sgn = 1.0 if out[t]["aggregate_score"] >= 0 else -1.0
                out[t]["aggregate_score"] = sgn * magnitude
                out[t]["optimizer_weight"] = 1.0  # already absorbed into score

        if self.debug:
            print(f"[PORTFOLIO_OPTIMIZER] {self.po_settings.method} applied "
                  f"to n={n} tickers, turnover_stats={self._turnover.stats}")
        return out

    @staticmethod
    def _build_returns_panel(
        tickers: List[str],
        data_map: Dict[str, pd.DataFrame],
        col: str = "Close",
    ) -> Optional[pd.DataFrame]:
        """Wide returns DataFrame across the active tickers, joined on
        the bar index. Returns None if no ticker has usable data.
        """
        series_map: Dict[str, pd.Series] = {}
        for t in tickers:
            df = data_map.get(t)
            if df is None or df.empty or col not in df.columns:
                continue
            s = df[col].astype(float).pct_change().dropna()
            if len(s) > 0:
                series_map[t] = s
        if not series_map:
            return None
        return pd.DataFrame(series_map).dropna(how="all")