"""
core/fitness.py
================
Profile-aware fitness function for Layer 3 (allocation) of the Phase 1
three-layer architecture.

Background: Sharpe-only optimization implicitly commits the system to a
single risk profile. A retiree wants low drawdown / high Sharpe; a
30-year-old wants high CAGR. Same edge pool, different desired
mixture. The fitness function is configurable — it's a weighted
combination of the metrics that `MetricsEngine.calculate_all` already
computes (Sharpe, Sortino, Calmar, CAGR, Max Drawdown).

This module:
  - defines `FitnessConfig` (a named profile + weight dict)
  - loads named profiles from `config/fitness_profiles.yml`
  - exposes `compute_fitness(metrics_dict, profile)` for downstream
    callers (meta-learner training target, allocation engine, gauntlet
    promotion gate, etc.)

The lifecycle layer (Layer 1: alive vs retired) intentionally does NOT
read this — retirement decisions are profile-independent. This module
is consumed only by Layer 3 (allocation).

See `docs/Core/phase1_metalearner_design.md` for the full architecture.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROFILES_PATH = ROOT / "config" / "fitness_profiles.yml"

# Canonical metric keys the fitness function reads from a metrics dict.
# Match the keys that MetricsEngine.calculate_all returns.
SHARPE_KEY = "Sharpe"
SORTINO_KEY = "Sortino"
CALMAR_KEY = "Calmar"
CAGR_PCT_KEY = "CAGR %"           # MetricsEngine returns CAGR as a percent
MDD_PCT_KEY = "Max Drawdown %"    # MetricsEngine returns MDD as a percent (negative)

# Recognized metric names a profile may weight. Profiles using unknown
# names are rejected at load time so silent typos never zero-weight a
# metric the user thought they were including.
RECOGNIZED_METRICS = {"sharpe", "sortino", "calmar", "cagr", "neg_mdd"}


@dataclass(frozen=True)
class FitnessConfig:
    """A named portfolio profile + the metric weights that define its
    fitness.

    Weights are arbitrary positive floats and don't have to sum to 1 —
    they're applied as a linear combination of the metrics. Higher
    fitness = better.

    Example:
        retiree   →  {calmar: 0.6, sortino: 0.3, sharpe: 0.1}
        balanced  →  {sharpe: 0.5, calmar: 0.3, cagr: 0.2}
        growth    →  {cagr: 0.5, sharpe: 0.3, calmar: 0.2}

    Optional `target_vol` and `max_drawdown_tolerance` are profile-level
    portfolio constraints. They're surfaced in the dataclass so the
    allocation engine can read them, but they don't directly enter the
    fitness scalar.
    """
    name: str
    weights: Dict[str, float] = field(default_factory=dict)
    target_vol: Optional[float] = None
    max_drawdown_tolerance: Optional[float] = None

    def __post_init__(self):
        # Validate weight keys against the recognized set so typos fail loud.
        unknown = set(self.weights.keys()) - RECOGNIZED_METRICS
        if unknown:
            raise ValueError(
                f"FitnessConfig '{self.name}' has unknown metric key(s): "
                f"{sorted(unknown)}. Valid: {sorted(RECOGNIZED_METRICS)}"
            )
        if not self.weights:
            raise ValueError(f"FitnessConfig '{self.name}' has empty weights")
        if any(w < 0 for w in self.weights.values()):
            raise ValueError(
                f"FitnessConfig '{self.name}' has negative weight(s): {self.weights}"
            )


def compute_fitness(metrics: Dict[str, float], profile: FitnessConfig) -> float:
    """Apply a profile's weights to a metrics dict and return a scalar fitness.

    `metrics` must be a dict in the shape returned by
    `MetricsEngine.calculate_all` (keys "Sharpe", "Sortino", "Calmar",
    "CAGR %", "Max Drawdown %"). Missing keys default to 0.0 — a degenerate
    or short-window run produces zero fitness rather than crashing.

    Convention:
      - sharpe, sortino, calmar: read directly (higher is better)
      - cagr: read as a fraction (CAGR % / 100) so it's comparable to
        the others
      - neg_mdd: read as -Max Drawdown % / 100 (so positive means
        smaller drawdown). Profile weights this when it cares about
        drawdown control directly rather than via Calmar.
    """
    sharpe = float(metrics.get(SHARPE_KEY, 0.0))
    sortino = float(metrics.get(SORTINO_KEY, 0.0))
    calmar = float(metrics.get(CALMAR_KEY, 0.0))
    cagr = float(metrics.get(CAGR_PCT_KEY, 0.0)) / 100.0
    mdd = float(metrics.get(MDD_PCT_KEY, 0.0)) / 100.0  # negative
    neg_mdd = -mdd  # smaller drawdown → larger neg_mdd

    return (
        profile.weights.get("sharpe", 0.0) * sharpe
        + profile.weights.get("sortino", 0.0) * sortino
        + profile.weights.get("calmar", 0.0) * calmar
        + profile.weights.get("cagr", 0.0) * cagr
        + profile.weights.get("neg_mdd", 0.0) * neg_mdd
    )


def load_profiles(path: Path = DEFAULT_PROFILES_PATH) -> Dict[str, FitnessConfig]:
    """Load all named profiles from a YAML file.

    Expected YAML shape:
      profiles:
        retiree:
          weights: {calmar: 0.6, sortino: 0.3, sharpe: 0.1}
          target_vol: 0.05
          max_drawdown_tolerance: 0.10
        ...
    """
    if not path.exists():
        raise FileNotFoundError(f"Fitness profiles file not found: {path}")
    raw = yaml.safe_load(path.read_text()) or {}
    profiles_raw = raw.get("profiles", {})
    profiles: Dict[str, FitnessConfig] = {}
    for name, body in profiles_raw.items():
        weights = {k: float(v) for k, v in (body.get("weights") or {}).items()}
        profiles[name] = FitnessConfig(
            name=name,
            weights=weights,
            target_vol=body.get("target_vol"),
            max_drawdown_tolerance=body.get("max_drawdown_tolerance"),
        )
    if not profiles:
        raise ValueError(f"No profiles found in {path}")
    return profiles


def get_active_profile(
    profile_name: Optional[str] = None,
    path: Path = DEFAULT_PROFILES_PATH,
) -> FitnessConfig:
    """Resolve the active profile.

    Resolution order:
      1. Explicit `profile_name` argument
      2. `active_profile` field in the YAML root
      3. Default to "balanced" if present
      4. First profile in the file (whatever it is) as last resort
    """
    profiles = load_profiles(path)
    if profile_name and profile_name in profiles:
        return profiles[profile_name]
    raw = yaml.safe_load(path.read_text()) or {}
    yaml_active = raw.get("active_profile")
    if yaml_active and yaml_active in profiles:
        return profiles[yaml_active]
    if "balanced" in profiles:
        return profiles["balanced"]
    return next(iter(profiles.values()))


__all__ = [
    "FitnessConfig",
    "RECOGNIZED_METRICS",
    "compute_fitness",
    "load_profiles",
    "get_active_profile",
    "DEFAULT_PROFILES_PATH",
    "SHARPE_KEY",
    "SORTINO_KEY",
    "CALMAR_KEY",
    "CAGR_PCT_KEY",
    "MDD_PCT_KEY",
]
