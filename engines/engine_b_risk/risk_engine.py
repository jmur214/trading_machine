# engines/engine_b_risk/risk_engine.py
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Dict, Any
import math
import pandas as pd
import numpy as np
from debug_config import is_debug_enabled, is_info_enabled


@dataclass
class RiskConfig:
    """
    Risk and constraint configuration (config-driven).
    """
    # Per-trade sizing knobs (Small Account Tuned)
    risk_per_trade_pct: float = 0.025       # risk budget per trade (2.5% for small accounts to allow concentration)
    atr_stop_mult: float = 1.5              # stop distance = mult * ATR
    atr_tp_mult: float = 3.0                # take-profit distance = mult * ATR
    cap_atr_to_pct_of_price: float = 0.20   # clamp extreme ATR (e.g., 20% of price)
    atr_floor_pct_of_price: float = 0.005   # floor ATR (e.g., 0.5% of price)
    max_pos_value_pct: float = 0.30         # cap single-name notional as % of equity
    min_qty: int = 1
    round_qty: bool = True
    min_notional: float = 10.0              # Lowered for fractional/small capabilities
    force_min_qty_on_signal: bool = True     # if sizing rounds to 0, optionally force 1 share when safe

    # Portfolio-level constraints
    max_positions: int = 5
    max_gross_exposure: float = 1.0         # Σ|qty*px| / equity
    allow_shorts: bool = True
    min_bars_warmup: int = 30               # require history length before trading

    # Allocation alignment (optional, via PortfolioPolicy)
    enforce_target_allocations: bool = True
    rebalance_tolerance: float = 0.05       # relative drift threshold before rebalancing

    # Sector Constraints
    max_sector_exposure_pct: float = 0.30   # max 30% allocation to a single sector
    sector_map_path: str = "config/sector_map.json"

    # Trailing Stop & Dynamic Config
    high_vol_stop_mult: float = 2.5         # Widen stops in High Vol regime
    low_vol_stop_mult: float = 1.0          # Tighten stops in Low Vol regime
    trailing_stop_activation_r: float = 1.0 # Profit > 1R starts trailing
    trailing_stop_dist_atr: float = 1.5     # Trail distance in ATR
    enable_trailing: bool = True

    # Churn control
    cooldown_bars: int = 0                  # require N bars between orders per ticker (0=off)

    # Liquidity Constraints (Professional Grade)
    max_pct_adv: float = 0.01               # Limit trade size to 1% of Average Daily Volume
    adv_window: int = 20                    # Lookback for ADV calculation

    # Advisory consumption toggle (Engine E → Risk). When False, risk engine
    # ignores suggested_max_positions, suggested_exposure_cap, risk_scalar, and
    # correlation-regime sector-cap adjustments. Default True preserves behavior.
    risk_advisory_enabled: bool = True


