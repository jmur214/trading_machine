# engines/engine_b_risk/risk_engine.py

from __future__ import annotations

import math
from typing import Optional, Dict, Any

import pandas as pd
from utils.math_utils import atr as _atr_func


class RiskEngine:
    """
    ATR-based position sizing and order preparation engine.

    Expected inputs:
        prepare_order(signal: dict, portfolio_value: float, df: pd.DataFrame)

    Returns either a full order dict or None:
        {
            "ticker": str,
            "side": "long" | "short",
            "qty": int,
            "entry_price_hint": float,
            "stop_price": float,
            "tp_price": float,
            "expected_rr": float
        }
    """

    def __init__(self, config: dict):
        # --- sizing controls ---
        self.max_risk_per_trade = float(config.get("max_risk_per_trade", 0.01))   # 1% of equity
        self.min_dollar_risk    = float(config.get("min_dollar_risk", 25.0))      # floor in $
        self.max_total_risk     = float(config.get("max_total_risk", 0.10))       # unused here (portfolio may enforce)

        # --- stop/target multiples ---
        self.stop_multiple      = float(config.get("stop_multiple", 1.5))
        self.tp_multiple        = float(config.get("tp_multiple", 3.0))

        # --- volatility sanity ---
        self.atr_period         = int(config.get("atr_period", 14))
        self.atr_cap_pct        = float(config.get("atr_cap_pct", 0.20))          # cap ATR to 20% of price
        self.require_strict_atr = bool(config.get("require_strict_atr", False))   # if True, skip when ATR missing

        # --- execution safety ---
        self.min_qty_floor      = int(config.get("min_qty_floor", 1))             # at least 1 share

    # ------------------ helpers ------------------

    def _latest_close(self, df: pd.DataFrame) -> Optional[float]:
        try:
            close = float(pd.to_numeric(df["Close"]).iloc[-1])
            return close if math.isfinite(close) and close > 0 else None
        except Exception:
            return None

    def _latest_atr(self, df: pd.DataFrame) -> Optional[float]:
        """
        Get ATR from existing column if present, otherwise compute.
        Uses the last non-NaN value (ATR often begins with NaN/0 for warm-up).
        """
        # Prefer precomputed ATR column if available
        if "ATR" in df.columns:
            try:
                s = pd.to_numeric(df["ATR"], errors="coerce").dropna()
                if not s.empty:
                    val = float(s.iloc[-1])
                    if val > 0 and math.isfinite(val):
                        return val
            except Exception:
                pass

        # Fallback: compute ATR from OHLC if possible
        try:
            s = _atr_func(df, period=self.atr_period)
            if s is None or s.empty:
                return None
            s = pd.to_numeric(s, errors="coerce").dropna()
            if s.empty:
                return None
            val = float(s.iloc[-1])
            return val if val > 0 and math.isfinite(val) else None
        except Exception:
            return None

    # ------------------ main API ------------------

    def prepare_order(self, signal: dict, portfolio_value: float, df: pd.DataFrame) -> Optional[Dict[str, Any]]:
        tkr = signal.get("ticker")
        side = signal.get("side")
        print(f"[DEBUG:RISK] Called prepare_order for {tkr} | side={side}")

        if side is None or side == "none":
            print(f"[DEBUG:RISK] Side is none for {tkr}, skipping.")
            return None

        if df is None or len(df) == 0:
            print(f"[RISK][ERROR] No data frame for {tkr}, skipping.")
            return None

        # --- fetch price & ATR ---
        last_close = self._latest_close(df)
        atr_last   = self._latest_atr(df)

        if last_close is None:
            print(f"[RISK][ERROR] Missing Close for {tkr}.")
            return None

        if atr_last is None:
            msg = f"[RISK][ERROR] Missing ATR for {tkr}."
            if self.require_strict_atr:
                print(msg + " Strict mode -> skipping.")
                return None
            else:
                print(msg + " Proceeding with conservative proxy (cap at atr_cap_pct of price).")
                atr_last = max(1e-6, self.atr_cap_pct * last_close)

        # cap extreme ATR to avoid absurd sizing
        if atr_last > self.atr_cap_pct * last_close:
            capped = self.atr_cap_pct * last_close
            print(f"[RISK] Capping ATR for {tkr}: {atr_last:.4f} -> {capped:.4f} ({self.atr_cap_pct:.0%} of price)")
            atr_last = capped

        # --- compute risk budget ---
        # Dynamic risk: max(min_dollar_risk, % of equity)
        dollar_risk = max(self.min_dollar_risk, self.max_risk_per_trade * float(portfolio_value))
        if dollar_risk <= 0:
            print(f"[RISK][ERROR] Non-positive dollar_risk ({dollar_risk}) for {tkr}, skipping.")
            return None

        # --- distance to stop (in $/share) ---
        stop_dist = self.stop_multiple * atr_last
        if stop_dist <= 0 or not math.isfinite(stop_dist):
            print(f"[RISK][ERROR] Invalid stop_dist for {tkr} (ATR={atr_last}, stop_mult={self.stop_multiple}).")
            return None

        # --- position size ---
        raw_qty = dollar_risk / stop_dist
        qty = int(raw_qty)

        if qty < self.min_qty_floor:
            # If we enforce the floor, warn if this breaches the per-trade risk cap
            risk_if_forced = self.min_qty_floor * stop_dist
            if risk_if_forced > dollar_risk:
                print(
                    f"[RISK][WARN] {tkr}: qty floor={self.min_qty_floor} would risk "
                    f"{risk_if_forced:.2f} > budget {dollar_risk:.2f}. Forcing min qty."
                )
            qty = self.min_qty_floor

        if qty <= 0:
            print(f"[RISK][SKIP] Qty too small for {tkr}, skipping.")
            return None

        # --- stops / targets ---
        if side == "long":
            stop_price = last_close - stop_dist
            tp_price   = last_close + self.tp_multiple * atr_last
        elif side == "short":
            stop_price = last_close + stop_dist
            tp_price   = last_close - self.tp_multiple * atr_last
        else:
            print(f"[RISK][ERROR] Invalid side '{side}' for {tkr}, skipping.")
            return None

        # --- assemble order ---
        order = {
            "ticker": tkr,
            "side": side,
            "qty": int(qty),
            "entry_price_hint": float(last_close),
            "stop_price": float(stop_price),
            "tp_price": float(tp_price),
            "expected_rr": float(self.tp_multiple / self.stop_multiple) if self.stop_multiple > 0 else float("nan"),
        }

        # --- diagnostics ---
        print(
            "[RISK] Prepared order | "
            f"{tkr} {side} | Close={last_close:.4f} ATR={atr_last:.4f} "
            f"| risk=${dollar_risk:.2f} stop_dist={stop_dist:.4f} raw_qty={raw_qty:.4f} qty={qty} "
            f"| stop={stop_price:.4f} tp={tp_price:.4f}"
        )

        return order