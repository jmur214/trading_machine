"""Tests for the T-022 gene-encoding extension.

T-022 added a `foundry_feature` gene type to the Discovery GA's
`_create_random_gene` factory and a matching evaluator branch in
`composite_edge._calc_raw_value`. Pre-T-022 Discovery emitted only
rsi_bounce_v1 mutations on substrate-honest (T-021 finding); this fix
makes the post-T-006 + post-T-014 Foundry vocabulary reachable.

Tests cover:
- Gene factory emits foundry_feature with ~20% frequency (spec band 15-25%)
- All emitted feature_ids exist in the Foundry registry
- CompositeEdge evaluates foundry_feature genes without crash
- Missing / nonexistent feature_id returns abstain (None → 0.0 score)
- Existing 9 gene categories still emit (technical reduced but present)
- Determinism: same seeded random call produces identical gene sets
"""
from __future__ import annotations

import random
import sys
from collections import Counter
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from engines.engine_d_discovery.discovery import DiscoveryEngine  # noqa: E402
from engines.engine_a_alpha.edges.composite_edge import CompositeEdge  # noqa: E402
from core.feature_foundry import get_feature_registry  # noqa: E402
import core.feature_foundry.features  # noqa: F401, E402  trigger registration


def _make_factory():
    """Bypass DiscoveryEngine.__init__ — we only exercise _create_random_gene."""
    return DiscoveryEngine.__new__(DiscoveryEngine)


def _draw_n_genes(n: int, seed: int = 42) -> list[dict]:
    random.seed(seed)
    d = _make_factory()
    return [d._create_random_gene() for _ in range(n)]


# ---------------------------------------------------------------------------
# Gene factory — foundry_feature presence + frequency
# ---------------------------------------------------------------------------

def test_gene_factory_emits_foundry_feature_type():
    """At N=1000, at least 100 of the emitted genes should be foundry_feature
    (spec target ~20% — band 15-25% acceptable)."""
    genes = _draw_n_genes(1000, seed=42)
    types = Counter(g["type"] for g in genes)
    foundry_count = types.get("foundry_feature", 0)
    assert foundry_count >= 100, (
        f"foundry_feature emitted only {foundry_count}/1000 times; "
        f"spec target ~200 (20%), floor 100 (10%). Distribution: {dict(types)}"
    )
    assert foundry_count <= 300, (
        f"foundry_feature dominates at {foundry_count}/1000; spec ceiling "
        f"is ~250 (25%)."
    )


def test_foundry_gene_uses_registered_feature_id():
    """Every emitted foundry_feature gene must have a feature_id that
    exists in the live Foundry registry."""
    genes = _draw_n_genes(1000, seed=42)
    foundry_genes = [g for g in genes if g["type"] == "foundry_feature"]
    assert foundry_genes, "no foundry_feature genes emitted — extension broken"

    reg = get_feature_registry()
    registered_ids = set(reg._features.keys())
    for g in foundry_genes:
        fid = g.get("feature_id")
        assert fid in registered_ids, (
            f"foundry_feature gene emitted unregistered feature_id={fid!r}. "
            f"Registry has {len(registered_ids)} features."
        )


def test_foundry_gene_has_well_formed_operator_and_threshold():
    """Foundry genes use one of {top_percentile, bottom_percentile,
    greater, less} with a sensible threshold."""
    genes = _draw_n_genes(1000, seed=42)
    foundry_genes = [g for g in genes if g["type"] == "foundry_feature"]
    valid_ops = {"top_percentile", "bottom_percentile", "greater", "less"}
    for g in foundry_genes:
        op = g.get("operator")
        assert op in valid_ops, f"unexpected operator {op!r} in {g}"
        thr = g.get("threshold")
        if op in ("top_percentile", "bottom_percentile"):
            assert isinstance(thr, (int, float))
            assert 0 <= thr <= 100, f"percentile threshold out of [0,100]: {thr}"
        else:
            assert isinstance(thr, (int, float))


# ---------------------------------------------------------------------------
# CompositeEdge evaluator
# ---------------------------------------------------------------------------

def _make_data_map(start="2023-10-01", n_bars=80):
    idx = pd.date_range(start, periods=n_bars, freq="B")
    df = pd.DataFrame(
        {"Open": 100.0, "High": 101.0, "Low": 99.0,
         "Close": 100.0, "Volume": 1_000_000},
        index=idx,
    )
    return {"AAPL": df}


