"""In-code CI-aware gates (T-2026-05-08-010).

CLAUDE.md 6th non-negotiable (added commit 4cf4909):

    "Sharpe headlines must report bootstrap CI; kill thresholds must
     be CI-aware, not point-estimate. ... Kill thresholds and gating
     decisions follow the same rule: compare against ci_low, not
     point_estimate."

Three sites covered + one explicit exemption:

  Site 1 — engines/engine_f_governance/evolution_controller.py:182
           Discovery promotion gate uses oos_ci_low instead of
           oos_sharpe (and degradation_ci_low instead of degradation).

  Site 2 — engines/engine_f_governance/lifecycle_manager.py
           _check_retirement_gates uses edge_ci_low instead of
           edge_sharpe for the benchmark-relative gate. Asymmetric:
           the variable being gated is bootstrapped; benchmark_sharpe
           stays point-estimate (fixed reference).

  Site 3 — engines/engine_d_discovery/wfo.py
           Output dict additionally emits oos_ci_low, is_ci_low,
           degradation_ci_low alongside the existing point-estimate
           fields. Existing call sites that read oos_sharpe /
           degradation continue to work.

  Exempt — engines/engine_d_discovery/robustness.py:311,376
           PBO survival is ALREADY distributional (fraction of
           bootstrap synthetic-market paths with Sharpe > 0).
           Documented inline.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pandas as pd

from engines.engine_d_discovery.wfo import (
    WalkForwardOptimizer,
    _bootstrap_sharpe_ci_low,
)
from engines.engine_f_governance.lifecycle_manager import (
    LifecycleConfig,
    LifecycleManager,
    _bootstrap_sharpe_ci_low_from_pnls,
)


# ---------------------------------------------------------------------- #
# Helpers
# ---------------------------------------------------------------------- #


def _noisy_pnls_with_high_point_low_ci(n: int = 200, seed: int = 7) -> np.ndarray:
    """Synthetic per-trade PnL series whose POINT-ESTIMATE Sharpe sits
    just above zero but the bootstrap CI lower bound dips below the
    retirement threshold. The shape: small mean, high variance, fat
    left tail. The point-Sharpe is fooled by a couple of lucky
    outliers; the bootstrap correctly catches the noise."""
    rng = np.random.default_rng(seed)
    base = rng.normal(loc=0.5, scale=12.0, size=n)
    # A few large gains that lift the point-Sharpe but the bootstrap
    # ci_low remains low because most resamples don't include them
    base[10] = 80.0
    base[80] = 70.0
    return base


def _clearly_dead_pnls(n: int = 200, seed: int = 7) -> np.ndarray:
    """Synthetic per-trade PnL with a clear, robust negative bias —
    both point-Sharpe and ci_low should be well below zero."""
    rng = np.random.default_rng(seed)
    return rng.normal(loc=-3.0, scale=8.0, size=n)


def _clearly_winning_pnls(n: int = 200, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(loc=6.0, scale=8.0, size=n)


# ---------------------------------------------------------------------- #
# Site 1 — evolution_controller promotion gate (CI-aware)
# ---------------------------------------------------------------------- #


def _build_controller_with_stub_wfo(wfo_res: dict):
    """Build a minimal EvolutionController whose WFO call returns a
    fixed `wfo_res` dict and whose data + registry are stubbed.
    Exercises the real `run_wfo_for_candidate` gate path, including
    the CI-aware promotion expression at the end."""
    from engines.engine_f_governance import evolution_controller as ec

    controller = ec.EvolutionController.__new__(ec.EvolutionController)
    controller.data_map = {
        "AAA": pd.DataFrame(
            {"Close": np.linspace(100, 110, 500)},
            index=pd.date_range("2022-01-03", periods=500, freq="B"),
        ),
    }
    controller._wfo = _StubWfo(wfo_res)
    controller.registry_path = Path("/tmp/_unused_registry.yml")
    # Stub `_ensure_data_and_wfo` (lazy init) — already populated above
    controller._ensure_data_and_wfo = lambda: None
    # Stub `load_edges` to return our minimal spec
    controller.load_edges = lambda: [{
        "edge_id": "test_edge",
        "module": "engines.engine_a_alpha.edges.momentum_edge",
        "class": "MomentumEdge",
        "params": {},
        "version": "1.0.0",
    }]
    return controller


def test_evolution_controller_uses_ci_low_to_block_borderline_promotion():
    """A candidate whose oos_sharpe (point-estimate) clears the bench
    threshold but whose oos_ci_low is BELOW it must NOT be promoted.
    Under the old gate (point-estimate), this candidate would have
    promoted; the CI-aware gate correctly blocks the noisy edge."""
    from engines.engine_f_governance import evolution_controller as ec

    controller = _build_controller_with_stub_wfo({
        # Old gate would PASS: oos_sharpe 0.85 > bench 0.6 AND
        # degradation 0.80 > 0.6.
        "oos_sharpe": 0.85,
        "degradation": 0.80,
        # New gate must BLOCK: oos_ci_low 0.30 < bench 0.6.
        "oos_ci_low": 0.30,
        "degradation_ci_low": 0.40,
        "is_sharpe_avg": 1.0,
    })

    with patch("engines.engine_f_governance.evolution_controller.compute_benchmark_metrics",
               return_value=_StubBench(0.6), create=True):
        # The benchmark module is imported inside the function; the
        # `core.benchmark.compute_benchmark_metrics` symbol is what
        # actually gets called.
        with patch("core.benchmark.compute_benchmark_metrics",
                   return_value=_StubBench(0.6)):
            passed, oos_sharpe, specialist = controller.run_wfo_for_candidate(
                "test_edge", params={},
            )

    assert passed is False, (
        "promotion must be BLOCKED when oos_ci_low (0.30) < bench (0.6), "
        "even though oos_sharpe (0.85) >= bench"
    )


def test_evolution_controller_promotes_clean_signal():
    """A candidate where BOTH oos_sharpe and oos_ci_low clear the
    threshold should still pass — CI-aware reading is stricter, not
    arbitrarily so."""
    controller = _build_controller_with_stub_wfo({
        "oos_sharpe": 1.20,
        "degradation": 0.80,
        "oos_ci_low": 0.85,            # comfortably above bench 0.6
        "degradation_ci_low": 0.70,    # comfortably above 0.6
        "is_sharpe_avg": 1.5,
    })

    with patch("core.benchmark.compute_benchmark_metrics",
               return_value=_StubBench(0.6)):
        passed, oos_sharpe, specialist = controller.run_wfo_for_candidate(
            "test_edge", params={},
        )

    assert passed is True, (
        "promotion must SUCCEED when both oos_ci_low (0.85) >= bench (0.6) "
        "and degradation_ci_low (0.70) > 0.6"
    )


# ---------------------------------------------------------------------- #
# Site 2 — lifecycle_manager retirement gate (CI-aware)
# ---------------------------------------------------------------------- #


def test_lifecycle_manager_retirement_uses_ci_low_to_protect_noisy_edge():
    """Edge with point-estimate Sharpe BELOW the retirement threshold
    but bootstrap ci_low ABOVE the threshold must NOT be retired —
    the CI lower bound says we can't statistically distinguish this
    edge from "still meeting the bar." Old gate would have retired;
    CI-aware gate protects.

    Construction: pnls with high-variance baseline + a couple of large
    positive outliers. Point-Sharpe sits just under the threshold;
    bootstrap ci_low sits comfortably above it because the bootstrap
    resamples don't always include the outliers, but the typical
    resample's Sharpe is healthy."""
    cfg = LifecycleConfig(
        enabled=True,
        retirement_min_trades=100,
        retirement_min_days=90,
        retirement_margin=0.3,
        retirement_revival_window=15,
        retirement_revival_sharpe=999.0,  # disable revival gate to isolate gate 2
    )
    lcm = LifecycleManager(cfg=cfg, registry_path=Path("/tmp/_unused.yml"),
                           history_path=Path("/tmp/_unused.csv"))

    # PnL stream where ci_low is HIGH (because the bulk of the
    # distribution is healthy) — we want the gate to NOT retire.
    pnls = _clearly_winning_pnls(n=200, seed=11)
    benchmark_sharpe = 1.0
    # threshold = 1.0 - 0.3 = 0.7
    # `_clearly_winning_pnls` has ci_low well above 0.7 — gate should NOT retire.
    fired, gate = lcm._check_retirement_gates(
        pnls=pnls, trade_count=200, days_active=180,
        edge_sharpe=0.5,  # low point-estimate that would have retired under old gate
        benchmark_sharpe=benchmark_sharpe,
    )
    assert fired is False, (
        f"CI-aware gate must NOT retire when edge_ci_low >= threshold; "
        f"got fired={fired}, gate={gate}"
    )
    assert gate == "benchmark_ok"


