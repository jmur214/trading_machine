# Spec — T-2026-05-12-039: Relocate observability layer (`cockpit/logger.py` + `cockpit/metrics.py`) → `core/observability/`

**Date drafted:** 2026-05-12 (director-side, ~30 min)
**Status:** SPEC for approval. **3+ engine refactor — requires explicit user propose-first sign-off per CLAUDE.md before dispatch.**
**Will be executed by:** Agent A or B once approved (~4-6 hr).
**Sequencing:** sits AFTER T-034 (cockpit metrics-pipeline bug fix). Do not bundle bug fix with refactor.
**Output:** moved + renamed files + updated imports + tests + CLAUDE.md doc update + audit doc.

---

## Why now

T-2026-05-11-030 (STR re-measurement) surfaced a system-wide metrics-pipeline bug that contaminated every prior bear-year Sharpe headline. The bug lived in `cockpit/logger.py` (`_flush_buffer` writes 11 fields against a 9-column header) and `cockpit/metrics.py` (`PerformanceMetrics` default `pd.read_csv` silently mis-aligns). User-observation that motivated this spec:

> "We didn't catch it sooner because it is in such a weird place."

The structural pathology:

- `cockpit/` is the DASHBOARD directory per CLAUDE.md ("Never edit `cockpit/dashboard/`. It is deprecated. Use `cockpit/dashboard_v2/` only").
- But `cockpit/logger.py` runs INSIDE every backtest (instantiated by `backtest_controller.py`, `mode_controller.py`, `wfo.py`). Every measurement uses it.
- `cockpit/metrics.py` is consumed by `mode_controller`, `backtest_controller`, `train_signal_gate.py`, `run_benchmark.py`, and the dashboard.
- Neither is dashboard code. They are system-wide observability infrastructure.

**Cognitive consequence:** when bugs surface, the file's location implies "dashboard concern" — encouraging shallow investigation. The bug-cycle would have been shorter with the right name + right location. This is the same misnaming pattern that drove `data/coordination/` confusion earlier in this project arc.

---

## What

Two file relocations + 7 caller-site import updates + 1 CLAUDE.md doc note.

### File moves

| Current | Better |
|---|---|
| `cockpit/logger.py` (class `CockpitLogger`) | `core/observability/portfolio_snapshot_logger.py` (class `PortfolioSnapshotLogger`) |
| `cockpit/metrics.py` (class `PerformanceMetrics`, fns `_compute_fifo_realized`, etc.) | `core/observability/performance_metrics.py` (same class + fn names) |

`core/observability/` already exists (contains `run_registry.py` from 2026-05-07). This is the natural home for cross-engine observability infrastructure. The pairing with `core/metrics_engine.py` (the pure calculation library) is intentional — observability uses metrics_engine to compute Sharpe/Sortino/CAGR/MDD.

### Class rename rationale

`CockpitLogger` → `PortfolioSnapshotLogger`:
- The "Cockpit" prefix is a UI-consumer name, not a producer name
- "PortfolioSnapshotLogger" describes what it does: writes per-bar portfolio snapshots during backtest execution

`PerformanceMetrics`: stays. The class name is already correct; only its file location is wrong.

### Caller-site import updates (audited 2026-05-12)

7 caller sites:

| File | Line | Current import |
|---|---|---|
| `engines/engine_d_discovery/wfo.py` | 14 | `from cockpit.logger import CockpitLogger` |
| `backtester/backtest_controller.py` | 876 | `from cockpit.metrics import PerformanceMetrics` |
| `orchestration/mode_controller.py` | 62 | `from cockpit.logger import CockpitLogger` |
| `orchestration/mode_controller.py` | 63 | `from cockpit.metrics import PerformanceMetrics` |
| `orchestration/run_backtest_pure.py` | 71, 111, 267 | docstring + interface references (no actual import) |
| `scripts/run_benchmark.py` | 37 | `from cockpit.metrics import PerformanceMetrics, _compute_fifo_realized` |
| `scripts/train_signal_gate.py` | 33 | `from cockpit.metrics import PerformanceMetrics` |
| `cockpit/dashboard_v2/callbacks/mode_callbacks.py` | 25 | `from cockpit.metrics import PerformanceMetrics` |

