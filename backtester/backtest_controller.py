# backtester/backtest_controller.py

from __future__ import annotations
from typing import Dict, List
import pandas as pd

from backtester.execution_simulator import ExecutionSimulator
from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine


def _to_naive_datetime_index(idx: pd.Index) -> pd.DatetimeIndex:
    di = pd.to_datetime(idx, errors="coerce")
    try:
        di = di.tz_localize(None)
    except Exception:
        pass
    return di


def _scalar_close(row_or_series) -> float:
    if isinstance(row_or_series, pd.Series):
        return float(row_or_series["Close"])
    return float(row_or_series["Close"].iloc[0])


class BacktestController:
    """
    Orchestrates Alpha -> Risk -> Execution -> Portfolio for historical bars.

    Realism points:
      - No auto-exit each bar. Positions persist until exit signal or stop/TP hit.
      - Entries/exits fill at NEXT open (with slippage/commission).
      - Stops/TPs trigger on the bar's High/Low at the stop/tp level (with slippage).
    """

    def __init__(
        self,
        data_map: Dict[str, pd.DataFrame],
        alpha_engine,
        risk_engine,
        cockpit_logger,
        exec_params: dict,
        initial_capital: float,
    ):
        # Normalize data
        self.data_map: Dict[str, pd.DataFrame] = {}
        for t, df in data_map.items():
            df = df.copy()
            df.index = _to_naive_datetime_index(df.index)
            df = df.sort_index()
            self.data_map[t] = df

        self.alpha = alpha_engine
        self.risk = risk_engine
        self.logger = cockpit_logger
        self.exec = ExecutionSimulator(
            slippage_bps=exec_params.get("slippage_bps", 10.0),
            commission=exec_params.get("commission", 0.0),
        )
        self.portfolio = PortfolioEngine(initial_capital)

        # make logger aware of the portfolio
        self.logger.portfolio = self.portfolio

        # let RiskEngine see current positions/exposure for constraints
        try:
            self.risk.portfolio = self.portfolio  # type: ignore[attr-defined]
        except Exception:
            pass

        all_sets = [set(df.index) for df in self.data_map.values() if not df.empty]
        self.timestamps = sorted(set().union(*all_sets)) if all_sets else []

    def run(self, start: str, end: str):
        start_dt = pd.to_datetime(start).tz_localize(None)
        end_dt = pd.to_datetime(end).tz_localize(None)
        timestamps = [ts for ts in self.timestamps if (start_dt <= ts <= end_dt)]

        if len(timestamps) < 2:
            print("Not enough timestamps to run backtest.")
            return self.portfolio.history

        # Snapshot at the first bar
        t0 = timestamps[0]
        first_prices = {t: float(df.loc[t0]["Close"]) for t, df in self.data_map.items() if t0 in df.index}
        init_snap = self.portfolio.snapshot(t0, first_prices)
        init_snap["positions"] = sum(1 for p in self.portfolio.positions.values() if p.qty != 0)
        self.logger.log_snapshot(init_snap)

        print(f"[DEBUG] Starting backtest from {t0} to {timestamps[-1]}, {len(timestamps)} total bars")

        for i, ts in enumerate(timestamps[:-1]):
            next_ts = timestamps[i + 1]

            # Slice up to current bar
            data_slice_full = {t: df.loc[:ts] for t, df in self.data_map.items() if ts in df.index}
            if not data_slice_full:
                continue

            # ---- Engine A: Signals
            signals = self.alpha.generate_signals(data_slice_full, ts) or []

            # Attribution: top edge per ticker if provided
            top_edge_by_ticker: Dict[str, str] = {}
            for s in signals:
                contrib = (s.get("meta", {}) or {}).get("edges_triggered", [])
                if contrib:
                    top = max(contrib, key=lambda c: abs(float(c.get("signal", 0.0)) * float(c.get("weight", 0.0))))
                    top_edge_by_ticker[s["ticker"]] = str(top.get("edge", "Unknown"))
                else:
                    top_edge_by_ticker[s["ticker"]] = "Unknown"

            # Equity at ts
            last_prices_at_ts = {t: _scalar_close(df.loc[ts]) for t, df in data_slice_full.items()}
            equity = self.portfolio.total_equity(last_prices_at_ts)

            # ---- Engine B: Risk / Orders
            orders: List[dict] = []
            for sig in signals:
                tkr = sig["ticker"]
                pos = self.portfolio.positions.get(tkr)
                curr_qty = 0 if (pos is None) else int(pos.qty)

                order = self.risk.prepare_order(sig, equity, data_slice_full[tkr], current_qty=curr_qty)
                if not order:
                    continue

                # avoid multiple adds on same side in same bar
                if order.get("side") in ("long", "short") and curr_qty != 0:
                    continue

                if tkr in top_edge_by_ticker:
                    order["edge"] = top_edge_by_ticker[tkr]
                orders.append(order)

            if not orders:
                print(f"[DEBUG][{ts}] No orders generated by risk engine.")
            else:
                print(f"[DEBUG][{ts}] Orders ready for execution: {orders}")

            # Next bar rows
            next_rows = {
                t: self.data_map[t].loc[next_ts]
                for t in data_slice_full
                if next_ts in self.data_map[t].index
            }

            # ---- Fill entries/exits at next open
            for order in orders:
                tkr = order["ticker"]
                if tkr not in next_rows:
                    continue
                fill = self.exec.fill_at_next_open(order, next_rows[tkr])
                if fill:
                    self.portfolio.apply_fill(fill)
                    self.logger.log_fill(fill, next_ts)

            # ---- Check SL/TP on next bar
            for ticker, pos in list(self.portfolio.positions.items()):
                if pos.qty == 0 or ticker not in next_rows:
                    continue
                stop_or_tp_fill = self.exec.check_stops_and_targets(ticker, pos, next_rows[ticker])
                if stop_or_tp_fill:
                    self.portfolio.apply_fill(stop_or_tp_fill)
                    self.logger.log_fill(stop_or_tp_fill, next_ts)

            # ---- Snapshot
            last_prices_next = {t: _scalar_close(next_rows[t]) for t in next_rows}
            snap = self.portfolio.snapshot(next_ts, last_prices_next)
            snap["positions"] = sum(1 for p in self.portfolio.positions.values() if p.qty != 0)
            self.logger.log_snapshot(snap)

            print(f"[DEBUG][{next_ts}] Active positions: {self.portfolio.positions}")

        print(f"[DEBUG] Backtest complete. Total snapshots logged: {len(self.portfolio.history)}")
        return self.portfolio.history