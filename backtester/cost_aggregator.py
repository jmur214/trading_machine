# backtester/cost_aggregator.py
"""
Cost-completeness aggregator.

Combines the three pluggable cost layers (slippage, borrow, taxes) plus
the Alpaca regulatory pass-through into a single post-processor that
produces three labeled equity curves:

  A  =  baseline (existing slippage already in fill_price; commission
        already debited at fill time — Alpaca fees may or may not be on
        depending on config)
  B  =  A − borrow drag                  (always honest for any short)
  C  =  B − tax drag                     (after-tax; opt-in)

The model deliberately runs *after* the backtest so it touches no engine
state. It reads:

  - The trade log (fills with ``timestamp, ticker, side, qty, fill_price,
    commission, pnl``) — used for FIFO matching, tax classification,
    short-position reconstruction.
  - The portfolio snapshot history (``timestamp, equity, ...``) — used
    as the equity-curve baseline.
  - A price/volume data_map for ADV bucketing on the borrow side.

Outputs a small dict the caller can merge into ``performance_summary.json``
or print.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional

import numpy as np
import pandas as pd

from backtester.alpaca_fees import AlpacaFees, get_alpaca_fees
from backtester.borrow_rate_model import BorrowRateModel, get_borrow_rate_model
from backtester.tax_drag_model import TaxDragModel, get_tax_drag_model


@dataclass
class CostAggregatorResult:
    equity_A: pd.Series                 # baseline (post-slippage, post-Alpaca)
    equity_B: pd.Series                 # A − borrow
    equity_C: pd.Series                 # B − taxes
    sharpe_A: float
    sharpe_B: float
    sharpe_C: float
    cagr_A: float
    cagr_B: float
    cagr_C: float
    max_dd_A: float
    max_dd_B: float
    max_dd_C: float
    total_alpaca_fees: float
    total_borrow_drag: float
    total_tax_drag: float
    yearly_tax_breakdown: Dict[int, Dict[str, float]]


def _annualized_sharpe(equity: pd.Series, periods_per_year: int = 252) -> float:
    """Sharpe of daily equity-curve returns (rf=0, std-of-returns)."""
    if equity is None or len(equity) < 3:
        return 0.0
    rets = equity.pct_change().dropna()
    if len(rets) == 0 or rets.std() == 0:
        return 0.0
    return float(rets.mean() / rets.std() * np.sqrt(periods_per_year))


def _cagr(equity: pd.Series, periods_per_year: int = 252) -> float:
    if equity is None or len(equity) < 2:
        return 0.0
    start = float(equity.iloc[0])
    end = float(equity.iloc[-1])
    if start <= 0 or end <= 0:
        return 0.0
    n_periods = max(1, len(equity) - 1)
    years = n_periods / periods_per_year
    if years <= 0:
        return 0.0
    return float((end / start) ** (1.0 / years) - 1.0)


def _max_drawdown(equity: pd.Series) -> float:
    if equity is None or len(equity) == 0:
        return 0.0
    running_max = equity.cummax()
    dd = (equity - running_max) / running_max
    return float(dd.min())


def _build_short_positions_map(
    fill_log: pd.DataFrame,
    snapshots: pd.DataFrame,
) -> Dict[pd.Timestamp, Dict[str, float]]:
    """Reconstruct per-snapshot short positions from the fill log.

    Walks the fill log forward, maintaining {ticker: signed_shares}.
    Emits a snapshot-aligned dict at every timestamp in ``snapshots``.

    Returns: {ts: {ticker: shares}} where shares is negative for shorts.
    """
    if fill_log is None or len(fill_log) == 0 or snapshots is None or len(snapshots) == 0:
        return {}

    df = fill_log.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)

    if "timestamp" in snapshots.columns:
        snap_ts = pd.to_datetime(snapshots["timestamp"]).sort_values().unique()
    else:
        snap_ts = pd.to_datetime(snapshots.index).sort_values().unique()

    out: Dict[pd.Timestamp, Dict[str, float]] = {}
    positions: Dict[str, float] = {}
    fill_idx = 0
    n_fills = len(df)

    for ts in snap_ts:
        ts_norm = pd.Timestamp(ts)
        # Apply all fills at or before ts
        while fill_idx < n_fills and df.loc[fill_idx, "timestamp"] <= ts_norm:
            row = df.loc[fill_idx]
            ticker = str(row["ticker"])
            side = str(row["side"]).lower()
            qty = int(row.get("qty", 0))
            if qty <= 0 or not ticker:
                fill_idx += 1
                continue
            cur = positions.get(ticker, 0.0)
            if side == "long":
                cur += qty
            elif side == "short":
                cur -= qty
            elif side == "exit":
                cur = max(0.0, cur - qty) if cur > 0 else cur  # reduce long
            elif side == "cover":
                cur = min(0.0, cur + qty) if cur < 0 else cur  # reduce short
            positions[ticker] = cur
            fill_idx += 1
        out[ts_norm] = {t: q for t, q in positions.items() if q < 0}
    return out


class CostAggregator:
    """Run the three cost layers and produce A/B/C equity curves.

    Construct via config:
        cfg = {
            "alpaca_fees": {"enabled": True, ...},
            "borrow_rate_model": {"enabled": True, ...},
            "tax_drag_model": {"enabled": False, ...},  # opt-in
        }
        agg = CostAggregator(cfg)
        result = agg.compute(snapshots, trades, price_data_map)
    """

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.alpaca_fees: AlpacaFees = get_alpaca_fees(cfg.get("alpaca_fees"))
        self.borrow: BorrowRateModel = get_borrow_rate_model(cfg.get("borrow_rate_model"))
        self.tax: TaxDragModel = get_tax_drag_model(cfg.get("tax_drag_model"))

    def compute(
        self,
        snapshots: pd.DataFrame,
        trades: pd.DataFrame,
        price_data_map: Optional[Mapping[str, pd.DataFrame]] = None,
    ) -> CostAggregatorResult:
        # Build the baseline equity (A) from snapshots
        if "timestamp" in snapshots.columns:
            ts = pd.to_datetime(snapshots["timestamp"])
        else:
            ts = pd.to_datetime(snapshots.index)
        equity_A = pd.Series(
            pd.to_numeric(snapshots["equity"], errors="coerce").values,
            index=ts,
        ).dropna()

        # ----- Total Alpaca fees: sum of per-fill commissions ---------- #
        total_alpaca_fees = 0.0
        if "commission" in trades.columns:
            total_alpaca_fees = float(
                pd.to_numeric(trades["commission"], errors="coerce").fillna(0.0).sum()
            )

        # ----- B: subtract borrow drag --------------------------------- #
        positions_by_ts = _build_short_positions_map(trades, snapshots)
        equity_B = self.borrow.apply_to_equity_curve(
            equity_A, snapshots, price_data_map, positions_by_ts
        )
        total_borrow_drag = float(equity_A.iloc[-1] - equity_B.iloc[-1]) if len(equity_A) and len(equity_B) else 0.0

        # ----- C: subtract tax drag ------------------------------------ #
        equity_C = self.tax.apply_to_equity_curve(
            equity_B,
            self.tax.reconstruct_trades(trades),
        )
        # Re-run pipeline to get yearly breakdown + total
        yearly = {}
        total_tax_drag = 0.0
        if self.tax.config.enabled:
            tax_pipeline = self.tax.compute(trades, equity_B)
            yearly = tax_pipeline["yearly_tax"]
            total_tax_drag = float(tax_pipeline["total_tax"])
        else:
            equity_C = equity_B.copy()

        return CostAggregatorResult(
            equity_A=equity_A,
            equity_B=equity_B,
            equity_C=equity_C,
            sharpe_A=_annualized_sharpe(equity_A),
            sharpe_B=_annualized_sharpe(equity_B),
            sharpe_C=_annualized_sharpe(equity_C),
            cagr_A=_cagr(equity_A),
            cagr_B=_cagr(equity_B),
            cagr_C=_cagr(equity_C),
            max_dd_A=_max_drawdown(equity_A),
            max_dd_B=_max_drawdown(equity_B),
            max_dd_C=_max_drawdown(equity_C),
            total_alpaca_fees=total_alpaca_fees,
            total_borrow_drag=total_borrow_drag,
            total_tax_drag=total_tax_drag,
            yearly_tax_breakdown=yearly,
        )

    @staticmethod
    def result_to_summary_dict(result: CostAggregatorResult) -> dict:
        """JSON-serializable summary, suitable for performance_summary.json."""
        return {
            "cost_completeness_layer_v1": {
                "sharpe_A_baseline": result.sharpe_A,
                "sharpe_B_after_borrow_alpaca": result.sharpe_B,
                "sharpe_C_after_tax": result.sharpe_C,
                "cagr_A_baseline": result.cagr_A,
                "cagr_B_after_borrow_alpaca": result.cagr_B,
                "cagr_C_after_tax": result.cagr_C,
                "max_dd_A_baseline": result.max_dd_A,
                "max_dd_B_after_borrow_alpaca": result.max_dd_B,
                "max_dd_C_after_tax": result.max_dd_C,
                "total_alpaca_fees_usd": result.total_alpaca_fees,
                "total_borrow_drag_usd": result.total_borrow_drag,
                "total_tax_drag_usd": result.total_tax_drag,
                "delta_A_to_B_sharpe": result.sharpe_B - result.sharpe_A,
                "delta_B_to_C_sharpe": result.sharpe_C - result.sharpe_B,
                "yearly_tax_breakdown": {
                    str(k): {kk: float(vv) for kk, vv in v.items()}
                    for k, v in result.yearly_tax_breakdown.items()
                },
            }
        }
