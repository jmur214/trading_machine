"""Loader for the Feature Foundry audit tab.

Pulls live state from `core.feature_foundry`:
  - registered features + tier
  - latest ablation contribution per feature_id
  - model card validation errors
  - data source freshness

Returns shape ready for the dash_table on the Foundry tab.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Dict, List, Optional


@dataclass
class FoundryRow:
    feature_id: str
    tier: str
    source: str
    horizon: int
    license: str
    has_model_card: bool
    last_revalidation: str
    ablation_contribution: Optional[float]
    twin_present: bool
    twin_id: Optional[str]
    health: str                # "ok" | "warn" | "fail"
    health_reason: str
    # Additive WS-D close-out fields — surface the 90-day archive
    # auditor's verdict on the Foundry tab.
    status: str = "active"             # active | review_pending | archived
    flagged_reason: Optional[str] = None

    def to_record(self) -> dict:
        contrib = (
            "—" if self.ablation_contribution is None
            else f"{self.ablation_contribution:+.4f}"
        )
        return {
            "feature_id": self.feature_id,
            "tier": self.tier,
            "source": self.source,
            "horizon": self.horizon,
            "license": self.license,
            "has_model_card": "yes" if self.has_model_card else "NO",
            "last_revalidation": self.last_revalidation,
            "ablation_contribution": contrib,
            "twin_present": "yes" if self.twin_present else "no",
            "twin_id": self.twin_id or "—",
            "health": self.health,
            "health_reason": self.health_reason,
            "status": self.status,
            "flagged_reason": self.flagged_reason or "—",
        }


def _classify_health(
    has_card: bool,
    last_revalidation: str,
    ablation_contribution: Optional[float],
    twin_present: bool,
) -> tuple[str, str]:
    if not has_card:
        return "fail", "missing model card"
    if not twin_present:
        return "warn", "no adversarial twin registered"
    if last_revalidation == "never":
        return "warn", "never revalidated"
    if ablation_contribution is not None and ablation_contribution < 0:
        return "fail", "negative ablation contribution"
    # Stale = > 90 days since revalidation
    try:
        last_dt = date.fromisoformat(last_revalidation)
        days_stale = (date.today() - last_dt).days
        if days_stale > 90:
            return "warn", f"stale ({days_stale}d since revalidation)"
    except Exception:
        pass
    return "ok", ""


def load_foundry_rows() -> List[dict]:
    """Build the per-feature audit row list. Excludes adversarial twins
    from the table (they're surfaced as a column on their real)."""
    # Local import to avoid pulling Foundry into dashboard import path
    # at module load (the dashboard may run in environments where Foundry
    # is wired but the substrate plugins aren't registered yet).
    from core.feature_foundry import (
        get_feature_registry, load_model_card, latest_ablation_for_feature,
    )
    from core.feature_foundry.adversarial import twin_id_for

    registry = get_feature_registry()
    real_features = [f for f in registry.list_features() if f.tier != "adversarial"]
    twin_ids = {f.feature_id for f in registry.list_features() if f.tier == "adversarial"}

    rows: List[FoundryRow] = []
    for feat in real_features:
        card = load_model_card(feat.feature_id)
        has_card = card is not None
        last_reval = card.last_revalidation if card else "—"
        contribution = latest_ablation_for_feature(feat.feature_id)
        twin_fid = twin_id_for(feat.feature_id)
        twin_present = twin_fid in twin_ids
        health, reason = _classify_health(
            has_card, last_reval, contribution, twin_present,
        )
        status = card.status if card else "active"
        flagged_reason = card.flagged_reason if card else None
        # If the auditor has flagged this feature, that's a stronger
        # signal than the heuristic health-classifier — escalate.
        if status == "review_pending":
            health = "warn"
            reason = (
                f"review_pending: {flagged_reason or 'see audit log'}"
            )
        rows.append(FoundryRow(
            feature_id=feat.feature_id,
            tier=feat.tier,
            source=feat.source,
            horizon=feat.horizon,
            license=feat.license,
            has_model_card=has_card,
            last_revalidation=last_reval,
            ablation_contribution=contribution,
            twin_present=twin_present,
            twin_id=twin_fid if twin_present else None,
            health=health,
            health_reason=reason,
            status=status,
            flagged_reason=flagged_reason,
        ))
    return [r.to_record() for r in rows]


def load_review_pending_rows() -> List[dict]:
    """Subset of `load_foundry_rows` filtered to status == review_pending.

    Powers the dashboard's "Review Pending" section. Surfacing
    flagged features here is the human-triage handoff: the audit
    script flips the status, the dashboard makes it visible, a person
    decides whether to archive (status='archived'), un-flag (return
    to active), or investigate further. Per CLAUDE.md "archive don't
    delete" — the audit script never deletes.
    """
    return [r for r in load_foundry_rows() if r.get("status") == "review_pending"]


def load_source_rows() -> List[dict]:
    """Per-DataSource health rows for the secondary panel on the tab."""
    from core.feature_foundry import get_source_registry
    rows = []
    for src in get_source_registry().list_sources():
        try:
            fresh = src.freshness_check()
        except Exception as exc:
            fresh = False
            fresh_msg = f"error: {exc}"
        else:
            fresh_msg = "fresh" if fresh else "stale"
        rows.append({
            "name": src.name,
            "license": src.license,
            "point_in_time_safe": "yes" if src.point_in_time_safe else "NO",
            "latency": f"{int(src.latency.total_seconds() // 86400)}d",
            "freshness": fresh_msg,
            "health": "ok" if fresh else "warn",
        })
    return rows


def load_validation_errors() -> List[str]:
    from core.feature_foundry import validate_all_model_cards
    return validate_all_model_cards()
