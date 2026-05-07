"""tests/test_operational_pattern_audit.py
============================================

Tests for `scripts/operational_pattern_audit` — the periodic audit
that captures the dev's 2026-05-09 meta-finding: "audit framework
caught substrate bias but not operational pattern."

Tests cover:
- Each section of the audit produces the expected shape
- Render functions handle empty / error states
- Flags fire correctly when thresholds are crossed
- End-to-end smoke (runs main() with --no-write, expects exit code 0)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts import operational_pattern_audit as ops


def test_audit_edge_population_returns_expected_shape():
    findings = ops.audit_edge_population()
    if "error" not in findings:
        assert "total_edges" in findings
        assert "by_status" in findings
        assert "active_count" in findings
        assert "autonomous_active_count" in findings
        assert "autonomous_active_pct" in findings
        assert isinstance(findings["by_status"], dict)


def test_audit_oos_lock_status_returns_expected_shape():
    findings = ops.audit_oos_lock_status()
    # Either ok-shape or error-shape
    assert "active" in findings or "error" in findings


def test_audit_discovery_cycle_activity_handles_missing_history():
    """Function must not crash when lifecycle_history.csv is absent."""
    findings = ops.audit_discovery_cycle_activity()
    assert "lifecycle_history_exists" in findings


def test_audit_metalearner_status():
    findings = ops.audit_metalearner_status()
    assert "enabled" in findings or "error" in findings


def test_audit_recent_param_sweeps_returns_list():
    findings = ops.audit_recent_param_sweeps()
    assert "sweep_docs" in findings
    assert isinstance(findings["sweep_docs"], list)


def test_render_summary_includes_all_four_potential_flags():
    """Construct a worst-case findings dict — every flag must fire and
    appear in the summary string."""
    findings = {
        "edges": {
            "total_edges": 283, "active_count": 9,
            "autonomous_active_count": 0, "autonomous_active_pct": 0.0,
        },
        "oos_lock": {"active": False},
        "discovery": {"promote_events_count": 0},
        "metalearner": {"enabled": False},
    }
    summary = ops.render_summary(findings)
    assert "FLAGS (4)" in summary
    assert "autonomous-active < 10%" in summary
    assert "OOS lock INACTIVE" in summary
    assert "Discovery has never promoted" in summary
    assert "MetaLearner disabled" in summary


def test_render_summary_no_flags_when_all_clean():
    """When everything's healthy, no FLAGS line."""
    findings = {
        "edges": {
            "total_edges": 50, "active_count": 20,
            "autonomous_active_count": 18, "autonomous_active_pct": 90.0,
        },
        "oos_lock": {"active": True},
        "discovery": {"promote_events_count": 12},
        "metalearner": {"enabled": True},
    }
    summary = ops.render_summary(findings)
    assert "FLAGS" not in summary


def test_render_markdown_report_includes_all_sections():
    findings = {
        "edges": {
            "total_edges": 283, "active_count": 9,
            "autonomous_active_count": 0, "autonomous_active_pct": 0.0,
            "active_with_origin_set": 0,
            "by_status": {"active": 9, "failed": 144},
        },
        "oos_lock": {"active": False},
        "discovery": {
            "lifecycle_history_exists": True,
            "promote_events_count": 0,
            "events_last_90_days": 0,
            "most_recent_event": "2025-12-31T00:00:00+00:00",
        },
        "metalearner": {"enabled": False},
        "sweeps": {"sweep_docs": ["docs/Measurements/2026-04/sweep_one.md"], "total_sweep_docs": 1},
    }
    report = ops.render_markdown_report(findings)
    for section in ("Edge-curation pattern", "F8 OOS lock status",
                    "Engine D autonomous-discovery activity", "MetaLearner status",
                    "Recent parameter-sweep activity"):
        assert section in report
    # Findings should surface as flags in the report
    assert "FLAG: < 10%" in report
    assert "FLAG: tuning scripts run unrestricted" in report
    assert "FLAG: Discovery cycle has never promoted" in report


def test_render_markdown_report_handles_inactive_oos_lock_message():
    findings = {
        "edges": {"total_edges": 0, "active_count": 0, "autonomous_active_count": 0,
                  "autonomous_active_pct": 0.0, "active_with_origin_set": 0, "by_status": {}},
        "oos_lock": {"active": False},
        "discovery": {"lifecycle_history_exists": False},
        "metalearner": {"enabled": False},
        "sweeps": {"sweep_docs": [], "total_sweep_docs": 0},
    }
    report = ops.render_markdown_report(findings)
    assert "OOS lock INACTIVE" in report


def test_render_markdown_report_handles_active_oos_lock():
    findings = {
        "edges": {"total_edges": 0, "active_count": 0, "autonomous_active_count": 0,
                  "autonomous_active_pct": 0.0, "active_with_origin_set": 0, "by_status": {}},
        "oos_lock": {
            "active": True, "window_start": "2026-01-01",
            "frozen_parameters": ["fill_share_cap", "PAUSED_MAX_WEIGHT"],
            "lock_reason": "Test lock.", "locked_at": "2026-05-09T22:00:00+00:00",
        },
        "discovery": {"lifecycle_history_exists": False},
        "metalearner": {"enabled": False},
        "sweeps": {"sweep_docs": [], "total_sweep_docs": 0},
    }
    report = ops.render_markdown_report(findings)
    assert "OOS lock ACTIVE" in report
    assert "fill_share_cap" in report


def test_main_no_write_returns_zero():
    """End-to-end smoke: main(--no-write) runs without exception, returns 0."""
    rc = ops.main(["--no-write"])
    assert rc == 0


def test_main_write_creates_report_file(tmp_path: Path):
    out = tmp_path / "test_audit.md"
    rc = ops.main(["--output", str(out)])
    assert rc == 0
    assert out.exists()
    content = out.read_text()
    assert "# Operational Pattern Audit" in content
