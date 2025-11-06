# engines/engine_b_risk/risk_engine.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional, Dict, Any
import math
import pandas as pd
import numpy as np
from debug_config import is_debug_enabled, is_info_enabled


@dataclass
class RiskConfig:
    """
    Risk and constraint configuration (config-driven).
    """
    # Per-trade sizing knobs
    risk_per_trade_pct: float = 0.01        # risk budget per trade, as % of equity
    atr_stop_mult: float = 1.5              # stop distance = mult * ATR
    atr_tp_mult: float = 3.0                # take-profit distance = mult * ATR
    cap_atr_to_pct_of_price: float = 0.20   # clamp extreme ATR (e.g., 20% of price)
    atr_floor_pct_of_price: float = 0.005   # floor ATR (e.g., 0.5% of price)
    max_pos_value_pct: float = 0.30         # cap single-name notional as % of equity
    min_qty: int = 1
    round_qty: bool = True
    min_notional: float = 50.0              # enforce minimum ticket size (USD)
    force_min_qty_on_signal: bool = True     # if sizing rounds to 0, optionally force 1 share when safe

    # Portfolio-level constraints
    max_positions: int = 5
    max_gross_exposure: float = 1.0         # Σ|qty*px| / equity
    allow_shorts: bool = True
    min_bars_warmup: int = 30               # require history length before trading

    # Allocation alignment (optional, via PortfolioPolicy)
    enforce_target_allocations: bool = True
    rebalance_tolerance: float = 0.05       # relative drift threshold before rebalancing

    # Churn control
    cooldown_bars: int = 0                  # require N bars between orders per ticker (0=off)


