"""One-time migration: tag failed edges with structured graveyard metadata.

Applies the schema introduced in WS-J cross-cutting batch (see
`docs/Measurements/2026-05/ws_j_cross_cutting_trio.md`). Each tagging decision below
cites a project memory that documents the reason.

Idempotent: running twice produces the same on-disk state (it sets
metadata to the same values; backward-compat fields stay None where
not specified).

Usage:
    python -m scripts.migrate_edge_graveyard_tags
    python -m scripts.migrate_edge_graveyard_tags --dry-run
    python -m scripts.migrate_edge_graveyard_tags \\
        --registry-path /custom/path/to/edges.yml
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engines.engine_a_alpha.edge_registry import (
    EdgeRegistry,
    VALID_FAILURE_REASONS,
)


# (edge_id, failure_reason, superseded_by, memory_citation)
# - momentum_factor_v1: 39-ticker universe was too narrow for cross-
#   sectional factor work; revisit after universe expansion to S&P 500.
# - low_vol_factor_v1: Signal real (40+ years academic) but only fires in
#   adverse regimes; constant-weight signal_processor can't express
#   regime-conditional alpha. Different failure mode from momentum_factor.
MIGRATIONS: List[Tuple[str, str, str, str]] = [
    (
        "momentum_factor_v1",
        "universe_too_small",
        "",  # no replacement edge yet
        "project_factor_edge_first_alpha_2026_04_24.md",
    ),
    (
        "low_vol_factor_v1",
        "regime_conditional",
        "",
        "project_low_vol_regime_conditional_2026_04_25.md",
    ),
]


def migrate(registry_path: Path, dry_run: bool = False) -> Dict[str, str]:
    """Apply graveyard tags. Returns map of edge_id -> action taken.

    Actions: "tagged", "skipped:not_found", "skipped:already_tagged".
    """
    if registry_path.exists():
        reg = EdgeRegistry(store_path=registry_path)
    else:
        print(f"[migrate][ERROR] registry path missing: {registry_path}")
        return {}

    actions: Dict[str, str] = {}
    for edge_id, reason, superseded_by, citation in MIGRATIONS:
        if reason not in VALID_FAILURE_REASONS:
            raise ValueError(
                f"Invalid migration: {reason!r} not in vocabulary"
            )
        spec = reg.get(edge_id)
        if spec is None:
            actions[edge_id] = "skipped:not_found"
            print(
                f"[migrate][SKIP] {edge_id}: not found in registry"
            )
            continue

        # Idempotency: if already tagged with the same value, skip.
        if (spec.failure_reason == reason
                and (spec.superseded_by or "") == (superseded_by or "")):
            actions[edge_id] = "skipped:already_tagged"
            print(
                f"[migrate][SKIP] {edge_id}: already tagged "
                f"failure_reason={spec.failure_reason!r}"
            )
            continue

        if dry_run:
            actions[edge_id] = "would_tag"
            print(
                f"[migrate][DRY] {edge_id}: would set "
                f"failure_reason={reason!r}, "
                f"superseded_by={superseded_by!r} "
                f"(memory: {citation})"
            )
            continue

        # Use the registry's validated tagging method.
        reg.set_failure_metadata(
            edge_id,
            failure_reason=reason,
            superseded_by=superseded_by or "",
        )
        actions[edge_id] = "tagged"
        print(
            f"[migrate][OK] {edge_id}: failure_reason={reason!r} "
            f"(memory: {citation})"
        )

    return actions


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    default_path = (
        Path(__file__).resolve().parents[1] / "data" / "governor" / "edges.yml"
    )
    p.add_argument(
        "--registry-path",
        type=Path,
        default=default_path,
        help=f"Path to edges.yml (default: {default_path})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migrations without writing.",
    )
    args = p.parse_args()

    actions = migrate(args.registry_path, dry_run=args.dry_run)
    n_tagged = sum(1 for v in actions.values() if v == "tagged")
    n_skipped = sum(1 for v in actions.values() if v.startswith("skipped"))
    n_not_found = sum(1 for v in actions.values() if v == "skipped:not_found")
    print(
        f"\n[migrate][SUMMARY] tagged={n_tagged}, skipped={n_skipped}, "
        f"not_found={n_not_found}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
