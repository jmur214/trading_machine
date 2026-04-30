"""tests/test_per_ticker_score_logger.py
==========================================
Phase 2.11 prep — regression coverage for the per-bar per-ticker
per-edge score logger and its AlphaEngine integration.

Three things must hold:
1. The logger captures every (ticker, edge) pair in `proc.edges_detail`
   on every bar, with the schema documented in
   `engines/engine_a_alpha/per_ticker_score_logger.py::SCHEMA_COLUMNS`.
2. The `fired` flag matches the per-ticker signal's `edges_triggered`
   list — i.e. equals True iff the edge cleared `min_edge_contribution`.
3. AlphaEngine runs cleanly without the logger (off-by-default), and
   when the logger is injected the parquet appears at the expected path.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.per_ticker_score_logger import (  # noqa: E402
    PerTickerScoreLogger,
    SCHEMA_COLUMNS,
)


# ---------------------------------------------------------------------------
# Direct logger tests (no AlphaEngine — isolate the data-shape contract)
# ---------------------------------------------------------------------------

class TestLoggerSchema:
    def test_log_bar_appends_one_row_per_edge_per_ticker(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="test1", out_dir=tmp_path)
        proc = {
            "AAPL": {
                "aggregate_score": 0.42,
                "regimes": {"trend": True, "vol_ok": True},
                "edges_detail": [
                    {"edge": "edge_a", "raw": 0.8, "norm": 0.5, "weight": 1.0},
                    {"edge": "edge_b", "raw": -0.3, "norm": -0.2, "weight": 0.5},
                ],
            },
            "MSFT": {
                "aggregate_score": -0.1,
                "regimes": {"trend": False, "vol_ok": True},
                "edges_detail": [
                    {"edge": "edge_a", "raw": -0.1, "norm": -0.1, "weight": 1.0},
                ],
            },
        }
        signals = [
            {"ticker": "AAPL", "side": "long", "strength": 0.42,
             "meta": {"edges_triggered": [
                 {"edge": "edge_a", "edge_id": "edge_a_v1",
                  "edge_category": "x", "raw": 0.8, "norm": 0.5, "weight": 1.0},
             ]}},
        ]
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15 09:30"),
            proc=proc, signals=signals,
            regime_meta={"advisory": {"regime_summary": "benign"}},
        )
        assert logger.n_rows() == 3  # AAPL × 2 + MSFT × 1

    def test_flush_writes_parquet_with_schema(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="test2", out_dir=tmp_path)
        proc = {
            "AAPL": {
                "aggregate_score": 0.5,
                "regimes": {},
                "edges_detail": [
                    {"edge": "edge_a", "raw": 0.5, "norm": 0.4, "weight": 1.0},
                ],
            },
        }
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc=proc, signals=[],
            regime_meta={"advisory": {"regime_summary": "stressed"}},
        )
        out = logger.flush()
        assert out is not None and out.exists()
        df = pd.read_parquet(out)
        assert list(df.columns) == SCHEMA_COLUMNS
        assert len(df) == 1
        row = df.iloc[0]
        assert row["ticker"] == "AAPL"
        assert row["edge_id"] == "edge_a_v1"  # synthesized
        assert row["raw_score"] == 0.5
        assert row["norm_score"] == 0.4
        assert row["weight"] == 1.0
        assert row["aggregate_score"] == 0.5
        assert row["regime_summary"] == "stressed"
        assert bool(row["fired"]) is False

    def test_flush_empty_buffer_returns_none(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="test_empty", out_dir=tmp_path)
        out = logger.flush()
        assert out is None
        assert not (tmp_path / "test_empty.parquet").exists()


class TestFiredFlag:
    """`fired` must reflect which edges were attached to a per-ticker
    signal's edges_triggered list (i.e. cleared min_edge_contribution)."""

    def test_fired_true_when_edge_in_signal_triggered_list(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="test_fired", out_dir=tmp_path)
        proc = {
            "AAPL": {
                "aggregate_score": 0.6,
                "regimes": {},
                "edges_detail": [
                    {"edge": "edge_a", "edge_id": "edge_a_v1",
                     "raw": 0.8, "norm": 0.5, "weight": 1.0},
                    {"edge": "edge_b", "edge_id": "edge_b_v1",
                     "raw": 0.05, "norm": 0.02, "weight": 0.5},  # weak
                ],
            },
        }
        # Only edge_a cleared min_edge_contribution this bar
        signals = [
            {"ticker": "AAPL", "side": "long", "strength": 0.6,
             "meta": {"edges_triggered": [
                 {"edge": "edge_a", "edge_id": "edge_a_v1",
                  "edge_category": "x", "raw": 0.8, "norm": 0.5, "weight": 1.0},
             ]}},
        ]
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc=proc, signals=signals,
            regime_meta={"advisory": {"regime_summary": "benign"}},
        )
        out = logger.flush()
        df = pd.read_parquet(out)
        fired_by_edge = dict(zip(df["edge_id"], df["fired"]))
        assert fired_by_edge["edge_a_v1"] is True or fired_by_edge["edge_a_v1"] == True  # noqa: E712
        assert fired_by_edge["edge_b_v1"] is False or fired_by_edge["edge_b_v1"] == False  # noqa: E712

    def test_fired_false_when_no_signal_for_ticker(self, tmp_path):
        """Ticker's score gets logged even if no signal was emitted; in
        that case `fired` must be False for every edge on that ticker."""
        logger = PerTickerScoreLogger(run_uuid="test_no_sig", out_dir=tmp_path)
        proc = {
            "AAPL": {
                "aggregate_score": 0.05,  # below threshold
                "regimes": {},
                "edges_detail": [
                    {"edge": "edge_a", "raw": 0.1, "norm": 0.05, "weight": 1.0},
                ],
            },
        }
        signals = []  # no signal emitted (below threshold)
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc=proc, signals=signals,
            regime_meta=None,
        )
        out = logger.flush()
        df = pd.read_parquet(out)
        assert len(df) == 1
        assert bool(df["fired"].iloc[0]) is False


