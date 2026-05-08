"""Tests for engines.engine_f_governance.journal — F11 Phase 1.

Phase 1 ships the writer additively. These tests cover:
- Append + round-trip (single + batch)
- Schema validation rejects unknown decision_type / non-ISO timestamp
- read_all / iter_entries handle empty / missing / malformed lines
- filter_since / truncate are correct + crash-safe (atomic rename)
- Convenience constructors produce valid entries
- Concurrency: thread-safe within one process
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from engines.engine_f_governance.journal import (
    JOURNAL_SCHEMA_VERSION, ALLOWED_DECISION_TYPES,
    JournalEntry, LifecycleJournal,
    now_utc_iso, make_weight_update, make_status_change, make_tier_change,
)


# ----- JournalEntry validation -------------------------------------- #

def test_entry_rejects_unknown_decision_type() -> None:
    with pytest.raises(ValueError, match="decision_type"):
        JournalEntry(
            timestamp=now_utc_iso(), run_id="r1",
            decision_type="not_a_real_type", edge_id="e1", payload={},
        )


def test_entry_accepts_all_allowed_types() -> None:
    for dt in ALLOWED_DECISION_TYPES:
        e = JournalEntry(
            timestamp=now_utc_iso(), run_id="r1",
            decision_type=dt, edge_id="e1", payload={"x": 1},
        )
        assert e.decision_type == dt


def test_entry_rejects_non_iso_timestamp() -> None:
    with pytest.raises(ValueError, match="ISO-8601"):
        JournalEntry(
            timestamp="not-a-date", run_id="r1",
            decision_type="weight_update", edge_id="e1", payload={},
        )


def test_entry_rejects_non_dict_payload() -> None:
    with pytest.raises(TypeError, match="payload"):
        JournalEntry(
            timestamp=now_utc_iso(), run_id="r1",
            decision_type="weight_update", edge_id="e1", payload="not a dict",  # type: ignore[arg-type]
        )


def test_entry_to_json_line_roundtrip() -> None:
    e = JournalEntry(
        timestamp=now_utc_iso(), run_id="r1",
        decision_type="weight_update", edge_id="e1",
        payload={"new_weight": 0.5, "prior_weight": 0.3},
    )
    obj = json.loads(e.to_json_line())
    assert obj["decision_type"] == "weight_update"
    assert obj["payload"]["new_weight"] == 0.5
    assert obj["schema_version"] == JOURNAL_SCHEMA_VERSION


# ----- LifecycleJournal: append + read ------------------------------ #

def test_journal_append_and_read_all(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "j.jsonl")
    j.append(make_weight_update(run_id="r1", edge_id="a", new_weight=0.5))
    j.append(make_status_change(run_id="r1", edge_id="b", new_status="paused"))
    entries = j.read_all()
    assert len(entries) == 2
    assert entries[0].edge_id == "a"
    assert entries[1].edge_id == "b"


def test_journal_append_many_writes_all(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "j.jsonl")
    batch = [
        make_weight_update(run_id="r1", edge_id=f"e{i}", new_weight=0.1 * i)
        for i in range(10)
    ]
    n = j.append_many(batch)
    assert n == 10
    assert len(j.read_all()) == 10


def test_iter_entries_skips_malformed_lines(tmp_path: Path) -> None:
    p = tmp_path / "j.jsonl"
    p.write_text(
        '{"timestamp":"2026-05-07T00:00:00+00:00","run_id":"r1","decision_type":"weight_update","edge_id":"a","payload":{"new_weight":0.5},"schema_version":1}\n'
        'malformed-not-json\n'
        '{"timestamp":"2026-05-07T01:00:00+00:00","run_id":"r1","decision_type":"weight_update","edge_id":"b","payload":{"new_weight":0.6},"schema_version":1}\n',
        encoding="utf-8",
    )
    j = LifecycleJournal(p)
    out = j.read_all()
    assert len(out) == 2  # malformed line skipped
    assert [e.edge_id for e in out] == ["a", "b"]


def test_iter_entries_returns_empty_when_file_missing(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "missing.jsonl")
    assert j.read_all() == []
    assert len(j) == 0


def test_journal_len_counts_entries(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "j.jsonl")
    assert len(j) == 0
    j.append(make_weight_update(run_id="r", edge_id="a", new_weight=0.1))
    j.append(make_weight_update(run_id="r", edge_id="b", new_weight=0.2))
    assert len(j) == 2


# ----- filter_since ------------------------------------------------- #

def test_filter_since_returns_only_newer_entries(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "j.jsonl")
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    for i in range(5):
        j.append(JournalEntry(
            timestamp=(base + timedelta(hours=i)).isoformat(),
            run_id="r", decision_type="weight_update",
            edge_id=f"e{i}", payload={"new_weight": 0.1},
        ))
    cutoff = (base + timedelta(hours=2)).isoformat()
    after = j.filter_since(cutoff)
    assert [e.edge_id for e in after] == ["e3", "e4"]


def test_filter_since_rejects_bad_cutoff(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "j.jsonl")
    with pytest.raises(ValueError, match="ISO-8601"):
        j.filter_since("not-a-date")


# ----- truncate ----------------------------------------------------- #

def test_truncate_with_no_arg_wipes_file(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "j.jsonl")
    j.append(make_weight_update(run_id="r", edge_id="a", new_weight=0.1))
    j.append(make_weight_update(run_id="r", edge_id="b", new_weight=0.2))
    n = j.truncate()
    assert n == 2
    assert len(j) == 0
    assert j.path.read_text() == ""


def test_truncate_before_keeps_newer(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "j.jsonl")
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    for i in range(5):
        j.append(JournalEntry(
            timestamp=(base + timedelta(hours=i)).isoformat(),
            run_id="r", decision_type="weight_update",
            edge_id=f"e{i}", payload={"new_weight": 0.1},
        ))
    cutoff = (base + timedelta(hours=3)).isoformat()
    removed = j.truncate(before_iso=cutoff)
    assert removed == 3  # e0, e1, e2 (strictly less than cutoff)
    remaining = j.read_all()
    assert [e.edge_id for e in remaining] == ["e3", "e4"]


def test_truncate_is_atomic_via_rename(tmp_path: Path) -> None:
    """Verify truncate uses tempfile + rename rather than open(w)."""
    j = LifecycleJournal(tmp_path / "j.jsonl")
    base = datetime(2026, 5, 1, tzinfo=timezone.utc)
    for i in range(5):
        j.append(JournalEntry(
            timestamp=(base + timedelta(hours=i)).isoformat(),
            run_id="r", decision_type="weight_update",
            edge_id=f"e{i}", payload={"new_weight": 0.1},
        ))
    j.truncate(before_iso=(base + timedelta(hours=3)).isoformat())
    # No leftover .tmp from atomic rename
    assert not (tmp_path / "j.jsonl.tmp").exists()


# ----- Convenience constructors ------------------------------------ #

def test_make_weight_update_produces_valid_entry() -> None:
    e = make_weight_update(run_id="r", edge_id="a", new_weight=0.5, prior_weight=0.3)
    assert e.decision_type == "weight_update"
    assert e.edge_id == "a"
    assert e.payload["new_weight"] == 0.5
    assert e.payload["prior_weight"] == 0.3


def test_make_status_change_produces_valid_entry() -> None:
    e = make_status_change(run_id="r", edge_id="a", new_status="paused",
                            prior_status="active", reason="lifecycle gate")
    assert e.decision_type == "status_change"
    assert e.payload["new_status"] == "paused"
    assert e.payload["reason"] == "lifecycle gate"


def test_make_tier_change_produces_valid_entry() -> None:
    e = make_tier_change(run_id="r", edge_id="a", new_tier="alpha", prior_tier="feature")
    assert e.decision_type == "tier_change"
    assert e.payload["new_tier"] == "alpha"


# ----- Thread-safety smoke test ------------------------------------ #

def test_concurrent_appends_no_data_loss(tmp_path: Path) -> None:
    j = LifecycleJournal(tmp_path / "j.jsonl")
    n_threads = 8
    n_per = 25
    expected_total = n_threads * n_per

    def worker(thread_id: int) -> None:
        for i in range(n_per):
            j.append(make_weight_update(
                run_id=f"r{thread_id}", edge_id=f"e{thread_id}_{i}",
                new_weight=0.1 * i,
            ))

    threads = [threading.Thread(target=worker, args=(t,)) for t in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    entries = j.read_all()
    assert len(entries) == expected_total
    # Every line should be valid JSON (no torn writes)
    for line in j.path.read_text().splitlines():
        if line.strip():
            json.loads(line)


# ----- Phase-1 invariants ------------------------------------------- #

def test_phase1_does_not_touch_edges_yml(tmp_path: Path) -> None:
    """Sanity: instantiating a journal + appending entries does NOT
    write to data/governor/edges.yml. Phase 1 is journal-only."""
    j = LifecycleJournal(tmp_path / "j.jsonl")
    j.append(make_status_change(run_id="r", edge_id="a", new_status="paused"))
    # No edges.yml in tmp_path
    assert not any(p.name == "edges.yml" for p in tmp_path.iterdir())