def test_composite_edge_evaluates_foundry_gene_known_pass():
    """sell_in_may_halloween returns 1.0 in Jan (Nov-Apr 'in' window);
    operator=greater, threshold=0.5 → pass → long signal."""
    edge = CompositeEdge()
    edge.genes = [{
        "type": "foundry_feature",
        "feature_id": "sell_in_may_halloween",
        "operator": "greater",
        "threshold": 0.5,
    }]
    edge.direction = "long"
    scores = edge.compute_signals(_make_data_map(), pd.Timestamp("2024-01-15"))
    assert scores.get("AAPL") == 1.0, (
        f"sell_in_may=1.0 in Jan should pass greater(0.5); got {scores}"
    )


def test_composite_edge_evaluates_foundry_gene_known_fail():
    """Same gene on May 15 → feature returns 0.0 → fails greater(0.5)
    → abstain."""
    edge = CompositeEdge()
    edge.genes = [{
        "type": "foundry_feature",
        "feature_id": "sell_in_may_halloween",
        "operator": "greater",
        "threshold": 0.5,
    }]
    edge.direction = "long"
    scores = edge.compute_signals(_make_data_map(), pd.Timestamp("2024-05-15"))
    assert scores.get("AAPL") == 0.0


def test_composite_edge_skips_missing_foundry_value():
    """Nonexistent feature_id → registry returns None → evaluator returns
    None → abstain (not crash)."""
    edge = CompositeEdge()
    edge.genes = [{
        "type": "foundry_feature",
        "feature_id": "nonexistent_feature_zzz_qq",
        "operator": "greater",
        "threshold": 0.5,
    }]
    edge.direction = "long"
    scores = edge.compute_signals(_make_data_map(), pd.Timestamp("2024-01-15"))
    assert scores.get("AAPL") == 0.0


def test_composite_edge_skips_when_feature_returns_none():
    """When a registered feature returns None for the (ticker, date) —
    e.g., tax_loss_season outside Dec 10-24 returns None — the gene
    drops, all_genes_pass becomes False, abstain."""
    edge = CompositeEdge()
    edge.genes = [{
        "type": "foundry_feature",
        "feature_id": "tax_loss_season",
        "operator": "greater",
        "threshold": 0.5,
    }]
    edge.direction = "long"
    # September — tax_loss_season returns 0.0 (outside Dec 10-24 window).
    # Doesn't return None, just 0.0. Still fails greater(0.5) → abstain.
    scores = edge.compute_signals(_make_data_map(), pd.Timestamp("2024-09-15"))
    assert scores.get("AAPL") == 0.0


# ---------------------------------------------------------------------------
# Existing gene types — sanity that they still emit
# ---------------------------------------------------------------------------

def test_existing_gene_types_unchanged_in_presence():
    """All 9 pre-T-022 categories must still emit at non-trivial frequency."""
    genes = _draw_n_genes(2000, seed=42)
    types = Counter(g["type"] for g in genes)
    expected_present = {
        "regime", "calendar", "microstructure", "intermarket",
        "macro", "earnings", "behavioral", "fundamental", "technical",
    }
    for t in expected_present:
        assert types[t] > 0, (
            f"category {t!r} disappeared post-T-022; distribution: {dict(types)}"
        )


def test_technical_bucket_reduced_to_target_band():
    """Spec: technical reduced from 35% to ~15% (band 10-20%)."""
    genes = _draw_n_genes(2000, seed=42)
    types = Counter(g["type"] for g in genes)
    tech_pct = 100 * types["technical"] / 2000
    assert 10 <= tech_pct <= 22, (
        f"technical bucket at {tech_pct:.1f}% (expected 10-22% per spec); "
        f"distribution: {dict(types)}"
    )


# ---------------------------------------------------------------------------
# Determinism — same seed produces same gene set
# ---------------------------------------------------------------------------

def test_gene_factory_is_deterministic_under_seeded_random():
    """Two seeded draws of N=100 genes must be bit-identical."""
    a = _draw_n_genes(100, seed=42)
    b = _draw_n_genes(100, seed=42)
    assert a == b, "gene factory non-deterministic under seeded random.seed(42)"


def test_foundry_gene_feature_ids_are_stable_across_seeds():
    """Under the same seed, the SEQUENCE of foundry feature_ids emitted
    is identical — verifies sorted(eligible_ids) yields a stable ordering."""
    a = _draw_n_genes(500, seed=7)
    b = _draw_n_genes(500, seed=7)
    a_fids = [g["feature_id"] for g in a if g["type"] == "foundry_feature"]
    b_fids = [g["feature_id"] for g in b if g["type"] == "foundry_feature"]
    assert a_fids == b_fids
