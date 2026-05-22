"""tests/test_spinoff_reversion_edge.py
========================================
Tests for T-2026-05-12-041 spin-off reversion edge.

Coverage:
1. Detector finds known events (Ferrari 2016, KBR 2007, etc.)
2. Detector returns deterministic + sorted output
3. Edge emits BUY in [entry_offset, entry_offset + holding_period]
4. Edge does NOT emit before distribution_date (look-ahead guard)
5. Edge does NOT emit past holding window
6. Edge handles zero events in window (empty universe of children)
7. Linear-decay mode produces a monotone-decreasing score
8. Curated YML loads + parses + sorts by date
9. Determinism across N reps on the same input
"""
from __future__ import annotations

import pandas as pd
import yaml

from engines.engine_a_alpha.edges._helpers.spinoff_detector import (
    SpinoffEvent,
    clear_cache,
    events_by_child,
    events_in_window,
    get_events,
    load_curated_events,
)
from engines.engine_a_alpha.edges.spinoff_reversion_v1 import (
    SpinoffReversionEdge,
)


# -------------------- detector tests -------------------- #

def test_detector_finds_ferrari_2016():
    """Ferrari (RACE) spun off from Fiat (F) on 2016-01-04."""
    clear_cache()
    events = get_events(use_cache=False)
    race = [e for e in events if e.child_ticker == "RACE"]
    assert len(race) == 1
    ev = race[0]
    assert ev.parent_ticker == "F"
    assert ev.distribution_date == pd.Timestamp("2016-01-04")
    assert ev.source == "curated"
    assert ev.confidence == 1.0


def test_detector_finds_kbr_2007():
    """KBR spun off from Halliburton (HAL) on 2007-04-05."""
    clear_cache()
    events = get_events(use_cache=False)
    kbr = [e for e in events if e.child_ticker == "KBR"]
    assert len(kbr) == 1
    assert kbr[0].parent_ticker == "HAL"
    assert kbr[0].distribution_date == pd.Timestamp("2007-04-05")


def test_detector_includes_recent_ge_spinoffs():
    """GE → GEHC (2023) and GE → GEV (2024) — recent test cases."""
    clear_cache()
    events = get_events(use_cache=False)
    gehc = [e for e in events if e.child_ticker == "GEHC"]
    gev = [e for e in events if e.child_ticker == "GEV"]
    assert len(gehc) == 1 and gehc[0].distribution_date == pd.Timestamp("2023-01-04")
    assert len(gev) == 1 and gev[0].distribution_date == pd.Timestamp("2024-04-02")


def test_detector_output_is_sorted_by_date():
    """get_events returns events sorted by distribution_date asc."""
    clear_cache()
    events = get_events(use_cache=False)
    dates = [e.distribution_date for e in events]
    assert dates == sorted(dates), "events must be sorted ascending by date"


def test_curated_events_yaml_parses(tmp_path):
    """load_curated_events handles a minimal valid YAML."""
    p = tmp_path / "synth.yml"
    p.write_text(yaml.safe_dump({
        "events": [
            {
                "parent_ticker": "ABC",
                "child_ticker": "XYZ",
                "distribution_date": "2020-06-15",
                "distribution_ratio": 0.5,
                "notes": "synthetic test",
            },
        ],
    }))
    events = load_curated_events(p)
    assert len(events) == 1
    assert events[0].parent_ticker == "ABC"
    assert events[0].child_ticker == "XYZ"
    assert events[0].distribution_date == pd.Timestamp("2020-06-15")
    assert events[0].distribution_ratio == 0.5


def test_events_in_window_filter():
    """events_in_window filters by date inclusive on both ends."""
    clear_cache()
    events = get_events(use_cache=False)
    win = events_in_window(events, "2015-01-01", "2020-12-31")
    # F→RACE 2016, BAX→BXLT 2015, ABT→ABBV 2013 (excluded), HPE→MFGP 2017,
    # DD→DOW 2019, DD→CTVA 2019 all in [2015, 2020].
    children_in = {e.child_ticker for e in win}
    assert "RACE" in children_in
    assert "BXLT" in children_in
    assert "DOW" in children_in
    assert "ABBV" not in children_in  # before window
    assert "GEHC" not in children_in  # after window


def test_events_by_child_indexes_correctly():
    """events_by_child gives O(1) child→event lookup."""
    clear_cache()
    events = get_events(use_cache=False)
    by_child = events_by_child(events)
    assert by_child["RACE"].parent_ticker == "F"
    assert by_child["KBR"].parent_ticker == "HAL"
    assert by_child["GEHC"].parent_ticker == "GE"


# -------------------- edge signal-timing tests -------------------- #

def test_edge_emits_buy_on_entry_offset():
    """Edge fires BUY at distribution_date + entry_offset trading days."""
    clear_cache()
    e = SpinoffReversionEdge()
    # RACE distribution 2016-01-04. entry_offset=3 → 2016-01-07 fires.
    data_map = {"RACE": pd.DataFrame({"Close": [50]},
                                     index=pd.date_range("2016-01-07", periods=1))}
    result = e.compute_signals(data_map, pd.Timestamp("2016-01-07"))
    assert "RACE" in result
    assert result["RACE"] == 1.0


