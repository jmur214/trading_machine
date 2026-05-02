"""Tests for the macro-edge → regime-input reclassification (2026-05-02).

Verifies (against the SOURCE-CONTROLLED record at
engines/engine_e_regime/reclassified_macros.yml — `data/governor/edges.yml`
itself is gitignored as regenerable engine state):

- All four target macros are listed in the reclassification record
- Their auto-register status in the .py source is 'retired' (not 'active')
- The regime-input feature panel produces values mapping to each macro
- AdvisoryEngine modulates `risk_scalar` via HMM posterior confidence
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

RECLASSIFIED = (
    "macro_credit_spread_v1",
    "macro_real_rate_v1",
    "macro_dollar_regime_v1",
    "macro_unemployment_momentum_v1",
)


def _load_reclassification_record():
    with open(ROOT / "engines/engine_e_regime/reclassified_macros.yml") as f:
        return yaml.safe_load(f)


def test_reclassification_record_lists_all_four_macros():
    rec = _load_reclassification_record()
    assert rec.get("new_role") == "regime_input"
    assert rec.get("reclassified_on") == "2026-05-02"
    listed = {r["edge_id"] for r in rec["reclassifications"]}
    assert set(RECLASSIFIED) <= listed, (
        f"reclassification record missing entries for: "
        f"{set(RECLASSIFIED) - listed}"
    )


def test_each_reclassified_macro_has_complete_metadata():
    rec = _load_reclassification_record()
    by_id = {r["edge_id"]: r for r in rec["reclassifications"]}
    for edge_id in RECLASSIFIED:
        r = by_id[edge_id]
        assert r["new_status"] == "retired", (
            f"{edge_id} new_status is {r['new_status']}, expected 'retired'"
        )
        assert r.get("fred_series"), f"{edge_id} missing fred_series"
        assert r.get("new_feature_name"), f"{edge_id} missing new_feature_name"
        assert r.get("feature_role") in ("canonical", "aux"), (
            f"{edge_id} feature_role should be canonical or aux"
        )
        assert r.get("note"), f"{edge_id} missing note"


def test_macro_edge_files_have_retired_auto_register():
    """Each macro edge file's auto-register block writes status='retired'."""
    macro_files = [
        "engines/engine_a_alpha/edges/macro_credit_spread_edge.py",
        "engines/engine_a_alpha/edges/macro_real_rate_edge.py",
        "engines/engine_a_alpha/edges/macro_dollar_regime_edge.py",
        "engines/engine_a_alpha/edges/macro_unemployment_momentum_edge.py",
    ]
    for relpath in macro_files:
        p = ROOT / relpath
        assert p.exists(), f"missing {relpath}"
        text = p.read_text()
        assert 'status="retired"' in text, (
            f"{relpath} auto-register should write status='retired' "
            f"(got: {[l for l in text.splitlines() if 'status=' in l]})"
        )
        assert 'status="active"' not in text, (
            f"{relpath} still has status='active' in auto-register"
        )


def test_macro_features_module_exposes_canonical_columns():
    from engines.engine_e_regime.macro_features import FEATURE_COLUMNS, AUX_COLUMNS

    # The 4 reclassified macros each have a corresponding feature
    expected = {
        "macro_credit_spread_v1": "credit_spread_baa_aaa",
        "macro_dollar_regime_v1": "dollar_ret_63d",
        "macro_real_rate_v1": "real_rate_level",
        "macro_unemployment_momentum_v1": "unemployment_momentum_3m",
    }
    canonical = set(FEATURE_COLUMNS)
    aux = set(AUX_COLUMNS)
    for edge_id, feat in expected.items():
        assert feat in canonical or feat in aux, (
            f"reclassified {edge_id} → expected feature '{feat}' missing "
            f"from FEATURE_COLUMNS + AUX_COLUMNS"
        )


def test_advisory_engine_consumes_hmm_proba_via_risk_scalar():
    """End-to-end: AdvisoryEngine modulates risk_scalar by hmm_proba confidence."""
    from engines.engine_e_regime.advisory import AdvisoryEngine

    eng = AdvisoryEngine()
    axis_states = {
        "trend": "bull",
        "volatility": "normal",
        "correlation": "normal",
        "breadth": "strong",
        "forward_stress": "calm",
    }
    axis_confidences = {k: 1.0 for k in axis_states}
    axis_durations = {k: 50 for k in axis_states}
    flip_counts = {k: 0 for k in axis_states}

    # No HMM — baseline
    _, adv_baseline = eng.generate(
        axis_states, axis_confidences, axis_durations, flip_counts
    )
    # Concentrated HMM (high confidence) — should match baseline
    _, adv_concentrated = eng.generate(
        axis_states, axis_confidences, axis_durations, flip_counts,
        hmm_proba={"benign": 1.0, "stressed": 0.0, "crisis": 0.0},
    )
    # Uniform HMM (zero confidence) — should reduce risk_scalar
    _, adv_uniform = eng.generate(
        axis_states, axis_confidences, axis_durations, flip_counts,
        hmm_proba={"benign": 1 / 3, "stressed": 1 / 3, "crisis": 1 / 3},
    )

    assert adv_baseline["regime_confidence"] == 1.0, (
        "regime_confidence defaults to 1.0 when HMM not provided"
    )
    assert adv_concentrated["regime_confidence"] > 0.99
    assert adv_uniform["regime_confidence"] < 0.01

    # Concentrated should not penalize risk_scalar
    assert adv_concentrated["risk_scalar"] == adv_baseline["risk_scalar"], (
        f"concentrated HMM unexpectedly modified risk_scalar: "
        f"{adv_concentrated['risk_scalar']} vs baseline {adv_baseline['risk_scalar']}"
    )
    # Uniform should down-scale risk_scalar
    assert adv_uniform["risk_scalar"] < adv_baseline["risk_scalar"], (
        f"uniform HMM should reduce risk_scalar: "
        f"{adv_uniform['risk_scalar']} vs baseline {adv_baseline['risk_scalar']}"
    )
