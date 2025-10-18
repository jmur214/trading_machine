# backtester/backtest_controller.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
import pandas as pd

from backtester.execution_simulator import ExecutionSimulator, ExecParams
from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine


# ------------------------------ helpers ------------------------------ #

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


def _safe_get_bar(df: pd.DataFrame, ts) -> Optional[pd.Series]:
    """Return df.loc[ts] as a Series or None if missing."""
    try:
        if ts in df.index:
            row = df.loc[ts]
            # If it's a DataFrame slice (duplicate index), take the last row deterministically
            if isinstance(row, pd.DataFrame):
                row = row.iloc[-1]
            return row
    except Exception:
        return None
    return None


# ------------------------------ config ------------------------------- #

@dataclass
class BacktestParams:
    """
    Controls bits of realism & log verbosity for the backtest orchestration.

    eval_stops_after_entry_on_next_bar:
        True => (Default) Fill entries/exits at next bar *open*, then check SL/TP
        intrabar using that same bar's High/Low (conservative intrabar tie-break
        is handled in ExecutionSimulator).
    verbose:
        Print debug lines (orders, snapshots, active positions).
    """
    eval_stops_after_entry_on_next_bar: bool = True
    verbose: bool = True


# ------------------------------ controller --------------------------- #

class BacktestController:
    """
    Orchestrates Alpha -> Risk -> Execution -> Portfolio over historical bars.

    Sequencing per bar (t -> t+1):
      1) At time t, build 'slice_map' of history up to t and call AlphaEngine.generate_signals(slice_map, t).
      2) Compute equity at t, ask RiskEngine for orders (including exits/flip exits).
      3) On next bar (t+1):
           a) Fill entries/exits at the next Open (with slippage/commission).
           b) Evaluate SL/TP *intrabar* using next bar High/Low (with conservative tie-break).
           c) Snapshot portfolio at t+1 (Close price map used for equity).

    Notes:
      - Positions persist; there is no forced daily exit.
      - Orders are de-duplicated per ticker per bar. Exits have priority over opens.
      - 'edge' attribution is propagated into fills (and thus into cockpit trades).
      - We pass PrevClose (from bar t) along with the next bar into the execution simulator,
        enabling realistic gap warnings without affecting fills.
    """

    def __init__(
        self,
        data_map: Dict[str, pd.DataFrame],
        alpha_engine,
        risk_engine,
        cockpit_logger,
        exec_params: Dict[str, Any],
        initial_capital: float,
        bt_params: Optional[BacktestParams] = None,
    ):
        # Normalize data
        self.data_map: Dict[str, pd.DataFrame] = {}
        for t, df in data_map.items():
            if df is None or df.empty:
                continue
            _df = df.copy()
            _df.index = _to_naive_datetime_index(_df.index)
            _df = _df.sort_index()
            # Ensure required columns exist
            for col in ("Open", "High", "Low", "Close"):
                if col not in _df.columns:
                    raise KeyError(f"[BACKTEST] Ticker {t} frame missing required column '{col}'.")
            self.data_map[t] = _df

        self.alpha = alpha_engine
        self.risk = risk_engine
        self.logger = cockpit_logger
        self.portfolio = PortfolioEngine(initial_capital)

        # Execution simulator with sane defaults (can be overridden via exec_params)
        self.exec = ExecutionSimulator(
            slippage_bps=float(exec_params.get("slippage_bps", 10.0)),
            commission=float(exec_params.get("commission", 0.0)),
            # Extra realism switches are available via ExecParams; keep defaults here
        )

        # Make logger aware of portfolio (some loggers compute equity diffs)
        self.logger.portfolio = self.portfolio

        # Let RiskEngine inspect live exposure/positions if it supports it
        try:
            self.risk.portfolio = self.portfolio  # type: ignore[attr-defined]
        except Exception:
            pass

        # Build unified timestamp vector
        all_sets = [set(df.index) for df in self.data_map.values() if not df.empty]
        self.timestamps: List[pd.Timestamp] = sorted(set().union(*all_sets)) if all_sets else []

        self.cfg = bt_params or BacktestParams()

    # ------------------------------- run ------------------------------- #

    def run(self, start: str, end: str):
        start_dt = pd.to_datetime(start).tz_localize(None)
        end_dt = pd.to_datetime(end).tz_localize(None)
        ts_vec = [ts for ts in self.timestamps if (start_dt <= ts <= end_dt)]

        if len(ts_vec) < 2:
            print("[BACKTEST] Not enough timestamps to run.")
            return self.portfolio.history

        # Initial snapshot at first available bar close
        t0 = ts_vec[0]
        first_prices = {t: float(self.data_map[t].loc[t0]["Close"]) for t in self.data_map if t0 in self.data_map[t].index}
        snap0 = self.portfolio.snapshot(t0, first_prices)
        # Human-friendly count of open positions in snapshot
        snap0["positions"] = sum(1 for p in self.portfolio.positions.values() if p.qty != 0)
        self.logger.log_snapshot(snap0)

        if self.cfg.verbose:
            print(f"[DEBUG] Starting backtest from {t0} to {ts_vec[-1]} ({len(ts_vec)} bars)")

        # Main bar loop (lookahead one bar for fills)
        for i, ts in enumerate(ts_vec[:-1]):
            nxt = ts_vec[i + 1]

            # Slice up to current bar ts
            slice_map: Dict[str, pd.DataFrame] = {}
            for t, df in self.data_map.items():
                if ts in df.index:
                    slice_map[t] = df.loc[:ts]

            if not slice_map:
                continue


            # ------------- Engine A: signals at time ts -------------
            signals = self.alpha.generate_signals(slice_map, ts) or []
            if self.cfg.verbose:
                print(f"[DEBUG][{ts}] Signals: {signals}")
                
            # Top edge attribution per ticker (if provided via meta.edges_triggered)
            top_edge_by_ticker: Dict[str, str] = {}
            for s in signals:
                if not isinstance(s, dict) or "ticker" not in s:
                    continue
                contrib = (s.get("meta", {}) or {}).get("edges_triggered", [])
                if contrib:
                    # strongest by |signal*weight|
                    top = max(
                        contrib,
                        key=lambda c: abs(float(c.get("signal", 0.0)) * float(c.get("weight", 0.0)))
                    )
                    top_edge_by_ticker[s["ticker"]] = str(top.get("edge", "Unknown"))
                else:
                    top_edge_by_ticker[s["ticker"]] = "Unknown"

            # Equity at ts (close-to-close accounting)
            last_prices_ts = {t: _scalar_close(df.loc[ts]) for t, df in slice_map.items()}
            equity = self.portfolio.total_equity(last_prices_ts)

            # ---- Engine B: Risk / Orders ------------------------------------
            orders: List[dict] = []
            target_weights = getattr(self, "target_weights", None)  # for future PortfolioPolicy support

            for sig in signals:
                tkr = sig.get("ticker")
                if not tkr or tkr not in slice_map:
                    continue

                pos = self.portfolio.positions.get(tkr)
                curr_qty = 0 if pos is None else int(pos.qty)

                order = self.risk.prepare_order(
                    signal=sig,
                    equity=equity,
                    df_hist=slice_map[tkr],
                    current_qty=curr_qty,
                    target_weights=target_weights,
                )

                # --- Skip logic & debug tracing ---
                if not order:
                    reason = getattr(self.risk, "last_skip_by_ticker", {}).get(tkr)
                    if reason:
                        print(f"[RISK][{ts}] {tkr} skipped → {reason}")
                    else:
                        print(f"[RISK][{ts}] {tkr} skipped (no order).")
                    continue

                # --- Prevent duplicates / double entries ---
                if order.get("side") in ("long", "short") and curr_qty != 0:
                    print(f"[RISK][{ts}] {tkr} already in position; skipping duplicate entry.")
                    continue

                # --- Edge attribution ---
                if tkr in top_edge_by_ticker:
                    order["edge"] = top_edge_by_ticker[tkr]

                orders.append(order)

            if not orders:
                print(f"[DEBUG][{ts}] No executable orders this bar.")
            else:
                print(f"[DEBUG][{ts}] Orders ready for execution: {orders}")

            # Build next-bar rows
            next_rows: Dict[str, pd.Series] = {}
            for t in slice_map:
                if nxt not in self.data_map[t].index:
                    continue
                row_next = self.data_map[t].loc[nxt].copy()
                if ts in slice_map[t].index:
                    row_next["PrevClose"] = float(slice_map[t].loc[ts]["Close"])
                next_rows[t] = row_next

            # ------------- Execution on next bar (entries/exits) -------------
            for order in orders:
                tkr = order["ticker"]
                row_next = next_rows.get(tkr)
                if row_next is None:
                    continue
                fill = self.exec.fill_at_next_open(order, row_next)
                if fill:
                    # --- Propagate edge attribution into the fill ---
                    fill["edge"] = order.get("edge", "Unknown")
                    fill["edge_group"] = order.get("edge_group", None)

                    self.portfolio.apply_fill(fill)
                    self.logger.log_fill(fill, nxt)

            # ------------- SL/TP evaluation on next bar -------------
            if self.cfg.eval_stops_after_entry_on_next_bar:
                for tkr, pos in list(self.portfolio.positions.items()):
                    if pos.qty == 0:
                        continue
                    row_next = next_rows.get(tkr)
                    if row_next is None:
                        continue
                    stop_or_tp = self.exec.check_stops_and_targets(tkr, pos, row_next)
                    if stop_or_tp:
                        self.portfolio.apply_fill(stop_or_tp)
                        self.logger.log_fill(stop_or_tp, nxt)

            # ------------- Snapshot at nxt (using Close map) -------------
            close_map_next = {t: _scalar_close(row) for t, row in next_rows.items()}
            snap = self.portfolio.snapshot(nxt, close_map_next)
            snap["positions"] = sum(1 for p in self.portfolio.positions.values() if p.qty != 0)
            self.logger.log_snapshot(snap)

            if self.cfg.verbose:
                print(f"[DEBUG][{nxt}] Active positions: {self.portfolio.positions}")

        if self.cfg.verbose:
            print(f"[DEBUG] Backtest complete. Total snapshots logged: {len(self.portfolio.history)}")
        return self.portfolio.history