"""
Performance Benchmark
=====================

Runs a standardized backtest across the full active edge ecosystem and produces
a comprehensive performance scorecard including:

- Portfolio-level metrics (Sharpe, Sortino, Calmar, CAGR, MDD, profit factor)
- Per-edge performance breakdown (PnL, win rate, trade count, avg profit)
- SPY buy-and-hold comparison (alpha measurement)
- Edge category summary (which categories contribute most)

Usage:
    python -m scripts.run_benchmark
    python -m scripts.run_benchmark --start 2023-01-01 --end 2024-12-31
    python -m scripts.run_benchmark --capital 50000
    python -m scripts.run_benchmark --json   # output as JSON only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from math import sqrt
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_backtest import run_backtest_logic
from cockpit.metrics import PerformanceMetrics, _compute_fifo_realized
from core.metrics_engine import MetricsEngine


def profit_factor(trades: pd.DataFrame) -> float:
    """Gross profit / gross loss."""
    if trades is None or "pnl" not in trades.columns:
        return float("nan")
    realized = pd.to_numeric(trades["pnl"], errors="coerce").dropna()
    gross_profit = realized[realized > 0].sum()
    gross_loss = abs(realized[realized < 0].sum())
    if gross_loss < 1e-9:
        return float("inf") if gross_profit > 0 else float("nan")
    return gross_profit / gross_loss


def max_consecutive(trades: pd.DataFrame, winning: bool = True) -> int:
    """Longest streak of consecutive winning (or losing) trades."""
    if trades is None or "pnl" not in trades.columns:
        return 0
    realized = pd.to_numeric(trades["pnl"], errors="coerce").dropna()
    if realized.empty:
        return 0
    flags = (realized > 0) if winning else (realized <= 0)
    streak = 0
    best = 0
    for f in flags:
        if f:
            streak += 1
            best = max(best, streak)
        else:
            streak = 0
    return best


def avg_trade_duration(trades: pd.DataFrame) -> float:
    """Average holding period in bars (approximate from trade timestamps)."""
    if trades is None or "timestamp" not in trades.columns or "side" not in trades.columns:
        return float("nan")
    df = trades.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values(["ticker", "timestamp"])

    durations = []
    open_times: dict[str, pd.Timestamp] = {}
    for _, row in df.iterrows():
        tkr = row.get("ticker", "")
        side = str(row.get("side", "")).lower()
        ts = row["timestamp"]
        if side in ("long", "short"):
            open_times[tkr] = ts
        elif side in ("exit", "cover") and tkr in open_times:
            dt = (ts - open_times.pop(tkr)).days
            if dt >= 0:
                durations.append(dt)
    return np.mean(durations) if durations else float("nan")


# ------------------------------------------------------------------ #
# Per-Edge Breakdown
# ------------------------------------------------------------------ #

def per_edge_metrics(trades: pd.DataFrame) -> list[dict]:
    """Compute per-edge performance from trade log."""
    if trades is None or trades.empty:
        return []

    trades = trades.copy()
    trades["pnl"] = pd.to_numeric(trades.get("pnl", pd.Series(dtype=float)), errors="coerce")

    # Determine edge identifier column
    edge_col = None
    for col in ("edge_id", "edge", "edge_group"):
        if col in trades.columns:
            edge_col = col
            break
    if edge_col is None:
        return []

    results = []
    for edge_name, group in trades.groupby(edge_col, sort=False):
        realized = group.dropna(subset=["pnl"])
        total_pnl = realized["pnl"].sum() if not realized.empty else 0.0
        n_trades = len(group)
        n_realized = len(realized)
        wins = (realized["pnl"] > 0).sum() if not realized.empty else 0
        wr = wins / n_realized if n_realized > 0 else float("nan")
        avg_pnl = realized["pnl"].mean() if not realized.empty else float("nan")

        cat = group["edge_category"].iloc[0] if "edge_category" in group.columns else "unknown"

        results.append({
            "edge": str(edge_name),
            "category": str(cat),
            "trades": n_trades,
            "realized_trades": n_realized,
            "total_pnl": round(total_pnl, 2),
            "win_rate": round(wr * 100, 1) if not np.isnan(wr) else None,
            "avg_pnl": round(avg_pnl, 2) if not np.isnan(avg_pnl) else None,
        })

    results.sort(key=lambda x: x["total_pnl"], reverse=True)
    return results


# ------------------------------------------------------------------ #
# SPY Buy-and-Hold Benchmark
# ------------------------------------------------------------------ #

def spy_benchmark(data_map: dict, start: str, end: str, capital: float) -> dict:
    """Compute SPY buy-and-hold metrics over the same period."""
    spy = data_map.get("SPY")
    if spy is None or spy.empty:
        return {"error": "SPY not in data_map"}

    spy = spy.copy()
    if hasattr(spy.index, "tz"):
        spy.index = spy.index.tz_localize(None) if spy.index.tz is None else spy.index.tz_convert(None)

    start_dt = pd.to_datetime(start)
    end_dt = pd.to_datetime(end)
    mask = (spy.index >= start_dt) & (spy.index <= end_dt)
    spy = spy.loc[mask]
    if spy.empty or len(spy) < 2:
        return {"error": "Insufficient SPY data for period"}

    close = spy["Close"] if "Close" in spy.columns else spy["close"]
    shares = int(capital / close.iloc[0])
    equity = close * shares
    total_return = (close.iloc[-1] / close.iloc[0]) - 1
    days = (spy.index[-1] - spy.index[0]).days
    cagr = (close.iloc[-1] / close.iloc[0]) ** (365.0 / max(days, 1)) - 1

    log_ret = np.log(close / close.shift()).dropna()
    vol = log_ret.std() * sqrt(252)
    sharpe = ((log_ret.mean() - 0.02 / 252) / log_ret.std()) * sqrt(252) if log_ret.std() > 1e-9 else 0.0

    roll_max = close.cummax()
    dd = (close - roll_max) / roll_max
    max_dd = dd.min()

    return {
        "total_return_pct": round(total_return * 100, 2),
        "cagr_pct": round(cagr * 100, 2),
        "sharpe": round(sharpe, 3),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "volatility_pct": round(vol * 100, 2),
    }


# ------------------------------------------------------------------ #
# Report Formatting
# ------------------------------------------------------------------ #

def print_scorecard(portfolio: dict, edges: list[dict], benchmark: dict, json_mode: bool = False):
    """Print a formatted performance scorecard."""
    report = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "portfolio": portfolio,
        "per_edge": edges,
        "spy_benchmark": benchmark,
    }

    if json_mode:
        print(json.dumps(report, indent=2, default=str))
        return report

    sep = "=" * 65
    thin = "-" * 65

    print(f"\n{sep}")
    print("  ARCHONDEX PERFORMANCE BENCHMARK")
    print(f"{sep}\n")

    # Portfolio Metrics
    print("  PORTFOLIO METRICS")
    print(f"  {thin}")
    for key in [
        "Starting Equity", "Ending Equity", "Net Profit",
        "Total Return (%)", "CAGR (%)", "Max Drawdown (%)",
        "Sharpe Ratio", "Sortino Ratio", "Calmar Ratio",
        "Volatility (%)", "Win Rate (%)", "Profit Factor",
        "Trades", "Avg Trade Duration (days)",
        "Max Consecutive Wins", "Max Consecutive Losses",
    ]:
        val = portfolio.get(key, "N/A")
        if val is None:
            val = "N/A"
        print(f"  {key:<30s}: {val}")

    # SPY Benchmark
    print(f"\n  SPY BUY-AND-HOLD BENCHMARK")
    print(f"  {thin}")
    if "error" in benchmark:
        print(f"  {benchmark['error']}")
    else:
        for key, label in [
            ("total_return_pct", "Total Return (%)"),
            ("cagr_pct", "CAGR (%)"),
            ("sharpe", "Sharpe Ratio"),
            ("max_drawdown_pct", "Max Drawdown (%)"),
            ("volatility_pct", "Volatility (%)"),
        ]:
            print(f"  {label:<30s}: {benchmark.get(key, 'N/A')}")

        # Alpha
        sys_sharpe = portfolio.get("Sharpe Ratio")
        spy_sharpe = benchmark.get("sharpe")
        if sys_sharpe is not None and spy_sharpe is not None:
            alpha_sharpe = round(sys_sharpe - spy_sharpe, 3)
            print(f"  {'Alpha (Sharpe vs SPY)':<30s}: {alpha_sharpe}")
        sys_ret = portfolio.get("Total Return (%)")
        spy_ret = benchmark.get("total_return_pct")
        if sys_ret is not None and spy_ret is not None:
            alpha_ret = round(sys_ret - spy_ret, 2)
            print(f"  {'Alpha (Return vs SPY)':<30s}: {alpha_ret}%")

    # Per-Edge Breakdown
    if edges:
        print(f"\n  PER-EDGE PERFORMANCE")
        print(f"  {thin}")
        header = f"  {'Edge':<28s} {'PnL':>10s} {'WR%':>7s} {'Trades':>7s} {'Avg PnL':>10s}"
        print(header)
        print(f"  {'-'*62}")
        for e in edges:
            wr = f"{e['win_rate']}%" if e['win_rate'] is not None else "N/A"
            avg = f"${e['avg_pnl']}" if e['avg_pnl'] is not None else "N/A"
            name = e['edge'][:27]
            print(f"  {name:<28s} ${e['total_pnl']:>9,.2f} {wr:>7s} {e['trades']:>7d} {avg:>10s}")

        # Category summary
        print(f"\n  CATEGORY SUMMARY")
        print(f"  {thin}")
        cat_pnl: dict[str, float] = {}
        cat_trades: dict[str, int] = {}
        for e in edges:
            c = e.get("category", "unknown")
            cat_pnl[c] = cat_pnl.get(c, 0) + e["total_pnl"]
            cat_trades[c] = cat_trades.get(c, 0) + e["trades"]
        for cat in sorted(cat_pnl, key=lambda x: cat_pnl[x], reverse=True):
            print(f"  {cat:<28s} ${cat_pnl[cat]:>9,.2f}  ({cat_trades[cat]} trades)")

    print(f"\n{sep}\n")
    return report


# ------------------------------------------------------------------ #
# Main
# ------------------------------------------------------------------ #

def run_benchmark(
    start: str | None = None,
    end: str | None = None,
    capital: float | None = None,
    json_mode: bool = False,
) -> dict:
    """Run benchmark and return full report dict."""

    # Run the backtest (fresh logs, no governor mutation, no discovery)
    summary = run_backtest_logic(
        env="prod",
        mode="prod",
        fresh=True,
        no_governor=True,
        alpha_debug=False,
        override_start=start,
        override_end=end,
        override_capital=capital,
        discover=False,
    )

    # Load detailed metrics
    snap_path = str(ROOT / "data" / "trade_logs" / "portfolio_snapshots.csv")
    trade_path = str(ROOT / "data" / "trade_logs" / "trades.csv")

    try:
        metrics = PerformanceMetrics(snapshots_path=snap_path, trades_path=trade_path)
    except Exception as e:
        print(f"[BENCHMARK] Could not load metrics: {e}")
        return {"error": str(e)}

    # Ensure FIFO PnL is computed
    if metrics.trades is not None and not metrics.trades.empty:
        if "pnl" not in metrics.trades.columns or metrics.trades["pnl"].isna().all():
            metrics.trades = _compute_fifo_realized(metrics.trades)

    # Portfolio-level metrics
    portfolio = {
        "Starting Equity": summary.get("Starting Equity"),
        "Ending Equity": summary.get("Ending Equity"),
        "Net Profit": summary.get("Net Profit"),
        "Total Return (%)": summary.get("Total Return (%)"),
        "CAGR (%)": summary.get("CAGR (%)"),
        "Max Drawdown (%)": summary.get("Max Drawdown (%)"),
        "Sharpe Ratio": summary.get("Sharpe Ratio"),
        "Sortino Ratio": round(MetricsEngine.sortino_ratio(metrics.returns), 3) if not metrics.returns.empty else None,
        "Calmar Ratio": None,
        "Volatility (%)": summary.get("Volatility (%)"),
        "Win Rate (%)": summary.get("Win Rate (%)"),
        "Profit Factor": round(profit_factor(metrics.trades), 2) if metrics.trades is not None else None,
        "Trades": summary.get("Trades", len(metrics.trades) if metrics.trades is not None else 0),
        "Avg Trade Duration (days)": round(avg_trade_duration(metrics.trades), 1) if metrics.trades is not None else None,
        "Max Consecutive Wins": max_consecutive(metrics.trades, winning=True),
        "Max Consecutive Losses": max_consecutive(metrics.trades, winning=False),
    }

    # Calmar needs CAGR and MDD
    cagr_val = summary.get("CAGR (%)")
    mdd_val = summary.get("Max Drawdown (%)")
    if cagr_val is not None and mdd_val is not None:
        calmar = (cagr_val / 100.0) / abs(mdd_val / 100.0) if abs(mdd_val) > 1e-7 else float("nan")
        portfolio["Calmar Ratio"] = round(calmar, 3)

    # Per-edge breakdown
    edges = per_edge_metrics(metrics.trades)

    # SPY benchmark — need data_map, reload it
    from utils.config_loader import load_json
    from engines.data_manager.data_manager import DataManager
    from datetime import timedelta

    cfg_bt = load_json(str(ROOT / "config" / "backtest_settings.json"))
    bt_start = start or cfg_bt.get("start_date", "2024-01-01")
    bt_end = end or cfg_bt.get("end_date", "2024-12-31")
    bt_capital = capital or float(cfg_bt.get("initial_capital", 100000.0))

    dm = DataManager(
        cache_dir=str(ROOT / "data" / "processed"),
        api_key=os.getenv("ALPACA_API_KEY"),
        secret_key=os.getenv("ALPACA_SECRET_KEY"),
        base_url=os.getenv("ALPACA_BASE_URL"),
    )
    spy_data = dm.ensure_data(["SPY"], bt_start, bt_end, timeframe="1d")
    benchmark = spy_benchmark(spy_data, bt_start, bt_end, bt_capital)

    # Print and return
    report = print_scorecard(portfolio, edges, benchmark, json_mode=json_mode)

    # Persist report
    report_path = ROOT / "data" / "research" / "benchmark_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)

    return report


def main():
    parser = argparse.ArgumentParser(description="Run ArchonDEX performance benchmark.")
    parser.add_argument("--start", type=str, default=None, help="Backtest start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, default=None, help="Backtest end date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=None, help="Initial capital")
    parser.add_argument("--json", action="store_true", help="Output as JSON only (no formatted table)")
    args = parser.parse_args()

    run_benchmark(
        start=args.start,
        end=args.end,
        capital=args.capital,
        json_mode=args.json,
    )


if __name__ == "__main__":
    main()
