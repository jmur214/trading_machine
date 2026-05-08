"""SQLite run registry — queryable index of every backtest run.

Forward-plan item: today, cross-run forensics requires walking
``data/trade_logs/<uuid>/`` directories and parsing performance_summary.json
+ engine_versions.json by hand. This registry ingests those files into a
single SQLite database so questions like "show me every run with mean Sharpe
> 1.0 across 2025" or "which runs used Engine A v0.2.0?" become one SQL
query.

The registry is build-from-scratch each time you call ``rebuild()``: idempotent,
non-destructive, treats ``data/trade_logs/`` as the source of truth.

CLI usage:
    python -m core.observability.run_registry --rebuild
    python -m core.observability.run_registry --query "SELECT run_id, sharpe FROM runs WHERE sharpe > 1.0 ORDER BY snapshot_at DESC LIMIT 20"
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional

DEFAULT_DB_PATH = Path("data/observability/run_registry.sqlite")
DEFAULT_TRADE_LOG_ROOT = Path("data/trade_logs")


@dataclass
class RunRecord:
    run_id: str
    snapshot_at: Optional[str]
    starting_equity: Optional[float]
    ending_equity: Optional[float]
    sharpe: Optional[float]
    cagr: Optional[float]
    max_drawdown: Optional[float]
    volatility: Optional[float]
    win_rate: Optional[float]
    psr: Optional[float]
    sortino: Optional[float]
    engine_a_version: Optional[str]
    engine_b_version: Optional[str]
    engine_c_version: Optional[str]
    engine_d_version: Optional[str]
    engine_e_version: Optional[str]
    engine_f_version: Optional[str]
    n_trades: Optional[int]
    perf_summary_path: str
    engine_versions_path: Optional[str]


def _safe_float(d: dict, key: str) -> Optional[float]:
    """Return a clean float from a dict that often has None/NaN/strings."""
    v = d.get(key)
    if v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:  # NaN
        return None
    return f


def _safe_int(v) -> Optional[int]:
    if v is None:
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_run_dir(run_dir: Path) -> Optional[RunRecord]:
    perf_path = run_dir / "performance_summary.json"
    ver_path = run_dir / "engine_versions.json"
    if not perf_path.exists():
        return None
    try:
        perf = json.loads(perf_path.read_text())
    except Exception:
        return None
    versions: dict = {}
    snapshot_at: Optional[str] = None
    if ver_path.exists():
        try:
            ver_doc = json.loads(ver_path.read_text())
            versions = ver_doc.get("engine_versions", {}) or {}
            snapshot_at = ver_doc.get("snapshot_at")
        except Exception:
            pass

    # Best-effort trade count from trades.csv (one line per trade after header).
    trades_path = run_dir / "trades.csv"
    n_trades: Optional[int] = None
    if trades_path.exists():
        try:
            with trades_path.open("rb") as f:
                count = sum(1 for _ in f) - 1  # subtract header
            n_trades = max(0, count)
        except Exception:
            n_trades = None

    return RunRecord(
        run_id=run_dir.name,
        snapshot_at=snapshot_at,
        starting_equity=_safe_float(perf, "Starting Equity"),
        ending_equity=_safe_float(perf, "Ending Equity"),
        sharpe=_safe_float(perf, "Sharpe Ratio"),
        cagr=_safe_float(perf, "CAGR (%)"),
        max_drawdown=_safe_float(perf, "Max Drawdown (%)"),
        volatility=_safe_float(perf, "Volatility (%)"),
        win_rate=_safe_float(perf, "Win Rate (%)"),
        psr=_safe_float(perf, "PSR"),
        sortino=_safe_float(perf, "Sortino Ratio"),
        engine_a_version=versions.get("A"),
        engine_b_version=versions.get("B"),
        engine_c_version=versions.get("C"),
        engine_d_version=versions.get("D"),
        engine_e_version=versions.get("E"),
        engine_f_version=versions.get("F"),
        n_trades=n_trades,
        perf_summary_path=str(perf_path),
        engine_versions_path=str(ver_path) if ver_path.exists() else None,
    )


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id              TEXT PRIMARY KEY,
    snapshot_at         TEXT,
    starting_equity     REAL,
    ending_equity       REAL,
    sharpe              REAL,
    cagr                REAL,
    max_drawdown        REAL,
    volatility          REAL,
    win_rate            REAL,
    psr                 REAL,
    sortino             REAL,
    engine_a_version    TEXT,
    engine_b_version    TEXT,
    engine_c_version    TEXT,
    engine_d_version    TEXT,
    engine_e_version    TEXT,
    engine_f_version    TEXT,
    n_trades            INTEGER,
    perf_summary_path   TEXT,
    engine_versions_path TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_snapshot_at  ON runs(snapshot_at);
CREATE INDEX IF NOT EXISTS idx_runs_sharpe       ON runs(sharpe);
CREATE INDEX IF NOT EXISTS idx_runs_a_version    ON runs(engine_a_version);
CREATE INDEX IF NOT EXISTS idx_runs_d_version    ON runs(engine_d_version);
"""


