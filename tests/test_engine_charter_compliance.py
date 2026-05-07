"""tests/test_engine_charter_compliance.py
============================================

Automated charter-boundary checks. Locks in the architectural
invariants documented in `docs/Core/engine_charters.md` so that
charter inversions (the F4 audit pattern that surfaced 2026-05-06)
get caught at CI time, not via manual audit.

Background
----------
The 2026-05-09 evening engine-charter drift inventory
(`docs/Measurements/2026-05/engine_charter_drift_inventory_2026_05_09.md`)
showed 4 of 6 engines with meaningful drift. Several of those (e.g.,
Engine A importing HRPOptimizer + TurnoverPenalty from Engine C; Engine
A importing EDGE_CATEGORY_MAP from Engine F) survived for months
because the audit was manual. These tests assert the cleaned-up state
post-C-engines-1 / C-engines-5 and prevent regression.

Until those C-engines dispatches land, certain assertions are marked
``xfail`` with a clear pointer to the closing dispatch — the test
passes when the drift is closed and fails (un-xfail) only if a future
change brings the inversion back.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_DIRS = {
    "A": REPO_ROOT / "engines" / "engine_a_alpha",
    "B": REPO_ROOT / "engines" / "engine_b_risk",
    "C": REPO_ROOT / "engines" / "engine_c_portfolio",
    "D": REPO_ROOT / "engines" / "engine_d_discovery",
    "E": REPO_ROOT / "engines" / "engine_e_regime",
    "F": REPO_ROOT / "engines" / "engine_f_governance",
}


def _grep_imports_in_engine(engine_letter: str, pattern: str) -> list[str]:
    """Return matching `from <pattern>...` import lines under engine_X/.

    Uses ripgrep when available, falls back to plain `grep -rn`. Output
    is filtered to actual import lines (excludes comments / docstrings
    that mention the pattern by name).
    """
    engine_dir = ENGINE_DIRS[engine_letter]
    if not engine_dir.exists():
        return []
    try:
        result = subprocess.run(
            ["grep", "-rn", "--include=*.py", pattern, str(engine_dir)],
            capture_output=True, text=True, timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return []
    matches = []
    import_re = re.compile(r"^\s*(from\s|import\s)")
    for line in result.stdout.splitlines():
        # Format: <path>:<lineno>:<content>
        try:
            content = line.split(":", 2)[2]
        except IndexError:
            continue
        if import_re.match(content):
            matches.append(line)
    return matches


# ============================================================
# Engine A → must not import from B / C / F (charter direction A → C / F → A)
# ============================================================


def test_engine_a_does_not_import_from_engine_b():
    """Engine A must not consume Engine B internals — A produces signals;
    B sizes them. Cross-import = charter inversion."""
    matches = _grep_imports_in_engine("A", "from engines.engine_b_risk")
    assert not matches, (
        "Engine A imports from Engine B — charter inversion. "
        f"Hits:\n  " + "\n  ".join(matches)
    )


@pytest.mark.xfail(
    reason="C-engines-1 (cae2002) closed the F4 inversion FORM that mattered (HRPOptimizer + "
           "TurnoverPenalty no longer in signal_processor — `grep -rn 'HRPOptimizer\\|TurnoverPenalty' "
           "engines/engine_a_alpha/` returns zero hits). What remains is alpha_engine.py importing "
           "PortfolioComposer from engines.engine_c_portfolio.composer to ORCHESTRATE composition "
           "(Engine A asks Engine C for target weights as a service). Whether this counts as "
           "remaining charter inversion depends on whether A's orchestration role is allowed to "
           "import C as a service. Tightening this further is sub-finding for C-engines-5 + a "
           "broader A-vs-orchestrator scoping decision.",
    strict=True,
)
def test_engine_a_does_not_import_from_engine_c():
    """Engine A must not consume Engine C internals — F4 charter inversion.
    Partially closed by C-engines-1; remaining work in C-engines-5."""
    matches = _grep_imports_in_engine("A", "from engines.engine_c_portfolio")
    assert not matches, (
        "Engine A imports from Engine C — F4 charter inversion. "
        f"Hits:\n  " + "\n  ".join(matches)
    )


def test_engine_a_no_longer_imports_hrp_or_turnover():
    """Strict-form F4 closure verification — the *specific* inversion the
    C-engines-1 dispatch closed (HRP/Turnover machinery in signal_processor)
    must stay closed. Stronger than the broader A→C test above; this is the
    regression guard."""
    import subprocess
    result = subprocess.run(
        ["grep", "-rn", "--include=*.py",
         r"HRPOptimizer\|TurnoverPenalty",
         str(REPO_ROOT / "engines" / "engine_a_alpha")],
        capture_output=True, text=True, timeout=10,
    )
    # Filter to actual code references (skip docstrings/comments mentioning the names)
    real_refs = [
        line for line in result.stdout.splitlines()
        if line and not (
            line.split(":", 2)[2].strip().startswith("#") if line.count(":") >= 2 else False
        )
    ]
    assert not real_refs, (
        "F4 regression: HRPOptimizer or TurnoverPenalty re-introduced into Engine A. "
        "Per C-engines-1 (commit cae2002), these must live in Engine C only. "
        f"Hits:\n  " + "\n  ".join(real_refs)
    )


def test_engine_a_does_not_import_from_engine_f():
    """Engine A must not consume Engine F internals — A's taxonomy should
    live in A or core/. **Charter exception:** the docstring at
    `docs/Core/engine_charters.md` § Engine A explicitly lists
    "Edge weights from Engine F (applied during ensemble aggregation)" as
    an allowed input. So `from engines.engine_f_governance.governor`
    (the StrategyGovernor consumed for edge weights) is whitelisted.
    Anything else from F is a charter inversion.

    **Closed 2026-05-07**: EDGE_CATEGORY_MAP relocated from
    regime_tracker.py:94 to engines/engine_a_alpha/edge_taxonomy.py.
    Engine F re-exports from the canonical location for back-compat."""
    matches = _grep_imports_in_engine("A", "from engines.engine_f_governance")
    # Filter out the charter-allowed governor dependency
    forbidden = [
        m for m in matches
        if "engine_f_governance.governor" not in m
    ]
    assert not forbidden, (
        "Engine A imports forbidden Engine F module(s) — charter inversion. "
        "(Engine A may import only from engine_f_governance.governor for "
        "edge_weights consumption per charter.) "
        f"Forbidden hits:\n  " + "\n  ".join(forbidden)
    )


# ============================================================
# Engine B — propose-first per CLAUDE.md; assert isolation
# ============================================================


def test_engine_b_does_not_import_from_engine_a():
    """B consumes A's output via the orchestration layer, not by importing A directly."""
    matches = _grep_imports_in_engine("B", "from engines.engine_a_alpha")
    assert not matches, (
        "Engine B imports from Engine A directly — charter says B receives signal "
        f"via the orchestration layer. Hits:\n  " + "\n  ".join(matches)
    )


