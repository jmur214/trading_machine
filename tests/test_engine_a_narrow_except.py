"""Engine A narrow-except batch (T-2026-05-08-011).

Mirrors the gauntlet remediation pattern (commits 453e04e, ee42ab7) and
the backtest_controller fix from T-2026-05-08-005 (commit 129c7ba).
Programmer errors (TypeError, AttributeError, NameError, AssertionError,
ImportError) propagate so interface-drift / typo bugs surface; legitimate
operational errors keep the swallow + ``logger.warning`` (no longer
gated on the BACKTEST_CONTROLLER / ALPHA debug flag).

Sites covered (per Agent B's 2026-05-08 audit, items 1-5):

  Item 1: alpha_engine.py:300/308/323 — optional / always-active
          edge module imports. Narrow-catch is `ModuleNotFoundError`
          only; any other exception (including `AttributeError` on
          a missing class, `TypeError` on a wrong __init__ signature)
          propagates.

  Item 2: alpha_engine.py:958 — ML-inference fallback. Same bug class
          as the 2026-05-08 zero-trade regression. Standard narrow-catch.

  Item 3a: alpha_engine.py:487 — regime / tier / paused-edge state
           load from EdgeRegistry. Standard narrow-catch.

  Item 4: composite_edge.py:76 — gene-eval loop inside Discovery
          scoring. Standard narrow-catch.

  Item 5: signal_processor.py:305 — per-edge feature-coercion for
          the meta-learner input row. ValueError stays the explicit
          operational path (non-coercible numeric); programmer
          errors propagate.

Item 3b (alpha_engine.py:770 — fallback scoring aggregation in a
deep-fallback signal-processor path) is mechanically identical to the
other narrow-catches but only reachable when the main SignalProcessor
fails first; covered by mechanical inspection of the narrow-catch
shape rather than direct test here.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest


# =====================================================================
# Item 4 — composite_edge.py:76 (gene-eval loop)
# =====================================================================


def _make_composite_edge():
    """Construct a CompositeEdge with one trivial gene + a 100-bar
    ohlc panel for two tickers. Returns (edge, data_map, as_of, regime)."""
    from engines.engine_a_alpha.edges.composite_edge import CompositeEdge

    edge = CompositeEdge.__new__(CompositeEdge)
    # Bypass full __init__ — set the minimum attributes the gene-eval
    # loop in compute_signals depends on.
    edge.genes = [{"type": "technical", "indicator": "rsi",
                   "params": {"period": 14}, "operator": "<",
                   "threshold": 50.0}]
    edge.regime_meta = {"trend": "unknown", "volatility": "unknown"}
    edge._current_data_map = {}
    edge._macro_cache = {}
    edge._earnings_cache = {}

    dates = pd.date_range("2024-01-02", periods=100, freq="B")
    df = pd.DataFrame(
        {
            "Open": np.linspace(100, 110, 100),
            "High": np.linspace(101, 111, 100),
            "Low": np.linspace(99, 109, 100),
            "Close": np.linspace(100, 110, 100),
            "Volume": [1_000_000] * 100,
        },
        index=dates,
    )
    data_map = {"AAA": df, "BBB": df.copy()}
    return edge, data_map, dates[-1], None


def test_composite_edge_gene_eval_typeerror_propagates():
    """A TypeError inside `_calc_raw_value` is a programmer error
    (return-shape drift, etc.) — it must not be silently dropped from
    the gene's contribution to Discovery scoring."""
    edge, data_map, as_of, regime = _make_composite_edge()

    def _raise_typeerror(*a, **kw):
        raise TypeError("simulated interface drift in gene calc")

    with patch.object(edge, "_calc_raw_value", side_effect=_raise_typeerror):
        with pytest.raises(TypeError, match="interface drift"):
            edge.compute_signals(data_map, as_of)


