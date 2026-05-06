"""
tests/test_run_isolated_globals.py
==================================
Unit tests for the module-level-globals reset path added to
``scripts/run_isolated.py`` (2026-05-07). The file-restore primitives
are tested in ``tests/test_run_isolated.py``; this file exclusively
covers the cross-run contamination of mutable globals OUTSIDE
``data/governor/`` flagged by the 2026-05-06 code-health audit.

Design context
--------------
Six module-level mutable globals were identified as silent corruption
vectors for measurement campaigns (same failure shape as the 04-25
registry-stomp bug and the 05-06 SPY-cache bug):

  HIGH-RISK
    engines/engine_a_alpha/edges/_fundamentals_helpers.py
        _PANEL_CACHE         (None | DataFrame)
        _PANEL_LOAD_FAILED   (bool)
    scripts/path_c_synthetic_compounder.py
        _LAST_OVERLAY_DIAGS  (list)

  MEDIUM-RISK (clear-helpers existed)
    core/feature_foundry/sources/local_ohlcv.py        _CLOSE_CACHE
    core/feature_foundry/sources/earnings_calendar.py  _DATES_CACHE
    core/feature_foundry/sources/fred_macro.py         _SERIES_CACHE

The harness now resets all six on isolated() entry and exit.
"""
from __future__ import annotations

import sys

import pytest

import scripts.run_isolated as run_isolated


# ---------------------------------------------------------------------------
# HIGH-RISK — V/Q/A fundamentals panel cache.
# ---------------------------------------------------------------------------

def test_panel_cache_reset_via_isolated_entry(monkeypatch, tmp_path):
    """Pollute _PANEL_CACHE / _PANEL_LOAD_FAILED with sentinels, enter
    isolated() with a no-op body, assert both reset to fresh state."""
    from engines.engine_a_alpha.edges import _fundamentals_helpers as fh

    fh._PANEL_CACHE = "SENTINEL"  # type: ignore[assignment]
    fh._PANEL_LOAD_FAILED = True
    assert fh._PANEL_CACHE == "SENTINEL"
    assert fh._PANEL_LOAD_FAILED is True

    # Stub out the file-restore path so this test doesn't require an
    # anchor / governor tree on disk.
    monkeypatch.setattr(run_isolated, "restore_anchor", lambda: None)

    with run_isolated.isolated():
        # On entry, the globals must already be reset.
        assert fh._PANEL_CACHE is None
        assert fh._PANEL_LOAD_FAILED is False
        # Re-pollute mid-run; exit must clean up too.
        fh._PANEL_CACHE = "SENTINEL2"  # type: ignore[assignment]
        fh._PANEL_LOAD_FAILED = True

    assert fh._PANEL_CACHE is None
    assert fh._PANEL_LOAD_FAILED is False


# ---------------------------------------------------------------------------
# HIGH-RISK — path_c standalone-script overlay-diags global.
# ---------------------------------------------------------------------------

def test_overlay_diags_reset_when_module_already_imported(monkeypatch):
    """If scripts.path_c_synthetic_compounder is already in sys.modules,
    the harness must reset its _LAST_OVERLAY_DIAGS list."""
    # Insert a synthetic stand-in so the test doesn't have to import the
    # 1300-line real script. The harness uses sys.modules.get(), so any
    # object with the attribute works.
    fake = type(sys)("scripts.path_c_synthetic_compounder")
    fake._LAST_OVERLAY_DIAGS = ["polluted", "with", "sentinels"]
    monkeypatch.setitem(sys.modules, "scripts.path_c_synthetic_compounder",
                        fake)
    monkeypatch.setattr(run_isolated, "restore_anchor", lambda: None)

    with run_isolated.isolated():
        assert fake._LAST_OVERLAY_DIAGS == []
        fake._LAST_OVERLAY_DIAGS.append("mid-run")
    assert fake._LAST_OVERLAY_DIAGS == []


def test_overlay_diags_reset_skipped_when_module_not_imported(monkeypatch):
    """If path_c isn't already imported, the harness must NOT force-load
    it. (The script's import side-effects are heavy and prod doesn't
    use it.)"""
    monkeypatch.delitem(sys.modules, "scripts.path_c_synthetic_compounder",
                        raising=False)
    monkeypatch.setattr(run_isolated, "restore_anchor", lambda: None)

    with run_isolated.isolated():
        # Lazy entry must remain absent.
        assert "scripts.path_c_synthetic_compounder" not in sys.modules


# ---------------------------------------------------------------------------
# MEDIUM-RISK — feature_foundry caches via existing clear helpers.
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "module_path, cache_attr, cache_seed",
    [
        ("core.feature_foundry.sources.local_ohlcv", "_CLOSE_CACHE",
         {"AAPL": "sentinel"}),
        ("core.feature_foundry.sources.earnings_calendar", "_DATES_CACHE",
         {"AAPL": "sentinel"}),
        ("core.feature_foundry.sources.fred_macro", "_SERIES_CACHE",
         {"DGS10": "sentinel"}),
    ],
)
def test_feature_foundry_caches_reset(module_path, cache_attr, cache_seed,
                                      monkeypatch):
    import importlib
    mod = importlib.import_module(module_path)

    cache = getattr(mod, cache_attr)
    cache.clear()
    cache.update(cache_seed)
    assert getattr(mod, cache_attr) == cache_seed

    monkeypatch.setattr(run_isolated, "restore_anchor", lambda: None)

    with run_isolated.isolated():
        assert getattr(mod, cache_attr) == {}


# ---------------------------------------------------------------------------
# Coverage assertion — if a future audit finds another mutable global,
# the registry must be updated. This test fails until it is.
# ---------------------------------------------------------------------------

def test_isolated_globals_registry_covers_all_six_audit_findings():
    """The 2026-05-06 code-health audit identified these six globals.
    If a future task adds another, update both the registry AND this
    test."""
    expected = {
        ("engines.engine_a_alpha.edges._fundamentals_helpers",
         "reset_panel_cache"),
        ("core.feature_foundry.sources.local_ohlcv",
         "clear_close_cache"),
        ("core.feature_foundry.sources.earnings_calendar",
         "clear_earnings_cache"),
        ("core.feature_foundry.sources.fred_macro",
         "clear_series_cache"),
        ("scripts.path_c_synthetic_compounder",
         "_LAST_OVERLAY_DIAGS"),
    }
    actual = {(p, n) for p, n, _ in run_isolated.ISOLATED_GLOBALS_EAGER}
    actual |= {(p, n) for p, n, _ in run_isolated.ISOLATED_GLOBALS_LAZY}
    assert actual == expected, (
        "Registry drifted from the 2026-05-06 audit's six findings. "
        f"Currently: {actual}; expected: {expected}. The fundamentals "
        "helper resets BOTH _PANEL_CACHE and _PANEL_LOAD_FAILED via "
        "one reset_panel_cache() call, so a single registry entry "
        "covers two of the six globals."
    )
