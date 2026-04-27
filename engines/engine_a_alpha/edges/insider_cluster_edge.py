"""
engines/engine_a_alpha/edges/insider_cluster_edge.py
=====================================================
Insider cluster-buying edge.

When multiple corporate insiders (officers / directors / 10pct owners)
purchase shares of their own company within a short window, that cluster
of independent decisions is one of the more robust positive-return
signals documented in the empirical asset-pricing literature. Single
insider buys have weaker signal (a single CEO buy on a routine schedule
adds little); clusters are stronger because they require independent
decisions to coincide.

References: Cohen, Malloy & Pomorski (2012) "Decoding Inside
Information"; Lakonishok & Lee (2001) "Are Insider Trades Informative?";
Jeng, Metrick & Zeckhauser (2003). Returns are typically reported in the
1-3 month forward horizon at 4-8% above benchmark for opportunistic
buying, with cluster events at the higher end.

Mechanism (v1, long-only):
  - Per ticker, per bar, look back 60 calendar days for purchases.
  - If at least N_distinct insiders bought in that window (default 3),
    a cluster is "fired" with trigger date = latest buy in the cluster.
  - Signal proportional to log(total cluster dollar value), clipped to
    a sensible range, decayed linearly over a 90-day hold window from
    the trigger date.
  - Insider sells are noisy (executives sell on schedules, for taxes,
    diversification, RSU vesting) — long-only in v1. Short variant is
    a separate v2 ship.

Cache behavior: reads via `InsiderDataManager.load_cached`. If the
cache is empty (fresh clone, OpenInsider down at bootstrap time),
the edge emits zeros across the universe — graceful degradation, no
crash. This lets the edge ship and stay active in code without forcing
the cache to be populated for backtests to run.
"""
from __future__ import annotations

import logging
import math
from typing import Optional

import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("InsiderClusterEdge")


