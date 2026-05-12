"""
tests/test_run_isolated.py
==========================
Unit tests for the determinism-restore harness in
`scripts/run_isolated.py`. The end-to-end determinism property (5x same
config produces Sharpe within ±0.02) is verified offline via
`scripts/run_isolated.py --runs N`; these tests cover the
state-snapshot/restore primitives.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _load_module(monkeypatch_root: Path):
    """Import scripts.run_isolated and repoint module-level constants
    to a temporary worktree root.

    The module's ROOT constants are evaluated at import time, so after
    exec_module we patch them to point at the temp tree. The re-exec
    guard is gated behind `_reexec_if_hashseed_unset()`, called only
    from `main()`, so importing the module here is side-effect-free.
    """
    spec = importlib.util.spec_from_file_location(
        "_test_run_isolated",
        Path(__file__).resolve().parents[1] / "scripts" / "run_isolated.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.ROOT = monkeypatch_root
    module.GOV_DIR = monkeypatch_root / "data" / "governor"
    module.ISOLATED_ANCHOR = module.GOV_DIR / "_isolated_anchor"
    module.TRADES_DIR = monkeypatch_root / "data" / "trade_logs"
    return module


@pytest.fixture
def tmp_worktree(tmp_path: Path) -> Path:
    """Build a synthetic worktree skeleton with data/governor/ populated."""
    gov = tmp_path / "data" / "governor"
    gov.mkdir(parents=True)
    (tmp_path / "data" / "trade_logs").mkdir()
    # Minimal contents for each ISOLATED_FILES entry
    (gov / "edges.yml").write_text("edges:\n- edge_id: foo\n  status: active\n")
    (gov / "edge_weights.json").write_text('{"weights": {"foo": 1.0}}')
    (gov / "regime_edge_performance.json").write_text(
        '{"_version": 2, "data": {}, "trigger_data": {}}'
    )
    # Note: no lifecycle_history.csv — it's optional and the harness
    # must handle absent files correctly.
    return tmp_path


def test_save_and_restore_roundtrip(tmp_worktree: Path):
    """save_anchor() then restore_anchor() must reproduce the original
    file contents byte-for-byte."""
    mod = _load_module(tmp_worktree)
    edges_path = mod.GOV_DIR / "edges.yml"
    original_bytes = edges_path.read_bytes()

    mod.save_anchor()
    assert mod.ISOLATED_ANCHOR.exists()
    assert (mod.ISOLATED_ANCHOR / "edges.yml").read_bytes() == original_bytes

    # Mutate the live file
    edges_path.write_text("edges: []\n")
    assert edges_path.read_bytes() != original_bytes

    mod.restore_anchor()
    assert edges_path.read_bytes() == original_bytes


def test_restore_deletes_files_absent_in_anchor(tmp_worktree: Path):
    """If lifecycle_history.csv was absent at snapshot time but
    accumulated in the live tree later, restore must DELETE the live
    copy so the run starts from the same empty-history state."""
    mod = _load_module(tmp_worktree)
    mod.save_anchor()

    # Live tree gains a lifecycle_history.csv after the anchor was taken.
    history_path = mod.GOV_DIR / "lifecycle_history.csv"
    history_path.write_text("ts,edge_id,from,to\n2025-01-01,foo,active,paused\n")
    assert history_path.exists()

    mod.restore_anchor()
    assert not history_path.exists(), (
        "restore_anchor() must remove files absent in the anchor; "
        "lifecycle_history.csv leaked across runs."
    )


def test_isolated_context_restores_on_exit(tmp_worktree: Path):
    """The `isolated()` context manager must restore on normal exit AND
    on exception."""
    mod = _load_module(tmp_worktree)
    mod.save_anchor()
    edges_path = mod.GOV_DIR / "edges.yml"
    original = edges_path.read_bytes()

    with mod.isolated():
        edges_path.write_text("edges: [tampered]\n")
        assert edges_path.read_bytes() != original
    assert edges_path.read_bytes() == original


def test_isolated_context_restores_on_exception(tmp_worktree: Path):
    """If the wrapped code raises, the harness still restores."""
    mod = _load_module(tmp_worktree)
    mod.save_anchor()
    edges_path = mod.GOV_DIR / "edges.yml"
    original = edges_path.read_bytes()

    with pytest.raises(RuntimeError):
        with mod.isolated():
            edges_path.write_text("mid-run mutation")
            raise RuntimeError("simulated backtest crash")
    assert edges_path.read_bytes() == original


def test_restore_without_anchor_raises(tmp_worktree: Path):
    """Calling restore_anchor() before save_anchor() should fail loudly,
    not silently leave state untouched."""
    mod = _load_module(tmp_worktree)
    with pytest.raises(RuntimeError):
        mod.restore_anchor()


def test_isolated_files_list_covers_phase_210d_mutations():
    """Documenting which files MUST be in the isolation set.

    Historical additions:
    - Phase 2.10d Task A (lifecycle triggers) added edges.yml +
      lifecycle_history.csv mutations.
    - Task B kept edge_weights.json + regime_edge_performance.json.
    - T-2026-05-11-026 added ga_population.yml to prevent stale GA
      population from skipping `seed_from_registry` on Discovery cycle
      start (root cause of T-025's 0% foundry_feature gene composition).

    If a future task adds another mutable governor file, this test
    fails until the harness is updated."""
    mod_path = Path(__file__).resolve().parents[1] / "scripts" / "run_isolated.py"
    spec = importlib.util.spec_from_file_location("_isolated_const", mod_path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    expected = {
        "edges.yml",
        "edge_weights.json",
        "regime_edge_performance.json",
        "lifecycle_history.csv",
        "ga_population.yml",
    }
    assert set(m.ISOLATED_FILES) == expected, (
        "ISOLATED_FILES drifted from the documented set. "
        f"Currently: {set(m.ISOLATED_FILES)}; expected: {expected}. "
        "If this is intentional, update the test AND the audit doc "
        "(docs/Audit/determinism_floor_restore_2026_05.md)."
    )


def test_ga_population_yml_isolated_when_anchor_lacks_it(tmp_worktree: Path):
    """Regression test for T-2026-05-11-026.

    Models the T-025 failure mode: live tree has a generation-N
    `ga_population.yml` from prior Discovery cycles; the anchor was
    captured before that population existed. `restore_anchor()` must
    DELETE the live file so the next Discovery cycle starts from the
    same clean state the anchor describes, forcing GA's
    `seed_from_registry` fallback to fire deterministically.
    """
    mod = _load_module(tmp_worktree)
    # Save anchor with NO ga_population.yml in the live tree.
    mod.save_anchor()
    assert not (mod.ISOLATED_ANCHOR / "ga_population.yml").exists()

    # Simulate Discovery running and writing a stale population.
    pop_path = mod.GOV_DIR / "ga_population.yml"
    pop_path.write_text(
        "generation: 3\n"
        "population_size: 20\n"
        "population:\n"
        "- edge_id: composite_gen0_deadbeef\n"
        "  genes:\n"
        "  - type: technical\n"
        "    indicator: rsi\n"
        "    operator: less\n"
        "    threshold: 30\n"
        "  direction: long\n"
    )
    assert pop_path.exists()

    mod.restore_anchor()
    assert not pop_path.exists(), (
        "restore_anchor() must DELETE live ga_population.yml when the "
        "anchor lacks it — recurrence guard for the T-025 stale-"
        "population bug."
    )


def test_ga_population_yml_restored_from_anchor_when_present(tmp_worktree: Path):
    """Symmetric case: if the anchor DID capture a `ga_population.yml`,
    `restore_anchor()` puts it back byte-for-byte. Confirms the round-
    trip works whether or not the anchor has the file."""
    mod = _load_module(tmp_worktree)
    pop_path = mod.GOV_DIR / "ga_population.yml"
    seed_text = (
        "generation: 0\n"
        "population_size: 5\n"
        "population: []\n"
    )
    pop_path.write_text(seed_text)
    mod.save_anchor()
    assert (mod.ISOLATED_ANCHOR / "ga_population.yml").exists()
    # Mutate the live file
    pop_path.write_text("generation: 99\npopulation: []\n")
    mod.restore_anchor()
    assert pop_path.read_text() == seed_text
