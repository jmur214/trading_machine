import pandas as pd
import numpy as np
import logging
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate

logger = logging.getLogger("EARNINGS_VOL")


class EarningsVolEdge(EdgeBase, EdgeTemplate):
    """
    Behavioral edge: earnings volatility patterns.

    Two modes:
    - pre_earnings: Bollinger Width shrinking before known earnings dates
      signals vol compression that tends to explode on the report.
    - post_earnings: Momentum in the gap direction persists 3-5 days after
      earnings (post-earnings announcement drift — PEAD).

    Earnings dates fetched from yfinance and cached per ticker.
    """

    EDGE_ID = "earnings_vol_v1"
    EDGE_GROUP = "behavioral"
    EDGE_CATEGORY = "event_driven"

    _earnings_cache = {}  # class-level cache: ticker -> list of dates

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "mode": {"type": "categorical", "choices": ["pre_earnings", "post_earnings"]},
            "bb_window": {"type": "int", "min": 15, "max": 30},
            "squeeze_pct": {"type": "float", "min": 0.01, "max": 0.05},
            "pre_days": {"type": "int", "min": 3, "max": 10},
            "post_days": {"type": "int", "min": 1, "max": 5},
            "drift_threshold": {"type": "float", "min": 0.01, "max": 0.05},
        }

    def compute_signals(self, data_map, as_of):
        scores = {}
        mode = self.params.get("mode", "pre_earnings")
        bb_win = self.params.get("bb_window", 20)
        squeeze_pct = self.params.get("squeeze_pct", 0.03)
        pre_days = self.params.get("pre_days", 5)
        post_days = self.params.get("post_days", 3)
        drift_thr = self.params.get("drift_threshold", 0.02)

        for t, df in data_map.items():
            if len(df) < bb_win + 10 or "Close" not in df.columns:
                continue

            earnings_dates = self._get_earnings_dates(t)
            if not earnings_dates:
                scores[t] = 0.0
                continue

            if mode == "pre_earnings":
                scores[t] = self._pre_earnings_signal(
                    df, as_of, earnings_dates, bb_win, squeeze_pct, pre_days
                )
            else:
                scores[t] = self._post_earnings_signal(
                    df, as_of, earnings_dates, post_days, drift_thr
                )

        return scores

    def _get_earnings_dates(self, ticker):
        """Fetch and cache earnings dates from yfinance."""
        if ticker in self._earnings_cache:
            return self._earnings_cache[ticker]

        try:
            import yfinance as yf
            tk = yf.Ticker(ticker)
            dates = tk.earnings_dates
            if dates is not None and not dates.empty:
                date_list = sorted(dates.index.normalize().tolist())
                self._earnings_cache[ticker] = date_list
                return date_list
        except Exception as e:
            logger.debug(f"Could not fetch earnings dates for {ticker}: {e}")

        self._earnings_cache[ticker] = []
        return []

    def _pre_earnings_signal(self, df, as_of, earnings_dates, bb_win, squeeze_pct, pre_days):
        """Vol compression before earnings → long (anticipate vol expansion)."""
        if not isinstance(as_of, pd.Timestamp):
            return 0.0

        # Find next earnings date
        future_dates = [d for d in earnings_dates if d > as_of]
        if not future_dates:
            return 0.0

        next_earnings = future_dates[0]
        days_until = np.busday_count(as_of.date(), next_earnings.date())

        if days_until < 1 or days_until > pre_days:
            return 0.0

        # Check Bollinger squeeze
        close = df["Close"]
        sma = close.rolling(bb_win).mean()
        std = close.rolling(bb_win).std()
        bb_width = ((2 * std) / sma).iloc[-1]

        if bb_width < squeeze_pct:
            return 1.0  # Vol compressed before earnings → long bias
        return 0.0

    def _post_earnings_signal(self, df, as_of, earnings_dates, post_days, drift_thr):
        """Post-earnings drift: momentum in the gap direction."""
        if not isinstance(as_of, pd.Timestamp):
            return 0.0

        # Find most recent past earnings date
        past_dates = [d for d in earnings_dates if d <= as_of]
        if not past_dates:
            return 0.0

        last_earnings = past_dates[-1]
        days_since = np.busday_count(last_earnings.date(), as_of.date())

        if days_since < 1 or days_since > post_days:
            return 0.0

        # Compute gap on earnings day
        close = df["Close"]
        # Find the index closest to earnings date
        try:
            idx = close.index.get_indexer([last_earnings], method="nearest")[0]
        except Exception:
            return 0.0

        if idx < 1 or idx >= len(close):
            return 0.0

        earnings_ret = (close.iloc[idx] - close.iloc[idx - 1]) / close.iloc[idx - 1]

        if earnings_ret > drift_thr:
            return 1.0  # Positive surprise → drift up
        elif earnings_ret < -drift_thr:
            return -1.0  # Negative surprise → drift down
        return 0.0