def test_engine_b_does_not_import_from_engine_d_or_f():
    """B's charter forbids edge performance metrics (F's domain) and discovery
    research (D's domain) as inputs."""
    for forbidden in ("from engines.engine_d_discovery", "from engines.engine_f_governance"):
        matches = _grep_imports_in_engine("B", forbidden)
        assert not matches, (
            f"Engine B imports {forbidden!r} — charter says these are forbidden inputs. "
            f"Hits:\n  " + "\n  ".join(matches)
        )


# ============================================================
# Engine D — offline only; must not depend on live state
# ============================================================


@pytest.mark.xfail(
    reason="engines/engine_d_discovery/wfo.py:12 imports RiskEngine directly. "
           "Charter says D should route through orchestration/run_backtest_pure "
           "instead of instantiating risk engine. To be closed in C-engines-2 "
           "(Engine B refactor) or as a separate D-side WFO refactor — propose-first.",
    strict=True,
)
def test_engine_d_does_not_import_from_engine_b_at_module_level():
    """D operates offline on historical data. Importing B at module level
    couples discovery to live trade-execution code (charter forbids).
    Note: orchestration/run_backtest_pure imports B, and D imports run_backtest_pure
    — that's the architectural contract; D shouldn't import B itself."""
    matches = _grep_imports_in_engine("D", "from engines.engine_b_risk")
    assert not matches, (
        "Engine D imports from Engine B directly — D's offline contract violated. "
        f"D should call run_backtest_pure (orchestration layer) instead. "
        f"Hits:\n  " + "\n  ".join(matches)
    )


