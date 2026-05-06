---
name: Bare-except pattern is the dominant failure mode
description: In ArchonDEX, the leading source of silent bugs is `except Exception` blocks swallowing programmer errors (TypeError, AttributeError, ImportError, missing-method) alongside legitimate runtime errors, with default-value continuation that makes the system appear functional.
type: project
---

When scanning for code health, bare `except Exception` blocks are the highest-yield finding category in this codebase. Pattern recurrences observed across multiple sessions:

- Caller/callee interface drift (e.g. `WalkForwardOptimizer()` ctor needs `data_map`, caller passes none) → caught silently → gate "passes" with default value
- Schema drift on dict access (e.g. `regime_meta["correlation"]` reads non-existent key) → falls through to default 0
- Import errors after module deletion (e.g. `rsi_mean_reversion.py` deleted 2025-11-12, references remain in `alpha_engine.py:251, 422`) → masked for ~6 months
- Method-name typos (e.g. `check_signal` vs `compute_signals`) → multi-method dispatcher returns `{}` silently
- Deprecated pandas APIs (e.g. `get_loc(method='nearest')` removed in pandas 2.0) → falls back to `start_idx = 0`, breaking WFO

**Why:** These aren't lazy programmers. They're authors trying to make the system "degrade gracefully" so a single edge failure doesn't crash a whole backtest. The result is the opposite: failures cascade silently and only surface when someone hand-traces a low Sharpe back to its source.

**How to apply:** When auditing this codebase, count `except Exception` occurrences per file (50+ in alpha_engine, governor, lifecycle_manager, system_governor — each is a potential silent-bug nest). Recommend narrowing to `except (RuntimeError, KeyError, FileNotFoundError)` at minimum, with a top-level `except Exception:` that logs traceback. Programmer errors should propagate.

**Verified examples already fixed**: 2026-04-28 commit dda474c (Gate 3, Gate 5, regime_meta correlation key — all bare-except masked). 2026-04-28 health_check additions: 5 more in same pattern.

**2026-05-06 follow-up scan after V/Q/A merge:**
- `engines/engine_a_alpha/edges/_fundamentals_helpers.py:205-208` — the
  shared helper `top_quintile_long_signals` swallows ALL exceptions inside
  the per-ticker score callable. All 6 new SimFin V/Q/A edges (`value_*`,
  `quality_*`, `accruals_inv_*`) inherit this. One narrow change at this
  one site removes the silent-bug surface for the whole cohort.
- All 6 new V/Q/A edges end with `try: _reg.ensure(...) except Exception:
  pass` for auto-registration. If the registry write throws (file lock,
  schema drift, FileNotFoundError), the edge silently fails to register
  but the import still succeeds — alpha_engine loads the class but
  lifecycle has no spec.
- Engine D Gates 2/4/5/6 (`discovery.py:975-1183`) still have the
  bare-except shape. Gate 3 was retrofitted on 2026-05-02 with
  `if isinstance(e, (TypeError, AttributeError)): raise` — that's the
  fix-pattern to apply across the other 4. The original gauntlet
  consolidated-fix closed the *measurement-geometry* bug class but did
  not propagate the defensive-promotion to all gates.

**Pattern observation:** When a fix lands for one instance of this class,
the codebase tends NOT to systematically apply it across siblings. Search
for `except Exception` after every consolidation; expect to find 3-5 more
adjacent cases that should have received the same patch.
