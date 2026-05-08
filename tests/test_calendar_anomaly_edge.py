"""Tests for CalendarAnomalyEdge — turn-of-month + day-of-week tilt.

Pure calendar-time edge; no price-action dependencies. Tests verify
the documented tilt mapping, turn-of-month logic, magnitude clamping,
uniform per-ticker output, and weekend abstention.
"""
from __future__ import annotations

import pandas as pd
import pytest

from engines.engine_a_alpha.edges.calendar_anomaly_edge import (
    CalendarAnomalyEdge, _is_turn_of_month,
)


@pytest.fixture()
def edge() -> CalendarAnomalyEdge:
    return CalendarAnomalyEdge()


@pytest.fixture()
def data_map() -> dict:
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    df = pd.DataFrame({
        "Open": [100, 101, 102, 103, 104],
        "High": [101, 102, 103, 104, 105],
        "Low":  [99, 100, 101, 102, 103],
        "Close": [101, 102, 103, 104, 105],
        "Volume": [1_000_000] * 5,
    }, index=idx)
    return {"AAPL": df, "MSFT": df.copy(), "GOOG": df.copy()}


# ---------- _is_turn_of_month --------------------------------------------- #

def test_turn_of_month_first_business_day() -> None:
    # 2024-04-01 is a Monday — 1st business day of April
    assert _is_turn_of_month(pd.Timestamp("2024-04-01")) is True


def test_turn_of_month_third_business_day() -> None:
    # 2024-04-03 is a Wednesday — 3rd business day of April
    assert _is_turn_of_month(pd.Timestamp("2024-04-03")) is True


def test_turn_of_month_fourth_business_day_is_not_tom() -> None:
    # 2024-04-04 is a Thursday — 4th business day; just out of window
    assert _is_turn_of_month(pd.Timestamp("2024-04-04")) is False


def test_turn_of_month_last_business_day() -> None:
    # 2024-03-29 is a Friday — last business day of March (March 30/31 are weekend)
    assert _is_turn_of_month(pd.Timestamp("2024-03-29")) is True


def test_mid_month_is_not_tom() -> None:
    # 2024-04-15 is a Monday, mid-month
    assert _is_turn_of_month(pd.Timestamp("2024-04-15")) is False


# ---------- compute_signals --------------------------------------------- #

def test_friday_outside_tom_uses_friday_tilt(edge, data_map) -> None:
    # 2024-04-12 is a Friday, NOT in TOM window → tilt = 0.10
    out = edge.compute_signals(data_map, pd.Timestamp("2024-04-12"))
    assert all(v == pytest.approx(0.10) for v in out.values())
    # All tickers get the SAME tilt — uniform by design
    assert len(set(out.values())) == 1


def test_monday_outside_tom_uses_negative_monday_tilt(edge, data_map) -> None:
    # 2024-04-15 is a Monday, mid-month → tilt = -0.05
    out = edge.compute_signals(data_map, pd.Timestamp("2024-04-15"))
    assert all(v == pytest.approx(-0.05) for v in out.values())


def test_friday_in_tom_combines_dow_and_tom_tilts(edge, data_map) -> None:
    # 2024-03-29 is the last Friday of March → in TOM AND Friday
    # Expected: 0.10 (Fri) + 0.10 (TOM) = 0.20 (capped at ceiling)
    out = edge.compute_signals(data_map, pd.Timestamp("2024-03-29"))
    assert all(v == pytest.approx(0.20) for v in out.values())


def test_monday_first_of_month_combines_to_positive_via_tom(edge, data_map) -> None:
    # 2024-04-01 is Monday + 1st business day → TOM AND Monday
    # Expected: -0.05 (Mon) + 0.10 (TOM) = +0.05
    out = edge.compute_signals(data_map, pd.Timestamp("2024-04-01"))
    assert all(v == pytest.approx(0.05) for v in out.values())


def test_weekend_returns_zero_defensively(edge, data_map) -> None:
    # 2024-04-13 is a Saturday
    out = edge.compute_signals(data_map, pd.Timestamp("2024-04-13"))
    assert all(v == 0.0 for v in out.values())


def test_tilt_ceiling_caps_extreme_combinations(edge, data_map) -> None:
    # Manually patch params to force the combined tilt above the ceiling
    edge.params["dow_tilts"] = {0: 0.50, 1: 0.50, 2: 0.50, 3: 0.50, 4: 0.50}
    edge.params["tom_tilt"] = 0.50
    out = edge.compute_signals(data_map, pd.Timestamp("2024-03-29"))
    # Sum 0.50 + 0.50 = 1.00 → clamped at ceiling 0.20
    assert all(v == pytest.approx(0.20) for v in out.values())


def test_tilt_floor_caps_extreme_negative(edge, data_map) -> None:
    edge.params["dow_tilts"] = {0: -0.50, 1: -0.50, 2: -0.50, 3: -0.50, 4: -0.50}
    edge.params["tom_tilt"] = 0.0
    out = edge.compute_signals(data_map, pd.Timestamp("2024-04-15"))
    # -0.50 → floored at -0.10
    assert all(v == pytest.approx(-0.10) for v in out.values())


def test_empty_data_map_returns_empty_dict(edge) -> None:
    out = edge.compute_signals({}, pd.Timestamp("2024-04-15"))
    assert out == {}


def test_all_tickers_get_same_tilt_irrespective_of_underlying(edge) -> None:
    """Calendar-time edge is universal — should return identical tilt for
    every ticker regardless of the underlying DataFrame contents."""
    idx = pd.date_range("2024-01-01", periods=5, freq="B")
    raw = pd.DataFrame({"Open": 100, "Close": 100}, index=idx)
    dm = {"AAPL": raw, "MSFT": raw.copy(), "GOOG": raw.copy(), "AMZN": raw.copy()}
    out = edge.compute_signals(dm, pd.Timestamp("2024-04-12"))
    assert len(set(out.values())) == 1


def test_edge_id_is_calendar_anomaly_v1() -> None:
    assert CalendarAnomalyEdge.EDGE_ID == "calendar_anomaly_v1"


def test_edge_category_is_calendar() -> None:
    assert CalendarAnomalyEdge.CATEGORY == "calendar"
