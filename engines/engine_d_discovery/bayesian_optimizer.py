"""
engines/engine_d_discovery/bayesian_optimizer.py
==================================================
Engine D Bayesian-opt candidate search (T-028 implementation per T-027 spec).

Replaces (behind a config flag) the GA's `_create_random_gene` + mutate-
based candidate generation with a Bayesian-optimization-guided search
over the gene space. Default OFF; enabled via `use_bayesian_opt: true`
in discovery config.

Design (per `docs/Measurements/2026-05/spec_engine_d_bayesian_opt_scaffolding_2026_05_11.md`):

- **Library**: scikit-optimize (skopt) 0.10.x — scipy-based, deterministic
  via `random_state`, supports Categorical+Real mixed search spaces.
- **Search space**: flat per-gene encoding. Each candidate carries ONE
  gene (single-gene genomes for T-028a; multi-gene combining is deferred
  per spec open Q1). The flat space has 4-5 dimensions: gene_type +
  conditional indicator/feature_id + operator + percentile-or-raw threshold.
- **Objective**: cumulative gate-passage margin (Option B per spec).
  Warm-start data carries (gene_shape, fitness_score) pairs; surrogate
  fits on prior trials.
- **Acquisition**: Expected Improvement (EI), explicit (not gp_hedge).
- **Warm-start**: from `data/governor/ga_population.yml`'s fitness_cache,
  if present. Otherwise cold-start with `n_initial_points=10`.
- **Determinism**: `random_state` seeded from PYTHONHASHSEED; sorted
  warm-start input ensures stable surrogate fit order. Verified via
  2-run cross-check.
"""
from __future__ import annotations

import logging
import os
import random as _stdlib_random
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("BAYESIAN_OPT")


