# backtester/borrow_rate_model.py
"""
Borrow rate model for short-position carrying costs.

Real short positions accrue borrow fees daily, charged by the broker /
prime. Rates vary widely:
  - Liquid mega-caps (AAPL, SPY, QQQ): ~5 bps/day (≈12.6% annualized)
  - Mid-caps:                          ~15 bps/day (≈37.8% annualized)
  - Hard-to-borrow / small-cap:        ~50+ bps/day (≈126%+ annualized)

ArchonDEX previously omitted borrow drag entirely. For long-only or
mostly-long ensembles the omission is small, but the moment any short
edge runs, the per-day cost compounds visibly. Including it is required
before claiming "beats SPY net of realistic costs."

Design:
  - A standalone post-processor: given the snapshot history (per-day
    equity + open positions) plus per-ticker price/volume data, compute
    daily borrow drag in dollars.
  - ADV-bucketed defaults that match ``RealisticSlippageModel`` so the
    classification is consistent across the cost stack.
  - Per-ticker overrides accepted via ``per_ticker_bps_per_day`` for
    known hard-to-borrow names.
  - Returns a ``pd.Series`` of cumulative drag indexed by snapshot
    timestamp, suitable for subtraction from the original equity curve.

Engine boundary: this is backtester territory, not Engine B (Risk). The
risk engine sizes positions; the cost layer accounts for what those
positions cost to hold. They are deliberately separate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, Mapping, Optional
import math

import numpy as np
import pandas as pd


@dataclass
class BorrowRateConfig:
    """Configuration for ``BorrowRateModel``.

    bps/day defaults are chosen to be conservative for retail accounts;
    real prime-broker rates for liquid mega-caps run 1-3 bps/day, but
    retail brokers (Alpaca, IBKR) typically charge a markup. 5 bps is the
    Alpaca-style midpoint.
    """

    enabled: bool = True
    # ADV-bucketed bps/day defaults (apply to dollar value of short
    # position). Buckets match RealisticSlippageModel thresholds.
    mega_cap_bps_per_day: float = 5.0    # ≈12.6%/yr
    mid_cap_bps_per_day: float = 15.0    # ≈37.8%/yr
    small_cap_bps_per_day: float = 50.0  # ≈126%/yr
    mega_cap_threshold_usd: float = 500_000_000.0
    mid_cap_threshold_usd: float = 100_000_000.0
    adv_lookback: int = 20
    # Optional per-ticker overrides — bps/day. Useful for known hard-to-
    # borrow names where the bucket misclassifies (e.g. squeezed small
    # floats trading > $500M ADV but still costing 100+ bps/day).
    per_ticker_bps_per_day: Mapping[str, float] = field(default_factory=dict)
    # Treat trading days as 252/year for the annualized headline number.
    trading_days_per_year: int = 252


class BorrowRateModel:
    """Per-day borrow drag on short positions.

    Use as a post-processor:

        model = BorrowRateModel(BorrowRateConfig(...))
        drag = model.compute_daily_drag(snapshots, price_data_map)
        adjusted_equity = snapshots["equity"] - drag.cumsum()
    """

    def __init__(self, config: Optional[BorrowRateConfig] = None):
        self.config = config or BorrowRateConfig()

    # ------------------------------------------------------------------ #
    # ADV bucketing
    # ------------------------------------------------------------------ #
    def _bucket_bps_per_day(self, adv_usd: float) -> float:
        cfg = self.config
        if adv_usd >= cfg.mega_cap_threshold_usd:
            return cfg.mega_cap_bps_per_day
        if adv_usd >= cfg.mid_cap_threshold_usd:
            return cfg.mid_cap_bps_per_day
        return cfg.small_cap_bps_per_day

    def get_bps_per_day(
        self,
        ticker: str,
        adv_usd: Optional[float] = None,
    ) -> float:
        """Resolve borrow rate for ``ticker`` in bps/day.

        Resolution order:
          1. Per-ticker override (if present) — wins.
          2. ADV bucket (if ``adv_usd`` provided).
          3. Mid-cap rate as a conservative fallback.
        """
        cfg = self.config
        if ticker in cfg.per_ticker_bps_per_day:
            return float(cfg.per_ticker_bps_per_day[ticker])
        if adv_usd is None or not math.isfinite(adv_usd) or adv_usd <= 0:
            return cfg.mid_cap_bps_per_day
        return self._bucket_bps_per_day(adv_usd)

    # ------------------------------------------------------------------ #
    # ADV computation (matches RealisticSlippageModel)
    # ------------------------------------------------------------------ #
    def _compute_adv_usd(self, bar_data: pd.DataFrame, as_of: pd.Timestamp) -> Optional[float]:
        """20-day rolling-mean dollar ADV up to ``as_of`` (inclusive)."""
        if "Close" not in bar_data.columns or "Volume" not in bar_data.columns:
            return None
        try:
            sub = bar_data.loc[bar_data.index <= as_of]
        except Exception:
            sub = bar_data
        n = self.config.adv_lookback
        recent = sub.tail(n)
        if len(recent) < max(5, n // 2):
            return None
        try:
            dollar_vol = (recent["Close"].astype(float) * recent["Volume"].astype(float))
            adv = float(dollar_vol.mean())
            if not math.isfinite(adv) or adv <= 0:
                return None
            return adv
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    # Daily drag from snapshot history
    # ------------------------------------------------------------------ #
    def compute_daily_drag(
        self,
        snapshots: pd.DataFrame,
        price_data_map: Optional[Mapping[str, pd.DataFrame]] = None,
        positions_by_timestamp: Optional[Mapping[pd.Timestamp, Mapping[str, float]]] = None,
    ) -> pd.Series:
        """Compute borrow drag in $ per snapshot timestamp.

        Inputs:
          snapshots:               DataFrame indexed by timestamp with at
                                   minimum a 'timestamp' column and
                                   optionally 'short_value_usd'.
          price_data_map:          {ticker: DataFrame[Close, Volume]} for
                                   ADV bucketing. Optional — when omitted,
                                   every short uses the mid-cap default.
          positions_by_timestamp:  {ts: {ticker: signed_shares}} or
                                   {ts: {ticker: signed_dollar_value}}.
                                   When provided, drag is computed per-
                                   ticker (more accurate). When omitted,
                                   falls back to applying mid-cap rate to
                                   ``short_value_usd`` if present, else 0.

        Returns: pd.Series(drag_usd) indexed by timestamp. Always >= 0.
        """
        if not self.config.enabled or snapshots is None or len(snapshots) == 0:
            return pd.Series(dtype=float)

        if "timestamp" in snapshots.columns:
            ts_index = pd.to_datetime(snapshots["timestamp"])
        else:
            ts_index = pd.to_datetime(snapshots.index)

        drag = pd.Series(0.0, index=ts_index)

        # Path A — explicit per-ticker positions: most accurate.
        if positions_by_timestamp:
            adv_cache: Dict[tuple, float] = {}
            for ts, pos_map in positions_by_timestamp.items():
                ts_norm = pd.Timestamp(ts)
                if ts_norm not in drag.index:
                    continue
                day_drag = 0.0
                for ticker, qty_or_value in pos_map.items():
                    short_dollar_value = self._extract_short_dollar_value(
                        ticker, qty_or_value, ts_norm, price_data_map
                    )
                    if short_dollar_value <= 0:
                        continue
                    cache_key = (ticker, ts_norm.normalize())
                    if cache_key in adv_cache:
                        adv_usd = adv_cache[cache_key]
                    else:
                        adv_usd = None
                        if price_data_map and ticker in price_data_map:
                            adv_usd = self._compute_adv_usd(
                                price_data_map[ticker], ts_norm
                            ) or 0.0
                        adv_cache[cache_key] = adv_usd
                    bps = self.get_bps_per_day(
                        ticker, adv_usd if adv_usd > 0 else None
                    )
                    day_drag += short_dollar_value * (bps / 10000.0)
                drag.loc[ts_norm] = day_drag
            return drag

        # Path B — fallback: aggregate short_value_usd in snapshots.
        if "short_value_usd" in snapshots.columns:
            short_vals = pd.to_numeric(snapshots["short_value_usd"], errors="coerce").fillna(0.0)
            short_vals.index = ts_index
            bps = self.config.mid_cap_bps_per_day
            drag = short_vals.abs() * (bps / 10000.0)
        return drag

    @staticmethod
    def _extract_short_dollar_value(
        ticker: str,
        qty_or_value: float,
        ts: pd.Timestamp,
        price_data_map: Optional[Mapping[str, pd.DataFrame]],
    ) -> float:
        """If ``qty_or_value`` looks like signed shares, multiply by price.
        If it looks like signed dollar value already, take its abs.

        Heuristic: if abs(value) > 1e6 we assume dollars (typical retail
        position sizes); otherwise we assume shares and look up price.
        """
        v = float(qty_or_value)
        if v >= 0:
            return 0.0  # not a short
        v_abs = abs(v)
        if v_abs > 1e6:
            return v_abs
        # Treat as shares: convert to dollars via Close
        if not price_data_map or ticker not in price_data_map:
            return 0.0
        df = price_data_map[ticker]
        if "Close" not in df.columns:
            return 0.0
        try:
            sub = df.loc[df.index <= ts]
            if sub.empty:
                return 0.0
            close = float(sub["Close"].iloc[-1])
            return v_abs * close
        except Exception:
            return 0.0

    # ------------------------------------------------------------------ #
    # Equity-curve adjustment
    # ------------------------------------------------------------------ #
    def apply_to_equity_curve(
        self,
        equity_curve: pd.Series,
        snapshots: pd.DataFrame,
        price_data_map: Optional[Mapping[str, pd.DataFrame]] = None,
        positions_by_timestamp: Optional[Mapping[pd.Timestamp, Mapping[str, float]]] = None,
    ) -> pd.Series:
        """Return ``equity_curve`` with cumulative borrow drag subtracted."""
        if not self.config.enabled:
            return equity_curve.copy()
        drag = self.compute_daily_drag(
            snapshots, price_data_map, positions_by_timestamp
        )
        if drag.empty:
            return equity_curve.copy()
        # Reindex drag onto equity_curve's index, fill missing with 0.
        drag_aligned = drag.reindex(equity_curve.index, fill_value=0.0)
        return equity_curve - drag_aligned.cumsum()


def get_borrow_rate_model(config_dict: Optional[dict] = None) -> BorrowRateModel:
    """Factory mirroring ``get_slippage_model`` for config-driven wiring."""
    if not config_dict:
        return BorrowRateModel(BorrowRateConfig())
    cfg = BorrowRateConfig(
        enabled=bool(config_dict.get("enabled", True)),
        mega_cap_bps_per_day=float(config_dict.get("mega_cap_bps_per_day", 5.0)),
        mid_cap_bps_per_day=float(config_dict.get("mid_cap_bps_per_day", 15.0)),
        small_cap_bps_per_day=float(config_dict.get("small_cap_bps_per_day", 50.0)),
        mega_cap_threshold_usd=float(
            config_dict.get("mega_cap_threshold_usd", 500_000_000.0)
        ),
        mid_cap_threshold_usd=float(
            config_dict.get("mid_cap_threshold_usd", 100_000_000.0)
        ),
        adv_lookback=int(config_dict.get("adv_lookback", 20)),
        per_ticker_bps_per_day=dict(
            config_dict.get("per_ticker_bps_per_day", {})
        ),
        trading_days_per_year=int(config_dict.get("trading_days_per_year", 252)),
    )
    return BorrowRateModel(cfg)
