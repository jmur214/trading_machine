"""Tests for the 90-day archive enforcement script.

Acceptance criterion from `docs/Audit/ws_d_foundry_closeout.md`:

  90-day archive flag mechanism works end-to-end: create a synthetic
  ablation history showing 90d negative lift, verify the script flips
  a feature's status to `review_pending`.

These tests do NOT touch the real `core/feature_foundry/model_cards`
directory — they construct a fixture cards-dir per test and operate
on it. The audit script is pure-on-input: pass it a path, get
decisions back.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.feature_foundry.model_card import ModelCard, load_model_card
from scripts.audit_feature_archive import (
    evaluate_card, apply_decision, run_audit, reset_pending,
)


def _build_card(
    feature_id: str = "test_feature",
    status: str = "active",
    history: list | None = None,
) -> ModelCard:
    return ModelCard(
        feature_id=feature_id,
        source_url="https://example.com",
        license="public",
        point_in_time_safe=True,
        expected_behavior="test",
        known_failure_modes=["test"],
        last_revalidation="2026-05-04",
        ablation_history=list(history or []),
        status=status,
    )


def _hist_row(measured_at_dt: datetime, lift: float,
              run_uuid: str = "test") -> dict:
    return {
        "run_uuid": run_uuid,
        "contribution_sharpe": float(lift),
        "measured_at": measured_at_dt.isoformat(),
    }


# ---------------------------------------------------------------------------
# evaluate_card — pure
# ---------------------------------------------------------------------------

def test_evaluate_flags_sustained_negative_lift():
    today = date(2026, 5, 4)
    # Five obs across last 90d, all negative — should flag.
    base = datetime(2026, 3, 15, tzinfo=timezone.utc)
    history = [
        _hist_row(base + timedelta(days=i * 14), lift=-0.05 - 0.01 * i)
        for i in range(5)
    ]
    card = _build_card(history=history)

    decision = evaluate_card(card, window_days=90, min_observations=3,
                             today=today)
    assert decision.action == "flag"
    assert decision.observations_in_window == 5
    assert decision.mean_lift is not None and decision.mean_lift < 0
    assert decision.most_recent_lift is not None
    assert decision.most_recent_lift < 0


def test_evaluate_skips_when_too_few_observations():
    today = date(2026, 5, 4)
    history = [
        _hist_row(datetime(2026, 4, 1, tzinfo=timezone.utc), lift=-0.5),
    ]
    card = _build_card(history=history)

    decision = evaluate_card(card, window_days=90, min_observations=3,
                             today=today)
    assert decision.action == "skipped"
    assert "only 1 ablation obs" in decision.reason


def test_evaluate_does_not_flag_when_recent_obs_positive():
    """Stale negatives followed by a positive print should NOT flag —
    the regime may have turned. Real-money lesson: regime-conditional
    edges (low_vol_factor_v1) bleed in some windows; we don't want to
    auto-flag them on the day after the regime flips back."""
    today = date(2026, 5, 4)
    base = datetime(2026, 3, 1, tzinfo=timezone.utc)
    history = [
        _hist_row(base + timedelta(days=0), lift=-0.10),
        _hist_row(base + timedelta(days=14), lift=-0.05),
        _hist_row(base + timedelta(days=28), lift=-0.02),
        _hist_row(base + timedelta(days=42), lift=+0.15),
    ]
    card = _build_card(history=history)

    decision = evaluate_card(card, window_days=90, min_observations=3,
                             today=today)
    assert decision.action == "no_change"


def test_evaluate_excludes_history_outside_window():
    """An old negative streak from 6 months ago must NOT trigger a
    flag if the recent window is empty / positive."""
    today = date(2026, 5, 4)
    old = datetime(2025, 8, 1, tzinfo=timezone.utc)
    history = [
        _hist_row(old + timedelta(days=i * 14), lift=-0.5)
        for i in range(5)
    ]
    card = _build_card(history=history)

    decision = evaluate_card(card, window_days=90, min_observations=3,
                             today=today)
    # Zero obs in window, must be skipped, not flagged.
    assert decision.action == "skipped"


def test_evaluate_idempotent_on_already_flagged():
    today = date(2026, 5, 4)
    base = datetime(2026, 3, 15, tzinfo=timezone.utc)
    history = [
        _hist_row(base + timedelta(days=i * 14), lift=-0.05)
        for i in range(5)
    ]
    card = _build_card(status="review_pending", history=history)

    decision = evaluate_card(card, window_days=90, min_observations=3,
                             today=today)
    assert decision.action == "no_change"
    assert "already review_pending" in decision.reason


def test_evaluate_does_not_touch_archived():
    """Archived is a human-triage decision — the audit must never
    revert it."""
    today = date(2026, 5, 4)
    base = datetime(2026, 3, 15, tzinfo=timezone.utc)
    history = [
        _hist_row(base + timedelta(days=i * 14), lift=+0.10)
        for i in range(5)
    ]
    card = _build_card(status="archived", history=history)

    decision = evaluate_card(card, window_days=90, min_observations=3,
                             today=today)
    assert decision.action == "no_change"
    assert "archived" in decision.reason


# ---------------------------------------------------------------------------
# End-to-end on disk
# ---------------------------------------------------------------------------

def test_audit_end_to_end_flips_status_on_disk(tmp_path):
    """The full path: synthetic 90d-negative history → run_audit →
    YAML reflects the new `review_pending` status with `flagged_reason`
    set, and a re-read of the card via `load_model_card` confirms it."""
    today = date(2026, 5, 4)
    base = datetime(2026, 3, 15, tzinfo=timezone.utc)
    history = [
        _hist_row(base + timedelta(days=i * 14), lift=-0.04 - 0.005 * i,
                  run_uuid=f"run-{i}")
        for i in range(5)
    ]
    bad = _build_card(feature_id="bleeder", history=history)
    bad.write(root=tmp_path)

    # Add a healthy feature too — must remain active.
    healthy = _build_card(feature_id="healthy_feat", history=[
        _hist_row(base + timedelta(days=i * 14), lift=+0.10)
        for i in range(5)
    ])
    healthy.write(root=tmp_path)

    decisions = run_audit(
        root=tmp_path, window_days=90, min_observations=3,
        dry_run=False, today=today,
    )
    by_id = {d.feature_id: d for d in decisions}
    assert by_id["bleeder"].action == "flag"
    assert by_id["healthy_feat"].action == "no_change"

    bleeder_after = load_model_card("bleeder", root=tmp_path)
    assert bleeder_after is not None
    assert bleeder_after.status == "review_pending"
    assert bleeder_after.flagged_reason is not None
    assert "negative" in bleeder_after.flagged_reason.lower()
    assert bleeder_after.last_ablation_lift is not None
    assert bleeder_after.last_ablation_lift < 0
    assert bleeder_after.last_ablation_date is not None

    healthy_after = load_model_card("healthy_feat", root=tmp_path)
    assert healthy_after is not None
    assert healthy_after.status == "active"
    assert healthy_after.flagged_reason is None


def test_audit_dry_run_does_not_mutate(tmp_path):
    """`--dry-run` must report the decisions but not touch disk."""
    today = date(2026, 5, 4)
    base = datetime(2026, 3, 15, tzinfo=timezone.utc)
    history = [
        _hist_row(base + timedelta(days=i * 14), lift=-0.05)
        for i in range(5)
    ]
    bad = _build_card(feature_id="bleeder2", history=history)
    bad.write(root=tmp_path)

    run_audit(root=tmp_path, window_days=90, min_observations=3,
              dry_run=True, today=today)

    on_disk = load_model_card("bleeder2", root=tmp_path)
    assert on_disk is not None
    assert on_disk.status == "active"
    assert on_disk.flagged_reason is None


def test_reset_pending_clears_only_review_pending(tmp_path):
    base = datetime(2026, 3, 15, tzinfo=timezone.utc)
    history = [
        _hist_row(base + timedelta(days=i * 14), lift=-0.05)
        for i in range(5)
    ]

    flagged = _build_card(
        feature_id="flag_me", status="review_pending", history=history,
    )
    flagged.flagged_reason = "test"
    flagged.write(root=tmp_path)

    # `archived` must NOT be cleared — that's a human decision.
    archived = _build_card(
        feature_id="hands_off", status="archived", history=history,
    )
    archived.flagged_reason = "human_decision"
    archived.write(root=tmp_path)

    cleared = reset_pending(root=tmp_path)
    assert cleared == 1

    flagged_after = load_model_card("flag_me", root=tmp_path)
    assert flagged_after is not None
    assert flagged_after.status == "active"
    assert flagged_after.flagged_reason is None

    archived_after = load_model_card("hands_off", root=tmp_path)
    assert archived_after is not None
    assert archived_after.status == "archived"
    assert archived_after.flagged_reason == "human_decision"


# ---------------------------------------------------------------------------
# Schema invariants
# ---------------------------------------------------------------------------

def test_status_field_validates_closed_vocabulary():
    with pytest.raises(ValueError, match="invalid status"):
        ModelCard(
            feature_id="x", source_url="https://example.com",
            license="public", point_in_time_safe=True,
            expected_behavior="t", known_failure_modes=[],
            last_revalidation="2026-05-04", status="bogus",
        )


def test_legacy_card_without_additive_fields_loads_clean(tmp_path):
    """Back-compat: a card written before the WS-D close-out schema
    additions (no status / last_ablation_date / flagged_reason) must
    still parse cleanly with `status` defaulting to active."""
    legacy_yaml = """\
feature_id: legacy_feat
source_url: https://example.com
license: public
point_in_time_safe: true
expected_behavior: legacy
known_failure_modes: ['none']
last_revalidation: '2026-05-04'
ablation_history: []
"""
    path = tmp_path / "legacy_feat.yml"
    path.write_text(legacy_yaml)

    card = load_model_card("legacy_feat", root=tmp_path)
    assert card is not None
    assert card.status == "active"
    assert card.last_ablation_date is None
    assert card.flagged_reason is None
