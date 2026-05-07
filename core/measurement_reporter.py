"""
core/measurement_reporter.py
============================
Loads a backtest run's portfolio snapshots into a `pd.Series` equity curve
and computes the full extended-metric ladder via `MetricsEngine.calculate_all`.

Used by `scripts/run_multi_year.py` and any other measurement-report writer
that wants to surface PSR / Information Ratio / Calmar / Sortino / Ulcer
Index / Skewness / Kurtosis / Tail Ratio alongside the headline Sharpe.

Added 2026-05-09 evening per the metric-framework upgrade in
`core/metrics_engine.py` and the outside-reviewer recommendation that
PSR replaces raw Sharpe as the headline statistic. See
`docs/State/lessons_learned.md` 2026-05-09 entry.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional, Dict, Any

import pandas as pd

from core.metrics_engine import MetricsEngine

ROOT = Path(__file__).resolve().parents[1]
TRADE_LOGS_DIR = ROOT / "data" / "trade_logs"
PROCESSED_DIR = ROOT / "data" / "processed"


def load_equity_curve(run_id: str) -> pd.Series:
    """
    Load the equity curve for ``run_id`` from the portfolio_snapshots.csv
    in its trade-log directory.

    Returns a `pd.Series` indexed by date (parsed to `pd.DatetimeIndex`).
    Raises `FileNotFoundError` if the run's snapshot file doesn't exist.
    """
    snap = TRADE_LOGS_DIR / run_id / "portfolio_snapshots.csv"
    if not snap.exists():
        raise FileNotFoundError(f"No portfolio_snapshots.csv for run_id={run_id} at {snap}")
    df = pd.read_csv(snap)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    return pd.Series(df["equity"].values, index=df["timestamp"], name="equity")


def load_benchmark_curve(start: pd.Timestamp, end: pd.Timestamp, ticker: str = "SPY") -> Optional[pd.Series]:
    """
    Load benchmark closing prices for ``ticker`` over [start, end], scaled to
    a synthetic equity curve starting at 100,000 (matches strategy starting
    equity for like-for-like Information Ratio).

    Returns `None` if the benchmark CSV is missing — caller should fall back
    to no-benchmark metric set.
    """
    csv_path = PROCESSED_DIR / f"{ticker}_1d.csv"
    if not csv_path.exists():
        return None
    df = pd.read_csv(csv_path)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.set_index("timestamp")
    elif "Date" in df.columns:
        df["Date"] = pd.to_datetime(df["Date"])
        df = df.set_index("Date")
    else:
        return None
    if "close" in df.columns:
        prices = df["close"]
    elif "Close" in df.columns:
        prices = df["Close"]
    else:
        return None
    prices = prices.loc[(prices.index >= start) & (prices.index <= end)]
    if prices.empty:
        return None
    # Scale to 100k starting equity for direct comparability with strategy curve
    return (prices / prices.iloc[0]) * 100_000.0


def compute_extended_metrics(
    run_id: str,
    benchmark_ticker: str = "SPY",
    n_trials_for_dsr: int = 1,
) -> Dict[str, Any]:
    """
    Load run_id's equity curve + matched-window benchmark, compute the full
    extended-metric ladder.

    Returns a dict with all keys from `MetricsEngine.calculate_all` plus
    `DSR` (Deflated Sharpe Ratio under ``n_trials_for_dsr``).
    """
    eq = load_equity_curve(run_id)
    bench = load_benchmark_curve(eq.index.min(), eq.index.max(), benchmark_ticker)
    metrics = MetricsEngine.calculate_all(eq, bench)
    # DSR is not part of calculate_all's default output (it requires
    # n_trials, which depends on the measurement context). Compute and append.
    returns = eq.pct_change().dropna()
    if len(returns) >= 4 and returns.std() > 0:
        metrics["DSR"] = MetricsEngine.deflated_sharpe_ratio(returns, n_trials_for_dsr)
    else:
        metrics["DSR"] = 0.0
    return metrics


def _format_metric_value(name: str, value: float) -> str:
    """Render a metric with appropriate decimals."""
    if name in ("PSR", "DSR"):
        return f"{value:.3f}"
    if "%" in name:
        return f"{value:.2f}"
    return f"{value:.4f}"


def render_extended_metric_summary(metrics: Dict[str, Any]) -> list[str]:
    """
    Build a markdown summary block for the extended metrics. Returns a list
    of lines that callers can splice into a report.
    """
    lines = []
    lines.append("**Statistical Sharpe (sample-size + skewness + kurtosis aware):**")
    lines.append(f"- PSR(SR>0): **{metrics.get('PSR', 0.0):.3f}** (probability true Sharpe > 0)")
    if "DSR" in metrics:
        lines.append(f"- DSR: {metrics['DSR']:.3f} (PSR with multiple-testing correction)")
    lines.append("")
    lines.append("**Drawdown-aware (Goal A — compound):**")
    lines.append(f"- Calmar: {metrics.get('Calmar', 0.0):.4f}")
    lines.append(f"- Ulcer Index: {metrics.get('Ulcer Index', 0.0):.2f}")
    lines.append(f"- Max Drawdown: {metrics.get('Max Drawdown %', 0.0):.2f}%")
    lines.append("")
    lines.append("**Asymmetry-aware (Goal C — moonshot, future):**")
    lines.append(f"- Skewness: {metrics.get('Skewness', 0.0):.4f}")
    lines.append(f"- Excess Kurtosis: {metrics.get('Excess Kurtosis', 0.0):.4f}")
    lines.append(f"- Tail Ratio: {metrics.get('Tail Ratio', 0.0):.4f}")
    lines.append("")
    lines.append("**Active vs SPY (Goal B — outperform):**")
    lines.append(f"- Information Ratio: {metrics.get('Information Ratio', 0.0):.4f}")
    lines.append(f"- Beta: {metrics.get('Beta', 0.0):.4f}")
    lines.append("")
    lines.append("**Headline Sharpe (kept as secondary reference):**")
    lines.append(f"- Sharpe: {metrics.get('Sharpe', 0.0):.4f}")
    lines.append(f"- Sortino: {metrics.get('Sortino', 0.0):.4f}")
    return lines