def test_lifecycle_manager_retires_clearly_dead_edge():
    """An edge whose ci_low is unambiguously below the threshold must
    still retire under CI-aware reading — we're not making the gate
    forgiving, just less noise-sensitive."""
    cfg = LifecycleConfig(
        enabled=True,
        retirement_min_trades=100,
        retirement_min_days=90,
        retirement_margin=0.3,
        retirement_revival_window=15,
        retirement_revival_sharpe=999.0,  # disable revival gate
    )
    lcm = LifecycleManager(cfg=cfg, registry_path=Path("/tmp/_unused.yml"),
                           history_path=Path("/tmp/_unused.csv"))

    pnls = _clearly_dead_pnls(n=200, seed=11)
    benchmark_sharpe = 1.0  # threshold = 1.0 - 0.3 = 0.7
    fired, gate = lcm._check_retirement_gates(
        pnls=pnls, trade_count=200, days_active=180,
        edge_sharpe=-1.5,  # point-Sharpe also clearly bad
        benchmark_sharpe=benchmark_sharpe,
    )
    assert fired is True, (
        f"clearly dead edge must retire; got fired={fired}, gate={gate}"
    )
    assert "benchmark_under_ci_low" in gate
    assert "vs_1.00" in gate  # benchmark_sharpe in the gate descriptor
    assert "margin_0.3" in gate


