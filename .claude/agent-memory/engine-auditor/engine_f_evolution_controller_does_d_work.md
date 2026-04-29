---
name: Charter boundary violation — F module doing D work
description: engine_f_governance/evolution_controller.py runs WFO + promotes candidates, which is Engine D territory per charter
type: project
---

`engines/engine_f_governance/evolution_controller.py::EvolutionController` implements `run_cycle`, `run_wfo_for_candidate`, and `update_production_config` — all of which are walk-forward optimization and candidate validation, which the charter assigns exclusively to Engine D.

Charter violation cite: engine_charters.md Engine F Forbidden Inputs explicitly lists "Edge discovery, parameter optimization, or walk-forward testing (that's D's job)." Authority Boundaries table reinforces: "What new edges might exist | D | A, B, C, E, F cannot hunt for or generate new edges."

**Why:** Per the file's own docstring, this controller was created when Discovery's WFO subprocess was calling a missing script (`walk_forward_validation.py`). The fix wired WFO directly — but it landed in `engine_f_governance/` instead of `engine_d_discovery/`. Likely because the original script-runner pattern was governance-orchestrated.

**How to apply:** When recommending consolidation, the move target is `engines/engine_d_discovery/`, not maintaining it where it is. The controller is also dead code in the production path — `mode_controller._run_discovery_cycle` calls `discovery.validate_candidate` directly, never `EvolutionController.run_cycle`. Pre-existing `scripts/run_evolution_cycle.py` may invoke it — check before deletion.

Currently both validate candidates with WFO; only the broken `validate_candidate` runs in production. The working controller lives in the wrong engine.
