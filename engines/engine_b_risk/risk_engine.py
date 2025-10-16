# engines/engine_b_risk/risk_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import math
import pandas as pd


@dataclass
class RiskConfig:
    # core risk knobs (can come from config JSON)
    risk_per_trade_pct: float = 0.01      # % of equity to risk per trade
    atr_stop_mult: float = 1.5            # stop = entry ± atr_stop_mult * ATR
    atr_tp_mult: float = 3.0              # take-profit multiple of ATR
    cap_atr_to_pct_of_price: float = 0.20 # cap ATR to 20% of price
    max_pos_value_pct: float = 0.30       # max notional per ticker (of equity)
    min_qty: int = 1                      # floor
    round_qty: bool = True                # integer sizing


class RiskEngine:
    """
    Turns Alpha signals into actionable orders with sizing + SL/TP.
    Also emits 'exit' orders on neutral or flip.
    """

    def __init__(self, cfg: Dict[str, Any]):
        c = RiskConfig(
            risk_per_trade_pct=float(cfg.get("risk_per_trade_pct", 0.01)),
            atr_stop_mult=float(cfg.get("atr_stop_mult", 1.5)),
            atr_tp_mult=float(cfg.get("atr_tp_mult", 3.0)),
            cap_atr_to_pct_of_price=float(cfg.get("cap_atr_to_pct_of_price", 0.20)),
            max_pos_value_pct=float(cfg.get("max_pos_value_pct", 0.30)),
            min_qty=int(cfg.get("min_qty", 1)),
            round_qty=bool(cfg.get("round_qty", True)),
        )
        self.cfg = c

    def _last_row(self, df: pd.DataFrame) -> pd.Series:
        if isinstance(df, pd.Series):
            return df
        return df.iloc[-1]

    def _cap_atr(self, price: float, atr: float) -> float:
        cap = self.cfg.cap_atr_to_pct_of_price * price
        if atr > cap:
            capped = cap
            print(f"[RISK] Capping ATR: {atr:.4f} -> {capped:.4f} (20% of price)")
            return capped
        return atr

    def prepare_order(
        self,
        signal: Dict[str, Any],
        equity: float,
        df_hist: pd.DataFrame,
        current_qty: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Returns one of:
          - None (no action)
          - {'ticker','side':'exit','qty'}  to close existing pos
          - {'ticker','side':'long|short','qty','stop','take_profit'}  open/add
        """
        ticker = signal["ticker"]
        side = signal.get("side", "none")
        if side not in ("long", "short", "none"):
            return None

        # If we have a position and alpha says NONE → exit
        if side == "none" and current_qty != 0:
            return {"ticker": ticker, "side": "exit", "qty": abs(current_qty)}

        # If we have a position and alpha flips → exit first (open on next bar)
        if current_qty != 0:
            have_long = current_qty > 0
            want_long = (side == "long")
            if side in ("long", "short") and (have_long != want_long):
                return {"ticker": ticker, "side": "exit", "qty": abs(current_qty)}

        if side == "none":
            return None  # nothing to do

        # Sizing for (open/add)
        row = self._last_row(df_hist)
        price = float(row["Close"])
        atr = float(row.get("ATR", 0.0))
        atr = self._cap_atr(price, atr)

        # Stop distance & risk budget
        stop_dist = self.cfg.atr_stop_mult * atr
        risk_budget = max(0.0, equity * self.cfg.risk_per_trade_pct)
        if stop_dist <= 0 or risk_budget <= 0:
            return None

        raw_qty = risk_budget / stop_dist
        # Max notional per ticker
        max_value = equity * self.cfg.max_pos_value_pct
        max_qty_by_value = (max_value / price) if price > 0 else 0.0
        target_qty = min(raw_qty, max_qty_by_value)

        if self.cfg.round_qty:
            target_qty = math.floor(target_qty)

        target_qty = max(target_qty, 0)
        if target_qty < self.cfg.min_qty:
            # still allow min 1 but warn
            if self.cfg.min_qty > 0:
                target_qty = self.cfg.min_qty
            else:
                return None

        add_qty = target_qty - abs(current_qty)
        if add_qty <= 0:
            return None  # already at/above target

        # Compute SL/TP levels
        if side == "long":
            stop = price - stop_dist
            tp = price + self.cfg.atr_tp_mult * atr
        else:
            stop = price + stop_dist
            tp = price - self.cfg.atr_tp_mult * atr

        return {
            "ticker": ticker,
            "side": side,
            "qty": int(add_qty),
            "stop": float(stop),
            "take_profit": float(tp),
        }