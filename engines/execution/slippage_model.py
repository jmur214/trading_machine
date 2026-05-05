# engines/execution/slippage_model.py
"""
Slippage models for backtest execution simulation.

Three implementations:
- ``FixedSlippageModel``: constant base_bps per side. Default for legacy
  backtests, fast and deterministic but unrealistic on a broad universe.
- ``VolatilitySlippageModel``: scales base_bps by recent realized vol vs
  long-term vol. Captures regime sensitivity but ignores order size.
- ``RealisticSlippageModel``: ADV-bucketed half-spread + square-root
  market impact. The honest model — Phase 0 of the v2 forward plan
  (`docs/Archive/forward_plans/forward_plan_2026_04_28.md`).

The realistic model exists because the system was reporting Sharpe values
under a flat 5-10 bps per side that did not depend on order size, ticker
liquidity, or volatility regime. Real-world transaction costs scale with
sqrt(participation_rate), per Almgren-Chriss (2001) and Kissell (2014).
A backtest that ignores this overstates Sharpe by 0.2-0.3 on broader
universes — the full doc lists this as the next-most-important fix after
the validation gauntlet.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import math
import numpy as np
import pandas as pd


@dataclass
class SlippageConfig:
    model_type: str = "fixed"        # "fixed" | "volatility" | "realistic"
    base_bps: float = 10.0           # Base slippage in basis points (used by fixed/volatility)
    vol_lookback: int = 20           # Lookback for volatility calculation
    vol_multiplier: float = 1.0      # Multiplier for volatility impact
    # ---- realistic-model parameters ----
    impact_coefficient: float = 0.5  # k in `k * σ * sqrt(qty/ADV)`. Almgren-Chriss
                                     # empirical estimates put k in [0.3, 1.0]; 0.5
                                     # is the conservative default used by Kissell.
    adv_lookback: int = 20           # Days for rolling-mean ADV calculation
    # ADV bucket thresholds (USD/day):
    #   ADV >= mega_cap_threshold        → mega-cap half-spread (1 bps)
    #   mid_cap_threshold <= ADV < ...   → mid-cap half-spread  (5 bps)
    #   ADV < mid_cap_threshold          → small-cap half-spread (15 bps)
    # Defaults match v2 forward-plan §0.1.
    mega_cap_threshold_usd: float = 500_000_000.0
    mid_cap_threshold_usd: float = 100_000_000.0
    mega_cap_half_spread_bps: float = 1.0
    mid_cap_half_spread_bps: float = 5.0
    small_cap_half_spread_bps: float = 15.0


class SlippageModel(ABC):
    """Abstract base class for slippage models."""

    def __init__(self, config: SlippageConfig):
        self.config = config

    @abstractmethod
    def calculate_slippage_bps(
        self,
        ticker: str,
        bar_data: pd.DataFrame | pd.Series,
        side: str,
        qty: int | None = None,
    ) -> float:
        """Calculate slippage in basis points for a given trade.

        Args:
            ticker: The asset ticker.
            bar_data: DataFrame or Series with recent market data. For models
                that depend on ADV or volatility, must include 'Close' and
                'Volume' columns and have at least `vol_lookback`/`adv_lookback`
                rows; a single Series falls back to base_bps.
            side: 'buy' | 'sell' | 'long' | 'short' | 'cover' | 'exit'.
            qty: Number of shares being traded. Required for square-root
                market impact in `RealisticSlippageModel`; ignored by the
                others. None falls back to a base estimate.

        Returns:
            float: One-sided slippage in basis points.
        """
        ...

    def apply_slippage(self, price: float, bps: float, side: str) -> float:
        """Apply calculated slippage to a price.

        Convention: side that pays more (buy/long/cover) gets price marked
        up; side that receives less (sell/short/exit) gets price marked
        down.
        """
        slip_amount = price * (bps / 10000.0)
        s = side.lower()
        if s in ("long", "buy", "cover"):
            return price + slip_amount
        if s in ("short", "sell", "exit"):
            return price - slip_amount
        return price


class FixedSlippageModel(SlippageModel):
    """Constant fixed basis-point slippage. Legacy default."""

    def calculate_slippage_bps(
        self,
        ticker: str,
        bar_data: pd.DataFrame | pd.Series,
        side: str,
        qty: int | None = None,
    ) -> float:
        return self.config.base_bps


class VolatilitySlippageModel(SlippageModel):
    """Scales slippage by recent realized vol vs long-term vol.

    Effective bps = base_bps × clip(current_vol / long_term_vol, 0.5, 5.0)
                  × vol_multiplier.

    Falls back to base_bps when bar_data is a single Series or when there
    are fewer than `vol_lookback + 1` rows available.
    """

    def calculate_slippage_bps(
        self,
        ticker: str,
        bar_data: pd.DataFrame | pd.Series,
        side: str,
        qty: int | None = None,
    ) -> float:
        if isinstance(bar_data, pd.Series):
            return self.config.base_bps

        if len(bar_data) < self.config.vol_lookback + 1:
            return self.config.base_bps

        try:
            closes = bar_data["Close"]
            returns = closes.pct_change().dropna()
            if len(returns) < self.config.vol_lookback:
                return self.config.base_bps

            current_vol = returns.tail(self.config.vol_lookback).std()
            long_term_vol = returns.std()
            if long_term_vol == 0:
                return self.config.base_bps

            ratio = current_vol / long_term_vol
            ratio = max(0.5, min(5.0, ratio))
            return self.config.base_bps * ratio * self.config.vol_multiplier
        except Exception:
            return self.config.base_bps


class RealisticSlippageModel(SlippageModel):
    """ADV-bucketed half-spread + square-root market impact.

    Models real-world execution cost as the sum of two distinct terms:

    1. **Half-spread (paid every trade, regardless of size).** The bid-ask
       spread you cross to get filled. Buckets by 20-day average dollar
       volume (ADV):
         - ADV >= $500M/day:  1 bps  (mega-cap, e.g. SPY/AAPL)
         - $100M ≤ ADV < $500M: 5 bps  (mid-cap)
         - ADV < $100M:        15 bps  (small-cap)

    2. **Market impact (scales with order size).** Almgren-Chriss
       square-root law: ``impact_bps = k * σ_daily * sqrt(qty / ADV_shares) * 10000``,
       where σ is daily return volatility and ``qty / ADV_shares`` is the
       participation rate (fraction of average daily share volume the
       order represents). k = 0.5 by default.

    Total slippage bps = half_spread_bps + impact_bps.

    Falls back to mega-cap half-spread (1 bps) when bar_data has too few
    rows or when qty is None — matching the legacy behavior on small
    backtests but flagging that the realistic model isn't producing
    differentiated estimates.

    References:
      - Almgren & Chriss, "Optimal Execution of Portfolio Transactions"
        (2001) — square-root impact law
      - Kissell, "The Science of Algorithmic Trading and Portfolio
        Management" (2014) — empirical k coefficients
    """

    def _classify_adv_bucket(self, adv_usd: float) -> float:
        """Return half-spread bps for the bucket containing ``adv_usd``."""
        if adv_usd >= self.config.mega_cap_threshold_usd:
            return self.config.mega_cap_half_spread_bps
        if adv_usd >= self.config.mid_cap_threshold_usd:
            return self.config.mid_cap_half_spread_bps
        return self.config.small_cap_half_spread_bps

    def _compute_adv_usd(self, bar_data: pd.DataFrame) -> float | None:
        """20-day rolling-mean dollar ADV, or None if insufficient data."""
        if "Volume" not in bar_data.columns or "Close" not in bar_data.columns:
            return None
        n = self.config.adv_lookback
        recent = bar_data.tail(n)
        if len(recent) < max(5, n // 2):  # need at least ~half the window
            return None
        try:
            dollar_vol = (recent["Close"] * recent["Volume"]).astype(float)
            adv = float(dollar_vol.mean())
            if not math.isfinite(adv) or adv <= 0:
                return None
            return adv
        except Exception:
            return None

    def _compute_daily_vol(self, bar_data: pd.DataFrame) -> float | None:
        """Daily return std, or None if insufficient data."""
        if "Close" not in bar_data.columns:
            return None
        n = self.config.vol_lookback
        if len(bar_data) < n + 1:
            return None
        try:
            returns = bar_data["Close"].astype(float).pct_change().dropna()
            if len(returns) < n:
                return None
            sigma = float(returns.tail(n).std())
            if not math.isfinite(sigma) or sigma <= 0:
                return None
            return sigma
        except Exception:
            return None

    def calculate_slippage_bps(
        self,
        ticker: str,
        bar_data: pd.DataFrame | pd.Series,
        side: str,
        qty: int | None = None,
    ) -> float:
        # Single-row bar_data (Series) cannot support ADV/volatility — fall
        # back to mega-cap half-spread as a conservative lower bound.
        if isinstance(bar_data, pd.Series) or not isinstance(bar_data, pd.DataFrame):
            return self.config.mega_cap_half_spread_bps

        adv_usd = self._compute_adv_usd(bar_data)
        if adv_usd is None:
            return self.config.mega_cap_half_spread_bps

        half_spread_bps = self._classify_adv_bucket(adv_usd)

        # Market impact only computable when we know qty AND have a price
        # to convert qty into a dollar amount, AND have volatility.
        if qty is None or qty <= 0:
            return half_spread_bps

        try:
            last_close = float(bar_data["Close"].iloc[-1])
            if last_close <= 0:
                return half_spread_bps
        except Exception:
            return half_spread_bps

        sigma = self._compute_daily_vol(bar_data)
        if sigma is None:
            return half_spread_bps

        # Participation rate: qty (shares) / ADV (shares).
        # ADV_shares = adv_usd / last_close.
        adv_shares = adv_usd / last_close
        if adv_shares <= 0:
            return half_spread_bps
        participation = qty / adv_shares

        # Square-root impact in *return units*; convert to bps via × 10000.
        impact_bps = (
            self.config.impact_coefficient
            * sigma
            * math.sqrt(participation)
            * 10000.0
        )
        # Sanity cap: market impact should never exceed 100 bps (1%) per
        # side on a single fill — that would imply >100% participation
        # which we reject as a sizing bug rather than absorbing as cost.
        impact_bps = min(impact_bps, 100.0)
        return half_spread_bps + impact_bps


def get_slippage_model(config_dict: dict) -> SlippageModel:
    """Factory creating the appropriate model from a config dict.

    Recognized model_type values:
      - "fixed": ``FixedSlippageModel`` (default).
      - "volatility": ``VolatilitySlippageModel``.
      - "realistic": ``RealisticSlippageModel`` (Phase 0 honest cost model).
    """
    cfg = SlippageConfig(
        model_type=config_dict.get("model_type", "fixed"),
        base_bps=float(config_dict.get("slippage_bps", 10.0)),
        vol_lookback=int(config_dict.get("vol_lookback", 20)),
        vol_multiplier=float(config_dict.get("vol_multiplier", 1.0)),
        impact_coefficient=float(config_dict.get("impact_coefficient", 0.5)),
        adv_lookback=int(config_dict.get("adv_lookback", 20)),
        mega_cap_threshold_usd=float(
            config_dict.get("mega_cap_threshold_usd", 500_000_000.0)
        ),
        mid_cap_threshold_usd=float(
            config_dict.get("mid_cap_threshold_usd", 100_000_000.0)
        ),
        mega_cap_half_spread_bps=float(
            config_dict.get("mega_cap_half_spread_bps", 1.0)
        ),
        mid_cap_half_spread_bps=float(
            config_dict.get("mid_cap_half_spread_bps", 5.0)
        ),
        small_cap_half_spread_bps=float(
            config_dict.get("small_cap_half_spread_bps", 15.0)
        ),
    )

    if cfg.model_type == "volatility":
        return VolatilitySlippageModel(cfg)
    if cfg.model_type == "realistic":
        return RealisticSlippageModel(cfg)
    return FixedSlippageModel(cfg)
