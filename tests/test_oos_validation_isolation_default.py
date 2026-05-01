"""
tests/test_oos_validation_isolation_default.py
===============================================
Tests confirming that `scripts/run_oos_validation.py` and
`scripts/sweep_cap_recalibration.py` use the determinism harness
(scripts.run_isolated.isolated()) by default after the 2026-05-01
update.

The end-to-end determinism property (3-run same-config produces
Sharpe within ±0.02 + bitwise-identical canon md5) is verified offline
via `scripts/path1_revalidation_grid.py` and reported in
`docs/Audit/path1_revalidation_under_harness_2026_05.md`. These tests
cover the API contract — that calling the OOS / sweep entry-points
without an explicit opt-out actually wraps the backtest in the
harness and that the opt-out flag works.
"""
from __future__ import annotations

import importlib.util
import inspect
from pathlib import Path

import pytest


def _load_oos_module():
    spec = importlib.util.spec_from_file_location(
        "_test_run_oos_validation",
        Path(__file__).resolve().parents[1] / "scripts" / "run_oos_validation.py",
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _load_sweep_module():
    spec = importlib.util.spec_from_file_location(
        "_test_sweep_cap_recalibration",
        Path(__file__).resolve().parents[1] / "scripts" / "sweep_cap_recalibration.py",
    )
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ---------------------------------------------------------------------------
# run_oos_validation.py
# ---------------------------------------------------------------------------

def test_run_q1_default_uses_isolation():
    """run_q1's default value of use_isolation must be True."""
    m = _load_oos_module()
    sig = inspect.signature(m.run_q1)
    assert sig.parameters["use_isolation"].default is True


def test_run_q2_default_uses_isolation():
    m = _load_oos_module()
    sig = inspect.signature(m.run_q2)
    assert sig.parameters["use_isolation"].default is True


def test_run_oos_main_no_isolation_flag_present():
    """The CLI must expose --no-isolation as the documented opt-out."""
    m = _load_oos_module()
    src = (Path(__file__).resolve().parents[1] / "scripts" / "run_oos_validation.py").read_text()
    assert "--no-isolation" in src, (
        "scripts/run_oos_validation.py must expose --no-isolation flag "
        "for backwards-compat opt-out from the determinism harness."
    )
    assert "use_isolation" in src
    assert "isolated()" in src


def test_isolation_ctx_returns_isolated_context_by_default(tmp_path: Path):
    """_isolation_ctx(use_isolation=True) must return the run_isolated
    context manager. Verifies the wiring without invoking a backtest."""
    m = _load_oos_module()
    # Repoint paths to a temp tree so we don't touch the live worktree.
    m.ROOT = tmp_path
    m.ISOLATED_ANCHOR = tmp_path / "data" / "governor" / "_isolated_anchor"
    # Build a minimal data/governor/ so save_anchor() (called inside
    # _isolation_ctx if no anchor exists) has something to copy.
    gov = tmp_path / "data" / "governor"
    gov.mkdir(parents=True)
    (gov / "edges.yml").write_text("edges: []\n")
    (gov / "edge_weights.json").write_text("{}")
    (gov / "regime_edge_performance.json").write_text("{}")
    # Patch run_isolated module's paths too.
    from scripts import run_isolated
    orig_root = run_isolated.ROOT
    orig_gov = run_isolated.GOV_DIR
    orig_anchor = run_isolated.ISOLATED_ANCHOR
    try:
        run_isolated.ROOT = tmp_path
        run_isolated.GOV_DIR = gov
        run_isolated.ISOLATED_ANCHOR = m.ISOLATED_ANCHOR

        ctx = m._isolation_ctx(use_isolation=True)
        # Should be the run_isolated.isolated() context manager (a
        # _GeneratorContextManager wrapping the @contextmanager generator).
        assert hasattr(ctx, "__enter__") and hasattr(ctx, "__exit__")
        # Anchor should exist after the call (auto-saved if missing)
        assert m.ISOLATED_ANCHOR.exists()
        with ctx:
            pass
    finally:
        run_isolated.ROOT = orig_root
        run_isolated.GOV_DIR = orig_gov
        run_isolated.ISOLATED_ANCHOR = orig_anchor


def test_isolation_ctx_returns_nullcontext_on_opt_out():
    """_isolation_ctx(use_isolation=False) must return a no-op
    context manager — legacy behavior preserved."""
    m = _load_oos_module()
    from contextlib import nullcontext
    ctx = m._isolation_ctx(use_isolation=False)
    assert isinstance(ctx, nullcontext)


# ---------------------------------------------------------------------------
# sweep_cap_recalibration.py
# ---------------------------------------------------------------------------

def test_sweep_run_one_default_post_restore():
    """sweep_cap_recalibration.run_one's post_restore default must be True
    (default-on idempotence)."""
    m = _load_sweep_module()
    sig = inspect.signature(m.run_one)
    assert sig.parameters["post_restore"].default is True


def test_sweep_lifecycle_files_includes_history():
    """LIFECYCLE_FILES must include lifecycle_history.csv (the missing
    file that allowed drift before the 2026-05-01 update)."""
    m = _load_sweep_module()
    names = {p.name for p in m.LIFECYCLE_FILES}
    assert "lifecycle_history.csv" in names, (
        "sweep_cap_recalibration.LIFECYCLE_FILES must snapshot+restore "
        "lifecycle_history.csv to match scripts/run_isolated.py's "
        "ISOLATED_FILES set."
    )


def test_sweep_no_isolation_flag_present():
    """The CLI must expose --no-isolation as the documented opt-out."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "sweep_cap_recalibration.py").read_text()
    assert "--no-isolation" in src
    assert "post_restore" in src


def test_sweep_lifecycle_files_match_run_isolated():
    """The two harnesses must agree on the snapshot file set so a
    measurement run is consistent regardless of which entry point is
    used."""
    sweep = _load_sweep_module()
    from scripts import run_isolated
    sweep_names = {p.name for p in sweep.LIFECYCLE_FILES}
    iso_names = set(run_isolated.ISOLATED_FILES)
    assert sweep_names == iso_names, (
        f"sweep set {sweep_names} != run_isolated set {iso_names}. "
        "If a future task adds a mutable governor file, both lists must "
        "be updated together."
    )
