from typing import Dict
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

        all_sets = [set(df.index) for df in self.data_map.values() if not df.empty]
        self.timestamps = sorted(set().union(*all_sets)) if all_sets else []

    def run(self, start: str, end: str):
        start_dt = pd.to_datetime(start).tz_localize(None)
        end_dt = pd.to_datetime(end).tz_localize(None)
        timestamps = [ts for ts in self.timestamps if (start_dt <= ts <= end_dt)]

        if len(timestamps) < 2:
            print("Not enough timestamps to run backtest.")
            return self.portfolio.history

        # ✅ Log initial snapshot before trading begins
        first_prices = {t: df["Close"].iloc[0] for t, df in self.data_map.items() if not df.empty}
        init_snap = self.portfolio.snapshot(start_dt, first_prices)
        init_snap["positions"] = len(self.portfolio.positions)
        self.logger.log_snapshot(init_snap)

        # Main backtest loop
        for i, ts in enumerate(timestamps[:-1]):
            next_ts = timestamps[i + 1]
            data_slice_full = {t: df.loc[:ts] for t, df in self.data_map.items() if ts in df.index}
            if not data_slice_full:
                continue

            # Engine A
            signals = self.alpha.generate_signals(data_slice_full, ts)

            # Portfolio equity
            last_prices_at_ts = {t: _scalar_close(df.loc[ts]) for t, df in data_slice_full.items()}
            equity = self.portfolio.total_equity(last_prices_at_ts)

            # Engine B
            orders = []
            for sig in signals:
                tkr = sig["ticker"]
                order = self.risk.prepare_order(sig, equity, data_slice_full[tkr])
                if order:
                    orders.append(order)

            next_rows = {
                t: self.data_map[t].loc[next_ts]
                for t in data_slice_full
                if next_ts in self.data_map[t].index
            }

            # Fill orders
            for order in orders:
                tkr = order["ticker"]
                if tkr not in next_rows:
                    continue
                fill = self.exec.fill_at_next_open(order, next_rows[tkr])
                if fill:
                    self.portfolio.apply_fill(fill)
                    self.logger.log_fill(fill, next_ts)

            # Check for exits
            for ticker, pos in list(self.portfolio.positions.items()):
                if ticker not in next_rows:
                    continue
                if not any(o["ticker"] == ticker for o in orders):
                    exit_fill = self.exec.exit_position(ticker, pos, next_rows[ticker])
                    if exit_fill:
                        self.portfolio.apply_fill(exit_fill)
                        self.logger.log_fill(exit_fill, next_ts)

            # ✅ Log snapshot at every bar
            last_prices_next = {t: _scalar_close(next_rows[t]) for t in next_rows}
            snap = self.portfolio.snapshot(next_ts, last_prices_next)
            snap["positions"] = len([p for p in self.portfolio.positions.values() if p.qty != 0])
            self.logger.log_snapshot(snap)

        return self.portfolio.history