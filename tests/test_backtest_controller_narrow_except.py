"""Regression tests for the narrowed bare-except in
``BacktestController._generate_signals``.

Closes the bug class behind the 2026-05-08 zero-trade regression — a
``TypeError`` raised inside ``EarningsVolEdge`` was silently swallowed
by a broad ``except Exception`` and produced ``signals=[]`` for ~24
hours before anyone noticed.

The narrowed catch (mirrors gauntlet remediation 453e04e) re-raises
programmer errors (``TypeError``, ``AttributeError``, ``NameError``,
``AssertionError``, ``ImportError``) and continues to swallow
operational/data errors (``KeyError``, ``ValueError``, ``IndexError``,
network/file errors) with a ``logger.warning`` that does not require
the ``BACKTEST_CONTROLLER`` debug flag to surface.
"""

from __future__ import annotations

import logging
from datetime import datetime
from unittest.mock import MagicMock

import pandas as pd
import pytest

from backtester.backtest_controller import BacktestController, BacktestParams


def _make_data_map():
    dates = pd.date_range("2024-01-02", periods=5, freq="B")
    df = pd.DataFrame(
        {
            "Open": [100.0] * 5,
            "High": [101.0] * 5,
            "Low": [99.0] * 5,
            "Close": [100.0] * 5,
            "Volume": [1_000_000] * 5,
        },
        index=dates,
    )
    return {"FAKE": df}, dates[-1]


class _FakeAlphaRaises:
    """Fake alpha engine whose ``generate_signals`` raises a configurable
    exception. Intentionally has no ``compute_signals`` so the controller
    falls into the ``else`` branch and hits ``generate_signals`` directly.
    """

    def __init__(self, exc: BaseException):
        self._exc = exc

    def generate_signals(self, slice_map, ts, regime_meta=None):  # noqa: D401
        raise self._exc


class _FakeAlphaNormal:
    """Fake alpha engine that returns a single fixed signal."""

    def generate_signals(self, slice_map, ts, regime_meta=None):
        return [{"ticker": "FAKE", "side": "BUY", "strength": 0.5}]


def _build_controller(alpha):
    data_map, _ = _make_data_map()
    risk = MagicMock()
    cockpit = MagicMock()
    return BacktestController(
        data_map=data_map,
        alpha_engine=alpha,
        risk_engine=risk,
        cockpit_logger=cockpit,
        exec_params={"commission": 0.0, "slippage_bps": 0.0},
        initial_capital=10_000.0,
        bt_params=BacktestParams(verbose=False),
    )


def _slice_map(controller):
    df = controller.data_map["FAKE"]
    return {"FAKE": df}


def _ts(controller):
    return controller.data_map["FAKE"].index[-1]


# ---------------------------------------------------------------------- #
# Programmer errors must propagate.
# ---------------------------------------------------------------------- #


def test_typeerror_in_alpha_propagates():
    """TypeError from alpha must escape the bare-except (this is exactly
    the 2026-05-08 zero-trade regression class)."""
    controller = _build_controller(
        _FakeAlphaRaises(TypeError("Cannot compare tz-naive and tz-aware timestamps"))
    )
    with pytest.raises(TypeError, match="tz-naive"):
        controller._generate_signals(_ts(controller), _slice_map(controller), {}, False)


def test_attributeerror_in_alpha_propagates():
    """AttributeError indicates an interface drift / typo and must
    propagate — not be silently zeroed out."""
    controller = _build_controller(
        _FakeAlphaRaises(AttributeError("'Foo' object has no attribute 'bar'"))
    )
    with pytest.raises(AttributeError, match="no attribute"):
        controller._generate_signals(_ts(controller), _slice_map(controller), {}, False)


# ---------------------------------------------------------------------- #
# Operational/data errors stay swallowed but must emit a logger.warning.
# ---------------------------------------------------------------------- #


def test_keyerror_in_alpha_swallowed_with_warning(caplog):
    """KeyError on a bad bar should not kill the run — but the operator
    must be able to see it without flipping the BACKTEST_CONTROLLER debug
    flag."""
    controller = _build_controller(_FakeAlphaRaises(KeyError("MISSING_TICKER")))
    with caplog.at_level(logging.WARNING, logger="backtester.backtest_controller"):
        signals = controller._generate_signals(
            _ts(controller), _slice_map(controller), {}, False
        )
    assert signals == []
    assert any(
        "Alpha signal generation error" in rec.getMessage()
        and "KeyError" in rec.getMessage()
        for rec in caplog.records
    ), f"Expected logger.warning with KeyError; got: {[r.getMessage() for r in caplog.records]}"


def test_valueerror_in_alpha_swallowed_with_warning(caplog):
    """ValueError (e.g., bad numeric input on a single bar) is
    operational — swallow + warn."""
    controller = _build_controller(_FakeAlphaRaises(ValueError("bad bar")))
    with caplog.at_level(logging.WARNING, logger="backtester.backtest_controller"):
        signals = controller._generate_signals(
            _ts(controller), _slice_map(controller), {}, False
        )
    assert signals == []
    assert any(
        "Alpha signal generation error" in rec.getMessage()
        and "ValueError" in rec.getMessage()
        for rec in caplog.records
    ), f"Expected logger.warning with ValueError; got: {[r.getMessage() for r in caplog.records]}"


# ---------------------------------------------------------------------- #
# Sanity: normal signal flow must be unaffected.
# ---------------------------------------------------------------------- #


def test_normal_alpha_unaffected():
    """The narrowing must not regress the happy path."""
    controller = _build_controller(_FakeAlphaNormal())
    signals = controller._generate_signals(
        _ts(controller), _slice_map(controller), {}, False
    )
    assert isinstance(signals, list)
    assert len(signals) == 1
    assert signals[0]["ticker"] == "FAKE"
