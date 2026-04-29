---
name: Where debt accumulates fastest in ArchonDEX
description: Orchestrator-style modules (alpha_engine.py, governor.py, system_governor.py, discovery.validate_candidate, lifecycle_manager.py) accumulate god-class lines and bare-except blocks faster than other parts of the codebase. Edges and detectors stay small; orchestrators sprawl.
type: project
---

Files >500 lines in the three target engines (A, D, F) as of 2026-04-28:

- `engines/engine_d_discovery/discovery.py` — 888 lines (DiscoveryEngine: hunt, generate_candidates, validate_candidate, _run_ga_evolution, _build_universe_b, _save_candidates_to_yaml, etc.)
- `engines/engine_a_alpha/alpha_engine.py` — 834 lines (config loading, dynamic edge import, generate_signals, instrument logic, formatter)
- `engines/engine_f_governance/governor.py` — 719 lines (StrategyGovernor: weights, regime weights, evaluator integration, allocation_evaluator, history persistence, lifecycle plumbing)
- `engines/engine_f_governance/system_governor.py` — 653 lines (DEAD: never called, see duplicate-orchestrator memory)
- `engines/engine_f_governance/lifecycle_manager.py` — 622 lines (gate evaluation + audit divergence + retirement transitions + persistence)
- `engines/engine_a_alpha/edges/composite_edge.py` — 518 lines (gene evaluation: technical, regime, macro, earnings, fundamental — each gets its own `_calc_*_val` with its own bare-except)

**Why:** Each new feature (lifecycle, regime tracking, learned affinity, soft-pause cap, audit divergence check) gets bolted onto the same orchestrator class because that's where the existing `__init__` already wires up the dependencies. Refactor pressure is real but always loses to "ship the feature."

**How to apply:** When the user says "scan for code health," prioritize these files. For each, expect to find: 30+ bare-excepts, 5+ private `_helper` methods that have grown to 100+ lines, and at least one method whose docstring promises one thing but does another (drift between docstring and code).

**Refactor patterns that have held up vs not held up:**
- **Held**: `LifecycleManager` was extracted from `StrategyGovernor` (commit ~2026-04-24) and stayed clean.
- **Held**: Adding `regime_gates` to `SignalProcessor` ctor (commit aa1cb65) instead of in-place patching.
- **Did not hold**: `evolution_controller.py` was supposed to replace `discovery.validate_candidate`'s WFO block — both still exist, and the broken one runs (existing health_check finding).
- **Did not hold**: `system_governor.py` was supposed to be the orchestrator on top of `governor.py` — instead, both grew independently and `system_governor` lost its consumers.

Pattern: extractions that ALSO migrated callers stuck. Extractions that left old paths "for backwards compat" became dead-code shadows.