def init_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_run(conn: sqlite3.Connection, rec: RunRecord) -> None:
    conn.execute(
        """
        INSERT INTO runs (
            run_id, snapshot_at, starting_equity, ending_equity,
            sharpe, cagr, max_drawdown, volatility, win_rate, psr, sortino,
            engine_a_version, engine_b_version, engine_c_version,
            engine_d_version, engine_e_version, engine_f_version,
            n_trades, perf_summary_path, engine_versions_path
        ) VALUES (
            :run_id, :snapshot_at, :starting_equity, :ending_equity,
            :sharpe, :cagr, :max_drawdown, :volatility, :win_rate, :psr, :sortino,
            :engine_a_version, :engine_b_version, :engine_c_version,
            :engine_d_version, :engine_e_version, :engine_f_version,
            :n_trades, :perf_summary_path, :engine_versions_path
        )
        ON CONFLICT(run_id) DO UPDATE SET
            snapshot_at=excluded.snapshot_at,
            starting_equity=excluded.starting_equity,
            ending_equity=excluded.ending_equity,
            sharpe=excluded.sharpe,
            cagr=excluded.cagr,
            max_drawdown=excluded.max_drawdown,
            volatility=excluded.volatility,
            win_rate=excluded.win_rate,
            psr=excluded.psr,
            sortino=excluded.sortino,
            engine_a_version=excluded.engine_a_version,
            engine_b_version=excluded.engine_b_version,
            engine_c_version=excluded.engine_c_version,
            engine_d_version=excluded.engine_d_version,
            engine_e_version=excluded.engine_e_version,
            engine_f_version=excluded.engine_f_version,
            n_trades=excluded.n_trades,
            perf_summary_path=excluded.perf_summary_path,
            engine_versions_path=excluded.engine_versions_path
        """,
        rec.__dict__,
    )


def iter_run_dirs(root: Path) -> Iterable[Path]:
    if not root.is_dir():
        return []
    for child in sorted(root.iterdir()):
        if child.is_dir():
            yield child


def rebuild(
    trade_log_root: Path = DEFAULT_TRADE_LOG_ROOT,
    db_path: Path = DEFAULT_DB_PATH,
    verbose: bool = True,
) -> dict:
    """Rebuild the registry from on-disk trade logs. Idempotent."""
    conn = _connect(db_path)
    init_schema(conn)
    n_total = n_ingested = n_skipped = 0
    for run_dir in iter_run_dirs(trade_log_root):
        n_total += 1
        rec = _parse_run_dir(run_dir)
        if rec is None:
            n_skipped += 1
            continue
        upsert_run(conn, rec)
        n_ingested += 1
    conn.commit()
    conn.close()
    summary = {
        "db_path": str(db_path),
        "trade_log_root": str(trade_log_root),
        "n_total_dirs": n_total,
        "n_ingested": n_ingested,
        "n_skipped": n_skipped,
    }
    if verbose:
        print(
            f"[run_registry] rebuilt: {n_ingested}/{n_total} ingested "
            f"({n_skipped} skipped, no perf_summary). DB: {db_path}"
        )
    return summary


def query(
    sql: str,
    db_path: Path = DEFAULT_DB_PATH,
    params: tuple = (),
) -> list[dict]:
    if not db_path.exists():
        raise FileNotFoundError(f"registry not found at {db_path}; run --rebuild first")
    conn = _connect(db_path)
    try:
        cur = conn.execute(sql, params)
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="SQLite run registry CLI")
    parser.add_argument("--rebuild", action="store_true", help="rebuild from data/trade_logs/")
    parser.add_argument("--query", type=str, default=None, help="SQL to run against the registry")
    parser.add_argument("--db", type=str, default=str(DEFAULT_DB_PATH))
    parser.add_argument("--trade-log-root", type=str, default=str(DEFAULT_TRADE_LOG_ROOT))
    args = parser.parse_args()

    db_path = Path(args.db)
    root = Path(args.trade_log_root)

    if args.rebuild:
        rebuild(trade_log_root=root, db_path=db_path)

    if args.query:
        rows = query(args.query, db_path=db_path)
        if not rows:
            print("(no rows)")
        else:
            cols = list(rows[0].keys())
            print(" | ".join(cols))
            print("-+-".join("-" * len(c) for c in cols))
            for r in rows:
                print(" | ".join(str(r[c]) for c in cols))

    if not args.rebuild and not args.query:
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
