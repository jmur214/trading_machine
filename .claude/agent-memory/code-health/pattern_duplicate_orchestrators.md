---
name: Duplicate orchestrator pattern in ArchonDEX
description: This codebase tends to grow a `system_X.py` or `X_v2.py` shadow next to `X.py` whenever a feature feels like it deserves a "complete rewrite," but production callers stay on the original. Check every scan.
type: project
---

Confirmed instances:

1. **`governor.py` + `system_governor.py`** (2026-04-28 finding) — `StrategyGovernor` is the canonical class used by `mode_controller`, `alpha_engine`, `analytics.edge_feedback`, and `scripts.system_validity_check`. `SystemGovernor` is a 653-line orchestrator with its own CLI, its own dataclass config, its own bare-except blocks (29). Nothing imports `SystemGovernor` from production code.
2. **`discovery.validate_candidate` + `evolution_controller.run_cycle`** (existing health_check finding) — both implement WFO-on-candidate-from-registry. The broken one in D runs in production (`mode_controller._run_discovery_cycle`); the working one in F is the dead alternative.
3. **`cockpit/dashboard/` + `cockpit/dashboard_v2/`** (CLAUDE.md non-negotiable) — old dashboard explicitly deprecated, new one is canonical, but old still exists.

**Why this happens here:** When a feature feels like a complete redesign, the author adds `_v2` or `system_` to give themselves room to iterate without breaking the existing path. The plan is "migrate callers when v2 is proven." The migration step gets dropped after the new version compiles, and now there are two implementations drifting independently.

**How to apply:** At every scan, check for these naming patterns:
- `<name>.py` + `system_<name>.py`
- `<name>.py` + `<name>_v2.py` / `<name>_new.py`
- `<name>.py` + `<name>.py.bak` / `<name>_old.py`
- Two files with similar one-line summaries in their module docstring

For each pair, run `grep -rn "import <ClassName>"` against the whole repo to find which is alive in production. The one with consumers is canonical; the one without is a candidate for `Archive/`. Per CLAUDE.md, **archive, never delete**.

**Anti-pattern signal:** A 600+ line file whose only consumer is its own `__main__` is almost always a duplicate orchestrator.