class TestEdgeIdResolution:
    """Regression coverage for the smoke-run double-suffix bug. The
    SignalProcessor's edges_detail item uses `edge` for the canonical
    registry key (e.g. `momentum_edge_v1`); appending another `_v1`
    yields `momentum_edge_v1_v1` and breaks downstream joins."""

    def test_edge_with_version_suffix_passes_through_unchanged(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="eid1", out_dir=tmp_path)
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc={"AAPL": {
                "aggregate_score": 0.0,
                "regimes": {},
                "edges_detail": [
                    {"edge": "momentum_edge_v1", "raw": 0.5,
                     "norm": 0.4, "weight": 1.0},
                ],
            }},
            signals=[], regime_meta=None,
        )
        out = logger.flush()
        df = pd.read_parquet(out)
        assert df["edge_id"].iloc[0] == "momentum_edge_v1", (
            "edge name with _v1 suffix must not be double-suffixed"
        )

    def test_bare_edge_name_synthesizes_v1_suffix(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="eid2", out_dir=tmp_path)
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc={"AAPL": {
                "aggregate_score": 0.0,
                "regimes": {},
                "edges_detail": [
                    {"edge": "rsi_bounce", "raw": 0.5,
                     "norm": 0.4, "weight": 1.0},
                ],
            }},
            signals=[], regime_meta=None,
        )
        out = logger.flush()
        df = pd.read_parquet(out)
        assert df["edge_id"].iloc[0] == "rsi_bounce_v1"

    def test_explicit_edge_id_wins_over_edge_name(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="eid3", out_dir=tmp_path)
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc={"AAPL": {
                "aggregate_score": 0.0,
                "regimes": {},
                "edges_detail": [
                    {"edge": "rsi_bounce", "edge_id": "rsi_bounce_v3",
                     "raw": 0.5, "norm": 0.4, "weight": 1.0},
                ],
            }},
            signals=[], regime_meta=None,
        )
        out = logger.flush()
        df = pd.read_parquet(out)
        assert df["edge_id"].iloc[0] == "rsi_bounce_v3"


