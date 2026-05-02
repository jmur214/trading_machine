"""Feature model cards — git-tracked YAML lineage per feature.

F5 of the Feature Foundry. Every registered Foundry feature MUST have a
model card on disk at:

    core/feature_foundry/model_cards/<feature_id>.yml

Schema:

    feature_id:             cot_commercial_net_long
    source_url:             https://www.cftc.gov/...   # canonical
    license:                public                     # match feature decorator
    point_in_time_safe:     true
    expected_behavior:      "Reflects commercial-trader net positioning..."
    known_failure_modes:
      - "Holiday weeks publish late; freshness_check returns False."
      - "Exchange code mappings drift annually..."
    last_revalidation:      2026-05-01    # auto-updated by ablation runs
    ablation_history:
      - run_uuid: foundry-bootstrap-2026-05-01
        contribution_sharpe: 0.04
        measured_at: 2026-05-01T15:00:00Z

The validator enforces:
  - every registered feature has a card
  - every card's `feature_id` resolves to a registered feature
  - required keys present
  - `license` matches the feature decorator's license string

The auto-update helper bumps `last_revalidation` and appends a row to
`ablation_history` whenever the ablation runner produces a result for
the feature.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional
import yaml

from .feature import Feature, get_feature_registry


CARD_ROOT = Path("core/feature_foundry/model_cards")
REQUIRED_KEYS = {
    "feature_id",
    "source_url",
    "license",
    "point_in_time_safe",
    "expected_behavior",
    "known_failure_modes",
    "last_revalidation",
}


@dataclass
class ModelCard:
    feature_id: str
    source_url: str
    license: str
    point_in_time_safe: bool
    expected_behavior: str
    known_failure_modes: List[str]
    last_revalidation: str                # ISO date or 'never'
    ablation_history: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "feature_id": self.feature_id,
            "source_url": self.source_url,
            "license": self.license,
            "point_in_time_safe": self.point_in_time_safe,
            "expected_behavior": self.expected_behavior,
            "known_failure_modes": list(self.known_failure_modes),
            "last_revalidation": self.last_revalidation,
            "ablation_history": list(self.ablation_history),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ModelCard":
        missing = REQUIRED_KEYS - set(data.keys())
        if missing:
            raise ValueError(
                f"Model card missing required keys: {sorted(missing)}"
            )
        return cls(
            feature_id=data["feature_id"],
            source_url=data["source_url"],
            license=data["license"],
            point_in_time_safe=bool(data["point_in_time_safe"]),
            expected_behavior=data["expected_behavior"],
            known_failure_modes=list(data["known_failure_modes"]),
            last_revalidation=str(data["last_revalidation"]),
            ablation_history=list(data.get("ablation_history") or []),
        )

    def write(self, root: Path = CARD_ROOT) -> Path:
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"{self.feature_id}.yml"
        path.write_text(yaml.safe_dump(self.to_dict(), sort_keys=False))
        return path


def card_path(feature_id: str, root: Path = CARD_ROOT) -> Path:
    return root / f"{feature_id}.yml"


def load_model_card(feature_id: str,
                    root: Path = CARD_ROOT) -> Optional[ModelCard]:
    path = card_path(feature_id, root)
    if not path.exists():
        return None
    data = yaml.safe_load(path.read_text()) or {}
    return ModelCard.from_dict(data)


def update_revalidation(
    feature_id: str,
    run_uuid: str,
    contribution_sharpe: float,
    root: Path = CARD_ROOT,
) -> None:
    """Bump `last_revalidation` and append to `ablation_history`. Called
    by the ablation runner after each measurement; safe to no-op if the
    card doesn't exist yet (a CI gate ensures cards exist before
    promotion to active features)."""
    card = load_model_card(feature_id, root)
    if card is None:
        return
    card.last_revalidation = date.today().isoformat()
    card.ablation_history.append({
        "run_uuid": run_uuid,
        "contribution_sharpe": float(contribution_sharpe),
        "measured_at": datetime.now(timezone.utc).isoformat(),
    })
    card.write(root)


def validate_all_model_cards(
    root: Path = CARD_ROOT,
    require_card_for_every_feature: bool = True,
) -> List[str]:
    """Validation entry point. Returns a list of human-readable error
    strings; empty list means clean.

    Checks:
      1. Every registered Foundry feature has a card on disk.
      2. Every card on disk has all required keys + parses cleanly.
      3. Card.license matches feature decorator license.
      4. Card.feature_id resolves to a registered feature.

    The dashboard surfaces these errors as red flags. The CI gate (when
    integrated with the production backtest pipeline) will fail on any
    non-empty list.
    """
    errors: List[str] = []
    registry = get_feature_registry()
    registered_ids = {f.feature_id for f in registry.list_features()}

    # 1 + 3 — every registered feature must have a parseable card with
    # matching license.
    if require_card_for_every_feature:
        for feat in registry.list_features():
            # Adversarial twins inherit their real's card by reference;
            # we don't require a separate one for the twin.
            if feat.tier == "adversarial":
                continue
            card = load_model_card(feat.feature_id, root)
            if card is None:
                errors.append(
                    f"[missing_card] feature {feat.feature_id!r} has no "
                    f"model card at {card_path(feat.feature_id, root)}"
                )
                continue
            if card.license != feat.license:
                errors.append(
                    f"[license_mismatch] {feat.feature_id!r}: card "
                    f"license={card.license!r}, decorator "
                    f"license={feat.license!r}"
                )

    # 2 + 4 — every card on disk must parse + reference a real feature.
    if root.exists():
        for path in root.glob("*.yml"):
            try:
                data = yaml.safe_load(path.read_text()) or {}
                card = ModelCard.from_dict(data)
            except Exception as exc:
                errors.append(f"[parse_error] {path.name}: {exc}")
                continue
            if card.feature_id not in registered_ids:
                errors.append(
                    f"[orphan_card] {path.name}: feature_id "
                    f"{card.feature_id!r} not in feature registry"
                )

    return errors
