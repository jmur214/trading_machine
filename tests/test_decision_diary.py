"""Tests for `core.observability.decision_diary`.

Coverage targets:
- append + read round-trip
- decision_type validation (string + enum)
- length and emptiness validation on what_changed
- malformed lines are skipped, not fatal
- decision_types filter works
- file is APPEND-ONLY (existing lines never modified across writes)
- mode_controller-style integration: simulated post-run write
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.observability.decision_diary import (
    DecisionDiaryEntry,
    DecisionType,
    SCHEMA_VERSION,
    append_entry,
    read_entries,
)


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------


def test_append_and_read_single_entry(tmp_path: Path) -> None:
    diary = tmp_path / "decision_diary.jsonl"
    written = append_entry(
        decision_type=DecisionType.MEASUREMENT_RUN,
        what_changed="2021-2025 multi-year run, mean Sharpe 1.296",
        rationale_link="docs/Audit/multi_year_foundation_measurement.md",
        diary_path=diary,
    )
    assert isinstance(written, DecisionDiaryEntry)
    entries = read_entries(diary_path=diary)
    assert len(entries) == 1
    assert entries[0].decision_type == "measurement_run"
    assert entries[0].what_changed == written.what_changed
    assert entries[0].rationale_link == written.rationale_link
    assert entries[0].schema_version == SCHEMA_VERSION


def test_append_accepts_string_decision_type(tmp_path: Path) -> None:
    """Callers can pass the string form without importing the enum."""
    diary = tmp_path / "diary.jsonl"
    append_entry(
        decision_type="flag_flip",
        what_changed="lifecycle_enabled flipped True",
        diary_path=diary,
    )
    entries = read_entries(diary_path=diary)
    assert entries[0].decision_type == "flag_flip"


def test_invalid_decision_type_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="decision_type"):
        append_entry(
            decision_type="not_a_real_type",
            what_changed="x",
            diary_path=tmp_path / "d.jsonl",
        )


def test_empty_what_changed_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="non-empty"):
        append_entry(
            decision_type="merge",
            what_changed="",
            diary_path=tmp_path / "d.jsonl",
        )


def test_oversized_what_changed_raises(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="≤200 chars"):
        append_entry(
            decision_type="merge",
            what_changed="x" * 201,
            diary_path=tmp_path / "d.jsonl",
        )


# ---------------------------------------------------------------------------
# Append-only invariant
# ---------------------------------------------------------------------------


def test_append_is_append_only(tmp_path: Path) -> None:
    """Subsequent writes must not modify earlier lines on disk."""
    diary = tmp_path / "diary.jsonl"
    append_entry(
        decision_type="merge",
        what_changed="first",
        diary_path=diary,
        timestamp="2026-05-04T10:00:00+00:00",
    )
    first_bytes = diary.read_bytes()
    append_entry(
        decision_type="config_change",
        what_changed="second",
        diary_path=diary,
        timestamp="2026-05-04T10:00:01+00:00",
    )
    second_bytes = diary.read_bytes()
    # First line bytes must remain a prefix of the file.
    assert second_bytes.startswith(first_bytes)
    # Two lines, terminated by \n
    lines = diary.read_text().splitlines()
    assert len(lines) == 2
    assert json.loads(lines[0])["what_changed"] == "first"
    assert json.loads(lines[1])["what_changed"] == "second"


# ---------------------------------------------------------------------------
# Read robustness
# ---------------------------------------------------------------------------


def test_read_skips_malformed_lines(tmp_path: Path, caplog) -> None:
    """A junk line must be skipped, not crash; rest of file still parsed."""
    diary = tmp_path / "diary.jsonl"
    # Write a valid line, a junk line, then another valid line
    append_entry(
        decision_type="merge", what_changed="ok1", diary_path=diary,
    )
    with diary.open("a") as fh:
        fh.write("this is not json\n")
    append_entry(
        decision_type="merge", what_changed="ok2", diary_path=diary,
    )
    with caplog.at_level("WARNING"):
        entries = read_entries(diary_path=diary)
    # Both valid entries returned; junk skipped
    assert len(entries) == 2
    assert {e.what_changed for e in entries} == {"ok1", "ok2"}


def test_read_returns_empty_on_missing_file(tmp_path: Path) -> None:
    assert read_entries(diary_path=tmp_path / "no.jsonl") == []


def test_read_filters_by_decision_type(tmp_path: Path) -> None:
    diary = tmp_path / "diary.jsonl"
    append_entry(decision_type="merge", what_changed="m1", diary_path=diary)
    append_entry(decision_type="flag_flip", what_changed="ff1", diary_path=diary)
    append_entry(decision_type="merge", what_changed="m2", diary_path=diary)

    merges = read_entries(diary_path=diary, decision_types=["merge"])
    assert {e.what_changed for e in merges} == {"m1", "m2"}

    enum_filter = read_entries(
        diary_path=diary, decision_types=[DecisionType.FLAG_FLIP],
    )
    assert {e.what_changed for e in enum_filter} == {"ff1"}


# ---------------------------------------------------------------------------
# Mode-controller-style integration
# ---------------------------------------------------------------------------


def test_simulated_measurement_run_entry(tmp_path: Path) -> None:
    """Mirrors the wiring in mode_controller.run_backtest's post-run hook."""
    diary = tmp_path / "decision_diary.jsonl"
    summary = {"sharpe": 1.296, "cagr": 0.062, "max_drawdown": -0.035}
    append_entry(
        decision_type=DecisionType.MEASUREMENT_RUN,
        what_changed=(
            "backtest mode=prod 2021-01-01..2025-12-31 tickers=109 edges=3"
        ),
        rationale_link=None,
        extra={
            "sharpe": summary["sharpe"],
            "cagr": summary["cagr"],
            "max_drawdown": summary["max_drawdown"],
            "n_tickers": 109,
            "n_edges_loaded": 3,
        },
        diary_path=diary,
    )
    entries = read_entries(diary_path=diary)
    assert len(entries) == 1
    e = entries[0]
    assert e.decision_type == "measurement_run"
    assert e.extra["sharpe"] == 1.296
    assert e.extra["n_tickers"] == 109


def test_jsonl_format_one_record_per_line(tmp_path: Path) -> None:
    """Each line must be parseable in isolation by `json.loads`."""
    diary = tmp_path / "diary.jsonl"
    for i in range(5):
        append_entry(
            decision_type="merge",
            what_changed=f"merge {i}",
            diary_path=diary,
        )
    raw_lines = diary.read_text().splitlines()
    assert len(raw_lines) == 5
    for ln in raw_lines:
        # Each line must be valid JSON, and must NOT contain a literal
        # newline inside the JSON itself (compact separators enforce that).
        payload = json.loads(ln)
        assert payload["decision_type"] == "merge"
        assert "\n" not in ln
