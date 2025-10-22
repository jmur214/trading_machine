# backtester/backtest_controller.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np
import time

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
        batch_flush_interval: int = 500,
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
        self.batch_flush_interval = batch_flush_interval

    # ------------------------------ logging helpers --------------------------- #
    def _log_fill_compat(self, fill: dict, ts):
        """
        Log a trade fill using whichever cockpit logger API is available.

        Tries `log_fill(fill, ts)` first (new API),
        then falls back to `log_trade(fill)` (legacy API),
        and finally to `log` with a dict payload if provided.
        """
        try:
            # Newer API: log_fill(fill_dict, timestamp)
            return self.logger.log_fill(fill, ts)
        except AttributeError:
            pass
        except Exception:
            # If the newer call exists but fails, try legacy below
            pass

        try:
            # Legacy API: log_trade(fill_dict)
            return self.logger.log_trade(fill)
        except AttributeError:
            pass
        except Exception:
            pass

        # Last resort: generic logger.log if present
        try:
            return self.logger.log({"type": "trade_fill", "timestamp": ts, **fill})
        except Exception:
            return None

    def get_portfolio_capital(self):
        """
        Returns portfolio capital, falling back to cash if capital attribute is missing.
        """
        # Debug logging import inline to avoid circular import
        from debug_config import is_debug_enabled
        try:
            return self.portfolio.capital
        except AttributeError:
            if is_debug_enabled("BACKTEST_CONTROLLER"):
                print("[BACKTEST_CONTROLLER][DEBUG] PortfolioEngine has no 'capital' attribute; falling back to 'cash'.")
            return getattr(self.portfolio, "cash", 0.0)

    # ------------------------------- run ------------------------------- #

    def run(self, start: str, end: str):
        from debug_config import is_debug_enabled, is_info_enabled
        import gc
        import threading
        import sys

        # Non-blocking flush helper for logger
        def flush_logger_with_timeout(logger, timeout=5.0):
            """Flush logger, but do not block indefinitely (prevent deadlocks)."""
            result = {"done": False}
            def flush_fn():
                try:
                    logger.flush()
                    result["done"] = True
                except Exception:
                    pass
            t = threading.Thread(target=flush_fn, daemon=True)
            t.start()
            t.join(timeout)
            if not result["done"]:
                if is_debug_enabled("BACKTEST_CONTROLLER"):
                    print("[BACKTEST_CONTROLLER][WARN] Logger flush timed out, continuing anyway.")

        start_dt = pd.to_datetime(start).tz_localize(None)
        end_dt = pd.to_datetime(end).tz_localize(None)
        ts_vec = [ts for ts in self.timestamps if (start_dt <= ts <= end_dt)]

        if len(ts_vec) < 2:
            if is_info_enabled("BACKTEST_CONTROLLER"):
                print("[BACKTEST] Not enough timestamps to run.")
            return self.portfolio.history

        # Initial snapshot at first available bar close
        t0 = ts_vec[0]
        first_prices = {t: float(self.data_map[t].loc[t0]["Close"]) for t in self.data_map if t0 in self.data_map[t].index}
        snap0 = self.portfolio.snapshot(t0, first_prices)
        # Human-friendly count of open positions in snapshot
        snap0["positions"] = sum(1 for p in self.portfolio.positions.values() if p.qty != 0)
        self.logger.log_snapshot(snap0)

        if self.cfg.verbose and is_debug_enabled("BACKTEST_CONTROLLER"):
            print(f"[DEBUG] Starting backtest from {t0} to {ts_vec[-1]} ({len(ts_vec)} bars)")

        total_bars = len(ts_vec) - 1
        equity_cache: Dict[pd.Timestamp, float] = {}

        # Precompute a DataFrame of Close prices for all tickers and all timestamps for vectorized equity
        tickers = list(self.data_map.keys())
        close_price_data = {}
        for tkr in tickers:
            df = self.data_map[tkr]
            # Align df Close prices to ts_vec, reindex with forward fill to handle missing bars
            close_series = df["Close"].reindex(ts_vec, method='ffill')
            close_price_data[tkr] = close_series
        close_prices_df = pd.DataFrame(close_price_data, index=ts_vec)

        start_time = time.time()
        last_checkpoint = start_time
        checkpoint_interval = max(5, self.batch_flush_interval // 2)

        try:
            # Main bar loop (lookahead one bar for fills)
            for i, ts in enumerate(ts_vec[:-1]):
                # Periodic progress report and timing checkpoint
                if i % self.batch_flush_interval == 0 and is_info_enabled("BACKTEST_CONTROLLER"):
                    print(f"[BACKTEST][INFO] Progress: {i}/{total_bars} bars processed...")
                if self.cfg.verbose and is_debug_enabled("BACKTEST_CONTROLLER"):
                    if i % checkpoint_interval == 0 and i > 0:
                        now = time.time()
                        elapsed = now - last_checkpoint
                        print(f"[DEBUG] Loop checkpoint: bar {i}/{total_bars}, {elapsed:.2f}s since last checkpoint, {now - start_time:.2f}s total elapsed.")
                        last_checkpoint = now

                nxt = ts_vec[i + 1]

                # Slice up to current bar ts using shallow slicing
                slice_map: Dict[str, pd.DataFrame] = {}
                for t in tickers:
                    df = self.data_map[t]
                    if ts in df.index:
                        # Use slicing with iloc to avoid deep copies
                        try:
                            idx = df.index.get_loc(ts)
                            slice_map[t] = df.iloc[:idx + 1]
                        except Exception:
                            # fallback safe get
                            slice_map[t] = df.loc[:ts]

                if not slice_map:
                    # Memory cleanup for unused slices
                    if i % self.batch_flush_interval == 0:
                        gc.collect()
                    continue

                # ------------- Engine A: signals at time ts -------------
                try:
                    # Attempt to create unified price matrix for cross-sectional edges
                    combined_prices = pd.DataFrame({t: df["Close"] for t, df in slice_map.items() if not df.empty})
                    if hasattr(self.alpha, "compute_signals"):
                        signals = self.alpha.compute_signals(combined_prices, ts) or []
                    else:
                        signals = self.alpha.generate_signals(slice_map, ts) or []
                except Exception as e:
                    signals = []
                    if is_debug_enabled("BACKTEST_CONTROLLER"):
                        print(f"[DEBUG][{ts}] Alpha signal generation error: {e}")

                if self.cfg.verbose and is_debug_enabled("BACKTEST_CONTROLLER"):
                    print(f"[DEBUG][{ts}] Generated signals: {signals}")

                # Top edge attribution per ticker (if provided via meta.edges_triggered)
                top_edge_by_ticker: Dict[str, str] = {}
                for s in signals:
                    try:
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
                    except Exception:
                        continue

                # ---- Engine B: Risk / Orders ------------------------------------
                orders: List[dict] = []
                target_weights = getattr(self, "target_weights", None)  # for future PortfolioPolicy support

                # Vectorized equity calculation: use cached if available
                if ts in equity_cache:
                    equity = equity_cache[ts]
                else:
                    # Compute portfolio equity at ts efficiently
                    try:
                        pos_qtys = {tkr: int(self.portfolio.positions.get(tkr).qty) if self.portfolio.positions.get(tkr) else 0 for tkr in tickers}
                        pos_values = []
                        for tkr, qty in pos_qtys.items():
                            price = close_prices_df.at[ts, tkr] if tkr in close_prices_df.columns else np.nan
                            if pd.isna(price):
                                price = 0.0
                            pos_values.append(qty * price)
                        equity = self.get_portfolio_capital() + sum(pos_values)
                    except Exception:
                        equity = self.get_portfolio_capital()
                    equity_cache[ts] = equity

                for sig in signals:
                    try:
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
                                if is_debug_enabled("RISK"):
                                    print(f"[RISK][{ts}] {tkr} skipped → {reason}")
                            else:
                                if is_debug_enabled("RISK"):
                                    print(f"[RISK][{ts}] {tkr} skipped (no order).")
                            continue

                        # --- Prevent duplicates / double entries ---
                        if order.get("side") in ("long", "short") and curr_qty != 0:
                            if is_debug_enabled("RISK") or is_info_enabled("RISK"):
                                print(f"[RISK][{ts}] {tkr} already in position; skipping duplicate entry.")
                            continue

                        # --- Edge attribution ---
                        if tkr in top_edge_by_ticker:
                            order["edge"] = top_edge_by_ticker[tkr]

                        orders.append(order)
                    except Exception:
                        continue

                if not orders:
                    if is_debug_enabled("BACKTEST_CONTROLLER"):
                        print(f"[DEBUG][{ts}] No executable orders this bar.")
                else:
                    if is_debug_enabled("BACKTEST_CONTROLLER"):
                        print(f"[DEBUG][{ts}] Orders ready for execution: {orders}")

                # Build next-bar rows with shallow copy and preallocation
                next_rows: Dict[str, pd.Series] = {}
                for t in slice_map:
                    try:
                        df = self.data_map[t]
                        if nxt not in df.index:
                            continue
                        idx = df.index.get_loc(nxt)
                        if isinstance(df.index, (pd.RangeIndex, pd.DatetimeIndex)):
                            row_next = df.iloc[idx]
                            row_next = row_next.copy(deep=False)
                        else:
                            row_next = df.loc[nxt].copy(deep=False)
                        if ts in slice_map[t].index:
                            row_next["PrevClose"] = float(slice_map[t].loc[ts]["Close"])
                        next_rows[t] = row_next
                    except Exception:
                        continue

                # ------------- Execution on next bar (entries/exits) -------------
                for order in orders:
                    try:
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
                            self._log_fill_compat(fill, nxt)
                    except Exception:
                        continue

                # ------------- SL/TP evaluation on next bar -------------
                if self.cfg.eval_stops_after_entry_on_next_bar:
                    for tkr, pos in list(self.portfolio.positions.items()):
                        try:
                            if pos.qty == 0:
                                continue
                            row_next = next_rows.get(tkr)
                            if row_next is None:
                                continue
                            stop_or_tp = self.exec.check_stops_and_targets(tkr, pos, row_next)
                            if stop_or_tp:
                                self.portfolio.apply_fill(stop_or_tp)
                                self._log_fill_compat(stop_or_tp, nxt)
                        except Exception:
                            continue

                # ------------- Snapshot at nxt (using Close map) -------------
                try:
                    close_map_next = {t: _scalar_close(row) for t, row in next_rows.items()}
                    snap = self.portfolio.snapshot(nxt, close_map_next)
                    snap["positions"] = sum(1 for p in self.portfolio.positions.values() if p.qty != 0)
                    self.logger.log_snapshot(snap)
                except Exception:
                    pass

                if self.cfg.verbose and is_debug_enabled("BACKTEST_CONTROLLER"):
                    print(f"[DEBUG][{nxt}] Active positions: {self.portfolio.positions}")

                # Periodic flush of logger and portfolio to reduce memory usage
                if (i + 1) % self.batch_flush_interval == 0:
                    try:
                        flush_logger_with_timeout(self.logger, timeout=5.0)
                    except Exception as e:
                        if is_debug_enabled("BACKTEST_CONTROLLER"):
                            print(f"[BACKTEST_CONTROLLER][WARN] Failed to flush logger at bar {i+1}: {e}")
                    # Periodic memory cleanup and yield CPU
                    gc.collect()
                    if hasattr(time, "sleep"):
                        time.sleep(0)  # Yield CPU time to other threads/processes
                elif (i + 1) % (self.batch_flush_interval // 4) == 0:
                    # More frequent lightweight memory cleanup
                    gc.collect()
                    if hasattr(time, "sleep"):
                        time.sleep(0)

        except KeyboardInterrupt:
            if is_info_enabled("BACKTEST_CONTROLLER"):
                print("[BACKTEST] Backtest interrupted by user. Flushing and exiting cleanly...")
            try:
                flush_logger_with_timeout(self.logger, timeout=10.0)
            except Exception:
                pass
            try:
                self.logger.close()
            except Exception:
                pass
            # Attempt to join flush threads if any
            for thread in threading.enumerate():
                if thread is not threading.current_thread() and thread.daemon:
                    try:
                        thread.join(timeout=2.0)
                    except Exception:
                        pass
            return self.portfolio.history
        except Exception as e:
            if is_debug_enabled("BACKTEST_CONTROLLER"):
                print(f"[BACKTEST] Unexpected error during backtest: {e}")

        # Final flush and summary
        try:
            flush_logger_with_timeout(self.logger, timeout=10.0)
        except Exception as e:
            if is_debug_enabled("BACKTEST_CONTROLLER"):
                print(f"[BACKTEST_CONTROLLER][WARN] Failed to flush logger at end: {e}")

        # Ensure logger background thread is stopped and buffers are flushed
        try:
            self.logger.close()
        except Exception:
            pass

        elapsed = time.time() - start_time
        if self.cfg.verbose and is_debug_enabled("BACKTEST_CONTROLLER"):
            print(f"[DEBUG] Backtest complete. Total bars processed: {total_bars}, Elapsed time: {elapsed:.2f} seconds.")
            print(f"[DEBUG] Total snapshots logged: {len(self.portfolio.history)}")

        return self.portfolio.history