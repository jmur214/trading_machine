# engines/engine_b_risk/risk_engine.py

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import math
import pandas as pd


@dataclass
class RiskConfig:
    # Core knobs (config-driven)
    risk_per_trade_pct: float = 0.01
    atr_stop_mult: float = 1.5
    atr_tp_mult: float = 3.0
    cap_atr_to_pct_of_price: float = 0.20
    atr_floor_pct_of_price: float = 0.005  # NEW: floor ATR to 0.5% of price to avoid micro ATR
    max_pos_value_pct: float = 0.30
    min_qty: int = 1
    round_qty: bool = True

    # New portfolio-aware constraints
    max_positions: int = 5            # max concurrent tickers
    max_gross_exposure: float = 1.0   # 100% of equity
    allow_shorts: bool = True
    min_notional: float = 50.0        # USD min trade size
    min_bars_warmup: int = 30         # do not trade until we have enough data


class RiskEngine:
    """
    Turns Alpha signals into actionable orders with sizing + SL/TP, under portfolio constraints.
    Returns None (skip) when constraints fail; caller may log reason.
    """

    def __init__(self, cfg: Dict[str, Any]):
        c = RiskConfig(
            risk_per_trade_pct=float(cfg.get("risk_per_trade_pct", 0.01)),
            atr_stop_mult=float(cfg.get("atr_stop_mult", 1.5)),
            atr_tp_mult=float(cfg.get("atr_tp_mult", 3.0)),
            cap_atr_to_pct_of_price=float(cfg.get("cap_atr_to_pct_of_price", 0.20)),
            atr_floor_pct_of_price=float(cfg.get("atr_floor_pct_of_price", 0.005)),
            max_pos_value_pct=float(cfg.get("max_pos_value_pct", 0.30)),
            min_qty=int(cfg.get("min_qty", 1)),
            round_qty=bool(cfg.get("round_qty", True)),
            max_positions=int(cfg.get("max_positions", 5)),
            max_gross_exposure=float(cfg.get("max_gross_exposure", 1.0)),
            allow_shorts=bool(cfg.get("allow_shorts", True)),
            min_notional=float(cfg.get("min_notional", 50.0)),
            min_bars_warmup=int(cfg.get("min_bars_warmup", 30)),
        )
        self.cfg = c
        self.portfolio = None  # optionally set by controller for exposure checks

    # ---------- helpers ---------- #

    def _last_row(self, df: pd.DataFrame) -> pd.Series:
        if isinstance(df, pd.Series):
            return df
        return df.iloc[-1]

    def _effective_atr(self, price: float, atr: float) -> float:
        """
        Apply both a cap (to avoid absurdly wide stops) and a floor (to avoid micro ATR leading to huge size).
        """
        cap = self.cfg.cap_atr_to_pct_of_price * price
        floor = self.cfg.atr_floor_pct_of_price * price
        a = float(atr)
        if a > cap:
            a = cap
        if a < floor:
            a = floor
        return a

    def _positions_count(self) -> int:
        try:
            return sum(1 for p in self.portfolio.positions.values() if p.qty != 0)  # type: ignore[union-attr]
        except Exception:
            return 0

    def _gross_exposure(self, price_map: Dict[str, float]) -> float:
        """
        Approx gross exposure = sum(abs(qty*price)) / equity. Requires portfolio to be attached.
        """
        if self.portfolio is None:
            return 0.0
        eq = float(self.portfolio.total_equity(price_map))  # type: ignore[union-attr]
        if eq <= 0:
            return float("inf")
        gross = 0.0
        for t, pos in self.portfolio.positions.items():  # type: ignore[union-attr]
            if pos.qty == 0:
                continue
            px = float(price_map.get(t, pos.avg_price))
            gross += abs(pos.qty * px)
        return gross / eq

    # ---------- main ---------- #

    def prepare_order(
        self,
        signal: Dict[str, Any],
        equity: float,
        df_hist: pd.DataFrame,
        current_qty: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Returns:
          - None (skip) with constraints enforced.
          - dict for {'ticker','side':'exit','qty'} or
                   {'ticker','side':'long|short','qty','stop','take_profit'}
        """
        ticker = signal["ticker"]
        side = signal.get("side", "none").lower()
        if side not in ("long", "short", "none"):
            return None

        # Warmup: require enough bars (guards tiny ATR / unstable signals)
        if len(df_hist) < self.cfg.min_bars_warmup:
            return None

        # Exit logic (neutral or flip) gets handled simply: if flipping, exit first; open next bar by alpha
        if side == "none" and current_qty != 0:
            return {"ticker": ticker, "side": "exit", "qty": abs(current_qty)}

        if current_qty != 0:
            have_long = current_qty > 0
            want_long = (side == "long")
            if side in ("long", "short") and (have_long != want_long):
                return {"ticker": ticker, "side": "exit", "qty": abs(current_qty)}

        if side == "none":
            return None

        # No-shorts policy
        if (side == "short") and (not self.cfg.allow_shorts):
            return None

        # Portfolio constraints: max positions
        if self._positions_count() >= self.cfg.max_positions and current_qty == 0:
            return None

        # Pricing / ATR
        row = self._last_row(df_hist)
        price = float(row["Close"])
        raw_atr = float(row.get("ATR", 0.0))
        atr = self._effective_atr(price, raw_atr)

        # Stop distance & risk budget
        stop_dist = max(self.cfg.atr_stop_mult * atr, 1e-9)
        risk_budget = max(0.0, float(equity) * self.cfg.risk_per_trade_pct)
        if risk_budget <= 0:
            return None

        # Raw qty from risk budget
        raw_qty = risk_budget / stop_dist

        # Cap by per-name notional
        max_value = float(equity) * self.cfg.max_pos_value_pct
        max_qty_by_value = (max_value / price) if price > 0 else 0.0
        target_qty = min(raw_qty, max_qty_by_value)

        if self.cfg.round_qty:
            target_qty = math.floor(target_qty)

        target_qty = max(target_qty, 0)

        # Enforce min qty and min notional
        if target_qty < max(self.cfg.min_qty, 1):
            return None
        if (target_qty * price) < self.cfg.min_notional:
            return None

        add_qty = int(target_qty) - abs(int(current_qty))
        if add_qty <= 0:
            return None

        # Gross exposure guard (requires portfolio attached)
        try:
            price_map = {ticker: price}
            gross_after = self._gross_exposure(price_map) + (abs(add_qty * price) / max(float(equity), 1e-9))
            if gross_after > self.cfg.max_gross_exposure:
                return None
        except Exception:
            pass

        # Compute SL/TP levels
        if side == "long":
            stop = price - self.cfg.atr_stop_mult * atr
            tp = price + self.cfg.atr_tp_mult * atr
        else:
            stop = price + self.cfg.atr_stop_mult * atr
            tp = price - self.cfg.atr_tp_mult * atr

        return {
            "ticker": ticker,
            "side": side,
            "qty": int(add_qty),
            "stop": float(stop),
            "take_profit": float(tp),
        }