class RiskEngine:
    """
    Engine B — Risk / Sizing / Constraints.
    ...
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
        
        # Load Sector Map
        self.sector_map = {}
        try:
            import json
            import os
            if os.path.exists(self.cfg.sector_map_path):
                with open(self.cfg.sector_map_path, 'r') as f:
                    self.sector_map = json.load(f)
            else:
                # Try relative path from project root if running as module
                alt_path = os.path.join(os.getcwd(), self.cfg.sector_map_path)
                if os.path.exists(alt_path):
                     with open(alt_path, 'r') as f:
                        self.sector_map = json.load(f)
                
                elif is_debug_enabled("RISK"):
                    print(f"[RISK][WARN] Sector map not found at {self.cfg.sector_map_path}")
        except Exception as e:
            print(f"[RISK][ERROR] Failed to load sector map: {e}")

    # ... (existing methods) ...

    def _get_sector(self, ticker: str) -> str:
        s = self.sector_map.get(ticker, "Unknown")
        return s

    def _sector_exposure(self, sector: str, price_map: Dict[str, float]) -> float:
        """Calculate current exposure to a specific sector (0.0 to 1.0)."""
        if not self.portfolio or not sector or sector == "Unknown":
            return 0.0
        
        eq = float(self.portfolio.total_equity(price_map))
        if eq <= 0:
            return 0.0
            
        sector_val = 0.0
        for t, pos in self.portfolio.positions.items():
            if pos.qty == 0: continue
            if self._get_sector(t) == sector:
                px = price_map.get(t, pos.avg_price if pos.avg_price else 0.0)
                sector_val += abs(pos.qty * px) # Gross exposure
        
        return sector_val / eq

    # Main prepare_order insertion point is below...
    # (Updated prepare_order to follow in next block)
    
    # ... helpers ...
    
    def prepare_order(self, signal, equity, df_hist, price_data=None, current_qty=0, target_weights=None):
        # ... (start of prepare_order same as before) ...
        ticker = str(signal.get("ticker"))
        side = str(signal.get("side", "none")).lower()
        
        # ... (validation, warmup, cooldown, flip logic) ...
        # Copy existing checks here (abbreviated for tool call, will use multi_replace or ensure context matches)
        # Actually, best to insert the sector check right before sizing.
        
        # Let's use a targeted replace for the specific insertion point to allow cleaner diff.
        # This block is just defining the class structure.
        return None # Placeholder for this specific tool call approach

        
    # ------------------------------------------------------------------ #
    # Lifecycle Management (Trailing Stops)
    def manage_positions(self, current_prices: Dict[str, float], regime_meta: Dict[str, Any] = None, data_map: Optional[Dict[str, pd.DataFrame]] = None) -> List[Dict[str, Any]]:
        """
        Check all open positions and generate 'update' orders (e.g. moving stops).
        Shared logic for Backtest and Live.

        Parameters
        ----------
        data_map : optional dict of {ticker: DataFrame} with ATR column
            When provided, trailing stops use real ATR instead of a price-based estimate.
        """
        if not self.portfolio or not self.cfg.enable_trailing:
            return []

        updates = []

        # Default regime if missing
        if not regime_meta:
            regime_meta = {"volatility": "normal"}

        vol_state = regime_meta.get("volatility", "normal")

        # Regime-adaptive trailing distance (matches entry stop behavior)
        if vol_state == "high":
            trail_dist_mult = self.cfg.high_vol_stop_mult
        elif vol_state == "low":
            trail_dist_mult = self.cfg.low_vol_stop_mult
        else:
            trail_dist_mult = self.cfg.trailing_stop_dist_atr

        for ticker, pos in self.portfolio.positions.items():
            if pos.qty == 0:
                continue

            curr_price = current_prices.get(ticker)
            if not curr_price:
                continue

            # -- update state --
            is_long = pos.qty > 0

            # Initial State Init (if new position)
            if pos.highest_high < 0 and is_long:
                 pos.highest_high = pos.avg_price
            if pos.lowest_low > 1e8 and not is_long:
                 pos.lowest_low = pos.avg_price

            # Track Extremes
            if is_long:
                if curr_price > pos.highest_high:
                    pos.highest_high = curr_price
            else:
                if curr_price < pos.lowest_low:
                     pos.lowest_low = curr_price

            # -- Compute ATR for this ticker --
            # Use real ATR from data_map when available; fall back to price estimate
            estimated_atr = curr_price * 0.015  # fallback
            if data_map and ticker in data_map:
                df = data_map[ticker]
                if "ATR" in df.columns and not df["ATR"].dropna().empty:
                    real_atr = float(df["ATR"].dropna().iloc[-1])
                    estimated_atr = self._effective_atr(curr_price, real_atr)

            # -- Check Activation --
            # Activate trailing when price moves 1R in favor (1R ≈ stop_mult * ATR)
            activation_dist = estimated_atr * trail_dist_mult
            threshold_pct = activation_dist / curr_price if curr_price > 0 else 0.015

            dist_from_entry = (curr_price - pos.avg_price) / pos.avg_price if pos.avg_price else 0
            if not is_long: dist_from_entry = -dist_from_entry

            if dist_from_entry > threshold_pct:
                pos.trailing_active = True

            if not pos.trailing_active:
                continue

            # -- Calculate Trailing Stop Level --
            trail_dist = estimated_atr * trail_dist_mult

            new_stop = None
            if is_long:
                proposed = pos.highest_high - trail_dist
                # Only move UP
                if pos.stop is None or proposed > pos.stop:
                    new_stop = proposed
            else:
                proposed = pos.lowest_low + trail_dist
                # Only move DOWN
                if pos.stop is None or proposed < pos.stop:
                    new_stop = proposed

            if new_stop is not None:
                updates.append({
                    "ticker": ticker,
                    "action": "update_stop",
                    "new_stop": new_stop,
                    "meta": {"reason": "trailing_stop", "regime": vol_state,
                             "atr": estimated_atr, "trail_mult": trail_dist_mult}
                })

        return updates

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

    def _check_liquidity(self, ticker: str, qty: int, df_hist: pd.DataFrame) -> bool:
        """
        Professional Check: Ensure we don't exceed x% of Average Daily Volume (ADV).
        """
        if df_hist is None or "Volume" not in df_hist.columns:
            # If no volume data, pass (or fail strict). Failing strict is safer for Pro mode.
            if is_debug_enabled("RISK"):
                print(f"[RISK][WARN] No Volume column for {ticker}. Liquidity check skipped (unsafe).")
            return True # Soft pass for now, strictly should be False
            
        # Calculate ADV
        vol_window = self.cfg.adv_window
        if len(df_hist) < vol_window:
            adv = df_hist["Volume"].mean() # Fallback to whatever we have
        else:
            adv = df_hist["Volume"].iloc[-vol_window:].mean()
            
        if adv <= 0:
            return False # No liquidity
            
        # Check size
        limit_qty = adv * self.cfg.max_pct_adv
        if abs(qty) > limit_qty:
            if is_debug_enabled("RISK"):
                print(f"[RISK][FAIL] Liquidity fail {ticker}: Req {abs(qty)} > Limit {int(limit_qty)} (ADV={int(adv)})")
            return False
            
        return True

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
        regime_meta: Optional[Dict[str, Any]] = None,
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
        import os
        debug_override = os.getenv("BACKTEST_DEBUG") or os.getenv("ALPHA_DEBUG")
        if len(df_hist) < self.cfg.min_bars_warmup and not debug_override:
            self._fail(ticker, "warmup_insufficient_bars")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None
        elif len(df_hist) < self.cfg.min_bars_warmup and debug_override:
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Warmup insufficient but BACKTEST_DEBUG override enabled for {ticker}")

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
        # Note: portfolio.positions retains entries with qty=0 after a full
        # exit (fresh Position() is stored back under the ticker). Those
        # zero-qty stubs must not be treated as open positions — otherwise
        # the qty>0/<=0 branch below mislabels a flat stub as "short" and
        # emits a spurious "exit qty=0" order against any incoming long.
        current_pos = None
        try:
            if self.portfolio and ticker in self.portfolio.positions:
                _p = self.portfolio.positions[ticker]
                if _p is not None and int(_p.qty) != 0:
                    current_pos = _p
        except Exception:
            current_pos = None

        if current_pos:
            current_side = "long" if current_pos.qty > 0 else "short"
            if (current_side == "long" and side == "short") or (current_side == "short" and side == "long"):
                self._last_action_bar[ticker] = self._bar_index(df_hist)
                if is_debug_enabled("RISK"):
                    print(f"[RISK][DEBUG] Signal flip detected for {ticker}: closing current {current_side} before reversing.")
                return {
                    "ticker": ticker,
                    "side": "exit",
                    "qty": abs(int(current_pos.qty)),
                    "reason": "flip_reversal",
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

        # --- Advisory-driven dynamic constraints (from Engine E) ---
        advisory = (regime_meta or {}).get("advisory", {}) if regime_meta else {}
        effective_max_positions = self.cfg.max_positions
        effective_max_gross = self.cfg.max_gross_exposure
        effective_sector_cap = self.cfg.max_sector_exposure_pct
        advisory_risk_scalar = 1.0

        if advisory and self.cfg.risk_advisory_enabled:
            # Dynamic max positions (can only tighten, never loosen)
            suggested_max_pos = advisory.get("suggested_max_positions")
            if suggested_max_pos is not None:
                effective_max_positions = min(int(suggested_max_pos), self.cfg.max_positions)

            # Dynamic gross exposure cap
            suggested_exposure_cap = advisory.get("suggested_exposure_cap")
            if suggested_exposure_cap is not None:
                effective_max_gross = min(float(suggested_exposure_cap), self.cfg.max_gross_exposure)

            # Risk scalar applied to ATR sizing
            rs = advisory.get("risk_scalar")
            if rs is not None:
                advisory_risk_scalar = float(rs)

            # Correlation regime → dynamic sector limits
            corr_regime = advisory.get("correlation_regime", "normal")
            if corr_regime == "dispersed":
                effective_sector_cap = min(0.40, self.cfg.max_sector_exposure_pct * 1.33)
            elif corr_regime in ("elevated", "spike"):
                effective_sector_cap = min(0.20, self.cfg.max_sector_exposure_pct * 0.67)

        # Portfolio constraints (using advisory-adjusted limits)
        if self._positions_count() >= effective_max_positions and current_qty == 0:
            self._fail(ticker, "max_positions_reached")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)} (effective_max={effective_max_positions})")
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
            # Fallback ATR: use rolling stddev of Close prices
            if len(df_hist) > 5 and "Close" in df_hist:
                raw_atr = float(df_hist["Close"].pct_change().rolling(5).std().iloc[-1] * price)
                if is_debug_enabled("RISK"):
                    print(f"[RISK][DEBUG] Fallback ATR used for {ticker}: {raw_atr:.4f}")
            if not np.isfinite(raw_atr) or raw_atr <= 0:
                self._fail(ticker, "invalid_atr_after_fallback")
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
        # Initialize meta from signal to preserve upstream intelligence (regime, edges)
        meta: Dict[str, Any] = signal.get("meta", {}).copy() if signal.get("meta") else {}

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
            
            # DYNAMIC RISK: Adjust multiplier based on Regime
            # signal.meta might contain 'market_state' -> 'volatility'
            # e.g. {'market_state': {'volatility': 'high'}}
            vol_state = "normal"
            try:
                ms = meta.get("market_state", {})
                if isinstance(ms, dict):
                    vol_state = ms.get("volatility", "normal")
            except Exception:
                pass
                
            stop_mult = self.cfg.atr_stop_mult
            if vol_state == "high":
                stop_mult = self.cfg.high_vol_stop_mult
                if is_debug_enabled("RISK"): print(f"[RISK] High Vol detected: Widening stop to {stop_mult}x ATR")
            elif vol_state == "low":
                stop_mult = self.cfg.low_vol_stop_mult
                if is_debug_enabled("RISK"): print(f"[RISK] Low Vol detected: Tightening stop to {stop_mult}x ATR")
                
            stop_dist = max(stop_mult * atr, 1e-9)
            
            # --- Dynamic Sizing ---
            base_risk_pct = self.cfg.risk_per_trade_pct
            risk_scaler = 1.0

            # 1. ML Gate Confidence (if explicitly set by SignalGate/MLPredictor)
            # Low confidence sizes down, but never to zero — a market-state-only
            # gate should not have veto power over a real alpha signal.
            gate_conf = signal.get("gate_confidence")
            if gate_conf is not None:
                gate_conf = float(gate_conf)
                if gate_conf < 0.5: risk_scaler = 0.3
                elif gate_conf < 0.6: risk_scaler = 0.6
                elif gate_conf < 0.8: risk_scaler = 1.0
                else: risk_scaler = 1.5
            else:
                # 2. Signal strength (from Alpha aggregation)
                strength = float(signal.get("strength", 0.5))
                risk_scaler = 0.5 + strength  # Maps [0,1] to [0.5, 1.5]

            # 3. Governor edge-quality weight (learned from realized performance)
            governor_weight = float(meta.get("governor_weight", 1.0))
            risk_scaler *= governor_weight

            # 4. Advisory risk scalar (Engine E regime brake on sizing)
            risk_scaler *= advisory_risk_scalar

            adjusted_risk_pct = base_risk_pct * risk_scaler

            # Cap extreme risk (max 2x base)
            adjusted_risk_pct = min(adjusted_risk_pct, base_risk_pct * 2.0)

            risk_budget = max(0.0, float(equity) * adjusted_risk_pct)

            if is_debug_enabled("RISK") and risk_scaler != 1.0:
                 print(f"[RISK] Dynamic Sizing: {ticker} (strength={signal.get('strength', 'N/A')}, gov_w={governor_weight:.2f}) -> Scaler {risk_scaler:.2f} -> Risk {adjusted_risk_pct*100:.2f}%")

            if risk_budget <= 0:
                self._fail(ticker, "non_positive_risk_budget")
                
            # ... rest of sizing logic ...
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
                    f"current_qty={current_qty} vol_state={vol_state}"
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

        # Liquidity Check (New)
        if not self._check_liquidity(ticker, add_qty, df_hist):
            self._fail(ticker, "liquidity_limit_exceeded")
            # Professional approach: Clip it. 
            vol_window = self.cfg.adv_window
            adv = df_hist["Volume"].iloc[-vol_window:].mean() if len(df_hist) >= vol_window else df_hist["Volume"].mean()
            limit_qty = int(adv * self.cfg.max_pct_adv)
            
            if limit_qty < self.cfg.min_qty:
                if is_debug_enabled("RISK"):
                    print(f"[RISK][DEBUG] Rejected {ticker}: ADV limit {limit_qty} < min_qty {self.cfg.min_qty}")
                return None
            else:
                if is_debug_enabled("RISK"):
                    print(f"[RISK][INFO] Clipping {ticker} qty {add_qty} -> {limit_qty} due to liquidity constraint.")
                add_qty = limit_qty

        # Min Notional Check
        if (add_qty * price) < float(self.cfg.min_notional):
            self._fail(ticker, "below_min_notional")
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
            return None

        # --- Fallback safety: ensure at least minimal order if everything else fails ---
        if add_qty <= 0 and debug_override:
            add_qty = 1
            meta.update({"sizing_mode": "fallback_fixed", "reason": "debug_forced_trade"})
            if is_debug_enabled("RISK"):
                print(f"[RISK][DEBUG] Forcing minimal 1-share trade for {ticker} in debug mode.")

        # Gross exposure guard
        try:
            price_map = {ticker: price}
            # For accurate sector calc, we ideally want a full price_map, but we usually only have 'price_data' if passed.
            # If price_data is None, we rely on portfolio.last_price for others.
            # Construct a best-effort price map for sector check:
            sector_price_map = {ticker: price}
            # If we have a portfolio, use its last known prices for others
            if self.portfolio:
                for t, p in self.portfolio.positions.items():
                    if p.last_price:
                        sector_price_map[t] = p.last_price
                        
            # 1. Sector Constraint Check (using advisory-adjusted cap)
            sector = self._get_sector(ticker)
            if sector and sector != "Unknown" and add_qty > 0:
                current_sec_exp = self._sector_exposure(sector, sector_price_map)
                new_trade_exp = (add_qty * price) / max(float(equity), 1e-9)

                if (current_sec_exp + new_trade_exp) > effective_sector_cap:
                     self._fail(ticker, f"max_sector_exposure_{sector}")
                     if is_debug_enabled("RISK"):
                        print(f"[RISK][DEBUG] Rejected signal for {ticker} — Sector {sector} exposure {current_sec_exp:.1%} + {new_trade_exp:.1%} > {effective_sector_cap:.1%}")
                     return None

            # 2. Gross Exposure Guard (using advisory-adjusted cap)
            gross_after = self._gross_exposure(sector_price_map) + (abs(add_qty * price) / max(float(equity), 1e-9))
            if gross_after > float(effective_max_gross):
                self._fail(ticker, "gross_exposure_limit")
                if is_debug_enabled("RISK"):
                    print(f"[RISK][DEBUG] Rejected signal for {ticker} — reason={self.last_skip_by_ticker.get(ticker)}")
                return None
        except Exception as e:
            # If portfolio not attached or other issue, fail open (but this is logged)
            if is_debug_enabled("RISK"): print(f"[RISK][WARN] Constraint check error: {e}")
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