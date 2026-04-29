# backtester/backtest_controller.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Any, Optional
import pandas as pd
import numpy as np
import time

from backtester.execution_simulator import ExecutionSimulator, ExecParams
import math
from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine
from debug_config import is_debug_enabled, is_info_enabled

def is_controller_debug():
    return is_debug_enabled("BACKTEST_CONTROLLER")

def is_controller_info():
    return is_info_enabled("BACKTEST_CONTROLLER")


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
        portfolio_cfg: Optional[Any] = None,
        regime_detector=None,
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
        self.run_id = getattr(self.logger, "run_id", None)
        self.portfolio = PortfolioEngine(initial_capital, policy_cfg=portfolio_cfg)
        # Store initial capital for later use
        self.initial_capital = float(initial_capital)
        # Ensure portfolio capital and cash are set to initial_capital if <= 0
        if float(getattr(self.portfolio, "capital", 0.0)) <= 0.0:
            self.portfolio.capital = self.initial_capital
        if hasattr(self.portfolio, "cash") and float(getattr(self.portfolio, "cash", 0.0)) <= 0.0:
            self.portfolio.cash = self.initial_capital
        # Defensive attach of portfolio to logger (reset first to avoid stale refs)
        if hasattr(self.logger, "set_portfolio"):
            try:
                self.logger.set_portfolio(None)  # reset first to avoid stale refs
                self.logger.set_portfolio(self.portfolio)
            except Exception:
                pass

        # Execution simulator with sane defaults (can be overridden via exec_params).
        # `slippage_model` selects between fixed (legacy), volatility, and
        # realistic (ADV-bucketed half-spread + Almgren-Chriss impact). The
        # realistic model honors `slippage_extra` for its specific knobs:
        # impact_coefficient, mega_cap_threshold_usd, etc.
        self.exec = ExecutionSimulator(
            slippage_bps=float(exec_params.get("slippage_bps", 10.0)),
            slippage_model=str(exec_params.get("slippage_model", "fixed")),
            commission=float(exec_params.get("commission", 0.0)),
            slippage_extra=exec_params.get("slippage_extra"),
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
        # Robustness: check if data_map is empty or invalid after constructing self.timestamps
        if not self.data_map or not self.timestamps:
            raise ValueError("[BACKTEST] Initialization error: data_map is empty or contains no valid bars after normalization. Check data sources, API keys, or data integrity.")

        self.cfg = bt_params or BacktestParams()
        self.batch_flush_interval = batch_flush_interval
        self.regime_detector = regime_detector
        
        # Load Signal Gate (AI Brain)
        try:
             from engines.engine_a_alpha.learning.signal_gate import SignalGate
             self.signal_gate = SignalGate()
             self.signal_gate.load()
        except Exception as e:
             if is_debug_enabled("BACKTEST_CONTROLLER"):
                 print(f"[BACKTEST] Could not load SignalGate: {e}")
             self.signal_gate = None

    # ------------------------------ logging helpers --------------------------- #
    def _log_fill_compat(self, fill: dict, ts):
        """
        Log a trade fill using whichever cockpit logger API is available.

        Tries `log_fill(fill, ts)` first (new API),
        then falls back to `log_trade(fill)` (legacy API),
        and finally to `log` with a dict payload if provided.
        If all else fails, writes directly to trades.csv via _safe_write_trade.
        """
        try:
            return self.logger.log_fill(fill, ts)
        except AttributeError:
            pass
        except Exception:
            pass

        try:
            return self.logger.log_trade(fill)
        except AttributeError:
            pass
        except Exception:
            pass

        try:
            return self.logger.log({"type": "trade_fill", "timestamp": ts, **fill})
        except Exception:
            # Last resort: write the CSV directly to preserve the fill
            try:
                self._safe_write_trade(fill, ts)
                return True
            except Exception:
                return None

    def _safe_write_trade(self, fill: dict, ts):
        """
        Append a trade fill to trades.csv, ensuring directory and header.
        Includes edge_id and edge_category if present.
        """
        import os
        import csv
        # Prefer cockpit logger's resolved paths if available
        logger_trade_path = getattr(self.logger, "trade_path", None)
        logger_out_dir = getattr(self.logger, "out_dir", None)
        if logger_trade_path:
            trades_path = str(logger_trade_path)
        else:
            # Fallback to legacy flat path
            root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            logs_dir = os.path.join(root, "data", "trade_logs")
            os.makedirs(logs_dir, exist_ok=True)
            trades_path = os.path.join(logs_dir, "trades.csv")
        # Ensure directory exists if we didn't already
        os.makedirs(os.path.dirname(trades_path), exist_ok=True)
        # normalize price keys for downstream consumers
        price_val = fill.get("fill_price", fill.get("price", ""))
        row = {
            "timestamp": str(ts),
            "ticker": fill.get("ticker", ""),
            "side": fill.get("side", ""),
            "qty": fill.get("qty", ""),
            "fill_price": price_val,
            "commission": fill.get("commission", 0.0),
            "pnl": fill.get("pnl", ""),
            "edge": fill.get("edge", ""),
            "edge_group": fill.get("edge_group", ""),
            "trigger": fill.get("trigger", ""),
            "meta": fill.get("meta", ""),
            "edge_id": fill.get("edge_id", ""),
            "edge_category": fill.get("edge_category", ""),
            "run_id": getattr(self, "run_id", None) or getattr(self.logger, "run_id", None) or "",
            "regime_label": fill.get("regime_label", ""),
        }
        header = [
            "timestamp", "ticker", "side", "qty", "fill_price", "commission", "pnl",
            "edge", "edge_group", "trigger", "meta", "edge_id", "edge_category", "run_id",
            "regime_label"
        ]
        # Check if file exists
        write_header = not os.path.exists(trades_path)
        try:
            with open(trades_path, "a", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=header)
                if write_header:
                    writer.writeheader()
                writer.writerow(row)
        except Exception:
            pass

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

    # ----------------------- side normalization map ---------------------- #
    SIDE_MAP = {
        "buy": "long",
        "sell": "exit",
        "sell_short": "short",
        "short": "short",
        "buy_to_cover": "cover",
        "cover": "cover",
    }

    # ----------------------- extracted private methods ------------------- #

    def _detect_regime(self, ts, slice_map):
        """[ENGINE E] Regime detection -- once per bar, before Alpha and Risk."""
        regime_meta = None
        if self.regime_detector is not None:
            try:
                benchmark_ticker = getattr(self.regime_detector, 'cfg', None)
                benchmarks = getattr(benchmark_ticker, 'benchmarks', ['SPY']) if benchmark_ticker else ['SPY']
                bm_ticker = benchmarks[0] if benchmarks else 'SPY'
                bm_df = slice_map.get(bm_ticker)
                if bm_df is not None and not bm_df.empty:
                    regime_meta = self.regime_detector.detect_regime(
                        bm_df, data_map=slice_map, now=str(ts)
                    )
            except Exception as e:
                if is_debug_enabled("BACKTEST_CONTROLLER"):
                    print(f"[BACKTEST][WARN] Regime detection failed at {ts}: {e}")

        # Inject learned edge affinity from Governor's regime tracker.
        # Gated by governor config flag `learned_affinity_enabled` (default True
        # for backward compat) so we can A/B it against baseline. When the
        # regime_tracker signal itself is unreliable (see 2026-04-23 walk-forward
        # findings), disabling this removes a noisy signal-scaler from the path.
        if regime_meta and hasattr(self, 'alpha') and self.alpha is not None:
            governor = getattr(self.alpha, 'governor', None)
            if governor is not None:
                affinity_enabled = getattr(governor.cfg, 'learned_affinity_enabled', True) if hasattr(governor, 'cfg') else True
                tracker = getattr(governor, 'regime_tracker', None)
                if tracker is not None and affinity_enabled:
                    macro = regime_meta.get("macro_regime")
                    if isinstance(macro, dict):
                        label = macro.get("label", "transitional")
                    elif isinstance(macro, str):
                        label = macro
                    else:
                        label = "transitional"
                    learned = tracker.get_learned_affinity(label)
                    if learned:
                        regime_meta.setdefault("advisory", {})["learned_edge_affinity"] = learned

        return regime_meta

    def _update_trailing_stops(self, slice_map, regime_meta):
        """[SMART SHIELD] Manage existing positions (Trailing Stops)."""
        if hasattr(self.risk, "manage_positions"):
            try:
                # Construct current price map for risk manager
                # We use 'ts' (current bar close) as the reference price
                current_prices = {}
                for t, df_slice in slice_map.items():
                    if not df_slice.empty:
                        current_prices[t] = float(df_slice.iloc[-1]["Close"])

                updates = self.risk.manage_positions(current_prices, regime_meta=regime_meta, data_map=slice_map)
                for upd in updates:
                    tkr = upd.get("ticker")
                    new_stop = upd.get("new_stop")
                    if tkr and new_stop is not None:
                        pos = self.portfolio.positions.get(tkr)
                        if pos:
                            old_stop = pos.stop
                            pos.stop = new_stop
                            if is_debug_enabled("BACKTEST_CONTROLLER"):
                                print(f"[SMART_SHIELD] Trailing Stop Update for {tkr}: {old_stop} -> {new_stop}")
            except Exception as e:
                if is_debug_enabled("BACKTEST_CONTROLLER"):
                    print(f"[BACKTEST][WARN] Trailing stop update failed: {e}")

    def _generate_signals(self, ts, slice_map, regime_meta, BACKTEST_DEBUG):
        """Engine A: signal generation + signal gate + bagholder protection."""
        # ------------- Engine A: signals at time ts -------------
        signals = []
        try:
            # Attempt to create unified price matrix for cross-sectional edges
            combined_prices = pd.DataFrame({t: df["Close"] for t, df in slice_map.items() if not df.empty})
            if hasattr(self.alpha, "compute_signals"):
                signals = self.alpha.compute_signals(combined_prices, ts) or []
                # fallback if compute_signals returns nothing
                if not signals:
                    signals = self.alpha.generate_signals(slice_map, ts, regime_meta=regime_meta) or []
            else:
                signals = self.alpha.generate_signals(slice_map, ts, regime_meta=regime_meta) or []
        except Exception as e:
            signals = []
            if is_debug_enabled("BACKTEST_CONTROLLER"):
                print(f"[DEBUG][{ts}] Alpha signal generation error: {e}")

        if BACKTEST_DEBUG and signals:
            print(f"[DEBUG_BACKTEST][{ts}] Raw signals: {signals[:3]}")

        if self.cfg.verbose and is_debug_enabled("BACKTEST_CONTROLLER"):
            print(f"[DEBUG][{ts}] Generated signals: {signals}")

        # [SIGNAL GATE] AI Filter based on trained regime model
        # This applies "learned" wisdom to block bad signals
        if hasattr(self, "signal_gate") and self.signal_gate and signals:
             try:
                 # We need a data interface for the gate. It expects {ticker: dataframe_history}
                 # slice_map is exactly that.
                 filtered_signals = self.signal_gate.predict(signals, slice_map)
                 if len(filtered_signals) < len(signals):
                     if is_debug_enabled("BACKTEST_CONTROLLER"):
                         print(f"[SIGNAL_GATE] Blocked {len(signals) - len(filtered_signals)} signals at {ts}")
                 signals = filtered_signals
             except Exception as e:
                 pass # Fail open if gate errors


        # [BAGHOLDER FIX] Data Gap Protection
        # If we hold a position but data is missing today, AlphaEngine didn't see it (likely).
        # We must injected a "Neutral/Exit" signal to allow RiskEngine to manage the exit (if possible).
        # And we must provide 'stale' history so RiskEngine doesn't crash.
        held_tickers = []
        if hasattr(self.portfolio, "positions"):
            held_tickers = [t for t, p in self.portfolio.positions.items() if p.qty != 0]

        for t in held_tickers:
            if t not in slice_map:
                # 1. Fetch stale history (up to ts)
                if t in self.data_map:
                    try:
                        # Safe get up to ts
                        stale_hist = self.data_map[t].loc[:ts]
                        if not stale_hist.empty:
                            slice_map[t] = stale_hist
                            # 2. Inject Panic/Zero Signal
                            # Signal 0.0 usually implies "Exit" or "No Edge" depending on Alpha/Risk logic.
                            # We rely on RiskEngine to treat 0.0 as "Close Long/Cover Short" if position exists.
                            signals.append({
                                "ticker": t,
                                "signal": 0.0,
                                "weight": 0.0,
                                "meta": {"note": "DATA_GAP_PROTECTION_EXIT", "edges_triggered": []}
                            })
                            if is_debug_enabled("BACKTEST_CONTROLLER"):
                                print(f"[CONTROLLER][PROBE] 🛡️ Injecting GAP EXIT signal for {t} (stale data).")
                    except Exception:
                        pass

        return signals

    def _prepare_orders(self, signals, ts, slice_map, equity_cache, close_prices_df, tickers, BACKTEST_DEBUG, regime_meta=None):
        """Prepare orders from signals through risk engine. Returns (orders, top_edge_by_ticker)."""
        # Top edge attribution per ticker (if provided via meta.edges_triggered)
        top_edge_by_ticker: Dict[str, str] = {}
        for s in signals:
            try:
                if not isinstance(s, dict) or "ticker" not in s:
                    continue
                contrib = (s.get("meta", {}) or {}).get("edges_triggered", [])
                if contrib:
                    # strongest by |norm*weight| (edges_triggered uses 'norm', not 'signal')
                    top = max(
                        contrib,
                        key=lambda c: abs(float(c.get("norm", c.get("signal", 0.0))) * float(c.get("weight", 0.0)))
                    )
                    top_edge_by_ticker[s["ticker"]] = str(top.get("edge", "Unknown"))
                else:
                    # edges_triggered is empty (all contributions below min_edge_contribution).
                    # Fall back to the signal's top-level edge field, which is always set by
                    # AlphaEngine even when no single edge clears the contribution threshold.
                    top_edge_by_ticker[s["ticker"]] = s.get("edge", "Unknown")
            except Exception:
                continue

        # ---- Engine C: Portfolio Optimization ---------------------------
        # Convert signals list to dict {ticker: score} for optimizer
        signal_map = {}
        for s in signals:
            # Generic signal parsing: look for 'strength', then 'confidence', then 'signal'
            # AlphaEngine typically returns 'strength' (0.0 to 1.0) and 'side'
            if "ticker" not in s:
                continue

            raw_score = s.get("strength", s.get("confidence", s.get("signal", 0.0)))
            side = s.get("side", "none").lower()

            if side == "none":
                continue

            side_mult = 1.0 if side == "long" else -1.0
            if side == "short":
                side_mult = -1.0

            score = float(raw_score) * side_mult
            signal_map[s["ticker"]] = score

        # Compute portfolio equity (cached or raw)
        if ts in equity_cache:
            equity = equity_cache[ts]
        else:
            # Quick equity calc
            mv = 0.0
            for t_pos, p_pos in self.portfolio.positions.items():
                 if p_pos.qty != 0 and t_pos in close_prices_df.columns:
                     mv += p_pos.qty * close_prices_df.at[ts, t_pos]
            equity = self.get_portfolio_capital() + mv
            equity_cache[ts] = equity

        # Call Policy (Engine C)
        # Note: 'slice_map' contains recent history for Volatility estimation
        target_weights = self.portfolio.compute_target_allocations(
            signals=signal_map,
            price_data=slice_map,
            equity=equity,
            regime_meta=regime_meta,
        )

        # ---- Engine B: Risk / Orders ------------------------------------
        orders: List[dict] = []
        # target_weights is now populated

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
                    regime_meta=regime_meta,
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

                # --- Prevent duplicate full-size entries (Path B ATR sizing) ---
                # Path A (target-weight) orders are delta-sized, so they correctly
                # top up or trim an existing position and must pass through.
                sizing_mode = (order.get("meta") or {}).get("sizing_mode")
                if (order.get("side") in ("long", "short")
                        and curr_qty != 0
                        and sizing_mode != "target_weight"):
                    if is_debug_enabled("RISK") or is_info_enabled("RISK"):
                        print(f"[RISK][{ts}] {tkr} already in position; skipping duplicate entry.")
                    continue

                # --- Edge attribution ---
                if tkr in top_edge_by_ticker:
                    order["edge"] = top_edge_by_ticker[tkr]
                if "edge_id" in sig:
                    order["edge_id"] = sig.get("edge_id")
                if "category" in sig:
                    order["edge_category"] = sig.get("category")

                orders.append(order)
            except Exception as e:
                if is_debug_enabled("BACKTEST_CONTROLLER"):
                    print(f"[CONTROLLER][ERROR] Risk processing error for {sig.get('ticker')}: {e}")
                continue

        if BACKTEST_DEBUG and orders:
            print(f"[DEBUG_BACKTEST][{ts}] Risk orders: {orders[:3]}")
        if BACKTEST_DEBUG and not orders and signals:
            first_sig = signals[0]
            forced_ticker = first_sig.get("ticker", list(slice_map.keys())[0])
            forced_order = {
                "ticker": forced_ticker,
                "side": "long",
                "qty": 10,
                "fill_price": float(slice_map[forced_ticker]["Close"].iloc[-1]),
                "edge": first_sig.get("edge", "debug_forced"),
                "edge_group": first_sig.get("edge_group", "debug"),
                "edge_id": first_sig.get("edge_id", "debug_v1"),
                "edge_category": first_sig.get("edge_category", "debug"),
                "meta": {"note": "forced_debug_order"},
            }
            print(f"[DEBUG_BACKTEST][{ts}] Injecting forced debug order: {forced_order}")
            orders.append(forced_order)

        if not orders:
            if is_debug_enabled("BACKTEST_CONTROLLER"):
                print(f"[DEBUG][{ts}] No executable orders this bar.")
        else:
            if is_debug_enabled("BACKTEST_CONTROLLER"):
                print(f"[DEBUG][{ts}] Orders ready for execution: {orders}")

        return orders, top_edge_by_ticker

    def _execute_fills(self, orders, next_rows, nxt, regime_meta=None):
        """Execute fill loop for entries/exits on next bar."""
        for order in orders:
            try:
                tkr = order["ticker"]
                row_next = next_rows.get(tkr)
                if row_next is None:
                    continue
                # Carry PrevClose into order meta for downstream PnL estimation
                try:
                    prev_close_val = float(row_next.get("PrevClose")) if "PrevClose" in row_next else None
                except Exception:
                    prev_close_val = None
                if prev_close_val is not None and math.isfinite(prev_close_val):
                    order.setdefault("meta", {})
                    order["meta"]["PrevClose"] = prev_close_val
                fill = self.exec.fill_at_next_open(order, row_next)
                # --- Normalize side/price/commission for engine & logger compatibility ---
                if fill:
                    try:
                        s = str(fill.get("side", "")).lower()
                        fill["side"] = self.SIDE_MAP.get(s, s)
                    except Exception:
                        pass
                    # ensure both keys exist for downstream consumers
                    if "fill_price" not in fill and "price" in fill:
                        fill["fill_price"] = fill["price"]
                    if "price" not in fill and "fill_price" in fill:
                        fill["price"] = fill["fill_price"]
                    # default commission
                    fill.setdefault("commission", float(getattr(self.exec, "commission", 0.0)))
                if fill:
                    # --- Ensure required numeric fields ---
                    try:
                        fill["qty"] = int(fill.get("qty", 0))
                    except Exception:
                        fill["qty"] = 0
                    try:
                        fill["fill_price"] = float(fill.get("fill_price", row_next.get("Open", np.nan)))
                    except Exception:
                        fill["fill_price"] = float("nan")

                    # PnL is computed by PortfolioEngine.apply_fill() — no pre-computation needed

                    # --- Propagate edge attribution into the fill ---
                    fill["edge"] = order.get("edge", "Unknown")
                    fill["edge_group"] = order.get("edge_group", None)
                    fill["edge_id"] = order.get("edge_id") if "edge_id" in order else None
                    fill["edge_category"] = order.get("edge_category") if "edge_category" in order else None

                    # --- Regime label for regime-conditional governance ---
                    if regime_meta:
                        macro = regime_meta.get("macro_regime")
                        if isinstance(macro, dict):
                            fill["regime_label"] = macro.get("label", "unknown")
                        elif isinstance(macro, str):
                            fill["regime_label"] = macro
                        else:
                            fill["regime_label"] = "unknown"
                    else:
                        fill["regime_label"] = "unknown"

                    print(f"[DEBUG_BACKTEST_FILL_CREATED] {fill}")
                    self.portfolio.apply_fill(fill)
                    if hasattr(self.logger, "set_portfolio"):
                        self.logger.set_portfolio(self.portfolio)
                    # Ensure edge attribution keys are present for logger schema
                    fill.setdefault("edge", order.get("edge", "Unknown"))
                    fill.setdefault("edge_group", order.get("edge_group"))
                    fill.setdefault("edge_id", order.get("edge_id"))
                    fill.setdefault("edge_category", order.get("edge_category"))
                    self._log_fill_compat(fill, nxt)
            except Exception:
                continue

    def _evaluate_stops(self, next_rows, nxt, regime_meta=None):
        """Evaluate SL/TP on next bar."""
        if self.cfg.eval_stops_after_entry_on_next_bar:
            # Resolve regime label once per bar (same logic as _execute_fills)
            if regime_meta:
                macro = regime_meta.get("macro_regime")
                if isinstance(macro, dict):
                    bar_regime_label = macro.get("label", "unknown")
                elif isinstance(macro, str):
                    bar_regime_label = macro
                else:
                    bar_regime_label = "unknown"
            else:
                bar_regime_label = "unknown"

            for tkr, pos in list(self.portfolio.positions.items()):
                try:
                    if pos.qty == 0:
                        continue
                    row_next = next_rows.get(tkr)
                    if row_next is None:
                        continue
                    stop_or_tp = self.exec.check_stops_and_targets(tkr, pos, row_next)
                    # Normalize SL/TP fill for engine & logger
                    if stop_or_tp:
                        s2 = str(stop_or_tp.get("side", "")).lower()
                        stop_or_tp["side"] = self.SIDE_MAP.get(s2, s2)
                        if "fill_price" not in stop_or_tp and "price" in stop_or_tp:
                            stop_or_tp["fill_price"] = stop_or_tp["price"]
                        if "price" not in stop_or_tp and "fill_price" in stop_or_tp:
                            stop_or_tp["price"] = stop_or_tp["fill_price"]
                        stop_or_tp.setdefault("commission", float(getattr(self.exec, "commission", 0.0)))
                        stop_or_tp["regime_label"] = bar_regime_label
                    if stop_or_tp:
                        # PnL is computed by PortfolioEngine.apply_fill()
                        self.portfolio.apply_fill(stop_or_tp)
                        if hasattr(self.logger, "set_portfolio"):
                            self.logger.set_portfolio(self.portfolio)
                        self._log_fill_compat(stop_or_tp, nxt)
                except Exception:
                    continue

    def _log_snapshot(self, next_rows, nxt):
        """Snapshot at nxt (using Close map)."""
        try:
            close_map_next = {t: _scalar_close(row) for t, row in next_rows.items()}
            snap = self.portfolio.snapshot(nxt, close_map_next)

            # DEBUG: full snapshot dict before we touch it further
            print(f"[DEBUG_SNAPSHOT_PAYLOAD_PRE_LOG] t={nxt}, snap={snap}")

            print(f"[DEBUG_SNAPSHOT_CHECK] Snapshot at {nxt}: cash={self.portfolio.cash}, positions={{t: p.qty for t,p in self.portfolio.positions.items()}}, realized_pnl={self.portfolio.realized_pnl}")
            # Ensure snapshot reflects live portfolio state using close prices for this bar
            snap["positions"] = sum(1 for p in self.portfolio.positions.values() if p.qty != 0)
            try:
                live_cash = float(getattr(self.portfolio, "cash", snap.get("cash", 0.0)))
                live_mv = 0.0
                for _tkr, _pos in getattr(self.portfolio, "positions", {}).items():
                    if hasattr(_pos, "qty") and _pos.qty != 0:
                        px = close_map_next.get(_tkr)
                        if px is None:
                            px = getattr(_pos, "last_price", getattr(_pos, "avg_price", 0.0))
                        if px is None:
                            continue
                        live_mv += float(_pos.qty) * float(px)
                snap["cash"] = live_cash
                snap["market_value"] = live_mv
                snap["equity"] = live_cash + live_mv
            except Exception as e:

                if is_debug_enabled("BACKTEST_CONTROLLER"):
                    print(f"[BACKTEST_CONTROLLER][DEBUG] Failed to sync live portfolio state for snapshot: {e}")
            # Tag snapshot with current run_id and persist into portfolio history
            snap["run_id"] = self.run_id
            self.logger.log_snapshot(snap)
            try:
                self.portfolio.history.append(snap)
            except Exception:
                pass
        except Exception:
            pass

    def _post_run(self, start_time, total_bars, BACKTEST_DEBUG):
        """Post-run logic: final flush, regime history save, edge feedback, metrics export, CSV promotion."""
        import threading
        import os

        # Non-blocking flush helper for logger (duplicated here for post-run use;
        # the identical closure lives inside run() for the main-loop path)
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
        if BACKTEST_DEBUG:
            print("[DEBUG_BACKTEST] Run complete, check trades.csv for forced fills.")

        # --- Save regime history if available ---
        if self.regime_detector is not None and hasattr(self.regime_detector, 'history'):
            try:
                history = self.regime_detector.history
                if len(history) > 0:
                    logger_out_dir = getattr(self.logger, "out_dir", None)
                    if logger_out_dir:
                        regime_path = os.path.join(str(logger_out_dir), "regime_history.csv")
                    else:
                        root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                        run_id = getattr(self.logger, "run_id", "default")
                        regime_path = os.path.join(root, "data", "trade_logs", str(run_id), "regime_history.csv")
                    history.save_csv(regime_path)
                    if is_info_enabled("BACKTEST_CONTROLLER"):
                        print(f"[BACKTEST][INFO] Saved regime history ({len(history)} bars) to {regime_path}")
            except Exception as e:
                if is_debug_enabled("BACKTEST_CONTROLLER"):
                    print(f"[BACKTEST][WARN] Could not save regime history: {e}")

        # Governor feedback (update_from_trades + save_weights) is handled by
        # ModeController post-run, gated on --no-governor. Doing it here as well
        # bypassed that gate and also double-merged evaluator recommendations,
        # polluting edge_weights.json with stale placeholder edges.

        # --- NEW: Export performance summary to JSON for research feedback loop ---
        try:
            from cockpit.metrics import PerformanceMetrics
            import json
            import pandas as _pd

            # Prefer cockpit logger's resolved files (run-scoped) if available
            snapshots_path_obj = getattr(self.logger, "snap_path", None)
            trades_path_obj = getattr(self.logger, "trade_path", None)
            if snapshots_path_obj and trades_path_obj:
                snapshots_path = str(snapshots_path_obj)
                trades_path = str(trades_path_obj)
            else:
                root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                snapshots_path = os.path.join(root, "data", "trade_logs", "portfolio_snapshots.csv")
                trades_path = os.path.join(root, "data", "trade_logs", "trades.csv")

            # Only proceed if both files exist and are non-empty
            if os.path.exists(snapshots_path) and os.path.getsize(snapshots_path) > 0 \
               and os.path.exists(trades_path) and os.path.getsize(trades_path) > 0:

                # By default, feed the raw paths into PerformanceMetrics
                snapshots_path_for_metrics = snapshots_path
                trades_path_for_metrics = trades_path

                # If run_id is present as a column, filter down to the current run only
                run_id = getattr(self.logger, "run_id", None)
                try:
                    if run_id is not None:
                        df_snap = _pd.read_csv(snapshots_path)
                        df_tr = _pd.read_csv(trades_path)
                        if "run_id" in df_snap.columns:
                            df_snap = df_snap[df_snap["run_id"] == run_id]
                        if "run_id" in df_tr.columns:
                            df_tr = df_tr[df_tr["run_id"] == run_id]
                        # --- NEW: Equity consistency check ---
                        try:
                            if "equity" in df_snap.columns:
                                start_eq = float(df_snap["equity"].iloc[0])
                                end_eq = float(df_snap["equity"].iloc[-1])
                                if abs(start_eq - self.initial_capital) > 1e-6:
                                    print(f"[PERF][WARN] start equity mismatch: snapshots={start_eq} expected={self.initial_capital}")
                                # Check end equity vs portfolio final
                                try:
                                    port_final = float(self.portfolio.cash) + sum(
                                        float(pos.qty) * float(getattr(pos, "last_price", pos.avg_price))
                                        for pos in self.portfolio.positions.values()
                                    )
                                    if abs(end_eq - port_final) > 1e-3:
                                        print(f"[PERF][WARN] end equity mismatch: snapshots={end_eq} vs portfolio={port_final}")
                                except Exception:
                                    pass
                        except Exception:
                            pass
                        # If we have any rows after filtering, write them to run-scoped temp files
                        if not df_snap.empty and not df_tr.empty:
                            perf_dir = os.path.dirname(snapshots_path)
                            os.makedirs(perf_dir, exist_ok=True)
                            snapshots_path_for_metrics = os.path.join(perf_dir, f"portfolio_snapshots_{run_id}.csv")
                            trades_path_for_metrics = os.path.join(perf_dir, f"trades_{run_id}.csv")
                            df_snap.to_csv(snapshots_path_for_metrics, index=False)
                            df_tr.to_csv(trades_path_for_metrics, index=False)
                except Exception:
                    # If filtering fails for any reason, fall back to unfiltered paths
                    snapshots_path_for_metrics = snapshots_path
                    trades_path_for_metrics = trades_path

                metrics = PerformanceMetrics(
                    snapshots_path=snapshots_path_for_metrics,
                    trades_path=trades_path_for_metrics,
                )
                if hasattr(metrics, "summary"):
                    stats = metrics.summary()
                elif hasattr(metrics, "summary_dict"):
                    stats = metrics.summary_dict
                else:
                    stats = {}

                # Save the summary next to the (possibly filtered) snapshots
                perf_dir = os.path.dirname(snapshots_path_for_metrics)
                perf_path = os.path.join(perf_dir, "performance_summary.json")
                os.makedirs(perf_dir, exist_ok=True)
                with open(perf_path, "w") as f:
                    json.dump(stats, f, indent=2)

                # Also promote run-scoped CSVs to top-level flat files for dashboards
                flat_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data", "trade_logs"))
                os.makedirs(flat_dir, exist_ok=True)
                try:
                    import shutil
                    # Clean replace flat CSVs before promotion
                    flat_snap = os.path.join(flat_dir, "portfolio_snapshots.csv")
                    flat_trades = os.path.join(flat_dir, "trades.csv")

                    # Remove old files if they exist (to avoid mixing runs)
                    if os.path.exists(flat_snap):
                        try:
                            os.remove(flat_snap)
                        except Exception:
                            pass

                    if os.path.exists(flat_trades):
                        try:
                            os.remove(flat_trades)
                        except Exception:
                            pass

                    # Promote run‑scoped CSVs freshly
                    shutil.copyfile(snapshots_path_for_metrics, flat_snap)
                    shutil.copyfile(trades_path_for_metrics, flat_trades)

                    if hasattr(self.logger, "run_id"):
                        print(f"[PROMOTE] Clean‑replaced flat CSVs from latest run '{self.logger.run_id}'.")
                except Exception:
                    pass
        except Exception as e:
            # Non-fatal; just skip
            pass

        if hasattr(self.logger, "run_id"):
            print(f"[BACKTEST][INFO] Completed run for run_id={self.logger.run_id}")
        try:
            out_dir = getattr(self.logger, "out_dir", None)
            snap_path = getattr(self.logger, "snap_path", None)
            trade_path = getattr(self.logger, "trade_path", None)
            if out_dir:
                print(f"[BACKTEST][PATHS] out_dir={out_dir}")
            if snap_path and trade_path:
                print(f"[BACKTEST][PATHS] snapshots={snap_path}")
                print(f"[BACKTEST][PATHS] trades={trade_path}")
        except Exception:
            pass

    # ------------------------------- run ------------------------------- #

    def run(self, start: str, end: str):
        import gc
        import threading
        import sys
        import os
        BACKTEST_DEBUG = bool(int(os.getenv("BACKTEST_DEBUG", "0")))
        if BACKTEST_DEBUG:
            print("[BACKTEST_CONTROLLER] Running in debug mode.")

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
        # Check for empty data_map or all empty DataFrames
        if not self.data_map or all(df.empty for df in self.data_map.values()):
            print("[BACKTEST_CONTROLLER][DEBUG] Entered run() with empty data_map or all empty DataFrames.")
            raise ValueError("[BACKTEST] No data available for backtest — data_map is empty or failed to load. Check data sources or API keys.")
        ts_vec = [ts for ts in self.timestamps if (start_dt <= ts <= end_dt)]

        if not ts_vec:
            print("[BACKTEST_CONTROLLER][DEBUG] Entered run() but no valid timestamps found in range.")
            raise ValueError("[BACKTEST] No valid timestamps found within range. Check data alignment or date filters.")

        # Always write an initial snapshot even if there's only one bar
        t0 = ts_vec[0]
        first_prices = {t: float(self.data_map[t].iloc[0]["Close"]) for t in self.data_map if not self.data_map[t].empty}
        # Ensure portfolio capital and cash are set to initial_capital if <= 0 before first snapshot
        if float(getattr(self.portfolio, "capital", 0.0)) <= 0.0:
            self.portfolio.capital = self.initial_capital
        if hasattr(self.portfolio, "cash") and float(getattr(self.portfolio, "cash", 0.0)) <= 0.0:
            self.portfolio.cash = self.initial_capital
        snap0 = self.portfolio.snapshot(t0, first_prices)
        snap0["positions"] = sum(1 for p in self.portfolio.positions.values() if p.qty != 0)
        snap0["run_id"] = self.run_id
        # DEBUG: see exactly what initial snapshot looks like before logger touches it
        print(f"[DEBUG_INITIAL_SNAPSHOT_PAYLOAD] {snap0}")
        try:
            self.logger.log_snapshot(snap0)
        except Exception as e:
            print(f"[BACKTEST_CONTROLLER][DEBUG] Exception logging initial snapshot: {e}")
        self.portfolio.history = [snap0]

        # Force at least one initial record into portfolio_snapshots.csv if portfolio.history is empty or snapshot could not be written
        try:
            pass
        except Exception as e:
            print(f"[BACKTEST_CONTROLLER][DEBUG] Could not write forced initial snapshot: {e}")

        if len(ts_vec) < 2:
            print("[BACKTEST_CONTROLLER][DEBUG] Only one bar of data available; recorded initial snapshot only and finishing early.")
            return self.portfolio.history

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

                # [BAGHOLDER PROBE] Check for held tickers that are missing from today's data slice
                # This explicitly visualizes the bug where we lose control of a position.
                current_holdings = list(self.portfolio.positions.keys())
                for held_ticker in current_holdings:
                    if held_ticker not in self.data_map: # Use self.data_map for full data, not slice_map
                        if is_controller_debug():
                            print(f"[CONTROLLER][PROBE] 🚨 DATA GAP for {held_ticker} at {ts}. "
                                  f"Position held but no price data! Logic will skip this ticker.")

                # Note: AlphaEngine only receives 'data_map' (the slice). It doesn't see tickers not in the slice.
                if not slice_map:
                    # Memory cleanup for unused slices
                    if i % self.batch_flush_interval == 0:
                        gc.collect()
                    continue

                regime_meta = self._detect_regime(ts, slice_map)

                self._update_trailing_stops(slice_map, regime_meta)

                signals = self._generate_signals(ts, slice_map, regime_meta, BACKTEST_DEBUG)

                orders, top_edge_by_ticker = self._prepare_orders(signals, ts, slice_map, equity_cache, close_prices_df, tickers, BACKTEST_DEBUG, regime_meta=regime_meta)

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

                self._execute_fills(orders, next_rows, nxt, regime_meta=regime_meta)

                self._evaluate_stops(next_rows, nxt, regime_meta=regime_meta)

                self._log_snapshot(next_rows, nxt)

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

        self._post_run(start_time, total_bars, BACKTEST_DEBUG)
        return self.portfolio.history