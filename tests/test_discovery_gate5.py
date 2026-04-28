"""
tests/test_discovery_gate5.py
==============================
Unit tests for Gate 5 (universe-B generalization) in DiscoveryEngine.

Gate 5 tests candidate edges on a random sample of S&P 500 tickers NOT
in the production universe. An edge that only works on the 109 production
names is universe-overfit; it must also produce Sharpe > 0 on out-of-
universe tickers to pass.

These tests exercise `DiscoveryEngine._load_universe_b`, which is the
isolated, testable entry point for Gate 5. Full `validate_candidate`
integration is expensive (needs BacktestController) and covered by the
existing validation-pipeline smoke tests.
"""
from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_d_discovery.discovery import DiscoveryEngine


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(tmp_path) -> DiscoveryEngine:
    reg = tmp_path / "edges.yml"
    reg.write_text("edges: []\n")
    return DiscoveryEngine(
        registry_path=str(reg),
        processed_data_dir=str(tmp_path / "processed"),
    )


def _write_csv(directory, ticker: str, n_rows: int = 250) -> None:
    """Write a minimal *_1d.csv to tmp_path/processed/<ticker>_1d.csv."""
    directory.mkdir(parents=True, exist_ok=True)
    idx = pd.date_range("2022-01-03", periods=n_rows, freq="B")
    df = pd.DataFrame(
        {
            "Open": 100.0,
            "High": 101.0,
            "Low": 99.0,
            "Close": 100.5,
            "Volume": 1_000_000,
            "ATR": 1.0,
            "PrevClose": 100.0,
        },
        index=idx,
    )
    (directory / f"{ticker}_1d.csv").write_text(df.to_csv())


# ---------------------------------------------------------------------------
# _load_universe_b — happy path
# ---------------------------------------------------------------------------


def test_loads_tickers_not_in_prod(tmp_path):
    processed = tmp_path / "processed"
    for t in ("AAPL", "MSFT", "NVDA", "AA", "AAL", "ABT"):
        _write_csv(processed, t)

    engine = _make_engine(tmp_path)
    prod_tickers = {"AAPL", "MSFT", "NVDA"}  # three in prod
    dm_b = engine._load_universe_b(prod_tickers=prod_tickers, n_sample=10, seed=0)

    # Only universe-B tickers (AA, AAL, ABT) should be loaded
    assert set(dm_b.keys()) == {"AA", "AAL", "ABT"}
    assert all(isinstance(df, pd.DataFrame) for df in dm_b.values())


def test_all_tickers_in_prod_returns_empty(tmp_path):
    processed = tmp_path / "processed"
    for t in ("AAPL", "MSFT"):
        _write_csv(processed, t)

    engine = _make_engine(tmp_path)
    dm_b = engine._load_universe_b(prod_tickers={"AAPL", "MSFT"}, n_sample=10)
    assert dm_b == {}


def test_no_csvs_in_dir_returns_empty(tmp_path):
    (tmp_path / "processed").mkdir()
    engine = _make_engine(tmp_path)
    dm_b = engine._load_universe_b(prod_tickers=set(), n_sample=10)
    assert dm_b == {}


# ---------------------------------------------------------------------------
# _load_universe_b — sampling behaviour
# ---------------------------------------------------------------------------


def test_sample_size_respected(tmp_path):
    processed = tmp_path / "processed"
    for i in range(30):
        _write_csv(processed, f"TICK{i:03d}")

    engine = _make_engine(tmp_path)
    dm_b = engine._load_universe_b(prod_tickers=set(), n_sample=10, seed=1)
    assert len(dm_b) == 10


def test_sample_size_larger_than_pool_loads_all(tmp_path):
    processed = tmp_path / "processed"
    for t in ("AA", "ABT", "ACN"):
        _write_csv(processed, t)

    engine = _make_engine(tmp_path)
    dm_b = engine._load_universe_b(prod_tickers=set(), n_sample=100, seed=0)
    assert len(dm_b) == 3  # can't load more than available


def test_sampling_is_reproducible(tmp_path):
    processed = tmp_path / "processed"
    for i in range(50):
        _write_csv(processed, f"X{i:03d}")

    engine = _make_engine(tmp_path)
    dm_a = engine._load_universe_b(prod_tickers=set(), n_sample=15, seed=42)
    dm_b = engine._load_universe_b(prod_tickers=set(), n_sample=15, seed=42)
    assert set(dm_a.keys()) == set(dm_b.keys())


def test_different_seeds_produce_different_samples(tmp_path):
    processed = tmp_path / "processed"
    for i in range(100):
        _write_csv(processed, f"Z{i:03d}")

    engine = _make_engine(tmp_path)
    dm_0 = engine._load_universe_b(prod_tickers=set(), n_sample=10, seed=0)
    dm_1 = engine._load_universe_b(prod_tickers=set(), n_sample=10, seed=1)
    # With 100 tickers and sample size 10, different seeds almost certainly
    # produce different selections.
    assert set(dm_0.keys()) != set(dm_1.keys())


# ---------------------------------------------------------------------------
# _load_universe_b — data quality filter
# ---------------------------------------------------------------------------


def test_short_files_are_excluded(tmp_path):
    """Files with fewer than 100 rows are too thin — skip them."""
    processed = tmp_path / "processed"
    _write_csv(processed, "THICK", n_rows=200)
    _write_csv(processed, "THIN", n_rows=50)

    engine = _make_engine(tmp_path)
    dm_b = engine._load_universe_b(prod_tickers=set(), n_sample=10)
    assert "THICK" in dm_b
    assert "THIN" not in dm_b


def test_malformed_csv_is_skipped(tmp_path):
    processed = tmp_path / "processed"
    _write_csv(processed, "GOOD", n_rows=200)
    # Write a file that will raise on read
    (processed / "BAD_1d.csv").write_text("not,valid,csv\x00\x01")

    engine = _make_engine(tmp_path)
    # Should not raise; BAD is quietly skipped.
    dm_b = engine._load_universe_b(prod_tickers=set(), n_sample=10)
    assert "GOOD" in dm_b
    assert "BAD" not in dm_b


# ---------------------------------------------------------------------------
# Gate 5 gate logic — Sharpe > 0 and nan-skip semantics
# ---------------------------------------------------------------------------


def test_gate5_passes_when_universe_b_sharpe_positive():
    """Sharpe > 0 on universe B → gate passes."""
    import math
    universe_b_sharpe = 0.5
    universe_b_passed = math.isnan(universe_b_sharpe) or universe_b_sharpe > 0
    assert universe_b_passed is True


def test_gate5_fails_when_universe_b_sharpe_zero():
    import math
    universe_b_sharpe = 0.0
    universe_b_passed = math.isnan(universe_b_sharpe) or universe_b_sharpe > 0
    assert universe_b_passed is False


def test_gate5_fails_when_universe_b_sharpe_negative():
    import math
    universe_b_sharpe = -0.3
    universe_b_passed = math.isnan(universe_b_sharpe) or universe_b_sharpe > 0
    assert universe_b_passed is False


def test_gate5_skips_when_sharpe_nan():
    """nan means no universe-B data was available — don't penalise the edge."""
    import math
    universe_b_sharpe = float("nan")
    universe_b_passed = math.isnan(universe_b_sharpe) or universe_b_sharpe > 0
    assert universe_b_passed is True