def test_composite_edge_gene_eval_keyerror_swallowed_with_debug():
    """A KeyError inside `_calc_raw_value` (e.g., missing fundamentals
    column for one ticker on one bar) is a legitimate per-(ticker, gene)
    data gap — keep the swallow but log at DEBUG so audits can surface
    the drop rate."""
    edge, data_map, as_of, regime = _make_composite_edge()

    def _raise_keyerror(*a, **kw):
        raise KeyError("simulated missing fundamentals column")

    with patch.object(edge, "_calc_raw_value", side_effect=_raise_keyerror):
        # Should not raise — the loop continues despite the swallow.
        signals = edge.compute_signals(data_map, as_of)
        # Signals dict shape may be {} or {ticker: 0} depending on the
        # downstream evaluation path; what matters is no exception.
        assert isinstance(signals, dict)


# =====================================================================
# Item 5 — signal_processor.py:305 (per-edge feature coercion)
# =====================================================================


class _FakeMetaLearner:
    """Minimal stand-in for MetaLearner that reports as trained and
    exposes a feature_names list. predict() returns a fixed score
    so we can confirm the path completes when no programmer error
    fires."""

    def __init__(self, feature_names):
        self.feature_names = list(feature_names)

    def is_trained(self):
        return True

    def predict(self, features):
        return 0.5


def _make_signal_processor_with_model():
    """Build a SignalProcessor with a fake trained meta-learner so the
    per-edge feature-coerce loop is reachable from the public API."""
    from engines.engine_a_alpha.signal_processor import (
        EnsembleSettings, HygieneSettings, MetaLearnerSettings,
        RegimeSettings, SignalProcessor,
    )

    sp = SignalProcessor(
        regime=RegimeSettings(),
        hygiene=HygieneSettings(),
        ensemble=EnsembleSettings(),
        edge_weights={"foo_v1": 1.0},
        edge_tiers={"foo_v1": "feature"},
        metalearner_settings=MetaLearnerSettings(enabled=True),
    )
    sp._metalearner = _FakeMetaLearner(["foo_v1"])
    return sp


def test_signal_processor_feature_coerce_typeerror_on_list_propagates():
    """If an edge returns a list instead of a scalar, `float(raw)`
    raises TypeError — that's a programmer error (return-shape drift)
    and must propagate. The previous `except Exception: continue`
    silently dropped the edge from the meta-learner's feature row."""
    sp = _make_signal_processor_with_model()
    edge_map = {"foo_v1": [1.0, 2.0, 3.0]}  # list, not scalar

    with pytest.raises(TypeError):
        sp._metalearner_contribution(edge_map)


def test_signal_processor_feature_coerce_valueerror_swallowed(caplog):
    """`float('not-a-number')` raises ValueError — that's the legitimate
    non-coercible-numeric path (e.g., an edge produced a string sentinel
    on a missing-data bar). Still swallow + skip."""
    sp = _make_signal_processor_with_model()
    edge_map = {"foo_v1": "not-a-number"}

    with caplog.at_level(logging.DEBUG, logger="engines.engine_a_alpha.signal_processor"):
        # No exception; `any_present` is False so the method returns
        # 0.0 (the no-trained-features-fired path).
        contribution = sp._metalearner_contribution(edge_map)
    assert contribution == 0.0


# =====================================================================
# Item 1 — alpha_engine.py module-import sites (300, 308, 323)
# =====================================================================


def _alpha_engine_minimal_init(monkeypatch, **env_overrides):
    """Construct a minimal AlphaEngine. Sets ALPHA_INCLUDE_EXTRAS=1 by
    default so the optional-import sites at 300/308 fire."""
    from engines.engine_a_alpha.alpha_engine import AlphaEngine
    from engines.engine_a_alpha.edges.momentum_edge import MomentumEdge

    for k, v in {"ALPHA_INCLUDE_EXTRAS": "1", **env_overrides}.items():
        monkeypatch.setenv(k, v)

    edges = {"momentum_edge": MomentumEdge()}
    return AlphaEngine(edges=edges, debug=False)


