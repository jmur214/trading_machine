"""tests/test_signal_collector_silent_failure.py
====================================================

Lock-in tests for the 2026-05-07 signal_collector silent-failure fix.
The HIGH-severity finding in `health_check.md` documented:

> Engine A signal_collector silently returns `{}` when an edge defines
> a typo'd method — same failure class as the just-fixed `check_signal`
> vs `compute_signals` bug.

Pre-fix path:
- `_call_edge` searched for compute_signals / generate_signals / generate
- If none of them existed (e.g., typo'd method name like `compute_signal`
  without the s), it fell through to `return {}` silently
- The outer try-except caught everything broadly; same shape as the
  gauntlet bare-except remediation (project_phase_a_substrate_cleanup_2026_05_07)
- An entire backtest could run with zero signals from a typo'd edge,
  no warning, no failure — just unexpectedly tiny PnL

Post-fix path:
- `_call_edge` raises AttributeError with a helpful message naming
  the searched-for methods AND any near-matches (typo hint)
- Outer try-except narrows to re-raise AttributeError / TypeError /
  NameError / AssertionError / ImportError as programmer errors
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.append(str(Path(__file__).resolve().parents[1]))

from engines.engine_a_alpha.signal_collector import SignalCollector


class _EdgeWithTypoedMethod:
    """Edge defines `compute_signal` (singular) instead of `compute_signals`.

    This is the exact failure class the HIGH-severity finding named — a
    Levenshtein-1 typo that the pre-fix code accepted silently.
    """

    def compute_signal(self, data_map, now):  # ← typo: missing 's'
        return {"AAPL": 1.0}


class _EdgeWithCorrectMethod:
    def compute_signals(self, data_map, now):
        return {"AAPL": 1.0}


class _EdgeWithNoSignalMethod:
    """Edge has no signal-producing method at all — not even close to one."""

    def some_unrelated_method(self):
        return 42


class _EdgeRaisingAttributeError:
    """Edge whose compute_signals raises AttributeError mid-execution.

    These are programmer errors (e.g., accessing a missing attribute on a
    DataFrame). Pre-fix the outer broad-except swallowed them. Post-fix
    they re-raise."""

    def compute_signals(self, data_map, now):
        # Trigger a real AttributeError
        broken = None
        return broken.iloc[0]  # noqa


class _EdgeRaisingValueError:
    """Edge whose compute_signals raises ValueError — a runtime/data error.

    These should NOT propagate (the broad-except path is correct for
    runtime errors that are environmental, not programmer errors).
    """

    def compute_signals(self, data_map, now):
        raise ValueError("simulated runtime data issue")


def _make_data_map():
    idx = pd.date_range("2024-01-02", periods=5, freq="B")
    return {"AAPL": pd.DataFrame({"Close": [100.0, 101, 102, 101, 103]}, index=idx)}


def test_typoed_method_raises_attribute_error_with_helpful_hint():
    """The exact failure class from the HIGH finding — typo'd method name
    must surface AttributeError with a hint about what the edge interface
    expects."""
    collector = SignalCollector(edges={"typo_edge": _EdgeWithTypoedMethod()})
    with pytest.raises(AttributeError) as exc:
        collector.collect(_make_data_map(), pd.Timestamp("2024-01-03"))
    msg = str(exc.value)
    assert "no recognized signal method" in msg
    # Hint should name what was searched for
    assert "compute_signals" in msg
    # The typo'd method should appear as a near-match suggestion
    assert "compute_signal" in msg


def test_no_signal_method_raises_attribute_error():
    """A class with no resemblance to the edge interface should also raise
    AttributeError — surfacing the integration mistake rather than
    producing zero signals."""
    collector = SignalCollector(edges={"unrelated_edge": _EdgeWithNoSignalMethod()})
    with pytest.raises(AttributeError) as exc:
        collector.collect(_make_data_map(), pd.Timestamp("2024-01-03"))
    assert "no recognized signal method" in str(exc.value)


def test_correct_edge_still_works():
    """Regression check — edges that follow the contract still work."""
    collector = SignalCollector(edges={"good_edge": _EdgeWithCorrectMethod()})
    scores = collector.collect(_make_data_map(), pd.Timestamp("2024-01-03"))
    assert "AAPL" in scores
    assert scores["AAPL"]["good_edge"] == 1.0


def test_attribute_error_inside_edge_propagates():
    """Programmer errors (AttributeError) inside an edge's compute_signals
    must propagate, not be swallowed by the outer broad-except. Pre-fix
    these were silently logged + zero signals returned for that edge."""
    collector = SignalCollector(edges={"buggy_edge": _EdgeRaisingAttributeError()})
    with pytest.raises(AttributeError):
        collector.collect(_make_data_map(), pd.Timestamp("2024-01-03"))


def test_value_error_inside_edge_does_not_propagate():
    """Runtime/data errors (ValueError, RuntimeError) are environmental;
    they SHOULD be caught + logged + the next edge processed. The
    narrowed catch only re-raises the programmer-error subset."""
    collector = SignalCollector(edges={
        "buggy_edge": _EdgeRaisingValueError(),
        "good_edge": _EdgeWithCorrectMethod(),
    })
    # No raise — broad ValueError caught + logged; good_edge still runs
    scores = collector.collect(_make_data_map(), pd.Timestamp("2024-01-03"))
    # good_edge's signal should still come through
    assert "AAPL" in scores
    assert scores["AAPL"].get("good_edge") == 1.0


def test_type_error_propagates_as_programmer_error():
    """TypeError is in the propagate set — typically signals a bad call
    signature or operating on the wrong type."""
    class _EdgeRaisingTypeError:
        def compute_signals(self, data_map, now):
            return None + "not_a_number"  # noqa

    collector = SignalCollector(edges={"buggy": _EdgeRaisingTypeError()})
    with pytest.raises(TypeError):
        collector.collect(_make_data_map(), pd.Timestamp("2024-01-03"))


def test_import_error_propagates():
    """ImportError is in the propagate set — typically signals a missing
    module or a typo in an import."""
    class _EdgeRaisingImportError:
        def compute_signals(self, data_map, now):
            raise ImportError("simulated missing module")

    collector = SignalCollector(edges={"buggy": _EdgeRaisingImportError()})
    with pytest.raises(ImportError):
        collector.collect(_make_data_map(), pd.Timestamp("2024-01-03"))