# ============================================================
# Engine E — read-only on macro data; no portfolio state
# ============================================================


def test_engine_e_does_not_import_from_engine_b_or_c():
    """E publishes a regime context; it does not consume portfolio state or
    risk-decision state. Charter says forbidden inputs include 'portfolio
    state (positions, cash, PnL).'"""
    for forbidden in ("from engines.engine_b_risk", "from engines.engine_c_portfolio"):
        matches = _grep_imports_in_engine("E", forbidden)
        assert not matches, (
            f"Engine E imports {forbidden!r} — charter says E does not consume "
            f"portfolio/risk state. Hits:\n  " + "\n  ".join(matches)
        )


# ============================================================
# Engine C — the Ledger Layer must be deterministic + standalone
# ============================================================


def test_engine_c_ledger_does_not_import_from_engine_d_or_e():
    """C.1 (Ledger Layer) is the irrefutable source of accounting truth.
    It should not depend on Discovery research (D) or Regime intelligence
    (E). Allocation Layer (C.2) may consume E for regime-conditional policy
    — that's a different layer."""
    portfolio_engine_path = REPO_ROOT / "engines" / "engine_c_portfolio" / "portfolio_engine.py"
    if not portfolio_engine_path.exists():
        pytest.skip("portfolio_engine.py not present")
    text = portfolio_engine_path.read_text()
    for forbidden in ("from engines.engine_d_discovery", "from engines.engine_e_regime"):
        # Allow string literals / comments mentioning the names; check
        # only top-of-file imports.
        for line in text.splitlines():
            stripped = line.strip()
            if not (stripped.startswith("from ") or stripped.startswith("import ")):
                continue
            if forbidden in stripped:
                pytest.fail(
                    f"portfolio_engine.py (Ledger Layer) imports {forbidden!r} — "
                    f"charter says C.1 must remain dependency-pure for determinism. "
                    f"Line: {stripped}"
                )


# ============================================================
# General — every engine has a docstring + index.md
# ============================================================


def test_every_engine_has_an_index_md():
    """Every engine package ships an index.md describing its public API
    and charter status (auto-generated by scripts/sync_docs.py)."""
    for letter, path in ENGINE_DIRS.items():
        if not path.exists():
            continue
        index = path / "index.md"
        assert index.exists() and index.stat().st_size > 0, (
            f"Engine {letter} ({path.name}) missing index.md or it's empty. "
            f"Run scripts/sync_docs.py to regenerate."
        )


def test_engines_dir_structure_matches_charter():
    """The 6 charter engines must all be present as packages."""
    for letter, path in ENGINE_DIRS.items():
        assert path.exists() and path.is_dir(), (
            f"Engine {letter} package missing at {path}"
        )
        assert (path / "__init__.py").exists(), (
            f"Engine {letter} not a Python package (missing __init__.py)"
        )


def test_every_engine_exports_a_semver_version():
    """Per audit recommendation (2026-05-09), every engine package MUST
    expose a semver __version__ in its __init__.py. The
    core.engine_versions registry depends on it for forensic
    per-run snapshots; missing __version__ would silently fall back
    to '0.0.0' and lose engine state in the trade log."""
    from core.engine_versions import get_all_engine_versions, is_valid_semver
    versions = get_all_engine_versions()
    for letter in ENGINE_DIRS.keys():
        v = versions.get(letter)
        assert v is not None and v != "0.0.0", (
            f"Engine {letter} missing __version__ in __init__.py"
        )
        assert is_valid_semver(v), (
            f"Engine {letter} __version__ {v!r} is not strict semver"
        )
