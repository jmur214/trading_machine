# backtester/execution_simulator.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Dict, Any
import math
import pandas as pd
from debug_config import is_debug_enabled, is_info_enabled
import os
import numpy as np


# ------------------------------- Config -------------------------------- #

@dataclass
class ExecParams:
    """
    Execution simulation knobs.

    slippage_bps     : per-side bps slippage added to fills
    commission       : per-fill commission (flat)
    gap_warn         : print a warning if next open differs from prev close by > this fraction
    prefer_close_fallback: if next Open is missing/invalid, fall back to Close
    conservative_intrabar: if both stop & target breach within a bar, assume the WORST outcome
                           for the position (i.e., stop wins before target). This prevents
                           optimistic bias when bar path is unknown.
    """
    slippage_bps: float = 10.0
    commission: float = 0.0
    gap_warn: float = 0.50
    prefer_close_fallback: bool = True
    conservative_intrabar: bool = True
    verbose: bool = True


# ------------------------------ Simulator ------------------------------ #

class ExecutionSimulator:
    """
    Simulates order execution for backtesting.

    - Entries/exits are executed at the *next bar* price:
        default: next Open (if invalid, falls back to Close when enabled).
    - Stop/Target checks are evaluated intrabar using High/Low breaches.
      If BOTH stop and target are breached in the same bar and we don't
      know the path, a conservative tie-break is applied (stop wins first)
      to avoid optimistic bias (configurable via ExecParams).

    Fills return a dict compatible with PortfolioEngine.apply_fill():
      {
        'ticker','side','qty','price','commission', ['edge'], ['trigger']
      }
    """

    def __init__(self,
                 slippage_bps: float = 10.0,
                 commission: float = 0.0,
                 gap_warn: float = 0.50,
                 prefer_close_fallback: bool = True,
                 conservative_intrabar: bool = True,
                 verbose: bool = True):
        self.params = ExecParams(
            slippage_bps=float(slippage_bps),
            commission=float(commission),
            gap_warn=float(gap_warn),
            prefer_close_fallback=bool(prefer_close_fallback),
            conservative_intrabar=bool(conservative_intrabar),
            verbose=bool(verbose),
        )

    # ---------------------------- internals ---------------------------- #

    def _log_debug(self, msg: str) -> None:
        if self.params.verbose and is_debug_enabled("EXEC"):
            print(msg)

    def _log_info(self, msg: str) -> None:
        if self.params.verbose and is_info_enabled("EXEC"):
            print(msg)

    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply per-side bps slippage to a *paid/received* price."""
        slip = price * (self.params.slippage_bps / 10_000.0)
        s = str(side).lower()
        if s in ("long", "buy", "cover"):   # paying (for buys / buy-to-cover)
            return price + slip
        if s in ("short", "sell", "exit"):  # receiving (for sells / sell-to-close)
            return price - slip
        return price

    def _extract_bar_prices(self, bar_like: Any) -> Dict[str, float]:
        """
        Obtain Open/High/Low/Close/PrevClose from Series/DataFrame row-like.
        Raises if O/H/L are missing since we need them for stop/target logic.
        """
        def extract_val(val):
            if isinstance(val, pd.Series) or (hasattr(np, 'ndarray') and isinstance(val, np.ndarray)):
                if hasattr(val, 'iloc'):
                    return float(val.iloc[0])
                else:
                    return float(val[0])
            return float(val)

        try:
            o = extract_val(bar_like["Open"])
            h = extract_val(bar_like["High"])
            l = extract_val(bar_like["Low"])
        except Exception:
            raise KeyError("Bar data must include numeric 'Open', 'High', and 'Low' fields.")
        c = extract_val(bar_like["Close"]) if "Close" in bar_like else float("nan")
        pc = extract_val(bar_like["PrevClose"]) if "PrevClose" in bar_like else float("nan")
        return {"Open": o, "High": h, "Low": l, "Close": c, "PrevClose": pc}

    def _next_price_for_entry_exit(self, bar: Dict[str, float]) -> float:
        """
        Use next bar Open by default; optionally fall back to Close when Open invalid.
        """
        px = bar.get("Open", float("nan"))
        if not math.isfinite(px) or px <= 0:
            if self.params.prefer_close_fallback:
                px = bar.get("Close", float("nan"))
        if not math.isfinite(px) or px <= 0:
            raise ValueError("No valid Open/Close found to execute next-bar fill.")
        return px

    # ----------------------------- public ------------------------------ #

    def fill_at_next_open(self, order: dict, next_bar_like: Any) -> Optional[dict]:
        """
        Execute an order at the *next* bar price (Open preferred).
        - Carries through 'edge' and 'meta' if provided on the order.
        - Warns on suspicious gaps vs PrevClose (if available).

        order: {'ticker','side','qty', 'edge'?, 'meta'?}
        next_bar_like: row-like w/ Open, High, Low, Close, PrevClose?
        """
        def extract_val(val):
            if isinstance(val, pd.Series) or (hasattr(np, 'ndarray') and isinstance(val, np.ndarray)):
                if hasattr(val, 'iloc'):
                    return float(val.iloc[0])
                else:
                    return float(val[0])
            return float(val)

        # --- Safe price selection & gap sanity check -------------------
        try:
            fill_px = extract_val(next_bar_like.get("Open", next_bar_like.get("Close")))
        except Exception:
            fill_px = float("nan")

        try:
            prev_close = extract_val(next_bar_like.get("PrevClose", next_bar_like.get("Close", fill_px)))
        except Exception:
            prev_close = fill_px

        # Warn if the next open is abnormally far from previous close
        if math.isfinite(fill_px) and math.isfinite(prev_close) and prev_close > 0:
            gap = abs(fill_px / prev_close - 1.0)
            if gap > self.params.gap_warn:
                self._log_info(
                    f"[EXEC][WARN] Suspicious gap {gap:.1%} on {order.get('ticker','?')} "
                    f"at {getattr(next_bar_like, 'name', '?')}: "
                    f"PrevClose={prev_close:.4f}, Open={fill_px:.4f}"
                )
        bar = self._extract_bar_prices(next_bar_like)

        side = str(order.get("side", "")).lower()
        qty = int(order.get("qty", 0))
        ticker = order.get("ticker")

        if qty <= 0 or side not in ("long", "short", "exit", "cover") or not ticker:
            return None

        raw = self._next_price_for_entry_exit(bar)

        # gap sanity warning (not fatal)
        prev = bar.get("PrevClose", float("nan"))
        if math.isfinite(prev) and prev > 0:
            gap = abs(raw / prev - 1.0)
            if gap > self.params.gap_warn:
                self._log_info(f"[WARN][EXEC] Gap > {self.params.gap_warn:.0%} on {ticker}: "
                               f"prev={prev:.4f}, open={raw:.4f} ({gap:.1%})")

        traded = self._apply_slippage(raw, side)
        fill = {
            "ticker": ticker,
            "side": side,
            "qty": qty,
            "fill_price": float(traded),
            "commission": float(self.params.commission),
        }
        # preserve attribution/meta if passed
        if "edge" in order:
            fill["edge"] = order["edge"]
        if "meta" in order:
            fill["meta"] = order["meta"]
        if "edge_id" in order:
            fill["edge_id"] = order["edge_id"]
        if "edge_category" in order:
            fill["edge_category"] = order["edge_category"]
        if "edge_group" in order:
            fill["edge_group"] = order["edge_group"]
        # Set trigger default if not present
        if "trigger" not in order:
            if side in {"long", "short"}:
                fill["trigger"] = "entry"
            elif side in {"exit", "cover"}:
                fill["trigger"] = "exit"
        else:
            fill["trigger"] = order["trigger"]

        if os.getenv("BACKTEST_DEBUG") == "1":
            print("[SIM][DEBUG] Filled order:", fill)

        self._log_info(f"[EXEC] Filled {side} {ticker} x{qty} @ {traded:.4f}")
        return fill

    def check_stops_and_targets(self, ticker: str, position, bar_like: Any) -> Optional[dict]:
        """
        Check if a position would be closed by stop or take-profit within THIS bar.
        Returns a fill dict if triggered, else None.

        Ambiguity rule:
          If both stop and target are breached in the same bar (unknown path),
          we assume *conservative* ordering if enabled:
            - For LONG: stop first (i.e., worse outcome for trader)
            - For SHORT: stop first
          If conservative_intrabar=False, we favor the target first (optimistic).
        """
        if position is None or position.qty == 0:
            return None

        def extract_val(val):
            if isinstance(val, pd.Series) or (hasattr(np, 'ndarray') and isinstance(val, np.ndarray)):
                if hasattr(val, 'iloc'):
                    return float(val.iloc[0])
                else:
                    return float(val[0])
            return float(val)

        bar = self._extract_bar_prices(bar_like)
        high, low = bar["High"], bar["Low"]

        qty = abs(int(position.qty))
        is_long = position.qty > 0
        stop = position.stop
        tp = position.take_profit

        if stop is not None:
            stop = extract_val(stop)
        if tp is not None:
            tp = extract_val(tp)

        if stop is None and tp is None:
            return None

        # Determine if levels were reached within bar
        hit_stop = False
        hit_tp = False
        if is_long:
            if stop is not None and low <= stop:
                hit_stop = True
            if tp is not None and high >= tp:
                hit_tp = True
        else:
            if stop is not None and high >= stop:
                hit_stop = True
            if tp is not None and low <= tp:
                hit_tp = True

        if not hit_stop and not hit_tp:
            return None

        # Tie-break rule when both hit in same bar (unknown intrabar path)
        # Conservative mode: assume stop before target (worse outcome).
        # Optimistic mode: assume target before stop (better outcome).
        trigger: str
        level: float
        if hit_stop and hit_tp:
            prefer_stop = self.params.conservative_intrabar
            if prefer_stop:
                trigger = "stop"
                level = stop  # type: ignore[arg-type]
            else:
                trigger = "take_profit"
                level = tp    # type: ignore[arg-type]
        elif hit_stop:
            trigger = "stop"
            level = stop      # type: ignore[arg-type]
        else:
            trigger = "take_profit"
            level = tp        # type: ignore[arg-type]

        exec_side = "exit" if is_long else "cover"

        # For stops/targets we model fill at the *level* (then add slippage).
        paid_side = "sell" if is_long else "buy"
        px = self._apply_slippage(level, paid_side)

        fill = {
            "ticker": ticker,
            "side": exec_side,
            "qty": qty,
            "fill_price": float(px),
            "commission": float(self.params.commission),
            "trigger": trigger,
        }
        # Preserve attribution keys from position if present
        if getattr(position, "edge", None) is not None:
            fill["edge"] = position.edge
        if getattr(position, "edge_group", None) is not None:
            fill["edge_group"] = position.edge_group
        if getattr(position, "edge_id", None) is not None:
            fill["edge_id"] = position.edge_id
        if getattr(position, "edge_category", None) is not None:
            fill["edge_category"] = position.edge_category

        if os.getenv("BACKTEST_DEBUG") == "1":
            print("[SIM][DEBUG] Stop/Target hit:", fill)

        self._log_info(f"[EXEC] {exec_side.upper()} via {trigger} {ticker} x{qty} @ {px:.4f}")
        return fill

    def exit_position(self, ticker: str, position, next_bar_like: Any) -> Optional[dict]:
        """
        Convenience helper to close a position at the *next bar* (Open preferred).
        """
        if position is None or position.qty == 0:
            return None
        side = "exit" if position.qty > 0 else "cover"
        return self.fill_at_next_open(
            {"ticker": ticker, "side": side, "qty": abs(int(position.qty))},
            next_bar_like,
        )