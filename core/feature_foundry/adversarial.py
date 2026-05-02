"""Adversarial twin generator.

F4 of the Feature Foundry. For every real feature, automatically create
a permuted version with the same statistical signature (per-ticker
distribution preserved) but no signal — the time series is shuffled
within each ticker, breaking any (ticker, date) → return relationship
while preserving marginal statistics.

The reviewer's adversarial-validation rule:

    Real features must rank above their twins in meta-learner importance.
    Twins ranking above their reals is direct evidence of overfitting.

This module ships the generator and a deterministic permutation scheme
keyed on `feature_id` so twins are reproducible across runs (the same
twin every time, given the same upstream data — required for
deterministic gauntlet measurement).

The twin Feature is registered with `tier='adversarial'`. The
meta-learner integration consumes both real and adversarial features
identically; the adversarial filter (real-importance > twin-importance)
runs as part of the feature audit dashboard.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import numpy as np
import pandas as pd

from .feature import Feature, get_feature_registry


def twin_id_for(feature_id: str) -> str:
    """Canonical twin id for a real feature."""
    return f"{feature_id}__adversarial_twin"


def _stable_seed(feature_id: str, ticker: str) -> int:
    """Deterministic per-(feature, ticker) seed. Permutations are stable
    across runs so the gauntlet sees the same twin time series every
    time — required for deterministic Sharpe measurement."""
    raw = f"{feature_id}|{ticker}".encode("utf-8")
    return int.from_bytes(raw, "big") % (2**32 - 1)


def generate_twin(real: Feature) -> Feature:
    """Build and register the adversarial twin for `real`.

    The twin closure permutes the real feature's per-ticker time series.
    Permutation preserves the per-ticker marginal distribution (same
    mean, std, skew) but destroys temporal alignment with returns.

    The twin is cached lazily — the first call for each (feature_id,
    ticker) materialises the real series, permutes it deterministically,
    and stores the (date → permuted_value) mapping. Subsequent calls hit
    the cache.
    """
    if real.tier == "adversarial":
        raise ValueError(
            f"Cannot generate twin of an adversarial feature "
            f"({real.feature_id!r}); twins are leaf nodes."
        )

    twin_fid = twin_id_for(real.feature_id)

    # Per-(real_feature, ticker) cache of (date -> permuted_value).
    cache: dict[str, dict[date, Optional[float]]] = {}

    def _twin_func(ticker: str, dt: date) -> Optional[float]:
        if ticker not in cache:
            # Lazy materialisation: we don't know the date universe at
            # registration time. We probe the real feature on a wide
            # window centered on the requested date so the permutation
            # is stable per ticker.
            start = date(dt.year - 5, 1, 1)
            end = date(dt.year + 1, 12, 31)
            dates = pd.date_range(start, end, freq="D").date
            values = [real.func(ticker, d) for d in dates]
            arr = np.array(
                [v if v is not None else np.nan for v in values],
                dtype=float,
            )
            rng = np.random.default_rng(_stable_seed(real.feature_id, ticker))
            # Permute only the non-null entries — preserves the missing-
            # value pattern (which itself can carry information; we don't
            # want the twin to gain "always-defined" coverage that the
            # real lacks).
            mask = ~np.isnan(arr)
            permuted = arr.copy()
            non_null = arr[mask]
            rng.shuffle(non_null)
            permuted[mask] = non_null
            cache[ticker] = {
                d: (None if np.isnan(v) else float(v))
                for d, v in zip(dates, permuted)
            }
        return cache[ticker].get(dt)

    twin = Feature(
        feature_id=twin_fid,
        func=_twin_func,
        tier="adversarial",
        horizon=real.horizon,
        license=real.license,
        source=real.source,
        description=f"Adversarial twin of {real.feature_id!r} — "
                    f"per-ticker shuffled, distribution-preserving.",
    )
    get_feature_registry().register(twin)
    return twin


def assert_adversarial_filter_passes(
    real_importance: float,
    twin_importance: float,
    feature_id: str,
) -> None:
    """Convenience guard for CI / dashboard: raises if the twin ranks
    above its real, which is the project's hard adversarial filter."""
    if twin_importance >= real_importance:
        raise AssertionError(
            f"Adversarial filter FAILED for {feature_id!r}: "
            f"twin importance {twin_importance:.4f} ≥ real "
            f"importance {real_importance:.4f}. Feature is overfit."
        )
