"""Tests for CotPositioningEdge.

Mock the CFTC source layer so tests run without network or fixture
files. Validate: ticker mapping abstention, z-score logic, contrarian
direction (long when commercials extreme short, short when commercials
extreme long), insufficient-history abstention.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from engines.engine_a_alpha.edges.cot_positioning_edge import CotPositioningEdge


@pytest.fixture()
def edge() -> CotPositioningEdge:
    return CotPositioningEdge()


def _synth_cot_frame(market: str, n_weeks: int, ratios: list[float]) -> pd.DataFrame:
    """Build a synthetic CFTC frame with the given commercial-net-long
    ratios. The edge converts (long - short) / OI back into the ratio,
    so we synthesize long/short pairs that produce the desired ratios."""
    assert len(ratios) == n_weeks
    end = pd.Timestamp("2024-12-31")
    dates = [(end - pd.DateOffset(weeks=n_weeks - 1 - i)).date() for i in range(n_weeks)]
    oi = 100_000.0
    rows = []
    for d, r in zip(dates, ratios):
        # ratio = (long - short) / oi  AND  long + short ≤ oi
        # Pick long = (oi + r*oi)/2, short = (oi - r*oi)/2 so the ratio resolves.
        long_p = (oi + r * oi) / 2.0
        short_p = (oi - r * oi) / 2.0
        rows.append({
            "Market_and_Exchange_Names": market,
            "Report_Date_as_YYYY-MM-DD": d,
            "Comm_Positions_Long_All": long_p,
            "Comm_Positions_Short_All": short_p,
            "Open_Interest_All": oi,
        })
    return pd.DataFrame(rows)


def _patched_source(df: pd.DataFrame):
    """Build a mock CFTCCommitmentsOfTraders source that returns `df`
    on fetch_cached and is_a-correct."""
    from core.feature_foundry.sources.cftc_cot import CFTCCommitmentsOfTraders
    src = MagicMock(spec=CFTCCommitmentsOfTraders)
    src.fetch_cached.return_value = df
    return src


# --------------------------------------------------------------------- #

def test_unmapped_ticker_returns_zero(edge) -> None:
    """Tickers not in TICKER_TO_MARKET (e.g. AAPL) must abstain."""
    out = edge.compute_signals({"AAPL": pd.DataFrame()}, pd.Timestamp("2024-12-15"))
    assert out == {"AAPL": 0.0}


def test_extreme_long_commercials_produces_short_signal(edge) -> None:
    """Commercials at z >= +1.5 → short tilt -0.5 (contrarian)."""
    market = "GOLD - COMMODITY EXCHANGE INC."
    # 52 weeks at ratio = 0.0, then last week at +0.5 (extreme spike).
    ratios = [0.0] * 52 + [0.5]
    df = _synth_cot_frame(market, n_weeks=53, ratios=ratios)
    src = _patched_source(df)

    with patch("core.feature_foundry.sources.cftc_cot.TICKER_TO_MARKET", {"GLD": market}):
        with patch("core.feature_foundry.data_source.get_source_registry") as gsr:
            gsr.return_value = {"cftc_cot": src}
            out = edge.compute_signals({"GLD": pd.DataFrame()}, pd.Timestamp("2024-12-31"))

    assert out["GLD"] == pytest.approx(-0.5)


def test_extreme_short_commercials_produces_long_signal(edge) -> None:
    """Commercials at z <= -1.5 → long tilt +0.5 (contrarian)."""
    market = "GOLD - COMMODITY EXCHANGE INC."
    ratios = [0.0] * 52 + [-0.5]
    df = _synth_cot_frame(market, n_weeks=53, ratios=ratios)
    src = _patched_source(df)

    with patch("core.feature_foundry.sources.cftc_cot.TICKER_TO_MARKET", {"GLD": market}):
        with patch("core.feature_foundry.data_source.get_source_registry") as gsr:
            gsr.return_value = {"cftc_cot": src}
            out = edge.compute_signals({"GLD": pd.DataFrame()}, pd.Timestamp("2024-12-31"))

    assert out["GLD"] == pytest.approx(0.5)


def test_neutral_zscore_produces_zero(edge) -> None:
    """Commercials at |z| < 1.5 → no signal."""
    market = "GOLD - COMMODITY EXCHANGE INC."
    rng = np.random.default_rng(0)
    ratios = list(rng.normal(0.0, 0.05, size=53))
    # Force the latest into the +0.5sigma range (clearly inside ±1.5)
    ratios[-1] = 0.025
    df = _synth_cot_frame(market, n_weeks=53, ratios=ratios)
    src = _patched_source(df)

    with patch("core.feature_foundry.sources.cftc_cot.TICKER_TO_MARKET", {"GLD": market}):
        with patch("core.feature_foundry.data_source.get_source_registry") as gsr:
            gsr.return_value = {"cftc_cot": src}
            out = edge.compute_signals({"GLD": pd.DataFrame()}, pd.Timestamp("2024-12-31"))

    assert out["GLD"] == 0.0


def test_no_fetcher_configured_returns_zero(edge) -> None:
    """When fetch_cached raises NotImplementedError (no fetcher), abstain
    silently — no exceptions."""
    from core.feature_foundry.sources.cftc_cot import CFTCCommitmentsOfTraders
    src = MagicMock(spec=CFTCCommitmentsOfTraders)
    src.fetch_cached.side_effect = NotImplementedError("no fetcher")

    with patch("core.feature_foundry.sources.cftc_cot.TICKER_TO_MARKET",
               {"GLD": "GOLD - COMMODITY EXCHANGE INC."}):
        with patch("core.feature_foundry.data_source.get_source_registry") as gsr:
            gsr.return_value = {"cftc_cot": src}
            out = edge.compute_signals({"GLD": pd.DataFrame()}, pd.Timestamp("2024-12-31"))

    assert out["GLD"] == 0.0


def test_short_history_abstains(edge) -> None:
    """Less than 12 weekly reports → abstain (insufficient history for z)."""
    market = "GOLD - COMMODITY EXCHANGE INC."
    df = _synth_cot_frame(market, n_weeks=8, ratios=[0.5] * 8)
    src = _patched_source(df)

    with patch("core.feature_foundry.sources.cftc_cot.TICKER_TO_MARKET", {"GLD": market}):
        with patch("core.feature_foundry.data_source.get_source_registry") as gsr:
            gsr.return_value = {"cftc_cot": src}
            out = edge.compute_signals({"GLD": pd.DataFrame()}, pd.Timestamp("2024-12-31"))

    assert out["GLD"] == 0.0


def test_zero_open_interest_rows_skipped(edge) -> None:
    """Rows with OI = 0 must be filtered (avoid divide-by-zero)."""
    market = "GOLD - COMMODITY EXCHANGE INC."
    df = _synth_cot_frame(market, n_weeks=53, ratios=[0.0] * 53)
    df.loc[10:15, "Open_Interest_All"] = 0  # Inject a few zero-OI rows
    src = _patched_source(df)

    with patch("core.feature_foundry.sources.cftc_cot.TICKER_TO_MARKET", {"GLD": market}):
        with patch("core.feature_foundry.data_source.get_source_registry") as gsr:
            gsr.return_value = {"cftc_cot": src}
            out = edge.compute_signals({"GLD": pd.DataFrame()}, pd.Timestamp("2024-12-31"))

    # Mostly flat → z near 0 → tilt 0
    assert out["GLD"] == 0.0


def test_empty_data_map_returns_empty(edge) -> None:
    out = edge.compute_signals({}, pd.Timestamp("2024-12-15"))
    assert out == {}


def test_caching_avoids_repeat_fetch(edge) -> None:
    market = "GOLD - COMMODITY EXCHANGE INC."
    df = _synth_cot_frame(market, n_weeks=53, ratios=[0.0] * 52 + [-0.5])
    src = _patched_source(df)

    with patch("core.feature_foundry.sources.cftc_cot.TICKER_TO_MARKET", {"GLD": market}):
        with patch("core.feature_foundry.data_source.get_source_registry") as gsr:
            gsr.return_value = {"cftc_cot": src}
            edge.compute_signals({"GLD": pd.DataFrame()}, pd.Timestamp("2024-12-31"))
            edge.compute_signals({"GLD": pd.DataFrame()}, pd.Timestamp("2024-12-31"))

    # fetch_cached should be called only once thanks to per-ticker caching
    assert src.fetch_cached.call_count == 1


def test_edge_id_and_category_are_stable() -> None:
    assert CotPositioningEdge.EDGE_ID == "cot_positioning_v1"
    assert CotPositioningEdge.CATEGORY == "macro_positioning"
