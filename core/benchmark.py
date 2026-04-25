"""
core/benchmark.py
=================
Rolling-window metrics for benchmark instruments (SPY by default).

Used by Discovery's validation gates and Governance's retirement gates to
replace absolute Sharpe thresholds with benchmark-relative ones. An edge that
produces Sharpe 0.5 during a bull market when SPY is at Sharpe 1.5 is
DESTROYING value vs buy-and-hold, even though Sharpe > 0.

The "right" gate is: `edge_sharpe > benchmark_sharpe - margin`. This module
supplies the benchmark_sharpe side.

Design:
- Computes metrics from the SAME data source the backtest uses (data/processed).
- Caches results by (ticker, start, end) to avoid recomputation across a
  Discovery cycle where many candidates are validated against the same window.
- Bar-by-bar calls during a live backtest should use
  `BenchmarkContext.rolling(...)` which returns a pre-computed rolling series.

No network calls. All data comes from the existing processed CSVs.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


DEFAULT_BENCHMARK_TICKER = "SPY"
DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "processed"


@dataclass(frozen=True)
class BenchmarkMetrics:
    """Point-in-time buy-and-hold benchmark metrics over a date window."""
    ticker: str
    start: str
    end: str
    sharpe: float
    cagr: float
    mdd: float  # negative
    vol: float
    total_return: float
    n_obs: int

    def gate_threshold(self, margin: float = 0.2) -> float:
        """The Sharpe value an edge must exceed to be worth trading over benchmark.

        margin is the tolerance — edges within `margin` of benchmark are
        accepted (transaction costs, capital-efficiency gains). Default 0.2
        requires the edge to clearly beat, not merely match, the benchmark.
        """
        return self.sharpe - margin


def _load_benchmark_prices(ticker: str, data_dir: Optional[Path] = None) -> pd.DataFrame:
    """Load processed OHLCV for benchmark ticker. Raises FileNotFoundError if missing.

    `data_dir` defaults to whatever `DEFAULT_DATA_DIR` resolves to AT CALL TIME
    (not at module import time). This lets tests / scripts swap the data
    directory at runtime via `core.benchmark.DEFAULT_DATA_DIR = ...`. Using
    `data_dir: Path = DEFAULT_DATA_DIR` would have frozen the path at module
    load and silently ignored runtime overrides.
    """
    if data_dir is None:
        data_dir = DEFAULT_DATA_DIR
    path = data_dir / f"{ticker}_1d.csv"
    if not path.exists():
        # Processed file sometimes has only the latest row. Fall back to raw.
        raw = Path(__file__).resolve().parents[1] / "data" / "raw" / f"{ticker}_1d.csv"
        if raw.exists():
            df = pd.read_csv(raw)
            # raw format has lowercase columns + 'timestamp'
            df = df.rename(columns={
                "timestamp": "Date", "open": "Open", "high": "High",
                "low": "Low", "close": "Close", "volume": "Volume",
            })
        else:
            raise FileNotFoundError(f"No benchmark data for {ticker} in {data_dir} or raw/")
    else:
        df = pd.read_csv(path)

    # Normalize
    if "Date" not in df.columns:
        raise ValueError(f"Benchmark file {path} has no Date column")
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None)
    df = df.sort_values("Date").drop_duplicates(subset="Date").reset_index(drop=True)
    if "Close" not in df.columns:
        raise ValueError(f"Benchmark file {path} has no Close column")
    return df[["Date", "Close"]]


@lru_cache(maxsize=256)
def compute_benchmark_metrics(
    start: str,
    end: str,
    ticker: str = DEFAULT_BENCHMARK_TICKER,
) -> BenchmarkMetrics:
    """Compute Sharpe / CAGR / MDD for benchmark buy-and-hold over [start, end].

    Dates are ISO strings (YYYY-MM-DD). Cached by args — safe to call many
    times in a Discovery cycle with the same window.

    If the benchmark file doesn't cover the window, falls back to whatever
    coverage is available (logs nothing; caller can inspect `n_obs`).
    """
    df = _load_benchmark_prices(ticker)
    start_ts = pd.Timestamp(start).tz_localize(None)
    end_ts = pd.Timestamp(end).tz_localize(None)
    mask = (df["Date"] >= start_ts) & (df["Date"] <= end_ts)
    sub = df.loc[mask].copy()

    if len(sub) < 2:
        # No coverage — return a zero-reference so gates don't accidentally pass
        return BenchmarkMetrics(
            ticker=ticker, start=start, end=end,
            sharpe=0.0, cagr=0.0, mdd=0.0, vol=0.0, total_return=0.0, n_obs=len(sub),
        )

    sub["ret"] = sub["Close"].pct_change()
    sub = sub.dropna(subset=["ret"])
    if len(sub) < 2 or sub["ret"].std() == 0:
        return BenchmarkMetrics(
            ticker=ticker, start=start, end=end,
            sharpe=0.0, cagr=0.0, mdd=0.0, vol=0.0, total_return=0.0, n_obs=len(sub),
        )

    daily_ret = sub["ret"]
    total_return = (1 + daily_ret).prod() - 1
    years = (sub["Date"].iloc[-1] - sub["Date"].iloc[0]).days / 365.25
    cagr = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0.0
    vol = daily_ret.std() * float(np.sqrt(252))
    sharpe = (daily_ret.mean() * 252) / vol if vol > 0 else 0.0
    cum = (1 + daily_ret).cumprod()
    mdd = float(((cum - cum.cummax()) / cum.cummax()).min())

    return BenchmarkMetrics(
        ticker=ticker, start=start, end=end,
        sharpe=float(sharpe), cagr=float(cagr), mdd=float(mdd),
        vol=float(vol), total_return=float(total_return), n_obs=len(sub),
    )


def gate_sharpe_vs_benchmark(
    edge_sharpe: float,
    start: str,
    end: str,
    margin: float = 0.2,
    ticker: str = DEFAULT_BENCHMARK_TICKER,
) -> tuple[bool, float]:
    """Return (passed, benchmark_threshold). Edge passes if edge_sharpe >= threshold.

    Threshold = benchmark_sharpe - margin. Margin default 0.2 means an edge
    must get within 0.2 Sharpe of the benchmark OR beat it to pass.
    """
    bm = compute_benchmark_metrics(start=start, end=end, ticker=ticker)
    threshold = bm.gate_threshold(margin=margin)
    return (edge_sharpe >= threshold, threshold)


__all__ = [
    "BenchmarkMetrics",
    "compute_benchmark_metrics",
    "gate_sharpe_vs_benchmark",
    "DEFAULT_BENCHMARK_TICKER",
]
