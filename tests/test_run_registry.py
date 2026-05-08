"""Tests for core.observability.run_registry."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.observability.run_registry import (
    rebuild, query, _parse_run_dir, init_schema, upsert_run, _connect,
)


def _write_run(root: Path, run_id: str, sharpe: float = 1.0, versions: bool = True, n_trades: int = 0) -> Path:
    rd = root / run_id
    rd.mkdir(parents=True)
    (rd / "performance_summary.json").write_text(json.dumps({
        "Starting Equity": 100_000.0,
        "Ending Equity": 110_000.0,
        "Sharpe Ratio": sharpe,
        "CAGR (%)": 10.0,
        "Max Drawdown (%)": -5.0,
        "Volatility (%)": 12.0,
        "Win Rate (%)": 55.0,
        "PSR": 0.85,
        "Sortino Ratio": 1.5,
    }))
    if versions:
        (rd / "engine_versions.json").write_text(json.dumps({
            "schema_version": 1,
            "snapshot_at": "2026-05-07T07:00:00+00:00",
            "engine_versions": {
                "A": "0.3.0", "B": "0.1.0", "C": "0.2.0",
                "D": "0.1.0", "E": "0.1.0", "F": "0.1.0",
            },
        }))
    # Synthesize trades
    rows = ["timestamp,ticker,side,qty,fill_price,commission,pnl,edge,edge_id,run_id"]
    for i in range(n_trades):
        rows.append(f"2024-01-{i+1:02d},AAPL,long,1,100.0,0.0,1.0,m,m,{run_id}")
    (rd / "trades.csv").write_text("\n".join(rows) + "\n")
    return rd


def test_rebuild_ingests_runs(tmp_path: Path) -> None:
    root = tmp_path / "trade_logs"
    db = tmp_path / "registry.sqlite"
    _write_run(root, "run-aaa", sharpe=1.2, n_trades=10)
    _write_run(root, "run-bbb", sharpe=0.5, n_trades=3)

    summary = rebuild(trade_log_root=root, db_path=db, verbose=False)
    assert summary["n_ingested"] == 2
    assert summary["n_skipped"] == 0

    rows = query("SELECT run_id, sharpe, n_trades FROM runs ORDER BY run_id", db_path=db)
    assert len(rows) == 2
    assert rows[0]["run_id"] == "run-aaa"
    assert rows[0]["sharpe"] == 1.2
    assert rows[0]["n_trades"] == 10
    assert rows[1]["sharpe"] == 0.5


def test_rebuild_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "trade_logs"
    db = tmp_path / "registry.sqlite"
    _write_run(root, "run-x", sharpe=1.0)
    rebuild(trade_log_root=root, db_path=db, verbose=False)
    rebuild(trade_log_root=root, db_path=db, verbose=False)
    rows = query("SELECT COUNT(*) AS c FROM runs", db_path=db)
    assert rows[0]["c"] == 1


def test_rebuild_skips_dirs_without_perf_summary(tmp_path: Path) -> None:
    root = tmp_path / "trade_logs"
    db = tmp_path / "registry.sqlite"
    _write_run(root, "run-good", sharpe=1.0)
    # Empty dir — no perf_summary.json
    (root / "run-empty").mkdir()
    summary = rebuild(trade_log_root=root, db_path=db, verbose=False)
    assert summary["n_ingested"] == 1
    assert summary["n_skipped"] == 1


def test_rebuild_handles_missing_engine_versions(tmp_path: Path) -> None:
    root = tmp_path / "trade_logs"
    db = tmp_path / "registry.sqlite"
    _write_run(root, "run-noversion", sharpe=1.0, versions=False)
    rebuild(trade_log_root=root, db_path=db, verbose=False)
    rows = query("SELECT engine_a_version FROM runs", db_path=db)
    assert rows[0]["engine_a_version"] is None


def test_rebuild_re_ingests_when_perf_summary_changes(tmp_path: Path) -> None:
    root = tmp_path / "trade_logs"
    db = tmp_path / "registry.sqlite"
    rd = _write_run(root, "run-change", sharpe=0.5)
    rebuild(trade_log_root=root, db_path=db, verbose=False)
    # Mutate the perf_summary; re-rebuild should overwrite the row
    perf = json.loads((rd / "performance_summary.json").read_text())
    perf["Sharpe Ratio"] = 2.5
    (rd / "performance_summary.json").write_text(json.dumps(perf))
    rebuild(trade_log_root=root, db_path=db, verbose=False)
    rows = query("SELECT sharpe FROM runs WHERE run_id='run-change'", db_path=db)
    assert rows[0]["sharpe"] == 2.5


def test_query_supports_filtering(tmp_path: Path) -> None:
    root = tmp_path / "trade_logs"
    db = tmp_path / "registry.sqlite"
    _write_run(root, "low",  sharpe=0.2)
    _write_run(root, "mid",  sharpe=0.8)
    _write_run(root, "high", sharpe=1.5)
    rebuild(trade_log_root=root, db_path=db, verbose=False)
    rows = query("SELECT run_id FROM runs WHERE sharpe > 1.0", db_path=db)
    assert len(rows) == 1
    assert rows[0]["run_id"] == "high"


def test_query_raises_when_db_missing(tmp_path: Path) -> None:
    db = tmp_path / "no.sqlite"
    with pytest.raises(FileNotFoundError):
        query("SELECT 1", db_path=db)


def test_handles_nan_sharpe_gracefully(tmp_path: Path) -> None:
    root = tmp_path / "trade_logs"
    db = tmp_path / "registry.sqlite"
    rd = root / "run-nan"
    rd.mkdir(parents=True)
    (rd / "performance_summary.json").write_text(json.dumps({
        "Starting Equity": 100_000.0,
        "Sharpe Ratio": "NaN",  # legacy serialized as string
    }))
    rebuild(trade_log_root=root, db_path=db, verbose=False)
    rows = query("SELECT sharpe FROM runs", db_path=db)
    assert rows[0]["sharpe"] is None