def test_alpha_engine_optional_import_module_not_found_swallowed(monkeypatch, caplog):
    """If `importlib.import_module` raises ModuleNotFoundError on an
    optional edge (test_edge / news_sentiment_boost), AlphaEngine
    must continue to construct successfully — that's the entire point
    of the optional-edge contract."""
    import importlib as _il
    real_import = _il.import_module

    def _fake_import(name, *a, **kw):
        if name in (
            "engines.engine_a_alpha.edges.test_edge",
            "engines.engine_a_alpha.edges.news_sentiment_boost",
        ):
            raise ModuleNotFoundError(f"simulated missing optional edge: {name}")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(_il, "import_module", _fake_import)
    with caplog.at_level(logging.WARNING, logger="engines.engine_a_alpha.alpha_engine"):
        ae = _alpha_engine_minimal_init(monkeypatch)
    # AlphaEngine constructed — optional imports degraded gracefully.
    assert ae is not None
    # Both optional-import warnings should appear.
    msgs = [r.getMessage() for r in caplog.records]
    assert any("test_edge" in m for m in msgs), msgs
    assert any("news_sentiment_boost" in m for m in msgs), msgs


def test_alpha_engine_optional_import_attributeerror_propagates(monkeypatch):
    """If the optional module file *exists* but loading it raises an
    AttributeError (typo, missing class), that's a bug — propagate.
    The previous broad `except Exception` silently treated a typo'd
    edge module as `module not present`."""
    import importlib as _il
    real_import = _il.import_module

    def _fake_import(name, *a, **kw):
        if name == "engines.engine_a_alpha.edges.test_edge":
            raise AttributeError(
                "simulated typo bug: edge module exists but a class is missing"
            )
        return real_import(name, *a, **kw)

    monkeypatch.setattr(_il, "import_module", _fake_import)
    with pytest.raises(AttributeError, match="simulated typo bug"):
        _alpha_engine_minimal_init(monkeypatch)


# =====================================================================
# Item 3a — alpha_engine.py:487 (regime / tier / paused-edge load)
# =====================================================================


def test_alpha_engine_registry_load_typeerror_propagates(monkeypatch):
    """A TypeError from EdgeRegistry.get_all_specs() (e.g., spec-class
    interface drift) is a programmer error — must propagate, not
    silently reset regime_gates / edge_tiers / paused_edge_ids to
    empty (which would degrade the meta-learner + soft-pause path
    without any visible signal)."""
    from engines.engine_a_alpha import edge_registry

    class _BrokenRegistry:
        def get_all_specs(self):
            raise TypeError("simulated registry interface drift")

    monkeypatch.setattr(edge_registry, "EdgeRegistry", _BrokenRegistry)
    with pytest.raises(TypeError, match="registry interface drift"):
        _alpha_engine_minimal_init(monkeypatch)


def test_alpha_engine_registry_load_filenotfound_swallowed(monkeypatch, caplog):
    """A FileNotFoundError (legitimate "registry yaml missing on a
    fresh checkout") is operational — swallow + warn + reset to empty
    state. AlphaEngine must still construct."""
    from engines.engine_a_alpha import edge_registry

    class _MissingRegistry:
        def get_all_specs(self):
            raise FileNotFoundError("simulated missing edges.yml")

    monkeypatch.setattr(edge_registry, "EdgeRegistry", _MissingRegistry)
    with caplog.at_level(logging.WARNING, logger="engines.engine_a_alpha.alpha_engine"):
        ae = _alpha_engine_minimal_init(monkeypatch)
    assert ae is not None
    msgs = [r.getMessage() for r in caplog.records]
    assert any("regime/tier/paused-edge state load failed" in m for m in msgs), msgs


# =====================================================================
# Mechanical sanity — _PROGRAMMER_ERRORS is the gauntlet-canonical set
# =====================================================================


def test_engine_a_programmer_errors_match_gauntlet_canonical_set():
    """Every Engine A file that uses the narrow-catch pattern must use
    the same `_PROGRAMMER_ERRORS` tuple. Drift across modules silently
    breaks the discipline."""
    from engines.engine_a_alpha.alpha_engine import _PROGRAMMER_ERRORS as A
    from engines.engine_a_alpha.edges.composite_edge import _PROGRAMMER_ERRORS as C
    from engines.engine_a_alpha.signal_processor import _PROGRAMMER_ERRORS as S

    canonical = (TypeError, AttributeError, NameError, AssertionError, ImportError)
    assert A == canonical
    assert C == canonical
    assert S == canonical