Each gets updated to the new import path (and `CockpitLogger` → `PortfolioSnapshotLogger` where applicable).

### CLAUDE.md update

Add a clarification under the non-negotiable rules section, near the existing "Never edit `cockpit/dashboard/`" rule:

> **`cockpit/` is dashboard-only.** Observability infrastructure (snapshot loggers, performance metrics) lives in `core/observability/`. If you find observability or instrumentation code inside `cockpit/`, that's a structural misnaming bug — flag it and move it. The dashboard CONSUMES observability output via the canonical `core/observability/` API; it does not OWN observability.

---

## Why both moves together, not piecemeal

The two files share a contract: the logger writes a schema; the metrics class reads that schema. If we move only one, the contract crosses the package boundary and becomes brittler. Same boundary, same move.

---

## Acceptance

1. **File moves:**
   - `cockpit/logger.py` → `core/observability/portfolio_snapshot_logger.py`, with class renamed `CockpitLogger` → `PortfolioSnapshotLogger`
   - `cockpit/metrics.py` → `core/observability/performance_metrics.py`, class name unchanged

2. **`cockpit/__init__.py` re-exports** for backwards compat ONE release cycle:
   ```python
   # Deprecated shims; use core.observability directly.
   from core.observability.portfolio_snapshot_logger import PortfolioSnapshotLogger as CockpitLogger  # noqa: F401
   from core.observability.performance_metrics import PerformanceMetrics  # noqa: F401
   ```
   These shims warn at import time via `warnings.warn(DeprecationWarning, ...)`. Removed in a follow-up dispatch (T-041) after all callers are confirmed migrated.

3. **All 7 caller sites updated** to the new import paths. Test the import in each.

4. **Tests:** new `tests/test_observability_relocation.py`:
   - `test_portfolio_snapshot_logger_importable_from_core_observability` — new path works
   - `test_performance_metrics_importable_from_core_observability` — new path works
   - `test_cockpit_shim_still_works_with_deprecation_warning` — backwards-compat shim works
   - `test_dashboard_v2_imports_work` — dashboard_v2's callback file imports correctly post-move

5. **Existing tests** still pass:
   - All `tests/test_cockpit_*.py` (if any) — update or delete if they tested cockpit-internal behavior
   - `tests/test_alpha_pipeline.py`, `tests/test_backtest_controller_narrow_except.py`, `tests/test_engine_d_*` — relevant integration tests

6. **Determinism guard:** running `python -m scripts.run_isolated --runs 1 --task q1` from main + your changes produces canon md5 IDENTICAL to clean main. This is a pure rename; behavior must not change.

7. **CLAUDE.md update** per "CLAUDE.md update" section above. Add the clarification paragraph.

8. **Audit doc** at `docs/Audit/observability_layer_relocation_2026_05_12.md`:
   - List of files moved + renamed
   - List of caller sites updated
   - Determinism evidence (canon md5 invariant)
   - CLAUDE.md update note
   - Forward-look: queue T-041 to remove the deprecation shim once one cycle has passed

9. **Branch:** `feature/observability-layer-relocation`. Push only; director merges + pushes after review.

---

## Hard constraints

- DO NOT modify the snapshot field schema or the PerformanceMetrics calculation logic. **Pure rename + relocate.** Behavior must be bitwise-identical post-fix.
- DO NOT remove the cockpit shim in THIS dispatch. Deprecation cycle convention is one full session-arc before removal; T-041 removes the shim.
- DO NOT modify any engine code (Engine A/B/C/D/E/F). Only the caller-site imports change.
- DO NOT bundle this with the cockpit metrics-pipeline bug fix (T-034). T-034 must merge to main FIRST; then this refactor is dispatched on top of that fixed code.
- DO NOT extend scope to other potentially-misplaced files. The "file-location audit" sweep is a separate task (~T-042 if user dispatches).
- Per CLAUDE.md: this is a 3+ engine refactor (touches Engine D's wfo.py + Engine A's caller in mode_controller + the backtester) — **propose-first applies. Director must have explicit user approval before dispatching this brief to an agent.**