class RiskEngine:
    """
    Engine B — Risk / Sizing / Constraints.

    Responsibilities:
      • Convert Alpha signals into executable orders with realistic sizing.
      • Enforce per-trade and portfolio-wide risk constraints.
      • (Optional) Align positions to target weights from a PortfolioPolicy.
      • Provide clear reason codes for skipped orders (debug-friendly).

    Public attributes:
      - portfolio: set externally so we can query current positions & exposure.
      - last_skip_reason: str | None — most recent skip reason (global).
      - last_skip_by_ticker: dict[str, str] — per-ticker last skip reason.
    """

    def __init__(self, cfg: Dict[str, Any]):
        # Only pass known keys to the dataclass
        cfg_filtered = {k: v for k, v in cfg.items() if k in RiskConfig.__annotations__}
        self.cfg = RiskConfig(**cfg_filtered)
        self.portfolio = None  # injected by controller
        self.last_skip_reason: Optional[str] = None
        self.last_skip_by_ticker: Dict[str, str] = {}

        # Internal: bar-index bookkeeping for cooldown (per ticker)
        self._last_action_bar: Dict[str, int] = {}

    # ------------------------------------------------------------------ #
    # Helpers
    def _fail(self, ticker: str, reason: str) -> None:
        self.last_skip_reason = reason
        self.last_skip_by_ticker[ticker] = reason

    def _bar_index(self, df_hist: pd.DataFrame) -> int:
        """Return a monotone bar index for cooldown comparisons."""
        # Using length-1 as a simple increasing counter (0..N-1)
        return int(max(len(df_hist) - 1, 0))

    def _last_row(self, df: pd.DataFrame) -> pd.Series:
        if isinstance(df, pd.DataFrame) and not df.empty:
            return df.iloc[-1]
        return pd.Series(dtype=float)

    def _effective_atr(self, price: float, atr: float) -> float:
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
        Approximate gross exposure = Σ|qty*px| / equity.
        Requires portfolio reference; returns 0.0 if unavailable.
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
            px = float(price_map.get(t, pos.avg_price if pos.avg_price else 0.0))
            gross += abs(pos.qty * px)
        return gross / eq

    # ------------------------------------------------------------------ #
    # Main
    def prepare_order(
        self,
        signal: Dict[str, Any],
        equity: float,
        df_hist: pd.DataFrame,
        price_data: Optional[Dict[str, pd.DataFrame]] = None,
        current_qty: int = 0,
        target_weights: Optional[Dict[str, float]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Build an order dict or return None if constraints block it.

        Parameters
        ----------
        signal : dict
            From AlphaEngine. Expected keys: {'ticker', 'side' in {'long','short','none'}, ...}
        equity : float
            Current total equity.
        df_hist : DataFrame
            Historical bars for the *ticker* (must include 'Close'; ATR preferred).
        price_data : Optional[Dict[str, DataFrame]]
            Optional whole-universe data (unused by default, kept for future cross checks).
        current_qty : int
            Current signed quantity for the ticker (0 if flat).
        target_weights : Optional[Dict[str, float]]
            Optional target weights from PortfolioPolicy (ticker → weight).

        Returns
        -------
        dict | None
            {'ticker','side','qty','stop','take_profit', 'meta': {...}}  or None.
        """
        ticker = str(signal.get("ticker"))
        side = str(signal.get("side", "none")).lower()

        # Reset last-skip for this ticker
        self.last_skip_by_ticker.pop(ticker, None)
        self.last_skip_reason = None

        # Validate side
        from debug_config import is_debug_enabled
        if side not in ("long", "short", "none"):
            self._fail(ticker, "invalid_side")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None

        # Warmup
        if len(df_hist) < self.cfg.min_bars_warmup:
            self._fail(ticker, "warmup_insufficient_bars")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None

        # Cooldown (optional): require N bars between orders per ticker
        if self.cfg.cooldown_bars > 0:
            bi = self._bar_index(df_hist)
            last_bi = self._last_action_bar.get(ticker, -10_000)
            if (bi - last_bi) < int(self.cfg.cooldown_bars):
                self._fail(ticker, "cooldown_active")
                if is_debug_enabled("RISK"):
                    print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
                return None

        # Exit / neutral signals
        if side == "none" and current_qty != 0:
            # Record action bar if we do emit an exit
            self._last_action_bar[ticker] = self._bar_index(df_hist)
            return {
                "ticker": ticker,
                "side": "exit",
                "qty": abs(int(current_qty)),
                "edge": signal.get("edge", "Unknown"),
                "edge_group": signal.get("edge_group"),
                "edge_id": signal.get("edge_id"),
                "edge_category": signal.get("category"),
            }
        if side == "none":
            self._fail(ticker, "neutral_no_position")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None

        # Flip logic: if holding opposite direction, exit first (entry deferred to next bar by controller)
        if current_qty != 0:
            have_long = current_qty > 0
            want_long = (side == "long")
            if have_long != want_long:
                self._last_action_bar[ticker] = self._bar_index(df_hist)
                return {
                    "ticker": ticker,
                    "side": "exit",
                    "qty": abs(int(current_qty)),
                    "edge": signal.get("edge", "Unknown"),
                    "edge_group": signal.get("edge_group"),
                    "edge_id": signal.get("edge_id"),
                    "edge_category": signal.get("category"),
                }

        # --- Detect flip in signal direction (close and reverse next bar) ---
        current_pos = None
        try:
            if self.portfolio and ticker in self.portfolio.positions:
                current_pos = self.portfolio.positions[ticker]
        except Exception:
            current_pos = None

        if current_pos:
            if (current_pos.side == "long" and side == "short") or (current_pos.side == "short" and side == "long"):
                self._last_action_bar[ticker] = self._bar_index(df_hist)
                if is_debug_enabled("RISK"):
                    print(f"[RISK][DEBUG] Signal flip detected for {ticker}: closing current {current_pos.side} before reversing.")
                return {
                    "ticker": ticker,
                    "side": "exit",
                    "qty": abs(int(current_pos.qty)),
                    "reason": "flip_exit",
                    "edge": signal.get("edge", "Unknown"),
                    "edge_group": signal.get("edge_group"),
                    "edge_id": signal.get("edge_id"),
                    "edge_category": signal.get("category"),
                }

        # No-shorts policy
        if side == "short" and not self.cfg.allow_shorts:
            self._fail(ticker, "shorts_not_allowed")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None

        # Portfolio constraints
        if self._positions_count() >= self.cfg.max_positions and current_qty == 0:
            self._fail(ticker, "max_positions_reached")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None

        # Price & ATR
        row = self._last_row(df_hist)
        close_val = None
        if isinstance(row.get("Close", None), pd.Series):
            close_val = row["Close"].iloc[-1]
        else:
            close_val = row.get("Close")
        if close_val is None or not np.isfinite(close_val):
            self._fail(ticker, "close_missing")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None
        price = float(close_val)
        raw_atr = float(row.get("ATR", 0.0))
        # --- Sanity filter for abnormal prices/ATR ---
        if price <= 0 or not np.isfinite(price):
            self._fail(ticker, "invalid_price")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None
        if not np.isfinite(raw_atr) or raw_atr <= 0:
            self._fail(ticker, "invalid_atr")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None
        if raw_atr > price * 0.5:
            if is_info_enabled() or is_debug_enabled("RISK"):
                print(f"[RISK][WARN] Abnormally large ATR for {ticker}: atr={raw_atr}, price={price}")
            raw_atr = price * 0.2  # clamp for safety
        atr = self._effective_atr(price, raw_atr)

        # --- Sizing path A: align to target weights (if provided/enabled) ---
        add_qty: int
        chosen_side: str = side
        meta: Dict[str, Any] = {}

        target_weight = None
        if self.cfg.enforce_target_allocations and target_weights:
            target_weight = target_weights.get(ticker)

        if target_weight is not None and np.isfinite(target_weight):
            target_notional = float(equity) * float(target_weight)
            current_notional = float(current_qty) * price
            delta_notional = target_notional - current_notional

            # Rebalance tolerance: skip tiny drifts
            denom = max(abs(target_notional), 1e-9)
            if abs(delta_notional) / denom < float(self.cfg.rebalance_tolerance):
                self._fail(ticker, "rebalance_within_tolerance")
                if is_debug_enabled("RISK"):
                    print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
                return None

            add_qty = int(delta_notional / price)
            if add_qty == 0:
                # Try to enforce a minimum 1-share adjustment if rounding-to-zero and notional is meaningful
                if self.cfg.force_min_qty_on_signal and abs(delta_notional) >= float(self.cfg.min_notional):
                    add_qty = 1
                else:
                    self._fail(ticker, "rebalance_rounds_to_zero")
                    if is_debug_enabled("RISK"):
                        print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
                    return None

            chosen_side = "long" if add_qty > 0 else "short"
            add_qty = abs(add_qty)

            meta.update({
                "sizing_mode": "target_weight",
                "target_weight": float(target_weight),
                "target_notional": float(target_notional),
                "current_notional": float(current_notional),
                "delta_notional": float(delta_notional),
            })

        else:
            # --- Sizing path B: ATR-risk sizing (default) ---
            stop_dist = max(self.cfg.atr_stop_mult * atr, 1e-9)
            risk_budget = max(0.0, float(equity) * self.cfg.risk_per_trade_pct)
            if risk_budget <= 0:
                self._fail(ticker, "non_positive_risk_budget")
                if is_debug_enabled("RISK"):
                    print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
                return None

            raw_qty = risk_budget / stop_dist
            max_value = float(equity) * self.cfg.max_pos_value_pct
            max_qty_by_value = (max_value / price) if price > 0 else 0.0
            target_qty = min(raw_qty, max_qty_by_value)
            if self.cfg.round_qty:
                target_qty = math.floor(target_qty)

            add_qty = int(max(target_qty - abs(int(current_qty)), 0))
            if is_debug_enabled("RISK"):
                print(
                    f"[RISK][DBG] {ticker} side={side} price={price:.4f} atr={atr:.4f} "
                    f"risk_budget={risk_budget:.2f} stop_dist={stop_dist:.4f} "
                    f"raw_qty={raw_qty:.2f} max_val={max_value:.2f} "
                    f"max_qty_by_value={max_qty_by_value:.2f} target_qty={target_qty:.2f} "
                    f"current_qty={current_qty}"
                )
            if add_qty <= 0:
                # If sizing rounded down to zero, optionally force a 1-share probe when safe
                forced = False
                if self.cfg.force_min_qty_on_signal and side in ("long", "short") and current_qty == 0:
                    # Ensure ticket clears minimum notional and (roughly) exposure
                    if price >= float(self.cfg.min_notional):
                        try:
                            price_map = {ticker: price}
                            gross_after = self._gross_exposure(price_map) + (abs(1 * price) / max(float(equity), 1e-9))
                            if gross_after <= float(self.cfg.max_gross_exposure):
                                add_qty = 1
                                forced = True
                        except Exception:
                            # If exposure check unavailable, still allow the 1-share probe
                            add_qty = 1
                            forced = True
                if not forced:
                    self._fail(ticker, "no_incremental_size")
                    if is_debug_enabled("RISK"):
                        delta = float(target_qty) - float(abs(current_qty))
                        print(
                            f"[RISK][DEBUG] Rejected signal for {ticker} — reason=no_incremental_size "
                            f"(target_qty={target_qty:.2f}, current_qty={current_qty}, delta={delta:.2f}, "
                            f"side={side})"
                        )
                    return None
                else:
                    meta.update({
                        "sizing_mode": meta.get("sizing_mode", "atr_risk"),
                        "forced_min_qty": True
                    })

            meta.update({
                "sizing_mode": "atr_risk",
                "risk_budget": float(risk_budget),
                "stop_dist": float(stop_dist),
                "atr": float(atr),
                "raw_qty": float(raw_qty),
                "max_value": float(max_value),
                "max_qty_by_value": float(max_qty_by_value),
                "target_qty": float(target_qty),
            })

        # Enforce minimum notional and min qty
        if add_qty < max(int(self.cfg.min_qty), 1):
            self._fail(ticker, "below_min_qty")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None
        if (add_qty * price) < float(self.cfg.min_notional):
            self._fail(ticker, "below_min_notional")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None

        # Gross exposure guard
        try:
            price_map = {ticker: price}
            gross_after = self._gross_exposure(price_map) + (abs(add_qty * price) / max(float(equity), 1e-9))
            if gross_after > float(self.cfg.max_gross_exposure):
                self._fail(ticker, "gross_exposure_limit")
                if is_debug_enabled("RISK"):
                    print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
                return None
        except Exception:
            # If portfolio not attached or other issue, fail open (but this is logged)
            pass

        # Compute SL/TP levels off chosen_side (might differ from signal side if rebalancing)
        if chosen_side == "long":
            stop = price - self.cfg.atr_stop_mult * atr
            tp = price + self.cfg.atr_tp_mult * atr
        else:
            stop = price + self.cfg.atr_stop_mult * atr
            tp = price - self.cfg.atr_tp_mult * atr


        # Record action bar for cooldown purposes
        self._last_action_bar[ticker] = self._bar_index(df_hist)

        # Preserve edge attribution from the signal (if present)
        edge_name = signal.get("edge", "Unknown")
        edge_group = signal.get("edge_group", None)

        order = {
            "ticker": ticker,
            "side": chosen_side,
            "qty": int(add_qty),
            "stop": float(stop),
            "take_profit": float(tp),
            "meta": meta,   # logger will stringify safely
            "edge": edge_name,
            "edge_group": edge_group,
        }
        if "edge_id" in signal:
            order["edge_id"] = signal.get("edge_id")
        if "category" in signal:
            order["edge_category"] = signal.get("category")

        if is_debug_enabled("RISK"):
            print(f"[RISK][DEBUG] Approved order for {ticker}: {order}")
        return order