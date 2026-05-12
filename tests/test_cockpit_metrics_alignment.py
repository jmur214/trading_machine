"""tests/test_cockpit_metrics_alignment.py
==========================================

Regression tests for T-2026-05-12-034 — the cockpit metrics-pipeline
field-count bug surfaced in T-030.

Bug summary: `cockpit/logger.py` wrote 11 fields per snapshot row
against a 9-column header (omitting `peak_equity` and
`current_drawdown_pct` from `SNAPSHOT_COLUMNS`). On read,
`pd.read_csv()` mis-aligned the columns, putting the constant
`peak_equity` into the `equity` slot. Result: losing years (where
peak_equity stays glued at the starting capital) reported flat
equity and Sharpe = 0.000.

These tests pin the corrected behavior:
1. `peak_equity` and `current_drawdown_pct` are persisted as named
   columns.
2. `PerformanceMetrics.__init__` raises clearly on any future
   schema mismatch rather than silently mis-aligning.
3. A synthetic losing-year equity curve produces a NEGATIVE Sharpe
   end-to-end through logger + metrics.
"""

from __future__ import annotations

import csv
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from cockpit.logger import CockpitLogger
from cockpit.metrics import PerformanceMetrics


SNAP_HEADER_T034 = [
    "timestamp", "cash", "market_value", "realized_pnl",
    "unrealized_pnl", "equity", "positions",
    "peak_equity", "current_drawdown_pct",
    "open_pos_by_edge", "run_id",
]


def _make_snap(ts: str, equity: float, peak: float, dd: float) -> dict:
    """Synthesize a snap dict matching PortfolioEngine.snapshot() shape."""
    return {
        "timestamp": pd.Timestamp(ts),
        "cash": equity * 0.5,
        "market_value": equity * 0.5,
        "realized_pnl": 0.0,
        "unrealized_pnl": equity - 100_000.0,
        "equity": equity,
        "positions": 10,
        "peak_equity": peak,
        "current_drawdown_pct": dd,
        "open_pos_by_edge": {"test_edge": 10},
    }


def test_snapshot_columns_match_writer_dict_order():
    """SNAPSHOT_COLUMNS must match what PortfolioEngine.snapshot()
    actually emits, otherwise the read mis-aligns. This is the
    structural invariant T-034 fixes."""
    assert CockpitLogger.SNAPSHOT_COLUMNS == SNAP_HEADER_T034


def test_logger_writes_header_matching_data_field_count():
    """The CSV header field-count must equal the per-row data field
    count. Pre-T-034 the header had 9 cols and data had 11 fields,
    which is the bug we're guarding against."""
    with tempfile.TemporaryDirectory() as tmp:
        logger = CockpitLogger(out_dir=tmp, flush_each_fill=True)
        logger.log_snapshot(_make_snap("2022-01-03", 100_000.0, 100_000.0, 0.0))
        logger.flush()

        snap_path = next(Path(tmp).rglob("portfolio_snapshots.csv"))
        with open(snap_path) as fh:
            r = csv.reader(fh)
            header = next(r)
            first_row = next(r)
        assert len(header) == len(first_row), (
            f"header has {len(header)} cols but data row has {len(first_row)} "
            f"fields — this is the T-034 bug"
        )
        assert "peak_equity" in header
        assert "current_drawdown_pct" in header


def test_metrics_asserts_on_header_data_mismatch():
    """PerformanceMetrics.__init__ must fail loud — not silently
    mis-align — when a snapshot CSV's header field-count differs
    from its data rows. This synthesizes the legacy pre-T-034
    layout and confirms the assert fires."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, newline=""
    ) as fh:
        # 9-col header, 11-field data row — the pre-T-034 corruption
        fh.write(
            "timestamp,cash,market_value,realized_pnl,unrealized_pnl,"
            "equity,positions,open_pos_by_edge,run_id\n"
        )
        fh.write(
            "2022-01-03,50000.0,50000.0,0.0,0.0,100000.0,10,100000.0,0.0,"
            "{'test_edge': 10},test-run-id\n"
        )
        tmp_path = fh.name

    try:
        with pytest.raises(ValueError, match="T-2026-05-12-034"):
            PerformanceMetrics(tmp_path)
    finally:
        Path(tmp_path).unlink()


def test_losing_year_metrics_compute_negative_sharpe_after_fix():
    """End-to-end: a losing-year equity series ($100K → $90K) flowed
    through CockpitLogger + PerformanceMetrics must produce a
    NEGATIVE Sharpe, not the pre-T-034 silent zero.

    This is the bug T-030 surfaced: in losing years, peak_equity
    stays glued at $100K but real equity decays. Pre-T-034 the
    reader put peak_equity into the equity slot → flat equity →
    Sharpe = 0. Post-T-034 the reader picks the real equity column,
    so the negative drift surfaces."""
    with tempfile.TemporaryDirectory() as tmp:
        logger = CockpitLogger(out_dir=tmp, flush_each_fill=True)
        # 20-day losing path with non-zero variance
        equities = [100_000.0, 99_500, 99_800, 99_200, 98_900,
                    98_400, 97_800, 97_500, 96_900, 96_200,
                    95_800, 95_100, 94_600, 94_200, 93_500,
                    92_900, 92_400, 91_800, 91_200, 90_500]
        peak = 100_000.0
        for i, eq in enumerate(equities):
            peak = max(peak, eq)
            dd = max(0.0, (peak - eq) / peak)
            ts = pd.Timestamp("2022-01-03") + pd.Timedelta(days=i)
            logger.log_snapshot(_make_snap(str(ts.date()), eq, peak, dd))
        logger.flush()

        snap_path = next(Path(tmp).rglob("portfolio_snapshots.csv"))
        pm = PerformanceMetrics(str(snap_path))
        sharpe = pm.sharpe_ratio()
        assert sharpe is not None and sharpe < 0, (
            f"Losing-year equity must produce negative Sharpe; got {sharpe}"
        )
        # Equity column must reflect real values, not the peak_equity column
        assert abs(pm.equity.iloc[0] - 100_000.0) < 1.0
        assert abs(pm.equity.iloc[-1] - 90_500.0) < 1.0


def test_winning_year_metrics_still_correct_after_fix():
    """Sanity guard — the fix must not regress winning-year metrics.
    Pre-T-034 winning years computed correct numbers by coincidence
    (peak_equity == equity when strategy advances above start).
    Post-fix should still compute correct numbers."""
    with tempfile.TemporaryDirectory() as tmp:
        logger = CockpitLogger(out_dir=tmp, flush_each_fill=True)
        # 20-day winning path with non-zero variance
        equities = [100_000.0, 100_500, 100_300, 101_000, 101_500,
                    102_000, 101_800, 102_500, 103_000, 103_500,
                    104_000, 104_800, 105_300, 105_900, 106_500,
                    107_000, 107_800, 108_400, 109_000, 109_500]
        peak = 100_000.0
        for i, eq in enumerate(equities):
            peak = max(peak, eq)
            dd = max(0.0, (peak - eq) / peak)
            ts = pd.Timestamp("2022-01-03") + pd.Timedelta(days=i)
            logger.log_snapshot(_make_snap(str(ts.date()), eq, peak, dd))
        logger.flush()

        snap_path = next(Path(tmp).rglob("portfolio_snapshots.csv"))
        pm = PerformanceMetrics(str(snap_path))
        sharpe = pm.sharpe_ratio()
        assert sharpe is not None and sharpe > 0, (
            f"Winning-year equity must produce positive Sharpe; got {sharpe}"
        )
        assert abs(pm.equity.iloc[-1] - 109_500.0) < 1.0