---

## Time budget

4-6 hr total: ~1 hr file moves + class rename, ~1 hr update 7 caller sites, ~1 hr test updates + new regression tests, ~30 min CLAUDE.md note + audit doc, ~30 min determinism verification, plus debugging buffer.

---

## Open questions for the implementing agent (surface in audit doc, not block)

1. **Should the deprecation shim warn at import time, or stay silent?** Recommend `DeprecationWarning` so callers see the migration prompt without breaking. CLAUDE.md doesn't have explicit guidance on deprecation cycles for internal modules; this is a discretionary call. Document the choice.

2. **`run_backtest_pure.py` has docstring references to `cockpit.metrics.PerformanceMetrics`** at lines 71, 111, 267. These aren't imports; they're explanatory text. Update them to reference `core.observability.performance_metrics.PerformanceMetrics` for consistency, OR leave the docstrings as historical references? Recommend update for clarity.

3. **Should `_compute_fifo_realized` (a helper function exported alongside `PerformanceMetrics`) be promoted to top-level `core/observability/__init__.py`?** Caller `scripts/run_benchmark.py` imports it directly. Cleaner public-API would have it as `core.observability.performance_metrics._compute_fifo_realized` (keeping the leading underscore signals "internal but importable for tests/scripts"). Recommend keeping the leading underscore; document.

4. **Dashboard_v2's import path.** `cockpit/dashboard_v2/callbacks/mode_callbacks.py` currently imports from `cockpit.metrics`. After the move, should this become a `core.observability.performance_metrics` import (dashboard reaches into core), or should the dashboard re-import via `cockpit.__init__`'s shim (dashboard stays scoped to cockpit/)? Cleaner: dashboard imports directly from `core.observability` since that's the canonical public API. Document the choice.

5. **Does `core/observability/__init__.py` need to expose `PortfolioSnapshotLogger` and `PerformanceMetrics` at top level?** Recommend yes for convenience:
   ```python
   from .portfolio_snapshot_logger import PortfolioSnapshotLogger  # noqa: F401
   from .performance_metrics import PerformanceMetrics  # noqa: F401
   ```
   Callers can then do `from core.observability import PerformanceMetrics`. Document the choice.

6. **Should the `cockpit/__init__.py` shim include `_compute_fifo_realized` for `scripts/run_benchmark.py`'s sake?** Yes — preserves the caller's existing import pattern through the deprecation cycle. Document.

---

## Forward-look (T-041 + T-042 candidates)

After T-039 lands and one session-arc passes:

- **T-041**: Remove the `cockpit/__init__.py` deprecation shim. Verify no callers still use the old path. ~30 min.
- **T-042 (director-side audit, ~2 hr)**: file-location audit across the project. Find other files whose folder doesn't match their actual role (the user's bigger insight: "is this file's location consistent with what it does?"). Surface candidates for future relocation dispatches. Mentioned in the user's 2026-05-12 message but out of scope for T-039.

---

## Director note

This spec is **propose-first per CLAUDE.md** because the file moves touch 3+ engine call sites (Engine D's `wfo.py`, the backtester, orchestration, scripts, and dashboard_v2). The user has provisionally approved drafting THIS spec; explicit approval for the IMPLEMENTATION dispatch is a separate gate.

When ready to dispatch the implementation:
1. Director confirms with user: "approve T-039 implementation dispatch?"
2. On approval, director writes T-039's full brief into an agent's inbox using this spec as the canonical source.
3. Agent executes; director merges + pushes after review.
