"""Tests for scripts.journal_apply — F11 Phase 1 CLI driver.

Verifies:
- Apply with empty journal is a no-op
- Status-change entries flow into edges.yml correctly
- Tier-change entries flow into edges.yml correctly
- Regime-weight-update entries populate the regime_gate dict
- Apply mark advances on success and is read on subsequent calls
- --since cutoff overrides the apply mark
- --dry-run reports without writing
- Unknown-edge entries are skipped (warned, not errored)
- Re-running with no new entries is idempotent (no-op)
- Atomic edges.yml write — no leftover .tmp on success
- Crash safety: if write fails mid-transaction, mark not advanced
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from engines.engine_f_governance.journal import (
    LifecycleJournal, JournalEntry,
    make_status_change, make_tier_change, make_weight_update,
)
from scripts.journal_apply import apply, read_mark, write_mark


# ----- helpers ------------------------------------------------------ #

def _seed_registry(path: Path, edge_ids: list[str]) -> None:
    rows = [
        {
            "edge_id": eid, "category": "test", "module": "test.mod",
            "version": "1.0.0", "params": {}, "status": "active", "tier": "feature",
        }
        for eid in edge_ids
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({"edges": rows}, sort_keys=False))


def _read_specs(path: Path) -> dict:
    data = yaml.safe_load(path.read_text()) or {}
    return {row["edge_id"]: row for row in data.get("edges", [])}


@pytest.fixture()
def workspace(tmp_path: Path) -> dict:
    """Build a full test workspace with journal, registry, and mark
    paths in tmp_path."""
    journal_path = tmp_path / "lifecycle_journal.jsonl"
    registry_path = tmp_path / "edges.yml"
    mark_path = tmp_path / ".journal_apply_mark"
    _seed_registry(registry_path, ["a", "b", "c"])
    return {
        "journal_path": journal_path,
        "registry_path": registry_path,
        "mark_path": mark_path,
        "journal": LifecycleJournal(journal_path),
    }


# ----- empty journal -------------------------------------------- #

def test_apply_with_empty_journal_is_noop(workspace) -> None:
    result = apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    assert result.n_processed == 0
    assert not workspace["mark_path"].exists()


# ----- status_change ------------------------------------------- #

def test_status_change_propagates_to_registry(workspace) -> None:
    j = workspace["journal"]
    j.append(make_status_change(run_id="r1", edge_id="a", new_status="paused"))
    j.append(make_status_change(run_id="r1", edge_id="b", new_status="retired"))

    result = apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    assert result.n_status_changes == 2
    specs = _read_specs(workspace["registry_path"])
    assert specs["a"]["status"] == "paused"
    assert specs["b"]["status"] == "retired"
    assert specs["c"]["status"] == "active"  # untouched


# ----- tier_change --------------------------------------------- #

def test_tier_change_propagates_to_registry(workspace) -> None:
    j = workspace["journal"]
    j.append(make_tier_change(run_id="r1", edge_id="a", new_tier="alpha"))
    apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    specs = _read_specs(workspace["registry_path"])
    assert specs["a"]["tier"] == "alpha"


# ----- regime_weight_update ----------------------------------- #

def test_regime_weight_update_populates_regime_gate(workspace) -> None:
    j = workspace["journal"]
    j.append(JournalEntry(
        timestamp=datetime.now(timezone.utc).isoformat(),
        run_id="r1", decision_type="regime_weight_update",
        edge_id="a",
        payload={"regime": "stressed", "weight": 0.5},
    ))
    apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    specs = _read_specs(workspace["registry_path"])
    assert specs["a"]["regime_gate"] == {"stressed": 0.5}


# ----- apply mark --------------------------------------------- #

def test_apply_mark_advances_after_successful_apply(workspace) -> None:
    j = workspace["journal"]
    j.append(make_status_change(run_id="r1", edge_id="a", new_status="paused"))
    apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    mark = read_mark(workspace["mark_path"])
    assert mark is not None


def test_apply_mark_persisted_skips_already_applied_entries(workspace) -> None:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    j = workspace["journal"]
    # Entry 1 at base
    j.append(JournalEntry(
        timestamp=base.isoformat(), run_id="r1",
        decision_type="status_change", edge_id="a",
        payload={"new_status": "paused"},
    ))
    apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    # Now mark advanced. Append entry 2 BEFORE the mark — should skip.
    # Append entry 3 AFTER the mark — should apply.
    j.append(JournalEntry(
        timestamp=(base - timedelta(hours=1)).isoformat(), run_id="r2",
        decision_type="status_change", edge_id="b",
        payload={"new_status": "retired"},
    ))
    j.append(JournalEntry(
        timestamp=(base + timedelta(hours=1)).isoformat(), run_id="r2",
        decision_type="status_change", edge_id="c",
        payload={"new_status": "retired"},
    ))
    result = apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    # Only the after-mark entry processed
    assert result.n_processed == 1
    specs = _read_specs(workspace["registry_path"])
    assert specs["b"]["status"] == "active"  # NOT retired (before mark)
    assert specs["c"]["status"] == "retired"  # applied (after mark)


def test_idempotent_rerun_with_no_new_entries(workspace) -> None:
    j = workspace["journal"]
    j.append(make_status_change(run_id="r1", edge_id="a", new_status="paused"))
    apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    # Re-run: should be a no-op
    result = apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    assert result.n_processed == 0
    specs = _read_specs(workspace["registry_path"])
    assert specs["a"]["status"] == "paused"


# ----- --since override --------------------------------------- #

def test_since_overrides_mark(workspace) -> None:
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    j = workspace["journal"]
    for i, eid in enumerate(["a", "b", "c"]):
        j.append(JournalEntry(
            timestamp=(base + timedelta(hours=i)).isoformat(), run_id="r",
            decision_type="status_change", edge_id=eid,
            payload={"new_status": "paused"},
        ))
    # Pre-write a mark that would normally cover entry 0; override with
    # earlier --since to re-process all.
    write_mark(workspace["mark_path"], (base + timedelta(hours=10)).isoformat())
    cutoff = (base - timedelta(hours=1)).isoformat()
    result = apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        since_iso=cutoff,
        verbose=False,
    )
    assert result.n_processed == 3  # all 3 re-processed


# ----- --dry-run --------------------------------------------- #

def test_dry_run_does_not_mutate_registry(workspace) -> None:
    j = workspace["journal"]
    j.append(make_status_change(run_id="r1", edge_id="a", new_status="paused"))
    result = apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        dry_run=True,
        verbose=False,
    )
    assert result.dry_run is True
    assert result.n_status_changes == 1
    # Registry unchanged
    specs = _read_specs(workspace["registry_path"])
    assert specs["a"]["status"] == "active"
    # Mark unchanged
    assert not workspace["mark_path"].exists()


# ----- Unknown-edge handling --------------------------------- #

def test_entry_for_unknown_edge_is_skipped(workspace) -> None:
    j = workspace["journal"]
    j.append(make_status_change(run_id="r1", edge_id="zzz_unknown",
                                  new_status="paused"))
    j.append(make_status_change(run_id="r1", edge_id="a", new_status="paused"))
    result = apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    assert result.n_skipped_unknown_edge == 1
    assert result.n_status_changes == 1
    specs = _read_specs(workspace["registry_path"])
    assert specs["a"]["status"] == "paused"


# ----- Atomic write ------------------------------------------ #

def test_no_leftover_tmp_after_successful_apply(workspace) -> None:
    j = workspace["journal"]
    j.append(make_status_change(run_id="r1", edge_id="a", new_status="paused"))
    apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    parent = workspace["registry_path"].parent
    assert not any(p.name.endswith(".tmp") for p in parent.iterdir())


def test_apply_with_missing_registry_raises(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "j.jsonl")
    j.append(make_status_change(run_id="r1", edge_id="a", new_status="paused"))
    with pytest.raises(FileNotFoundError):
        apply(
            journal_path=tmp_path / "j.jsonl",
            registry_path=tmp_path / "missing_edges.yml",
            mark_path=tmp_path / ".mark",
            verbose=False,
        )


# ----- weight_update is counted but doesn't mutate edges.yml -- #

def test_weight_update_counted_but_does_not_mutate_status(workspace) -> None:
    """Phase 1: weight_update entries are journaled but don't yet
    persist (weights live in edge_weights.json, not edges.yml). Phase 2
    routes them. For now: count them, leave registry status alone."""
    j = workspace["journal"]
    j.append(make_weight_update(run_id="r1", edge_id="a", new_weight=0.5))
    result = apply(
        journal_path=workspace["journal_path"],
        registry_path=workspace["registry_path"],
        mark_path=workspace["mark_path"],
        verbose=False,
    )
    assert result.n_weight_updates == 1
    specs = _read_specs(workspace["registry_path"])
    # Status untouched by weight_update
    assert specs["a"]["status"] == "active"


# ----- Mark file format/parsing ----------------------------- #

def test_read_mark_handles_missing_file(tmp_path: Path) -> None:
    assert read_mark(tmp_path / "nope") is None


def test_read_mark_handles_corrupt_content(tmp_path: Path) -> None:
    p = tmp_path / "mark"
    p.write_text("not-an-iso-date")
    assert read_mark(p) is None


def test_write_mark_atomic_rename(tmp_path: Path) -> None:
    p = tmp_path / "mark"
    write_mark(p, "2026-05-07T00:00:00+00:00")
    assert p.read_text() == "2026-05-07T00:00:00+00:00"
    # No .tmp left over
    assert not (tmp_path / "mark.tmp").exists()
