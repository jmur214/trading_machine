"""tests/test_run_multi_year_report.py
========================================

Lock-in tests for `scripts/run_multi_year._format_markdown_report` —
specifically the heterogeneous-failure handling fix (MEDIUM finding in
`docs/State/health_check.md`):

> `scripts/run_multi_year.py` per-year report assumes uniform rep counts
> — silent KeyError on heterogeneous failures.

Pre-fix: a results list mixing successful runs (record has
sharpe/cagr_pct/trades_canon_md5) with failed runs (record has
ok=False/error only) raised KeyError on `r["sharpe"]` access for the
first failed record.

Post-fix: failed records are filtered into a separate `failed` bucket,
surfaced in their own section. Per-year metric calculation uses
defensive `.get()` access.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from scripts.run_multi_year import _format_markdown_report


def _ok_record(year: int, rep: int, run_id: str, sharpe: float = 1.0):
    return {
        "year": year, "rep": rep, "run_id": run_id, "sharpe": sharpe,
        "cagr_pct": 5.0, "trades_canon_md5": f"canon_{year}_{rep}",
        "ok": True,
    }


def _failed_record(year: int, rep: int, error: str):
    return {
        "year": year, "rep": rep, "ok": False,
        "error": error, "wall_time_seconds": 1.0,
    }


def test_report_handles_heterogeneous_results_without_keyerror(tmp_path: Path):
    """Mix successful + failed records — pre-fix raised KeyError on the
    first failed record's r['sharpe'] access. Post-fix should write a
    valid markdown report."""
    results = [
        _ok_record(2024, 1, "rid_2024_1", 1.5),
        _ok_record(2024, 2, "rid_2024_2", 1.5),
        _failed_record(2024, 3, "RuntimeError: synthetic"),  # ← used to crash
        _ok_record(2023, 1, "rid_2023_1", 1.0),
        _failed_record(2022, 1, "ValueError: synthetic"),
    ]
    out_path = tmp_path / "report.md"
    # Should NOT raise — the bug under test
    _format_markdown_report(results, out_path)
    assert out_path.exists()
    content = out_path.read_text()
    # Ensure successful runs still surface in per-year results
    assert "2023" in content
    assert "2024" in content


def test_report_surfaces_failed_runs_in_dedicated_section(tmp_path: Path):
    results = [
        _ok_record(2024, 1, "rid_2024_1"),
        _failed_record(2024, 2, "RuntimeError: explosion"),
        _failed_record(2022, 1, "ValueError: data missing"),
    ]
    out_path = tmp_path / "report.md"
    _format_markdown_report(results, out_path)
    content = out_path.read_text()
    assert "## Failed runs" in content
    assert "RuntimeError: explosion" in content
    assert "ValueError: data missing" in content
    # Total-runs header includes both buckets
    assert "1 successful + 2 failed" in content


def test_report_handles_all_runs_failed(tmp_path: Path):
    """If every run failed, by_year is empty — pre-fix raised
    StopIteration in `next(iter(by_year.values()))`. Post-fix should
    render a report indicating zero successful runs."""
    results = [
        _failed_record(2024, 1, "RuntimeError: synthetic"),
        _failed_record(2024, 2, "RuntimeError: synthetic"),
        _failed_record(2023, 1, "RuntimeError: synthetic"),
    ]
    out_path = tmp_path / "report.md"
    # Should NOT raise StopIteration
    _format_markdown_report(results, out_path)
    content = out_path.read_text()
    assert "0 successful + 3 failed" in content
    assert "## Failed runs" in content


def test_report_reports_heterogeneous_rep_counts_honestly(tmp_path: Path):
    """When years have different rep counts (one with 1, others with 3),
    pre-fix used `len(next(iter(by_year.values())))` which silently picked
    whichever year happened to be first. Post-fix should report the
    heterogeneity rather than misrepresent."""
    results = [
        _ok_record(2024, 1, "a"),
        _ok_record(2024, 2, "b"),
        _ok_record(2024, 3, "c"),  # 2024 has 3 reps
        _ok_record(2023, 1, "d"),  # 2023 has 1 rep
    ]
    out_path = tmp_path / "report.md"
    _format_markdown_report(results, out_path)
    content = out_path.read_text()
    assert "heterogeneous" in content


def test_report_uniform_rep_count_reports_cleanly(tmp_path: Path):
    """Regression: when all years have the same rep count, the header
    should NOT say 'heterogeneous' (the legacy clean path)."""
    results = [
        _ok_record(2024, 1, "a"),
        _ok_record(2024, 2, "b"),
        _ok_record(2023, 1, "c"),
        _ok_record(2023, 2, "d"),
    ]
    out_path = tmp_path / "report.md"
    _format_markdown_report(results, out_path)
    content = out_path.read_text()
    assert "heterogeneous" not in content
    assert "2 reps" in content


def test_report_no_warning_banner_when_no_failures(tmp_path: Path):
    """When all runs succeeded, the failed-runs warning banner is suppressed."""
    results = [_ok_record(2024, 1, "a")]
    out_path = tmp_path / "report.md"
    _format_markdown_report(results, out_path)
    content = out_path.read_text()
    assert "run(s) failed" not in content
    assert "## Failed runs" not in content
