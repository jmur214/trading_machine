"""tests/test_oos_lock.py
=========================

Tests for the F8 frozen-code OOS window discipline (`core/oos_lock.py`).
Captures the audit's discipline lesson programmatically: parameter
sweeps must not observe data inside the OOS window for any frozen
parameter. Catches the same anti-pattern that allowed `fill_share_cap`,
`PAUSED_MAX_WEIGHT`, ADV floors, and `sustained_score` to be hand-tuned
on biased substrate (lessons_learned 2026-05-09 entry).
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from core import oos_lock as ol


def test_load_returns_inactive_when_file_missing(tmp_path: Path):
    lock = ol.load_oos_lock(tmp_path / "does_not_exist.json")
    assert lock.active is False
    assert lock.window_start_iso is None
    assert lock.frozen_parameters == []


def test_load_returns_inactive_when_json_malformed(tmp_path: Path):
    p = tmp_path / "oos_window.json"
    p.write_text("not valid json {{{")
    lock = ol.load_oos_lock(p)
    assert lock.active is False


def test_inactive_lock_no_op_for_all_helpers():
    """Inactive lock must let everything through — preserves prior behavior
    when a project hasn't yet declared an OOS window."""
    lock = ol.OOSLock(active=False)
    assert ol.is_in_oos_window("2026-12-31", lock=lock) is False
    assert ol.date_range_overlaps_oos("2026-01-01", "2026-12-31", lock=lock) is False
    # No raise even when 'parameter' would normally be frozen
    ol.assert_not_tuning_in_oos(
        "fill_share_cap", "2026-01-01", "2026-12-31", lock=lock,
    )


def test_active_lock_recognizes_in_window():
    lock = ol.OOSLock(
        active=True, window_start_iso="2026-01-01",
        frozen_parameters=["fill_share_cap"],
    )
    assert ol.is_in_oos_window("2026-06-01", lock=lock) is True
    assert ol.is_in_oos_window("2025-12-31", lock=lock) is False
    assert ol.is_in_oos_window(date(2026, 1, 1), lock=lock) is True


def test_assert_raises_when_frozen_parameter_sweep_overlaps_oos():
    """The load-bearing failure case — a sweep of a frozen parameter that
    would observe OOS data must be blocked, even if start_date is pre-OOS."""
    lock = ol.OOSLock(
        active=True, window_start_iso="2026-01-01",
        frozen_parameters=["fill_share_cap"],
        lock_reason="Post-engine-completion baseline; do not retune until 2026-Q4.",
    )
    with pytest.raises(ol.OOSLockViolation) as exc:
        ol.assert_not_tuning_in_oos(
            "fill_share_cap", "2025-01-01", "2026-06-30", lock=lock,
        )
    assert "fill_share_cap" in str(exc.value)
    assert "2026-01-01" in str(exc.value)


def test_assert_passes_when_sweep_pre_oos_only():
    """A sweep that ends before the OOS window starts is fine."""
    lock = ol.OOSLock(
        active=True, window_start_iso="2026-01-01",
        frozen_parameters=["fill_share_cap"],
    )
    # No raise — sweep ends 2025-12-31 (one day before OOS window opens)
    ol.assert_not_tuning_in_oos(
        "fill_share_cap", "2024-01-01", "2025-12-31", lock=lock,
    )


def test_assert_passes_when_parameter_not_in_frozen_set():
    """An unfrozen parameter is freely tunable even on OOS data — the lock
    only protects parameters that have been explicitly frozen."""
    lock = ol.OOSLock(
        active=True, window_start_iso="2026-01-01",
        frozen_parameters=["fill_share_cap"],
    )
    # 'risk_per_trade_pct' is not in frozen_parameters — sweep allowed
    ol.assert_not_tuning_in_oos(
        "risk_per_trade_pct", "2026-01-01", "2026-12-31", lock=lock,
    )


def test_write_lock_creates_active_lock(tmp_path: Path):
    p = tmp_path / "oos_window.json"
    lock = ol.write_lock(
        window_start_iso="2026-01-01",
        frozen_parameters=["fill_share_cap", "PAUSED_MAX_WEIGHT"],
        lock_reason="Test lock",
        locked_by="test_suite",
        path=p,
    )
    assert lock.active is True
    assert lock.window_start_iso == "2026-01-01"
    assert "fill_share_cap" in lock.frozen_parameters
    assert "PAUSED_MAX_WEIGHT" in lock.frozen_parameters
    assert lock.lock_reason == "Test lock"
    assert lock.locked_by == "test_suite"
    # Round-trip: file exists + parses back identically
    data = json.loads(p.read_text())
    assert data["active"] is True
    assert data["schema_version"] == 1


def test_write_lock_dedupes_and_sorts_frozen_parameters(tmp_path: Path):
    p = tmp_path / "oos_window.json"
    lock = ol.write_lock(
        window_start_iso="2026-01-01",
        frozen_parameters=["fill_share_cap", "fill_share_cap", "ADV_FLOOR"],
        lock_reason="Test",
        path=p,
    )
    assert lock.frozen_parameters == ["ADV_FLOOR", "fill_share_cap"]


def test_report_lock_status_reflects_inactive_vs_active():
    inactive = ol.OOSLock(active=False)
    assert "INACTIVE" in ol.report_lock_status(inactive)

    active = ol.OOSLock(
        active=True, window_start_iso="2026-01-01",
        frozen_parameters=["fill_share_cap"],
        lock_reason="Hands off until next pre-commit.",
        locked_at="2026-05-09T22:00:00+00:00", locked_by="user",
    )
    msg = ol.report_lock_status(active)
    assert "ACTIVE" in msg
    assert "fill_share_cap" in msg
    assert "Hands off" in msg


def test_load_oos_lock_round_trip_via_write(tmp_path: Path):
    """write_lock → load_oos_lock should produce the same in-memory object."""
    p = tmp_path / "oos_window.json"
    written = ol.write_lock(
        window_start_iso="2026-04-01",
        frozen_parameters=["sustained_score", "fill_share_cap"],
        lock_reason="Round trip test",
        locked_by="pytest",
        path=p,
    )
    loaded = ol.load_oos_lock(p)
    assert loaded.active == written.active
    assert loaded.window_start_iso == written.window_start_iso
    assert loaded.frozen_parameters == written.frozen_parameters
    assert loaded.lock_reason == written.lock_reason
    assert loaded.locked_by == written.locked_by


def test_is_parameter_frozen_method():
    inactive = ol.OOSLock(active=False, frozen_parameters=["fill_share_cap"])
    assert inactive.is_parameter_frozen("fill_share_cap") is False  # inactive overrides

    active = ol.OOSLock(active=True, frozen_parameters=["fill_share_cap"])
    assert active.is_parameter_frozen("fill_share_cap") is True
    assert active.is_parameter_frozen("other_param") is False
