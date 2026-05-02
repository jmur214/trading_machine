"""Feature Foundry — substrate for cheap, validated feature additions.

The Foundry is the infrastructure layer that makes adding the 50th feature
cost the same as adding the 5th. Six components:

  F1. DataSource     — generic ingestion plugin ABC + registry + parquet cache
  F2. feature        — function decorator + registry capturing metadata
  F3. ablation       — leave-one-out runner measuring per-feature contribution
  F4. adversarial    — permuted twin generator (real must beat its twin)
  F5. model_card     — YAML lineage + validator (license/PIT/failure modes)
  F6. dashboard tab  — single audit view (importance, contribution, drift)

Built per the reviewer rule (`docs/Progress_Summaries/Other-dev-opinion/
05-1-26_1-percent.md` Workstream D): "marginal cost of feature N is constant
once the substrate exists."

Foundry features are DELIBERATELY DECOUPLED from `engines/engine_a_alpha/
edge_registry.py`. Edges are tradeable signals with lifecycle/tier; Foundry
features are meta-learner inputs with adversarial filtering. They may
eventually integrate, but the substrate ships first.
"""
from __future__ import annotations

from .data_source import DataSource, DataSourceRegistry, get_source_registry
from .feature import Feature, FeatureRegistry, feature, get_feature_registry
from .ablation import (
    AblationResult,
    run_ablation,
    latest_ablation,
    latest_ablation_for_feature,
)
from .adversarial import generate_twin, twin_id_for
from .model_card import ModelCard, load_model_card, validate_all_model_cards

__all__ = [
    "DataSource",
    "DataSourceRegistry",
    "get_source_registry",
    "Feature",
    "FeatureRegistry",
    "feature",
    "get_feature_registry",
    "AblationResult",
    "run_ablation",
    "latest_ablation",
    "latest_ablation_for_feature",
    "generate_twin",
    "twin_id_for",
    "ModelCard",
    "load_model_card",
    "validate_all_model_cards",
]