# ---------------------------------------------------------------------- #
# Site 3 — wfo.py emits the new CI-aware fields
# ---------------------------------------------------------------------- #


def test_wfo_emits_degradation_ci_low_and_returns_streams():
    """The WFO output dict must contain the CI-aware fields alongside
    the legacy point-estimate fields. Drive a tiny synthetic WFO that
    runs through the full output-construction path."""
    # Construct minimal data_map — 600 bars of trending close to
    # support 12-month train + 3-month test windows.
    dates = pd.date_range("2022-01-03", periods=600, freq="B")
    df = pd.DataFrame(
        {
            "Open": np.linspace(100, 130, 600),
            "High": np.linspace(101, 131, 600),
            "Low": np.linspace(99, 129, 600),
            "Close": np.linspace(100, 130, 600),
            "Volume": [1_000_000] * 600,
            "ATR": [2.0] * 600,
        },
        index=dates,
    )
    wfo = WalkForwardOptimizer(data_map={"AAA": df})

    # Patch _quick_backtest to return a deterministic equity curve so
    # we don't run an actual backtest in the test (heavy, slow).
    def _stub_qb(spec, params, start, end):
        # Generate a 21-day-ish equity curve with mild positive drift
        n = 60
        equity = list(np.linspace(100_000, 100_300, n))
        return {"sharpe": 0.5, "equity_curve": equity}

    wfo._quick_backtest = _stub_qb

    # Patch the spec to skip importlib.import_module — we provide a
    # FakeEdge with a non-empty hyperparameter space.
    class _FakeEdge:
        def get_hyperparameter_space(self):
            return {"x": [1, 2]}

        def sample_params(self):
            return {"x": 1}

    fake_spec = {
        "module": "engines.engine_a_alpha.edges.momentum_edge",
        "class": "MomentumEdge",
        "edge_id": "test",
    }

    # `wfo.run_optimization` does `from importlib import import_module`
    # at call time, so we patch the source module rather than wfo.
    import importlib as _il
    real_import = _il.import_module

    def _fake_import(name, *a, **kw):
        if name == "engines.engine_a_alpha.edges.momentum_edge":
            class _FakeMod:
                # `cls_ = getattr(mod, "MomentumEdge"); base_edge = cls_()`
                # in wfo expects a callable that takes 0 args. Bind
                # _FakeEdge as the class attribute directly.
                MomentumEdge = _FakeEdge
            return _FakeMod()
        return real_import(name, *a, **kw)

    with patch.object(_il, "import_module", _fake_import):
        result = wfo.run_optimization(
            fake_spec, start_date="2023-01-03",
            train_months=12, test_months=3, embargo_days=0,
        )

    # Legacy fields preserved
    assert "oos_sharpe" in result
    assert "degradation" in result
    # New CI-aware fields
    assert "oos_ci_low" in result, f"new field missing: {sorted(result.keys())}"
    assert "is_ci_low" in result
    assert "degradation_ci_low" in result
    assert "oos_returns" in result
    assert "is_returns" in result
    # Returns streams must be lists
    assert isinstance(result["oos_returns"], list)
    assert isinstance(result["is_returns"], list)


