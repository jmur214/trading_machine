"""Tests for `scripts/backfill_decision_diary.py`.

The backfill script's ENTRIES list is the committed source of truth
for the 12 historical decisions populated on 2026-05-06. The actual
JSONL output lives at `data/governor/decision_diary.jsonl` which is
gitignored and may not exist in CI checkouts. These tests therefore
operate on:

1. The ENTRIES list itself (always available — committed in scripts/).
2. A round-trip through ``append_entry`` into a tmp diary file.

Together this confirms every entry conforms to the
``DecisionDiaryEntry`` schema and produces valid JSONL.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.observability.decision_diary import (  # noqa: E402
    DecisionDiaryEntry,
    DecisionType,
    SCHEMA_VERSION,
    append_entry,
    read_entries,
)
from scripts.backfill_decision_diary import ENTRIES  # noqa: E402


REQUIRED_FIELDS = {
    "timestamp",
    "decision_type",
    "what_changed",
    "expected_impact",
    "actual_impact",
    "rationale_link",
}
VALID_TYPES = {t.value for t in DecisionType}


# ---------------------------------------------------------------------------
# ENTRIES list shape
# ---------------------------------------------------------------------------


def test_entry_count_is_twelve() -> None:
    assert len(ENTRIES) == 12, (
        f"backfill targets 12 load-bearing decisions, got {len(ENTRIES)}"
    )


def test_each_entry_has_required_fields() -> None:
    for i, spec in enumerate(ENTRIES, start=1):
        missing = REQUIRED_FIELDS - set(spec.keys())
        assert not missing, f"entry {i} missing fields: {missing}"


def test_decision_types_are_valid() -> None:
    for i, spec in enumerate(ENTRIES, start=1):
        dt = spec["decision_type"]
        value = dt.value if isinstance(dt, DecisionType) else str(dt)
        assert value in VALID_TYPES, (
            f"entry {i}: decision_type {value!r} not in {sorted(VALID_TYPES)}"
        )


def test_what_changed_within_length_limits() -> None:
    for i, spec in enumerate(ENTRIES, start=1):
        wc = spec["what_changed"]
        assert wc, f"entry {i}: what_changed must be non-empty"
        assert len(wc) <= 200, (
            f"entry {i}: what_changed has {len(wc)} chars, max is 200"
        )


def test_timestamps_are_iso8601_utc() -> None:
    for i, spec in enumerate(ENTRIES, start=1):
        ts = spec["timestamp"]
        # ISO-8601 with explicit UTC offset (+00:00) — the same form
        # ``_now_iso`` produces.
        assert "T" in ts and ts.endswith("+00:00"), (
            f"entry {i}: timestamp {ts!r} not ISO-8601 UTC"
        )


def test_rationale_links_are_strings() -> None:
    for i, spec in enumerate(ENTRIES, start=1):
        link = spec["rationale_link"]
        assert isinstance(link, str) and link, (
            f"entry {i}: rationale_link must be a non-empty string"
        )


# ---------------------------------------------------------------------------
# Round-trip into DecisionDiaryEntry / JSONL
# ---------------------------------------------------------------------------


def test_each_entry_constructs_valid_decision_diary_entry() -> None:
    """Every ENTRIES dict must produce a valid DecisionDiaryEntry.

    This is the schema gate: ``__post_init__`` raises on invalid
    decision_type or oversized what_changed.
    """
    for i, spec in enumerate(ENTRIES, start=1):
        dt = spec["decision_type"]
        dt_value = dt.value if isinstance(dt, DecisionType) else str(dt)
        entry = DecisionDiaryEntry(
            timestamp=spec["timestamp"],
            decision_type=dt_value,
            what_changed=spec["what_changed"],
            expected_impact=spec.get("expected_impact"),
            actual_impact=spec.get("actual_impact"),
            rationale_link=spec.get("rationale_link"),
        )
        assert entry.schema_version == SCHEMA_VERSION
        assert entry.decision_type in VALID_TYPES, (
            f"entry {i}: decision_type round-trip invalid"
        )


def test_jsonl_roundtrip_via_append_and_read(tmp_path: Path) -> None:
    """Append all 12 entries to a tmp diary, then read them back.

    Confirms each line is a single JSON object that the official
    ``read_entries`` parser accepts without warnings.
    """
    diary = tmp_path / "decision_diary.jsonl"
    for spec in ENTRIES:
        append_entry(
            decision_type=spec["decision_type"],
            what_changed=spec["what_changed"],
            expected_impact=spec.get("expected_impact"),
            actual_impact=spec.get("actual_impact"),
            rationale_link=spec.get("rationale_link"),
            timestamp=spec["timestamp"],
            diary_path=diary,
        )

    raw_lines = [l for l in diary.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(raw_lines) == 12

    for i, raw in enumerate(raw_lines, start=1):
        payload = json.loads(raw)  # raises if malformed
        missing = REQUIRED_FIELDS - set(payload.keys())
        assert not missing, f"line {i}: missing serialized fields {missing}"
        assert payload["decision_type"] in VALID_TYPES
        assert payload["schema_version"] == SCHEMA_VERSION

    parsed = read_entries(diary)
    assert len(parsed) == 12, (
        f"read_entries returned {len(parsed)} of 12 — some lines failed schema parse"
    )


def test_no_duplicate_keys_across_entries() -> None:
    """The idempotency key in the backfill script is (timestamp, what_changed).

    No two ENTRIES may share the same key, otherwise re-running the
    script would only append one of the duplicates (silent loss).
    """
    keys = [(spec["timestamp"], spec["what_changed"]) for spec in ENTRIES]
    assert len(keys) == len(set(keys)), (
        "duplicate (timestamp, what_changed) detected in ENTRIES"
    )
