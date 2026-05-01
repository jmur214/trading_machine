"""tests/test_signal_processor_per_ticker.py
==============================================
Phase 2.11 — per-ticker meta-learner integration tests for SignalProcessor.

Three things must hold:
1. With `per_ticker=False`, behavior is identical to portfolio-only mode.
2. With `per_ticker=True` and a ticker-specific model present, that
   model's prediction drives the contribution.
3. With `per_ticker=True` but the requested ticker has NO ticker-specific
   model, the portfolio model is used (cold-start fallback).

The test fixtures train tiny GBR models in-memory so the test doesn't
need real backtest data.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from engines.engine_a_alpha.metalearner import MetaLearner  # noqa: E402
from engines.engine_a_alpha.signal_processor import (  # noqa: E402
    EnsembleSettings, HygieneSettings, MetaLearnerSettings,
    RegimeSettings, SignalProcessor,
)


def _build_processor(
    metalearner_settings: MetaLearnerSettings,
    edge_tiers=None,
) -> SignalProcessor:
    return SignalProcessor(
        regime=RegimeSettings(enable_trend=False, enable_vol=False),
        hygiene=HygieneSettings(min_history=2, dedupe_last_n=1, clamp=6.0),
        ensemble=EnsembleSettings(enable_shrink=False, shrink_lambda=0.0),
        edge_weights={"edge_a": 1.0, "edge_b": 1.0},
        regime_gates=None,
        debug=False,
        metalearner_settings=metalearner_settings,
        edge_tiers=edge_tiers or {"edge_a": "feature", "edge_b": "feature"},
    )


def _train_demo_model(profile_name: str, multiplier: float) -> MetaLearner:
    """Train a tiny GBR whose prediction is roughly `multiplier * edge_a`.

    Used to assert that different model files produce different contributions
    so the test confirms which one was loaded.
    """
    rng = np.random.default_rng(seed=42)
    X = pd.DataFrame({
        "edge_a": rng.uniform(-1, 1, 200),
        "edge_b": rng.uniform(-1, 1, 200),
    })
    # Target = multiplier * edge_a (so the model learns to give that weight).
    y = pd.Series(multiplier * X["edge_a"].values)
    model = MetaLearner(profile_name=profile_name)
    model.fit(X, y)
    return model


def _save_per_ticker(model: MetaLearner, ticker: str, model_dir: Path) -> Path:
    """Mirror scripts/train_per_ticker_metalearner.py::_save_per_ticker."""
    import joblib
    model_dir.mkdir(parents=True, exist_ok=True)
    path = model_dir / f"{ticker}.pkl"
    payload = {
        "profile_name": model.profile_name,
        "ticker": ticker,
        "hyperparams": model.hyperparams,
        "model": model._model,
        "feature_names": model.feature_names,
        "target_clip": model.target_clip,
        "n_train_samples": model.n_train_samples,
        "train_metadata": model.train_metadata,
    }
    joblib.dump(payload, path)
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPerTickerModelLoading:

    def test_per_ticker_disabled_falls_through_to_portfolio(self, tmp_path, monkeypatch):
        """With per_ticker=False, only the portfolio model is consulted."""
        # Save a portfolio model in the default location
        portfolio = _train_demo_model("balanced", multiplier=2.0)
        portfolio_dir = tmp_path / "default"
        portfolio_dir.mkdir()
        portfolio_path = portfolio_dir / "metalearner_balanced.pkl"
        # Use MetaLearner.save() pattern
        import joblib
        joblib.dump({
            "profile_name": "balanced",
            "hyperparams": portfolio.hyperparams,
            "model": portfolio._model,
            "feature_names": portfolio.feature_names,
            "target_clip": portfolio.target_clip,
            "n_train_samples": portfolio.n_train_samples,
            "train_metadata": portfolio.train_metadata,
        }, portfolio_path)
        monkeypatch.setattr(
            "engines.engine_a_alpha.metalearner.DEFAULT_MODEL_DIR",
            portfolio_dir,
        )

        sp = _build_processor(MetaLearnerSettings(
            enabled=True, profile_name="balanced",
            contribution_weight=0.1, per_ticker=False,
        ))
        # AAPL contribution should come from portfolio model, NOT a
        # per-ticker model (none loaded). Just assert it runs and is finite.
        c = sp._metalearner_contribution(
            {"edge_a": 0.5, "edge_b": -0.2}, ticker="AAPL",
        )
        assert isinstance(c, float)
        assert np.isfinite(c)

    def test_per_ticker_enabled_uses_ticker_model_when_available(
        self, tmp_path, monkeypatch,
    ):
        """When the ticker has its own model, per-ticker mode picks it
        over the portfolio model. Use models with very different
        multipliers so we can detect which was used."""
        # Portfolio model: multiplier 2 → contribution sign=positive when edge_a positive
        portfolio = _train_demo_model("balanced", multiplier=+2.0)
        portfolio_dir = tmp_path / "portfolio"
        portfolio_dir.mkdir()
        import joblib
        joblib.dump({
            "profile_name": "balanced",
            "hyperparams": portfolio.hyperparams,
            "model": portfolio._model,
            "feature_names": portfolio.feature_names,
            "target_clip": portfolio.target_clip,
            "n_train_samples": portfolio.n_train_samples,
            "train_metadata": portfolio.train_metadata,
        }, portfolio_dir / "metalearner_balanced.pkl")
        monkeypatch.setattr(
            "engines.engine_a_alpha.metalearner.DEFAULT_MODEL_DIR",
            portfolio_dir,
        )

        # Per-ticker model for AAPL: multiplier -2 → contribution is OPPOSITE sign
        per_ticker_dir = tmp_path / "per_ticker_models"
        ticker_model = _train_demo_model("balanced", multiplier=-2.0)
        _save_per_ticker(ticker_model, "AAPL", per_ticker_dir)

        sp = _build_processor(MetaLearnerSettings(
            enabled=True, profile_name="balanced",
            contribution_weight=0.1, per_ticker=True,
            per_ticker_model_dir=str(per_ticker_dir),
        ))
        # With edge_a = 0.5: portfolio model would predict ~+1.0 → contribution > 0
        # Per-ticker model (multiplier -2) would predict ~-1.0 → contribution < 0
        contribution = sp._metalearner_contribution(
            {"edge_a": 0.5, "edge_b": 0.0}, ticker="AAPL",
        )
        assert contribution < 0, (
            f"per-ticker AAPL model trained with multiplier=-2 should "
            f"produce negative contribution on edge_a=+0.5, got {contribution}"
        )

    def test_per_ticker_falls_back_to_portfolio_for_missing_ticker(
        self, tmp_path, monkeypatch,
    ):
        """If per_ticker is on but the ticker has no model file, the
        portfolio model is used. With multiplier=+2 portfolio model and
        edge_a=+0.5 we expect positive contribution."""
        portfolio = _train_demo_model("balanced", multiplier=+2.0)
        portfolio_dir = tmp_path / "portfolio"
        portfolio_dir.mkdir()
        import joblib
        joblib.dump({
            "profile_name": "balanced",
            "hyperparams": portfolio.hyperparams,
            "model": portfolio._model,
            "feature_names": portfolio.feature_names,
            "target_clip": portfolio.target_clip,
            "n_train_samples": portfolio.n_train_samples,
            "train_metadata": portfolio.train_metadata,
        }, portfolio_dir / "metalearner_balanced.pkl")
        monkeypatch.setattr(
            "engines.engine_a_alpha.metalearner.DEFAULT_MODEL_DIR",
            portfolio_dir,
        )

        per_ticker_dir = tmp_path / "per_ticker_empty"
        # Save a model for MSFT, NOT for AAPL
        ticker_model = _train_demo_model("balanced", multiplier=-3.0)
        _save_per_ticker(ticker_model, "MSFT", per_ticker_dir)

        sp = _build_processor(MetaLearnerSettings(
            enabled=True, profile_name="balanced",
            contribution_weight=0.1, per_ticker=True,
            per_ticker_model_dir=str(per_ticker_dir),
        ))
        # AAPL has no per-ticker model → fall back to portfolio (mult +2)
        # → positive contribution on edge_a=+0.5
        c_aapl = sp._metalearner_contribution(
            {"edge_a": 0.5, "edge_b": 0.0}, ticker="AAPL",
        )
        assert c_aapl > 0, f"AAPL fallback should give positive, got {c_aapl}"

        # MSFT has its own model (mult -3) → negative contribution
        c_msft = sp._metalearner_contribution(
            {"edge_a": 0.5, "edge_b": 0.0}, ticker="MSFT",
        )
        assert c_msft < 0, f"MSFT per-ticker should give negative, got {c_msft}"

    def test_per_ticker_load_caches(self, tmp_path, monkeypatch):
        """Per-ticker model should be loaded at most once per ticker per
        SignalProcessor lifetime — repeated calls hit the cache."""
        portfolio_dir = tmp_path / "portfolio"
        portfolio_dir.mkdir()
        monkeypatch.setattr(
            "engines.engine_a_alpha.metalearner.DEFAULT_MODEL_DIR",
            portfolio_dir,
        )

        per_ticker_dir = tmp_path / "ptm"
        ticker_model = _train_demo_model("balanced", multiplier=+1.0)
        _save_per_ticker(ticker_model, "AAPL", per_ticker_dir)

        sp = _build_processor(MetaLearnerSettings(
            enabled=True, profile_name="balanced",
            contribution_weight=0.1, per_ticker=True,
            per_ticker_model_dir=str(per_ticker_dir),
        ))
        sp._metalearner_contribution({"edge_a": 0.5}, ticker="AAPL")
        first_cache = dict(sp._per_ticker_models or {})
        sp._metalearner_contribution({"edge_a": 0.5}, ticker="AAPL")
        second_cache = dict(sp._per_ticker_models or {})
        assert "AAPL" in first_cache
        assert first_cache["AAPL"] is second_cache["AAPL"]  # same instance

    def test_missing_ticker_recorded_in_misses(self, tmp_path, monkeypatch):
        """A miss should be recorded so subsequent calls don't re-hit disk."""
        portfolio_dir = tmp_path / "portfolio"
        portfolio_dir.mkdir()
        monkeypatch.setattr(
            "engines.engine_a_alpha.metalearner.DEFAULT_MODEL_DIR",
            portfolio_dir,
        )

        per_ticker_dir = tmp_path / "ptm_empty"
        per_ticker_dir.mkdir()

        sp = _build_processor(MetaLearnerSettings(
            enabled=True, profile_name="balanced",
            contribution_weight=0.1, per_ticker=True,
            per_ticker_model_dir=str(per_ticker_dir),
        ))
        sp._metalearner_contribution({"edge_a": 0.5}, ticker="MISSING")
        assert "MISSING" in sp._per_ticker_misses