class InsiderClusterEdge(EdgeBase):
    EDGE_ID = "insider_cluster_v1"
    CATEGORY = "event_driven"
    DESCRIPTION = (
        "Insider cluster-buying: long signal when ≥3 distinct insiders "
        "purchase within a 60-day window. Magnitude proportional to "
        "log(cluster $ value), linear decay over 90-day hold. Long-only."
    )

    DEFAULT_PARAMS = {
        # How far back to look for clustering activity, in calendar days.
        # 60 covers ~2 trading-month window — long enough that genuinely
        # independent insider decisions can stack, short enough that the
        # cluster is contemporaneous (not 6 months apart on different
        # information sets).
        "lookback_days": 60,
        # Minimum number of distinct insiders required for a cluster to
        # fire. Cohen-Malloy-Pomorski use 3 as the empirical inflection
        # where opportunistic-buying alpha emerges above the routine-buy
        # noise floor.
        "min_distinct_insiders": 3,
        # Hold window post-trigger, calendar days. Literature shows the
        # cluster-buying drift is concentrated in the first ~60 trading
        # days (~84 calendar). 90 is conservative and matches the
        # PEAD edge for consistency.
        "hold_days": 90,
        # Magnitude clipping: cluster $ values span 4-5 orders of
        # magnitude (a $50K small-cap director cluster vs a $50M
        # mega-cap board-wide cluster). Log-scale and clip to a
        # reasonable band so neither extreme dominates.
        "value_clip_low_usd": 50_000.0,
        "value_clip_high_usd": 50_000_000.0,
        # Maximum signal magnitude. Bounded so cluster-buying doesn't
        # dominate per-ticker technical signals.
        "long_score_max": 0.4,
    }

    def __init__(self):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        self._frames: dict[str, pd.DataFrame] = {}
        self._frames_loaded = False

    @classmethod
    def sample_params(cls):
        """Used by Engine D's GA. Returns canonical defaults — this is
        an academic-signal edge with established parameters and tuning
        them on a single backtest is the textbook overfitting trap."""
        return dict(cls.DEFAULT_PARAMS)

    def _load_frames(self, symbols: list[str]) -> None:
        """Lazy-load each ticker's insider transactions parquet from cache.
        Tickers with no cache contribute nothing — they score 0 in
        compute_signals. Pre-filters to purchases only and to the
        ``transaction_date`` column being a clean naive Timestamp index."""
        if self._frames_loaded:
            return
        self._frames_loaded = True

        try:
            from engines.data_manager.insider_data import InsiderDataManager
        except Exception as exc:
            log.debug(f"InsiderDataManager import failed ({exc}); abstaining")
            return

        try:
            mgr = InsiderDataManager()
        except Exception as exc:
            log.debug(f"InsiderDataManager init failed ({exc}); abstaining")
            return

        for sym in symbols:
            try:
                df = mgr.load_cached(sym)
            except Exception as exc:
                log.debug(f"insider cache load failed for {sym} ({exc})")
                continue
            if df is None or df.empty:
                continue
            try:
                idx = pd.to_datetime(df.index)
                if getattr(idx, "tz", None) is not None:
                    idx = idx.tz_localize(None)
                df = df.copy()
                df.index = idx
                # Pre-filter to purchases only — cluster math doesn't
                # care about sales. Reduces work in the per-bar loop.
                df = df[df["transaction_type"] == "P"]
                if df.empty:
                    continue
                df = df.sort_index()
            except Exception:
                continue
            self._frames[sym] = df

        if not self._frames:
            log.debug(
                "insider cache is empty for all tickers in universe; "
                "InsiderClusterEdge abstaining. Populate via "
                "InsiderDataManager().fetch_universe(<tickers>)."
            )

    def _compute_one_signal(self, sym: str, now: pd.Timestamp) -> float:
        """Return signal magnitude for one ticker at one timestamp.
        Zero if no qualifying cluster within the hold window."""
        frame = self._frames.get(sym)
        if frame is None or frame.empty:
            return 0.0

        lookback = int(self.params.get("lookback_days", 60))
        min_distinct = int(self.params.get("min_distinct_insiders", 3))
        hold_days = int(self.params.get("hold_days", 90))
        clip_lo = float(self.params.get("value_clip_low_usd", 50_000.0))
        clip_hi = float(self.params.get("value_clip_high_usd", 50_000_000.0))
        long_score_max = float(self.params.get("long_score_max", 0.4))

        try:
            ts = pd.Timestamp(now)
            if ts.tzinfo is not None:
                ts = ts.tz_localize(None)
        except Exception:
            return 0.0

        # Find the most recent qualifying cluster trigger within the
        # past `hold_days`. A cluster fires on date D if there are
        # ≥ min_distinct insiders purchasing in [D - lookback, D].
        # We scan backwards from `now` over the hold window — the most
        # recent qualifying D wins (linear decay from D forward).
        hold_window_start = ts - pd.Timedelta(days=hold_days)
        candidates = frame.loc[
            (frame.index >= hold_window_start) & (frame.index <= ts)
        ]
        if candidates.empty:
            return 0.0

        # Walk candidate buy dates from latest to earliest; first one
        # that has ≥min_distinct insiders in its trailing lookback window
        # is the trigger. Iterating gives deterministic behavior — sets
        # in pandas .unique() preserve insertion order.
        trigger_date: Optional[pd.Timestamp] = None
        cluster_value: float = 0.0
        for d in reversed(candidates.index.unique()):
            window_start = d - pd.Timedelta(days=lookback)
            window = frame.loc[(frame.index >= window_start) & (frame.index <= d)]
            distinct_buyers = window["insider_name"].nunique()
            if distinct_buyers >= min_distinct:
                trigger_date = d
                # Cluster value = sum of buy dollar amounts. `value`
                # is signed but we filtered to P only, so all positive.
                cluster_value = float(window["value"].abs().sum())
                break

        if trigger_date is None or cluster_value <= 0:
            return 0.0

        # Magnitude: log-scaled within the clip band, mapped to [0, 1].
        log_clip_lo = math.log(clip_lo)
        log_clip_hi = math.log(clip_hi)
        log_val = math.log(max(cluster_value, clip_lo))
        log_val = min(log_val, log_clip_hi)
        denom = max(1e-9, log_clip_hi - log_clip_lo)
        magnitude_factor = (log_val - log_clip_lo) / denom
        magnitude_factor = max(0.0, min(1.0, magnitude_factor))

        # Time decay: linear from 1.0 at trigger to 0.0 at hold-window end
        days_since = (ts - trigger_date).days
        time_factor = max(0.0, 1.0 - (days_since / max(1, hold_days)))

        return long_score_max * magnitude_factor * time_factor

    def compute_signals(self, data_map, now):
        symbols = list(data_map.keys())
        self._load_frames(symbols)

        if not self._frames:
            return {sym: 0.0 for sym in symbols}

        return {sym: self._compute_one_signal(sym, now) for sym in symbols}


# ---------------------------------------------------------------------------
# Auto-register on import. Safe post-2026-04-25 registry fix —
# `EdgeRegistry.ensure()` write-protects status on existing specs.
# ---------------------------------------------------------------------------
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=InsiderClusterEdge.EDGE_ID,
        category=InsiderClusterEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=dict(InsiderClusterEdge.DEFAULT_PARAMS),
        status="active",
    ))
except Exception as _exc:
    log.debug(f"InsiderClusterEdge auto-register skipped: {_exc}")