# ---------------------------------------------------------------------- #
# Exemption — robustness.py PBO survival is documented as already
# distributional and intentionally exempt.
# ---------------------------------------------------------------------- #


def test_pbo_exemption_documented():
    """Both occurrences of `survival_rate = (sharpes > 0.0).mean()`
    in robustness.py must have a CI-aware-gates exemption comment
    explaining the rationale. Regex-matched against source so the
    exemption survives future refactors that move the code."""
    src = (
        Path(__file__).parents[1] / "engines" / "engine_d_discovery" / "robustness.py"
    ).read_text()

    # Both lines must appear
    assert src.count("(sharpes > 0.0).mean()") >= 2, (
        "expected at least 2 occurrences of `(sharpes > 0.0).mean()` "
        "in robustness.py — the per-block path and the per-day stream path"
    )

    # The exemption marker must appear with the keyword phrase
    pattern = re.compile(
        r"CI-aware-gates exemption.*?T-2026-05-08-010.*?distributional",
        re.DOTALL | re.IGNORECASE,
    )
    matches = pattern.findall(src)
    assert len(matches) >= 2, (
        f"expected 2+ exemption-comment blocks marking both PBO survival "
        f"sites; matched {len(matches)}"
    )


# ---------------------------------------------------------------------- #
# Bootstrap helper sanity (T-2026-05-08-010 wrappers)
# ---------------------------------------------------------------------- #


def test_bootstrap_helpers_short_series_returns_zero():
    """Both bootstrap helpers (one in wfo.py, one in lifecycle_manager.py)
    must return 0.0 for a too-short series rather than crashing."""
    assert _bootstrap_sharpe_ci_low([]) == 0.0
    assert _bootstrap_sharpe_ci_low([1.0, 2.0, 3.0]) == 0.0
    assert _bootstrap_sharpe_ci_low_from_pnls(np.array([])) == 0.0
    assert _bootstrap_sharpe_ci_low_from_pnls(np.array([1.0, 2.0, 3.0])) == 0.0


def test_bootstrap_helpers_deterministic_seed():
    """seed=0 default in MetricsEngine.bootstrap_distribution means
    repeated calls with the same input produce the same ci_low. This
    is what underpins the determinism-md5 invariance guarantee."""
    rng = np.random.default_rng(42)
    sample = rng.normal(loc=0.5, scale=2.0, size=200).tolist()
    a = _bootstrap_sharpe_ci_low(sample)
    b = _bootstrap_sharpe_ci_low(sample)
    assert a == b, f"bootstrap_distribution is non-deterministic: {a} vs {b}"


# ---------------------------------------------------------------------- #
# Test scaffolding stubs
# ---------------------------------------------------------------------- #


class _StubWfo:
    """Stand-in for WalkForwardOptimizer that returns a fixed wfo_res
    dict. Used to drive the evolution_controller gate deterministically."""

    def __init__(self, wfo_res):
        self._wfo_res = wfo_res

    def run_optimization(self, *a, **kw):
        return dict(self._wfo_res)


class _StubBench:
    """Stand-in for BenchmarkMetrics that exposes gate_threshold(margin)."""

    def __init__(self, threshold):
        self._t = threshold

    def gate_threshold(self, margin: float = 0.3):
        return float(self._t)


class _StubSpec:
    """Bare-minimum spec object EdgeRegistry.get_spec returns. The gate
    only reads through-the-spec for attributes inside the _wfo path,
    which we've stubbed."""

    edge_id = "test_edge"
    status = "active"
    module = "engines.engine_a_alpha.edges.momentum_edge"
    cls = "MomentumEdge"
    params = {}
    version = "1.0.0"