def test_edge_does_not_emit_before_distribution_date():
    """Look-ahead guard: no signal before distribution_date."""
    clear_cache()
    e = SpinoffReversionEdge()
    data_map = {"RACE": pd.DataFrame({"Close": [50]},
                                     index=pd.date_range("2015-12-15", periods=1))}
    # 2015-12-15 is BEFORE RACE's 2016-01-04 distribution.
    result = e.compute_signals(data_map, pd.Timestamp("2015-12-15"))
    assert "RACE" not in result
    assert result == {}


def test_edge_does_not_emit_on_distribution_date_itself():
    """Day 0 (distribution day) is below entry_offset → no signal."""
    clear_cache()
    e = SpinoffReversionEdge()
    data_map = {"RACE": pd.DataFrame({"Close": [50]},
                                     index=pd.date_range("2016-01-04", periods=1))}
    result = e.compute_signals(data_map, pd.Timestamp("2016-01-04"))
    assert "RACE" not in result


def test_edge_emits_exit_after_holding_period():
    """Past entry_offset + holding_period (93 trading days) → no signal."""
    clear_cache()
    e = SpinoffReversionEdge()
    # 2016-05-13 is 94 trading days after 2016-01-04 → outside [3, 93]
    data_map = {"RACE": pd.DataFrame({"Close": [50]},
                                     index=pd.date_range("2016-05-13", periods=1))}
    result = e.compute_signals(data_map, pd.Timestamp("2016-05-13"))
    assert "RACE" not in result


def test_edge_emits_in_mid_window():
    """Mid-window (day ~50) fires with constant score 1.0 by default."""
    clear_cache()
    e = SpinoffReversionEdge()
    # 2016-03-15 is ~50 trading days after 2016-01-04
    data_map = {"RACE": pd.DataFrame({"Close": [50]},
                                     index=pd.date_range("2016-03-15", periods=1))}
    result = e.compute_signals(data_map, pd.Timestamp("2016-03-15"))
    assert result["RACE"] == 1.0


def test_edge_handles_zero_events_in_universe():
    """When data_map has no spin-off children, edge returns empty dict."""
    clear_cache()
    e = SpinoffReversionEdge()
    data_map = {
        "AAPL": pd.DataFrame({"Close": [100]},
                             index=pd.date_range("2020-06-01", periods=1)),
        "MSFT": pd.DataFrame({"Close": [200]},
                             index=pd.date_range("2020-06-01", periods=1)),
    }
    result = e.compute_signals(data_map, pd.Timestamp("2020-06-01"))
    assert result == {}


def test_edge_linear_decay_monotone_decreasing():
    """When linear_decay=True, score decreases monotonically across window."""
    clear_cache()
    e = SpinoffReversionEdge()
    e.params["linear_decay"] = True
    # Sample 4 points across the RACE window.
    points = ["2016-01-07", "2016-02-15", "2016-03-15", "2016-04-15"]
    scores = []
    for d in points:
        result = e.compute_signals(
            {"RACE": pd.DataFrame({"Close": [50]},
                                  index=pd.date_range(d, periods=1))},
            pd.Timestamp(d),
        )
        scores.append(result.get("RACE", 0.0))
    # Monotone decreasing
    for i in range(len(scores) - 1):
        assert scores[i] >= scores[i + 1], (
            f"linear decay should be monotone decreasing, got {scores}"
        )
    # First point should be close to 1.0 (just after entry)
    assert scores[0] > 0.9
    # Last point should be smaller than first
    assert scores[-1] < scores[0]


def test_edge_determinism_across_repeated_calls():
    """Same input → same output across multiple instantiations."""
    clear_cache()
    data_map = {
        "RACE": pd.DataFrame({"Close": [50]},
                             index=pd.date_range("2016-03-01", periods=1)),
        "KBR": pd.DataFrame({"Close": [25]},
                            index=pd.date_range("2016-03-01", periods=1)),
    }
    as_of = pd.Timestamp("2016-03-01")
    results = []
    for _ in range(3):
        clear_cache()
        e = SpinoffReversionEdge()
        results.append(e.compute_signals(data_map, as_of))
    # All three reps identical
    assert results[0] == results[1] == results[2]


def test_event_post_init_normalizes_inputs():
    """SpinoffEvent.__post_init__ normalizes ticker case + strips tz."""
    ev = SpinoffEvent(
        parent_ticker="abc",
        child_ticker="xyz",
        distribution_date=pd.Timestamp("2020-06-15 14:00:00", tz="UTC"),
        distribution_ratio=0.5,
        source="curated",
        confidence=1.0,
    )
    assert ev.parent_ticker == "ABC"
    assert ev.child_ticker == "XYZ"
    assert ev.distribution_date.tzinfo is None
    assert ev.distribution_date == pd.Timestamp("2020-06-15")
