"""Sample Foundry feature exercising the CFTC COT data source.

`cot_commercial_net_long(ticker, date)` returns the most-recent (≤ date)
commercial-trader net-long ratio:

    (Comm_Long - Comm_Short) / Open_Interest_All

Returns None for tickers without a futures-correlated mapping (most
single-name equities) or when no COT report has yet been published as
of `date` (early in a series).

The horizon is 5 business days — the typical hold for a positioning-
based reversal/continuation signal. The feature is tier='B' until it
has accumulated ablation evidence to graduate to tier='A'.
"""
from __future__ import annotations

from datetime import date
from typing import Optional

import pandas as pd

from ..feature import feature
from ..data_source import get_source_registry
from ..sources.cftc_cot import TICKER_TO_MARKET, CFTCCommitmentsOfTraders


def _latest_report_for(ticker: str, dt: date) -> Optional[pd.Series]:
    """Return the row of the most-recent COT report ≤ dt for the
    futures market mapped to `ticker`, or None if unavailable."""
    market = TICKER_TO_MARKET.get(ticker)
    if market is None:
        return None
    src = get_source_registry().get("cftc_cot")
    if src is None or not isinstance(src, CFTCCommitmentsOfTraders):
        return None
    try:
        df = src.fetch_cached(date(dt.year - 1, 1, 1), dt)
    except (NotImplementedError, ValueError):
        # No fetcher configured (substrate-only run) → feature returns
        # None gracefully. The dashboard surfaces this as "no data".
        return None
    if df.empty:
        return None
    sub = df[df["Market_and_Exchange_Names"] == market]
    sub = sub[sub["Report_Date_as_YYYY-MM-DD"] <= dt]
    if sub.empty:
        return None
    return sub.sort_values("Report_Date_as_YYYY-MM-DD").iloc[-1]


@feature(
    feature_id="cot_commercial_net_long",
    tier="B",
    horizon=5,
    license="public",
    source="cftc_cot",
    description=(
        "Commercial-trader net-long ratio from the CFTC futures-only "
        "legacy report, scaled by open interest. Defined only for "
        "ETFs with a mapped underlying futures market."
    ),
)
def cot_commercial_net_long(ticker: str, dt: date) -> Optional[float]:
    row = _latest_report_for(ticker, dt)
    if row is None:
        return None
    long = float(row["Comm_Positions_Long_All"])
    short = float(row["Comm_Positions_Short_All"])
    oi = float(row["Open_Interest_All"])
    if oi <= 0:
        return None
    return (long - short) / oi
