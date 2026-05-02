"""Feature interface — `@feature` decorator + registry.

F2 of the Feature Foundry. Wrap any `(ticker, date) -> Optional[float]`
function with the decorator and the Foundry takes over: metadata is
captured, the function is registered, the meta-learner can enumerate
all known features, and the dashboard surfaces them.

Usage:

    from core.feature_foundry import feature

    @feature(
        feature_id="cot_commercial_net_long",
        tier="B",
        horizon=5,
        license="public",
        source="cftc_cot",
    )
    def cot_commercial_net_long(ticker: str, dt: date) -> float | None:
        ...

`tier` here is the Foundry feature tier (A/B/adversarial) — distinct
from the existing `engines.engine_a_alpha.edge_registry` tier vocabulary
(alpha/feature/context). Edges trade; Foundry features feed the
meta-learner. Reuse via name overlap is intentional but the mappings
live in different registries to keep substrate concerns separate.

Tier vocabulary:
  A           — primary feature, strong prior of signal
  B           — secondary / experimental feature
  adversarial — auto-generated permuted twin (see adversarial.py)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Callable, Dict, List, Optional

import pandas as pd


VALID_TIERS = {"A", "B", "adversarial"}


@dataclass
class Feature:
    """Metadata + callable for a single Foundry feature."""

    feature_id: str
    func: Callable[[str, date], Optional[float]]
    tier: str
    horizon: int                # in days
    license: str
    source: str                 # name of the DataSource it consumes
    description: str = ""
    registered_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def __post_init__(self) -> None:
        if self.tier not in VALID_TIERS:
            raise ValueError(
                f"Feature {self.feature_id!r} has invalid tier {self.tier!r}; "
                f"must be one of {sorted(VALID_TIERS)}"
            )
        if self.horizon < 0:
            raise ValueError(
                f"Feature {self.feature_id!r} horizon must be ≥ 0, got {self.horizon}"
            )

    def __call__(self, ticker: str, dt: date) -> Optional[float]:
        return self.func(ticker, dt)

    def evaluate_panel(self, tickers: List[str],
                       dates: List[date]) -> pd.DataFrame:
        """Evaluate this feature across the (ticker × date) panel and
        return a long-format DataFrame. Used by the ablation runner and
        the adversarial twin generator. Missing values stay NaN."""
        rows = []
        for t in tickers:
            for d in dates:
                rows.append({
                    "ticker": t,
                    "date": d,
                    "value": self.func(t, d),
                })
        df = pd.DataFrame(rows)
        df["date"] = pd.to_datetime(df["date"])
        return df


class FeatureRegistry:
    """Process-local registry of `Feature` instances. Decorated functions
    self-register at import time; the dashboard, ablation runner, and
    adversarial twin generator enumerate via `list_features()`."""

    def __init__(self) -> None:
        self._features: Dict[str, Feature] = {}

    def register(self, feat: Feature) -> None:
        if feat.feature_id in self._features:
            existing = self._features[feat.feature_id]
            # Re-registration of the same callable is fine (re-import); a
            # different callable under the same id is a bug.
            if existing.func is not feat.func:
                raise ValueError(
                    f"Feature id collision: {feat.feature_id!r} already "
                    f"registered to a different function "
                    f"({existing.func!r} vs {feat.func!r})"
                )
        self._features[feat.feature_id] = feat

    def get(self, feature_id: str) -> Optional[Feature]:
        return self._features.get(feature_id)

    def list_features(self, tier: Optional[str] = None) -> List[Feature]:
        feats = list(self._features.values())
        if tier:
            feats = [f for f in feats if f.tier == tier]
        return feats

    def clear(self) -> None:
        """Test-only — drop all registrations."""
        self._features.clear()


_REGISTRY = FeatureRegistry()


def get_feature_registry() -> FeatureRegistry:
    return _REGISTRY


def feature(
    *,
    feature_id: str,
    tier: str,
    horizon: int,
    license: str,
    source: str,
    description: str = "",
):
    """Decorator that wraps a `(ticker, date) -> Optional[float]` function
    in a `Feature` and registers it with the Foundry registry.

    Returns the `Feature` instance itself (callable) so call sites get
    the same surface as the underlying function.
    """

    def _wrap(func: Callable[[str, date], Optional[float]]) -> Feature:
        feat = Feature(
            feature_id=feature_id,
            func=func,
            tier=tier,
            horizon=horizon,
            license=license,
            source=source,
            description=description or (func.__doc__ or "").strip(),
        )
        get_feature_registry().register(feat)
        return feat

    return _wrap
