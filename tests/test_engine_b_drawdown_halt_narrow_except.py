"""Engine B drawdown-halt narrow-except (T-2026-05-08-012).

Closes the highest-blast-radius bug class in Engine B: a silent
TypeError in the drawdown-percent extraction at
``risk_engine.py:796`` would default ``dd_pct=0.0`` and silently
defeat the 5%/10%/15% kill switch — the kill switch becoming inert
without anyone noticing is the catastrophic-failure mode for live
trading.

Pattern matches T-005 (commit 129c7ba) and T-011 (commit 7c9dac0):
programmer errors (TypeError, AttributeError, NameError,
AssertionError, ImportError) propagate; operational errors
(KeyError, ValueError) keep the swallow + ``logger.warning``
(unconditional, not gated on the RISK debug flag).

Tests drive ``prepare_order`` end-to-end with the kill switch armed
and a stub portfolio whose ``current_drawdown_pct`` triggers each
exception branch — confirming the PRODUCTION catch's behavior, not
a mirror of it.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd
import pytest

from engines.engine_b_risk.risk_engine import RiskEngine, _PROGRAMMER_ERRORS


# ---------------------------------------------------------------------- #
# Test scaffolding
# ---------------------------------------------------------------------- #


class _NaughtyValue:
    """Object whose ``__float__`` raises a configurable exception. Used
    to surgically trigger each branch of the narrow-catch at the
    ``float(...)`` call inside risk_engine.py:794."""

    def __init__(self, exc: BaseException):
        self._exc = exc

    def __float__(self):
        raise self._exc


class _StubPortfolio:
    """Stand-in for PortfolioEngine that exposes the only two
    attributes the kill-switch path reads: ``history`` (list of
    snapshot dicts) and ``positions`` (used for the prior-position
    check at line 562)."""

    def __init__(self, current_drawdown_pct):
        self.history = [{"current_drawdown_pct": current_drawdown_pct}]
        self.positions = {}


def _make_df_hist(periods: int = 50) -> pd.DataFrame:
    """Minimum-viable per-ticker frame: 50 bars, valid ATR populated,
    enough history to clear the warmup gate."""
    dates = pd.date_range("2024-01-02", periods=periods, freq="B")
    return pd.DataFrame(
        {
            "Open": np.linspace(100, 110, periods),
            "High": np.linspace(101, 111, periods),
            "Low": np.linspace(99, 109, periods),
            "Close": np.linspace(100, 110, periods),
            "Volume": [1_000_000] * periods,
            "ATR": [2.0] * periods,
        },
        index=dates,
    )


def _make_re_with_dd_value(value) -> RiskEngine:
    """RiskEngine with the kill switch armed and a stub portfolio whose
    latest snapshot has ``current_drawdown_pct=value``."""
    re = RiskEngine(cfg={
        "drawdown_kill_switch_enabled": True,
        "min_bars_warmup": 30,
    })
    re.portfolio = _StubPortfolio(value)
    return re


def _signal(ticker: str = "AAA", side: str = "long") -> dict:
    return {"ticker": ticker, "side": side, "strength": 0.5}


# ---------------------------------------------------------------------- #
# Programmer errors must propagate
# ---------------------------------------------------------------------- #


def test_typeerror_in_drawdown_calc_propagates():
    """If Engine C's portfolio_snapshot schema drifts and emits a
    non-numeric current_drawdown_pct that triggers TypeError on
    float(), the narrow-catch must propagate — not silently default
    to 0.0 and defeat the kill switch."""
    re = _make_re_with_dd_value(
        _NaughtyValue(TypeError("simulated schema drift"))
    )
    with pytest.raises(TypeError, match="schema drift"):
        re.prepare_order(_signal(), equity=100_000.0,
                         df_hist=_make_df_hist(), current_qty=0)


def test_attributeerror_in_drawdown_calc_propagates():
    """A snapshot that's not a dict (e.g., None) raises AttributeError
    on `.get()`. That's a snapshot-shape bug — must propagate so the
    operator sees Engine C's contract is broken, not silently fall
    back to dd_pct=0.0 and disable the kill switch."""
    re = _make_re_with_dd_value(0.0)
    re.portfolio.history = [None]  # snapshot is None, not a dict
    with pytest.raises(AttributeError):
        re.prepare_order(_signal(), equity=100_000.0,
                         df_hist=_make_df_hist(), current_qty=0)


# ---------------------------------------------------------------------- #
# Operational errors stay swallowed but emit logger.warning
# ---------------------------------------------------------------------- #


def test_valueerror_in_drawdown_calc_swallowed_with_warning(caplog):
    """A malformed numeric string ("not-a-number") raises ValueError
    on float(). Operational error — keep the dd_pct=0.0 fallback but
    warn unconditionally so the operator sees the kill-switch path
    is degraded."""
    re = _make_re_with_dd_value("not-a-number")
    with caplog.at_level(logging.WARNING, logger="engines.engine_b_risk.risk_engine"):
        # prepare_order should complete (kill-switch never fires
        # because dd_pct fell back to 0.0).
        result = re.prepare_order(_signal(), equity=100_000.0,
                                  df_hist=_make_df_hist(), current_qty=0)
    # No exception; processing continued.
    assert result is None or isinstance(result, dict)
    msgs = [r.getMessage() for r in caplog.records]
    assert any(
        "Drawdown calc fell back" in m and "ValueError" in m and "kill switch may be inert" in m
        for m in msgs
    ), f"Expected logger.warning about kill-switch degradation; got: {msgs}"


def test_keyerror_in_drawdown_calc_swallowed_with_warning(caplog):
    """A custom history-entry that raises KeyError on .get() exercises
    the operational-error swallow + warn path. Confirms KeyError is
    NOT in _PROGRAMMER_ERRORS and the catch handles it gracefully."""

    class _KeyErrorOnGet:
        def get(self, key, default=None):
            raise KeyError(f"simulated stale snapshot shape: {key}")

    re = _make_re_with_dd_value(0.0)
    re.portfolio.history = [_KeyErrorOnGet()]
    with caplog.at_level(logging.WARNING, logger="engines.engine_b_risk.risk_engine"):
        result = re.prepare_order(_signal(), equity=100_000.0,
                                  df_hist=_make_df_hist(), current_qty=0)
    assert result is None or isinstance(result, dict)
    msgs = [r.getMessage() for r in caplog.records]
    assert any(
        "Drawdown calc fell back" in m and "KeyError" in m
        for m in msgs
    ), f"Expected logger.warning about KeyError; got: {msgs}"


# ---------------------------------------------------------------------- #
# Sanity: normal numeric path is unaffected (kill-switch behavior intact)
# ---------------------------------------------------------------------- #


def test_normal_drawdown_calc_unaffected_below_threshold():
    """With a valid float well below the halt threshold (default 15%),
    the kill switch does not fire and prepare_order returns a normal
    order dict."""
    re = _make_re_with_dd_value(0.05)  # 5% drawdown — below 15% halt
    result = re.prepare_order(_signal(), equity=100_000.0,
                              df_hist=_make_df_hist(), current_qty=0)
    assert isinstance(result, dict)
    assert result.get("ticker") == "AAA"
    assert result.get("side") == "long"


def test_normal_drawdown_calc_unaffected_above_threshold_blocks():
    """With a valid float at/above the halt threshold (15%), the kill
    switch fires and prepare_order returns None with a
    'drawdown_halt' skip reason. This regression-tests that the
    narrow-catch did not break the kill-switch's actual job."""
    re = _make_re_with_dd_value(0.20)  # 20% drawdown — above 15% halt
    result = re.prepare_order(_signal(), equity=100_000.0,
                              df_hist=_make_df_hist(), current_qty=0)
    assert result is None
    assert re.last_skip_by_ticker.get("AAA") == "drawdown_halt"


# ---------------------------------------------------------------------- #
# Mechanical sanity: Engine B's _PROGRAMMER_ERRORS matches the
# gauntlet-canonical 5-class set used by Engine A (T-011), backtester
# (T-005), and Engine D (commits 453e04e + ee42ab7).
# ---------------------------------------------------------------------- #


def test_engine_b_programmer_errors_match_canonical_set():
    canonical = (TypeError, AttributeError, NameError, AssertionError, ImportError)
    assert _PROGRAMMER_ERRORS == canonical


def test_engine_b_tuple_matches_engine_a_tuple():
    """Cross-module sanity: Engine B's tuple must equal Engine A's
    (alpha_engine, composite_edge, signal_processor) — drift across
    modules silently breaks the discipline."""
    from engines.engine_a_alpha.alpha_engine import _PROGRAMMER_ERRORS as A
    from engines.engine_a_alpha.edges.composite_edge import _PROGRAMMER_ERRORS as C
    from engines.engine_a_alpha.signal_processor import _PROGRAMMER_ERRORS as S
    assert _PROGRAMMER_ERRORS == A == C == S
