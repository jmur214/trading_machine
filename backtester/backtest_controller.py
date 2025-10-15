# backtester/backtest_controller.py
from typing import Dict
import pandas as pd

from backtester.execution_simulator import ExecutionSimulator
from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine


def _to_naive_datetime_index(idx: pd.Index) -> pd.DatetimeIndex:
    """Coerce any index to tz-naive DatetimeIndex."""
    di = pd.to_datetime(idx, errors="coerce")
    # Drop tz if present
    try:
        di = di.tz_localize(None)
    except Exception:
        pass
    return di


def _scalar_close(row_or_series) -> float:
    """
    Return a float Close price from either a Series (single row)
    or a DataFrame row selection (possibly 1-row DataFrame).
    """
    if isinstance(row_or_series, pd.Series):
        # typical case: row is a Series with 'Close'
        return float(row_or_series["Close"])
    # otherwise it's a DataFrame slice
    return float(row_or_series["Close"].iloc[0])


def _scalar_open(row_or_series) -> float:
    if isinstance(row_or_series, pd.Series):
        return float(row_or_series["Open"])
    return float(row_or_series["Open"].iloc[0])


class BacktestController:
    def __init__(
        self,
        data_map: Dict[str, pd.DataFrame],
        alpha_engine,
        risk_engine,
        cockpit_logger,
        exec_params: dict,
        initial_capital: float,
    ):
        # Normalize all dataframes (tz-naive, datetime index, sorted)
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

        # Use UNION of timestamps so a missing bar on one ticker doesn't zero out the run
        all_sets = [set(df.index) for df in self.data_map.values() if not df.empty]
        self.timestamps = sorted(set().union(*all_sets)) if all_sets else []

    def run(self, start: str, end: str):
        start_dt = pd.to_datetime(start).tz_localize(None)
        end_dt = pd.to_datetime(end).tz_localize(None)

        # Filter timestamps by date range
        timestamps = [ts for ts in self.timestamps if (start_dt <= ts <= end_dt)]
        if len(timestamps) < 2:
            print("Not enough timestamps to run backtest.")
            return self.portfolio.history

        for i, ts in enumerate(timestamps[:-1]):  # exclude last, we fill at next open
            next_ts = timestamps[i + 1]

            # Build full data slice up to ts (for indicators) per ticker that has ts
            data_slice_full = {
                t: df.loc[:ts] for t, df in self.data_map.items() if ts in df.index
            }
            if not data_slice_full:
                continue

            # Engine A → candidate signals
            signals = self.alpha.generate_signals(data_slice_full, ts)

            # Equity (use last close at ts for each ticker present)
            last_prices_at_ts = {}
            for t, df_hist in data_slice_full.items():
                row = df_hist.loc[ts]
                last_prices_at_ts[t] = _scalar_close(row)
            equity = self.portfolio.total_equity(last_prices_at_ts)

            # Engine B → orders
            orders = []
            for sig in signals:
                tkr = sig["ticker"]
                order = self.risk.prepare_order(sig, equity, data_slice_full[tkr])
                if order:
                    orders.append(order)

            # Prepare next-bar rows for fills (only tickers that have next_ts)
            next_rows = {
                t: self.data_map[t].loc[next_ts]
                for t in data_slice_full
                if next_ts in self.data_map[t].index
            }

            # Simulate fills
            fills = []
            for order in orders:
                tkr = order["ticker"]
                if tkr not in next_rows:
                    continue
                fill = self.exec.fill_at_next_open(order, next_rows[tkr])
                if not fill:
                    continue

                # --- NEW: enforce capital constraints ---
                fill_price = fill.get("price") or fill.get("fill_price")
                fill_qty = fill.get("qty", 0)
                fill_side = str(fill.get("side", "")).lower()
                fill_cost = fill_price * fill_qty

                # Skip if not enough cash for long trades
                if fill_side == "long" and fill_cost > self.portfolio.cash:
                    print(
                        f"[PORTFOLIO][SKIP] Not enough cash for {tkr} "
                        f"(need {fill_cost:.2f}, have {self.portfolio.cash:.2f})"
                    )
                    continue

                # Apply fill to portfolio
                self.portfolio.apply_fill(fill)
                self.logger.log_fill(fill, next_ts)
                fills.append(fill)

            # Snapshot portfolio at next_ts using next bar's Close
            last_prices_next = {}
            for t in data_slice_full:
                if t in next_rows:
                    last_prices_next[t] = _scalar_close(next_rows[t])

            snap = self.portfolio.snapshot(next_ts, last_prices_next)
            snap["n_positions"] = len(self.portfolio.positions)

            # --- NEW: Log equity/cash live ---
            print(
                f"[PORTFOLIO][DEBUG] {next_ts} | cash={self.portfolio.cash:.2f} | "
                f"equity={snap['equity']:.2f} | pos={snap['n_positions']}"
            )

            self.logger.log_snapshot(snap)

        return self.portfolio.history