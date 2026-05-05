"""Tests for the edge-graveyard structured-tagging schema extension.

Coverage targets:
- New fields `failure_reason` / `superseded_by` round-trip through YAML
- Legacy entries WITHOUT these fields still parse fine (backward compat)
- `set_failure_metadata` validates the closed vocabulary
- `set_failure_metadata` rejects unknown superseded_by edge_ids
- `set_failure_metadata` rejects self-supersession
- Empty-string sentinel clears a field
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
import yaml

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.edge_registry import (
    EdgeRegistry,
    EdgeSpec,
    VALID_FAILURE_REASONS,
)


@pytest.fixture
def tmp_registry(tmp_path: Path) -> EdgeRegistry:
    return EdgeRegistry(store_path=tmp_path / "edges.yml")


def _make_failed(reg: EdgeRegistry, edge_id: str = "e1") -> None:
    spec = EdgeSpec(
        edge_id=edge_id,
        category="factor",
        module="m",
        version="1.0.0",
        status="failed",
    )
    reg.register(spec)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_failure_reason_round_trips(tmp_registry: EdgeRegistry, tmp_path: Path) -> None:
    _make_failed(tmp_registry, "momentum_factor_v1")
    tmp_registry.set_failure_metadata(
        "momentum_factor_v1",
        failure_reason="universe_too_small",
    )
    # Re-load from disk
    reg2 = EdgeRegistry(store_path=tmp_path / "edges.yml")
    spec = reg2.get("momentum_factor_v1")
    assert spec is not None
    assert spec.failure_reason == "universe_too_small"
    assert spec.superseded_by is None  # not set


def test_superseded_by_round_trips(tmp_registry: EdgeRegistry, tmp_path: Path) -> None:
    _make_failed(tmp_registry, "old_v1")
    tmp_registry.register(EdgeSpec(edge_id="new_v1", category="factor", module="m"))
    tmp_registry.set_failure_metadata(
        "old_v1",
        failure_reason="overfit",
        superseded_by="new_v1",
    )
    reg2 = EdgeRegistry(store_path=tmp_path / "edges.yml")
    spec = reg2.get("old_v1")
    assert spec is not None
    assert spec.superseded_by == "new_v1"


# ---------------------------------------------------------------------------
# Backward compatibility — legacy entries
# ---------------------------------------------------------------------------


def test_legacy_yaml_without_new_fields_loads_clean(tmp_path: Path) -> None:
    """A pre-existing edges.yml has no `failure_reason` / `superseded_by`
    keys. Loading it must produce specs with those fields = None and
    must NOT introduce nulls into the YAML on save.
    """
    legacy_yml = tmp_path / "edges.yml"
    legacy_yml.write_text(yaml.safe_dump({
        "edges": [{
            "edge_id": "legacy_v1",
            "category": "technical",
            "module": "m",
            "version": "1.0.0",
            "params": {},
            "status": "failed",
            "tier": "feature",
        }],
    }, sort_keys=False))

    reg = EdgeRegistry(store_path=legacy_yml)
    spec = reg.get("legacy_v1")
    assert spec is not None
    assert spec.failure_reason is None
    assert spec.superseded_by is None

    # Saving must not introduce these keys
    reg._save()
    on_disk = yaml.safe_load(legacy_yml.read_text())
    row = on_disk["edges"][0]
    assert "failure_reason" not in row
    assert "superseded_by" not in row


def test_extra_fields_still_round_trip(tmp_path: Path) -> None:
    """The pre-existing `extra` catch-all (e.g. reclassified_to from
    2026-05-02) must continue to round-trip even with the new keys
    in known_keys.
    """
    legacy_yml = tmp_path / "edges.yml"
    legacy_yml.write_text(yaml.safe_dump({
        "edges": [{
            "edge_id": "macro_v1",
            "category": "macro",
            "module": "m",
            "status": "retired",
            "reclassified_to": "regime_input",
            "reclassified_on": "2026-05-02",
        }],
    }, sort_keys=False))
    reg = EdgeRegistry(store_path=legacy_yml)
    reg._save()
    on_disk = yaml.safe_load(legacy_yml.read_text())
    row = on_disk["edges"][0]
    assert row["reclassified_to"] == "regime_input"
    assert row["reclassified_on"] == "2026-05-02"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def test_invalid_failure_reason_raises(tmp_registry: EdgeRegistry) -> None:
    _make_failed(tmp_registry)
    with pytest.raises(ValueError, match="failure_reason"):
        tmp_registry.set_failure_metadata("e1", failure_reason="bogus_value")


def test_unknown_superseded_by_raises(tmp_registry: EdgeRegistry) -> None:
    _make_failed(tmp_registry)
    with pytest.raises(ValueError, match="not a registered edge_id"):
        tmp_registry.set_failure_metadata(
            "e1", superseded_by="does_not_exist",
        )


def test_self_supersession_raises(tmp_registry: EdgeRegistry) -> None:
    _make_failed(tmp_registry)
    with pytest.raises(ValueError, match="cannot supersede itself"):
        tmp_registry.set_failure_metadata(
            "e1", superseded_by="e1",
        )


def test_unknown_edge_id_raises(tmp_registry: EdgeRegistry) -> None:
    with pytest.raises(KeyError):
        tmp_registry.set_failure_metadata(
            "never_registered", failure_reason="other",
        )


def test_empty_string_clears_field(tmp_registry: EdgeRegistry, tmp_path: Path) -> None:
    _make_failed(tmp_registry, "old")
    tmp_registry.register(EdgeSpec(edge_id="new", category="factor", module="m"))
    tmp_registry.set_failure_metadata(
        "old", failure_reason="overfit", superseded_by="new",
    )
    # Now clear them
    tmp_registry.set_failure_metadata("old", failure_reason="", superseded_by="")
    reg2 = EdgeRegistry(store_path=tmp_path / "edges.yml")
    spec = reg2.get("old")
    assert spec is not None
    assert spec.failure_reason is None
    assert spec.superseded_by is None


def test_all_valid_failure_reasons_are_accepted(tmp_registry: EdgeRegistry) -> None:
    """Smoke test the whole closed vocabulary."""
    for reason in VALID_FAILURE_REASONS:
        edge_id = f"edge_{reason}"
        _make_failed(tmp_registry, edge_id)
        tmp_registry.set_failure_metadata(edge_id, failure_reason=reason)
        spec = tmp_registry.get(edge_id)
        assert spec is not None
        assert spec.failure_reason == reason


# ---------------------------------------------------------------------------
# Status integration — set_failure_metadata is independent of status
# ---------------------------------------------------------------------------


def test_metadata_does_not_change_status(tmp_registry: EdgeRegistry) -> None:
    """Tagging metadata must not silently flip status."""
    spec = EdgeSpec(
        edge_id="e1", category="x", module="m", status="paused",
    )
    tmp_registry.register(spec)
    tmp_registry.set_failure_metadata("e1", failure_reason="overfit")
    got = tmp_registry.get("e1")
    assert got is not None
    assert got.status == "paused"  # unchanged
    assert got.failure_reason == "overfit"
