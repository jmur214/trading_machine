"""Tests for scripts/train_minimal_hmm.py — variant configuration + outputs."""
from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

REPO = Path(__file__).resolve().parents[1]


def _has_required_data() -> bool:
    needed = [
        "BAMLH0A0HYM2.parquet", "BAMLC0A0CM.parquet",
        "HG_F.parquet", "GC_F.parquet", "XLP.parquet", "XLY.parquet",
        "T10Y2Y.parquet", "BAA10Y.parquet", "AAA10Y.parquet", "DTWEXBGS.parquet",
    ]
    return all((REPO / "data" / "macro" / n).exists() for n in needed)


def test_variants_dict_is_well_formed():
    """The VARIANTS registry shapes the training contract; make sure it
    stays well-typed."""
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    from train_minimal_hmm import VARIANTS

    assert set(VARIANTS) == {"A", "B", "C"}
    for v, (features, kwargs) in VARIANTS.items():
        assert isinstance(features, tuple)
        assert all(isinstance(f, str) for f in features)
        # Variant A: 4 long-history FRED features
        if v == "A":
            assert len(features) == 4
            assert "hyg_ig_oas" not in features
            assert "copper_gold_ratio" not in features
            assert kwargs["include_hyg_ig"] is False
            assert kwargs["include_leading_rs"] is False
        # Variant B: A + hyg_ig_oas
        if v == "B":
            assert "hyg_ig_oas" in features
            assert "copper_gold_ratio" not in features
            assert kwargs["include_hyg_ig"] is True
            assert kwargs["include_leading_rs"] is False
        # Variant C: B + intermarket RS
        if v == "C":
            assert "hyg_ig_oas" in features
            assert "copper_gold_ratio" in features
            assert "xlp_xly_ratio" in features
            assert kwargs["include_hyg_ig"] is True
            assert kwargs["include_leading_rs"] is True


def test_variant_a_features_are_subset_of_variant_b():
    """Variant B must add exactly one feature (hyg_ig_oas) over A."""
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    from train_minimal_hmm import VARIANTS

    a_feats = set(VARIANTS["A"][0])
    b_feats = set(VARIANTS["B"][0])
    assert a_feats.issubset(b_feats)
    assert b_feats - a_feats == {"hyg_ig_oas"}


def test_variant_b_features_are_subset_of_variant_c():
    """Variant C must add exactly two intermarket features over B."""
    import sys
    sys.path.insert(0, str(REPO / "scripts"))
    from train_minimal_hmm import VARIANTS

    b_feats = set(VARIANTS["B"][0])
    c_feats = set(VARIANTS["C"][0])
    assert b_feats.issubset(c_feats)
    assert c_feats - b_feats == {"copper_gold_ratio", "xlp_xly_ratio"}


def test_states_artifact_schema_if_trained():
    """If train_minimal_hmm has been run, validate the output schema."""
    states_dir = REPO / "data" / "macro"
    found_any = False
    for variant in ("A", "B", "C"):
        path = states_dir / f"minimal_hmm_states_{variant}.parquet"
        if not path.exists():
            continue
        found_any = True
        df = pd.read_parquet(path)
        # Must have a 'regime' column with valid label values
        assert "regime" in df.columns
        for state in ("benign",):
            assert state in df.columns, \
                f"missing state probability column {state!r} in variant {variant}"
        # regime values must be one of the standard 3-state labels
        valid = {"benign", "stressed", "crisis"}
        assert set(df["regime"].unique()).issubset(valid), \
            f"variant {variant} has unexpected regime label"
        # state probabilities should sum to ~1
        prob_cols = [c for c in df.columns if c != "regime" and c in valid]
        if len(prob_cols) > 0:
            sums = df[prob_cols].sum(axis=1).dropna()
            assert (sums > 0.99).all() and (sums < 1.01).all(), \
                f"variant {variant} state probabilities don't sum to 1"
    if not found_any:
        pytest.skip("no minimal_hmm_states_*.parquet artifacts present")


def test_validation_results_schema_if_run():
    """If validate_minimal_hmm has been run, validate the output schema."""
    p = REPO / "data" / "research" / "hmm_minimal_validation_2026_05.json"
    if not p.exists():
        pytest.skip("validation has not been run")
    import json
    d = json.loads(p.read_text())
    assert "variants" in d
    assert "horizons" in d
    for v in ("A", "B", "C"):
        assert v in d["variants"], f"missing variant {v} in results"
        cells = d["variants"][v]["by_horizon"]
        for h in d["horizons"]:
            cell = cells[str(h)]
            assert "auc_p_risk_vs_fwd_dd" in cell
            assert "verdict" in cell
            assert cell["verdict"] in ("LEADING", "COINCIDENT", "INDETERMINATE")