class TestRegimeSummaryResolution:
    """regime_summary should pull from advisory.regime_summary when
    present, fall back to top-level regime, then 'unknown'."""

    def test_advisory_regime_summary_wins(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="r1", out_dir=tmp_path)
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc={"X": {"aggregate_score": 0.0, "regimes": {},
                        "edges_detail": [{"edge": "e", "raw": 0,
                                          "norm": 0, "weight": 1}]}},
            signals=[],
            regime_meta={
                "regime": "neutral_normal_vol",
                "advisory": {"regime_summary": "stressed"},
            },
        )
        out = logger.flush()
        df = pd.read_parquet(out)
        assert df["regime_summary"].iloc[0] == "stressed"

    def test_falls_back_to_top_level_regime(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="r2", out_dir=tmp_path)
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc={"X": {"aggregate_score": 0.0, "regimes": {},
                        "edges_detail": [{"edge": "e", "raw": 0,
                                          "norm": 0, "weight": 1}]}},
            signals=[],
            regime_meta={"regime": "robust_expansion"},
        )
        out = logger.flush()
        df = pd.read_parquet(out)
        assert df["regime_summary"].iloc[0] == "robust_expansion"

    def test_unknown_when_regime_meta_missing(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="r3", out_dir=tmp_path)
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc={"X": {"aggregate_score": 0.0, "regimes": {},
                        "edges_detail": [{"edge": "e", "raw": 0,
                                          "norm": 0, "weight": 1}]}},
            signals=[],
            regime_meta=None,
        )
        out = logger.flush()
        df = pd.read_parquet(out)
        assert df["regime_summary"].iloc[0] == "unknown"


class TestDefensiveBehavior:
    """The logger must never raise through the public API — bar-level
    failures should be swallowed with a warning, not break the backtest."""

    def test_log_bar_handles_malformed_proc(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="d1", out_dir=tmp_path)
        # malformed: ticker maps to non-dict
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc={"AAPL": "not_a_dict"},
            signals=[], regime_meta=None,
        )
        # Should produce zero rows but not raise
        assert logger.n_rows() == 0

    def test_log_bar_handles_empty_proc(self, tmp_path):
        logger = PerTickerScoreLogger(run_uuid="d2", out_dir=tmp_path)
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc={}, signals=[], regime_meta=None,
        )
        assert logger.n_rows() == 0

    def test_log_bar_handles_edge_detail_missing_keys(self, tmp_path):
        """Edge detail with missing raw/norm/weight should default to 0
        rather than raise."""
        logger = PerTickerScoreLogger(run_uuid="d3", out_dir=tmp_path)
        logger.log_bar(
            timestamp=pd.Timestamp("2024-03-15"),
            proc={"AAPL": {"aggregate_score": 0.0, "regimes": {},
                           "edges_detail": [{"edge": "edge_a"}]}},  # no scores
            signals=[], regime_meta=None,
        )
        out = logger.flush()
        df = pd.read_parquet(out)
        assert df["raw_score"].iloc[0] == 0.0
        assert df["norm_score"].iloc[0] == 0.0
        assert df["weight"].iloc[0] == 0.0


# ---------------------------------------------------------------------------
# AlphaEngine integration — off-by-default + on-emits
# ---------------------------------------------------------------------------

class TestAlphaEngineIntegration:
    """AlphaEngine must accept None (default) and a real logger and not
    behave differently in either case beyond the parquet emit."""

    def test_alpha_engine_constructs_without_logger(self):
        """Default construction should NOT require the logger arg."""
        from engines.engine_a_alpha.alpha_engine import AlphaEngine
        engine = AlphaEngine(edges={})
        assert engine.per_ticker_score_logger is None

    def test_alpha_engine_accepts_logger_and_stores_it(self, tmp_path):
        """Passing a logger should attach it to the engine instance."""
        from engines.engine_a_alpha.alpha_engine import AlphaEngine
        logger = PerTickerScoreLogger(run_uuid="ae_test", out_dir=tmp_path)
        engine = AlphaEngine(edges={}, per_ticker_score_logger=logger)
        assert engine.per_ticker_score_logger is logger

    def test_mode_controller_signature_includes_flag(self):
        """run_backtest must expose the flag so CLI/programmatic callers
        can opt in. Source-level guard so nobody removes the parameter."""
        from orchestration.mode_controller import ModeController
        import inspect
        sig = inspect.signature(ModeController.run_backtest)
        assert "log_per_ticker_scores" in sig.parameters
        # Default must be False — backwards-compat with existing callers
        assert sig.parameters["log_per_ticker_scores"].default is False


# ---------------------------------------------------------------------------
# CLI surface — argparse must surface the flag
# ---------------------------------------------------------------------------

def test_cli_exposes_log_per_ticker_scores_flag():
    """CLI guard: scripts/run_backtest.py must surface the flag in argparse
    so users can enable score logging without code edits."""
    src = (Path(__file__).resolve().parents[1]
           / "scripts" / "run_backtest.py").read_text()
    assert "--log-per-ticker-scores" in src
    assert "log_per_ticker_scores" in src