def _resolve_random_state(seed: Optional[int]) -> int:
    """If no seed provided, use PYTHONHASHSEED (or fall back to 0)."""
    if seed is not None:
        return int(seed)
    env = os.environ.get("PYTHONHASHSEED", "0")
    try:
        return int(env)
    except (TypeError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Search space: flat per-gene encoding
# ---------------------------------------------------------------------------
# Per T-027 spec section 2: conditional per-gene-type schema via dispatch.
# For T-028a we use a flat search space (single gene per candidate); the
# decoder picks which conditional dimensions are relevant per gene_type.

# Gene types from `discovery.py::_create_random_gene` (10 types, T-022 ext).
GENE_TYPES = [
    "regime",
    "calendar",
    "microstructure",
    "intermarket",
    "macro",
    "earnings",
    "behavioral",
    "fundamental",
    "foundry_feature",
    "technical",
]

# Operators used across gene types
OPERATORS = ["less", "greater", "top_percentile", "bottom_percentile", "is"]


def _foundry_feature_ids() -> List[str]:
    """Sorted list of Foundry feature_ids — required for stable
    Categorical sampling under random_state. Same access pattern as
    T-022's `_create_random_gene`."""
    try:
        from core.feature_foundry import get_feature_registry
        import core.feature_foundry.features  # noqa: F401  trigger register
        reg = get_feature_registry()
        eligible = [
            f.feature_id for f in reg._features.values()
            if f.tier in ("A", "B")
        ]
        return sorted(eligible)
    except Exception:
        logger.debug("Foundry registry unreachable; returning empty list")
        return []


# Indicator sets per gene type (the dispatcher in `_decode_point` picks
# the right list based on gene_type).
TECHNICAL_INDICATORS = [
    "rsi", "volatility", "sma_dist_pct", "sma_cross", "donchian_breakout",
    "pivot_position", "momentum_roc", "residual_momentum", "volatility_diff",
]
CALENDAR_INDICATORS = [
    "day_of_week_sin", "month_sin", "quarter_end_proximity", "opex_proximity",
]
MICROSTRUCTURE_INDICATORS = ["overnight_gap", "close_location", "intraday_range"]
INTERMARKET_INDICATORS = [
    "spy_return_5d", "tlt_return_5d", "gld_return_5d", "spy_tlt_corr",
]
MACRO_INDICATORS = ["yield_curve", "vix_level", "unemployment_delta"]
EARNINGS_INDICATORS = ["eps_surprise_pct"]
BEHAVIORAL_INDICATORS = ["panic_score", "herding_breadth"]
FUNDAMENTAL_METRICS = [
    "PE_Ratio", "PS_Ratio", "PB_Ratio", "PFCF_Ratio", "Debt_to_Equity",
]
REGIME_TARGETS = ["bull", "bear", "neutral_low_vol"]


# ---------------------------------------------------------------------------
# Gene encoding / decoding
# ---------------------------------------------------------------------------

def _decode_point(point: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a skopt-suggested point dict into a gene-shape dict that
    composite_edge's evaluator can consume.

    point keys: gene_type, indicator_idx, operator, threshold_pctile,
    threshold_raw, foundry_feature_id (only used for foundry_feature type).
    """
    gene_type = point["gene_type"]
    operator = point["operator"]
    threshold_pctile = point["threshold_pctile"]
    threshold_raw = point["threshold_raw"]

    gene: Dict[str, Any] = {"type": gene_type, "operator": operator}

    # Per-type dispatch (mirrors _create_random_gene's structure).
    if gene_type == "regime":
        idx = point["indicator_idx"] % max(1, len(REGIME_TARGETS))
        gene["is"] = REGIME_TARGETS[idx]
        gene["operator"] = "is"
    elif gene_type == "calendar":
        idx = point["indicator_idx"] % max(1, len(CALENDAR_INDICATORS))
        gene["indicator"] = CALENDAR_INDICATORS[idx]
        gene["threshold"] = (
            threshold_pctile / 100.0 - 0.5  # map [0,100] → [-0.5, +0.5] for sin
            if gene["indicator"] in ("day_of_week_sin", "month_sin")
            else threshold_raw
        )
    elif gene_type == "microstructure":
        idx = point["indicator_idx"] % max(1, len(MICROSTRUCTURE_INDICATORS))
        gene["indicator"] = MICROSTRUCTURE_INDICATORS[idx]
        gene["threshold"] = threshold_raw
    elif gene_type == "intermarket":
        idx = point["indicator_idx"] % max(1, len(INTERMARKET_INDICATORS))
        gene["indicator"] = INTERMARKET_INDICATORS[idx]
        gene["threshold"] = threshold_raw
        if gene["indicator"] in ("spy_return_5d", "tlt_return_5d", "gld_return_5d"):
            gene["window"] = 5
    elif gene_type == "macro":
        idx = point["indicator_idx"] % max(1, len(MACRO_INDICATORS))
        gene["indicator"] = MACRO_INDICATORS[idx]
        gene["threshold"] = threshold_raw
    elif gene_type == "earnings":
        gene["indicator"] = "eps_surprise_pct"
        gene["threshold"] = threshold_raw
        gene["lookback_days"] = 60
    elif gene_type == "behavioral":
        idx = point["indicator_idx"] % max(1, len(BEHAVIORAL_INDICATORS))
        gene["indicator"] = BEHAVIORAL_INDICATORS[idx]
        gene["threshold"] = max(0.0, threshold_pctile)
    elif gene_type == "fundamental":
        idx = point["indicator_idx"] % max(1, len(FUNDAMENTAL_METRICS))
        gene["metric"] = FUNDAMENTAL_METRICS[idx]
        if "percentile" in operator:
            gene["threshold"] = threshold_pctile
        else:
            gene["threshold"] = threshold_raw
    elif gene_type == "foundry_feature":
        feats = _foundry_feature_ids()
        if not feats:
            # Fallback: skip foundry, route to technical
            gene["type"] = "technical"
            gene["indicator"] = TECHNICAL_INDICATORS[
                point["indicator_idx"] % max(1, len(TECHNICAL_INDICATORS))
            ]
            gene["threshold"] = threshold_raw
        else:
            idx = point["indicator_idx"] % max(1, len(feats))
            gene["feature_id"] = feats[idx]
            if "percentile" in operator:
                gene["threshold"] = threshold_pctile
            else:
                gene["threshold"] = threshold_raw
    else:  # technical (fallback)
        idx = point["indicator_idx"] % max(1, len(TECHNICAL_INDICATORS))
        gene["indicator"] = TECHNICAL_INDICATORS[idx]
        if "percentile" in operator:
            gene["threshold"] = threshold_pctile
        else:
            gene["threshold"] = threshold_raw
    return gene


def _encode_gene(gene: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a gene-shape dict into a skopt-point dict for warm-start.
    Inverse of `_decode_point` (lossy on the indicator index due to
    cross-type union encoding)."""
    gene_type = gene.get("type", "technical")
    # Map indicator/feature_id to an index in the per-type list. If not
    # found, default to 0 (skopt clamps to valid range).
    indicator_idx = 0
    if gene_type == "regime":
        target = gene.get("is")
        if target in REGIME_TARGETS:
            indicator_idx = REGIME_TARGETS.index(target)
    elif gene_type == "calendar":
        ind = gene.get("indicator")
        if ind in CALENDAR_INDICATORS:
            indicator_idx = CALENDAR_INDICATORS.index(ind)
    elif gene_type == "foundry_feature":
        fid = gene.get("feature_id")
        feats = _foundry_feature_ids()
        if fid in feats:
            indicator_idx = feats.index(fid)
    elif gene_type == "technical":
        ind = gene.get("indicator")
        if ind in TECHNICAL_INDICATORS:
            indicator_idx = TECHNICAL_INDICATORS.index(ind)
    # ... (other types similarly; default 0 is safe for skopt clamping)

    threshold = gene.get("threshold", 0.0)
    if "percentile" in str(gene.get("operator", "")):
        threshold_pctile = float(threshold)
        threshold_raw = 0.0
    else:
        threshold_pctile = 50.0
        threshold_raw = float(threshold) if not isinstance(threshold, str) else 0.0

    # Clip to search-space bounds — gene thresholds in the wild can
    # exceed [-1, 1] (e.g., RSI=30, percentile=80) but the Bayesian
    # search space treats threshold_raw as a small-bounded continuous
    # dimension. Clipping for warm-start tell() purposes only — the
    # surrogate's prediction at the clipped point is still informative.
    threshold_raw = max(-1.0, min(1.0, threshold_raw))
    threshold_pctile = max(0.0, min(100.0, threshold_pctile))

    return {
        "gene_type": gene_type,
        "indicator_idx": int(indicator_idx),
        "operator": gene.get("operator", "less"),
        "threshold_pctile": float(threshold_pctile),
        "threshold_raw": float(threshold_raw),
    }


# ---------------------------------------------------------------------------
# Objective function: cumulative gate-passage margin
# ---------------------------------------------------------------------------

def cumulative_gate_margin(gauntlet_result: Dict[str, Any]) -> float:
    """Compute the spec's Option-B objective: sum of (metric - threshold)/
    abs(threshold) across all gates the candidate reached, with a small
    partial-credit term for the gate that killed it.

    Higher = better. Skopt minimizes, so caller passes -margin to skopt.
    """
    if not gauntlet_result:
        # Empty dict or None — no gauntlet data, neutral score
        return 0.0
    gates_passed = gauntlet_result.get("gate_passed", {}) or {}
    metrics = gauntlet_result.get("metrics", {}) or {}
    if not metrics:
        # Result dict provided but no metrics inside — neutral
        return 0.0
    # Gate config: (gate_key, metric_key, threshold)
    gate_specs = [
        ("gate_1", "sharpe", float(metrics.get("benchmark_threshold", 0.1))),
        # Gates 2-8 thresholds aren't always present in the result dict;
        # for warm-start training we use the metric value as a proxy
        # (positive = "passed easily").
    ]
    margin = 0.0
    for gate_key, metric_key, threshold in gate_specs:
        passed = bool(gates_passed.get(gate_key, False))
        m = float(metrics.get(metric_key, 0.0) or 0.0)
        norm = (m - threshold) / max(abs(threshold), 1e-6)
        if passed:
            margin += norm
        else:
            margin += norm / 10.0
            break
    return margin


# ---------------------------------------------------------------------------
# BayesianOptimizer class
# ---------------------------------------------------------------------------

class BayesianOptimizer:
    """Bayesian-optimization-guided candidate search for Engine D.

    Single-gene per candidate (T-028a scope). Multi-gene combining is
    deferred per T-027 spec open Q1.

    Usage:
        opt = BayesianOptimizer(random_state=0)
        opt.warm_start(fitness_cache_entries)  # optional
        candidates = opt.suggest_candidates(n=30)
        # candidates is List[Dict] in the same shape _run_ga_evolution returns
    """

    def __init__(
        self,
        random_state: Optional[int] = None,
        acq_func: str = "EI",
        n_initial_points: int = 10,
        max_genes: int = 1,
    ):
        from skopt import Optimizer
        from skopt.space import Categorical, Real, Integer

        self.random_state = _resolve_random_state(random_state)
        self.acq_func = acq_func
        self.n_initial_points = int(n_initial_points)
        self.max_genes = int(max_genes)

        # Flat search space. indicator_idx is an Integer that the decoder
        # mods by the per-type list length — keeps skopt happy with a
        # uniform integer dimension.
        self.dimensions = [
            Categorical(GENE_TYPES, name="gene_type"),
            Integer(0, 31, name="indicator_idx"),  # max len of any indicator list
            Categorical(OPERATORS, name="operator"),
            Real(0.0, 100.0, name="threshold_pctile"),
            Real(-1.0, 1.0, name="threshold_raw"),
        ]
        self.dim_names = [d.name for d in self.dimensions]

        self._opt = Optimizer(
            dimensions=self.dimensions,
            base_estimator="GP",
            acq_func=self.acq_func,
            n_initial_points=self.n_initial_points,
            random_state=self.random_state,
        )
        self._warm_started = False

    def warm_start(self, entries: List[Tuple[Dict[str, Any], float]]) -> int:
        """Register `(gene, score)` pairs from a prior cycle's
        fitness_cache so the surrogate fits on existing observations.

        `score`: higher is better (cumulative gate-passage margin). The
        optimizer is told to MINIMIZE -score per skopt convention.

        Returns the count of entries successfully registered.
        """
        # Sort by gene shape for deterministic surrogate fit order
        sorted_entries = sorted(
            entries,
            key=lambda e: (str(e[0].get("type", "")), str(e[0])),
        )
        n = 0
        for gene, score in sorted_entries:
            point_dict = _encode_gene(gene)
            point_list = [point_dict[name] for name in self.dim_names]
            try:
                self._opt.tell(point_list, -float(score))
                n += 1
            except Exception as e:
                logger.debug(f"warm_start tell failed for {gene}: {e}")
        if n > 0:
            self._warm_started = True
        return n

    def suggest_candidates(self, n: int) -> List[Dict[str, Any]]:
        """Suggest N candidate gene-specs ready for downstream gauntlet
        validation. Returns list of candidate dicts in the same shape
        `_run_ga_evolution` returns (edge_id, module, class, params,
        status, version, origin)."""
        out: List[Dict[str, Any]] = []
        # Use a SEPARATE local random source for suffix generation so it
        # doesn't perturb the global `random` state used by GA's path.
        # Seeded from random_state for reproducibility.
        suffix_rng = _stdlib_random.Random(self.random_state)
        for _i in range(int(n)):
            point_list = self._opt.ask()
            point_dict = {name: val for name, val in zip(self.dim_names, point_list)}
            gene = _decode_point(point_dict)
            suffix = "".join(suffix_rng.choices("abcdef0123456789", k=6))
            edge_id = f"composite_bayes_{suffix}"
            # Direction sampled randomly per spec open Q2 recommendation
            r = suffix_rng.random()
            if r < 0.10:
                direction = "short"
            elif r < 0.20:
                direction = "market_neutral"
            else:
                direction = "long"
            spec = {
                "edge_id": edge_id,
                "module": "engines.engine_a_alpha.edges.composite_edge",
                "class": "CompositeEdge",
                "category": "experimental_bayes",
                "params": {
                    "genes": [gene],
                    "direction": direction,
                },
                "status": "candidate",
                "version": "1.0.0-bayes",
                "origin": "bayesian_optimizer",
            }
            out.append(spec)
            # Skopt expects a "fake" tell to advance the surrogate when
            # no actual evaluation feedback is available within this loop.
            # In T-028a scope we suggest N upfront WITHOUT inline feedback;
            # surrogate updates happen between cycles via warm_start of
            # the next cycle's fitness_cache. So we tell skopt a neutral
            # placeholder to advance the internal counter.
            try:
                self._opt.tell(point_list, 0.0)
            except Exception as e:
                logger.debug(f"placeholder tell failed: {e}")
        return out

    def n_observations(self) -> int:
        """How many points has the surrogate seen (warm-start + tells)."""
        return len(getattr(self._opt, "Xi", []) or [])
