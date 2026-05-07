"""tests/test_engine_versions.py
==================================

Tests for `core.engine_versions` — engine versioning per audit
recommendation (2026-05-09 evening).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from core import engine_versions as ev


def test_all_six_engines_export_a_version():
    versions = ev.get_all_engine_versions()
    assert set(versions.keys()) == {"A", "B", "C", "D", "E", "F"}
    for letter, version in versions.items():
        assert version != "0.0.0", (
            f"Engine {letter} missing __version__ — every engine package "
            f"must export a semver string in its __init__.py"
        )


def test_all_six_engines_versions_are_semver():
    versions = ev.get_all_engine_versions()
    for letter, version in versions.items():
        assert ev.is_valid_semver(version), (
            f"Engine {letter} version {version!r} is not valid semver "
            f"(MAJOR.MINOR.PATCH); see core.engine_versions.SEMVER_RE"
        )


def test_all_six_engines_have_charter_status():
    statuses = ev.get_charter_statuses()
    assert set(statuses.keys()) == {"A", "B", "C", "D", "E", "F"}
    for letter, status in statuses.items():
        assert status and status != "(not declared)", (
            f"Engine {letter} missing __charter_status__ in __init__.py"
        )


def test_is_valid_semver():
    assert ev.is_valid_semver("0.1.0") is True
    assert ev.is_valid_semver("1.0.0") is True
    assert ev.is_valid_semver("99.99.99") is True
    # Reject non-strict forms
    assert ev.is_valid_semver("1.0") is False
    assert ev.is_valid_semver("1.0.0-beta") is False
    assert ev.is_valid_semver("1.0.0+build123") is False
    assert ev.is_valid_semver("v1.0.0") is False
    assert ev.is_valid_semver("") is False


def test_get_engine_versions_snapshot_contains_required_fields():
    snap = ev.get_engine_versions_snapshot()
    assert snap["schema_version"] == 1
    assert "snapshot_at" in snap
    assert "engine_versions" in snap
    assert "charter_statuses" in snap
    assert isinstance(snap["engine_versions"], dict)


def test_get_engine_versions_snapshot_includes_run_id_when_provided():
    snap = ev.get_engine_versions_snapshot(run_id="abc123")
    assert snap["run_id"] == "abc123"


def test_write_and_load_round_trip(tmp_path: Path):
    run_id = "test-run-versions-round-trip"
    written_path = ev.write_engine_versions_for_run(
        run_id, trade_logs_dir=tmp_path,
    )
    assert written_path.exists()
    assert written_path.name == "engine_versions.json"
    loaded = ev.load_engine_versions_for_run(run_id, trade_logs_dir=tmp_path)
    assert loaded is not None
    assert loaded["run_id"] == run_id
    assert "A" in loaded["engine_versions"]
    assert "F" in loaded["engine_versions"]


def test_write_refuses_to_overwrite_existing_snapshot(tmp_path: Path):
    """Run-id collision should raise FileExistsError, not silently
    overwrite — protects forensic reconstruction integrity."""
    run_id = "collision-test"
    ev.write_engine_versions_for_run(run_id, trade_logs_dir=tmp_path)
    with pytest.raises(FileExistsError):
        ev.write_engine_versions_for_run(run_id, trade_logs_dir=tmp_path)


def test_load_returns_none_for_missing_run(tmp_path: Path):
    """Legacy runs from before this feature shipped have no snapshot.
    Caller should get None, not a KeyError."""
    result = ev.load_engine_versions_for_run("never-existed", trade_logs_dir=tmp_path)
    assert result is None


def test_snapshot_json_is_valid_and_human_readable(tmp_path: Path):
    """The snapshot file should be human-readable JSON (indent=2) so
    forensic ops can `cat` and read it directly."""
    run_id = "readable-test"
    path = ev.write_engine_versions_for_run(run_id, trade_logs_dir=tmp_path)
    text = path.read_text()
    assert "\n  " in text, "Should be indented for human reading"
    parsed = json.loads(text)
    assert parsed["run_id"] == run_id


def test_report_engine_versions_includes_every_engine():
    report = ev.report_engine_versions()
    for letter in ("A", "B", "C", "D", "E", "F"):
        assert f"Engine {letter}:" in report
