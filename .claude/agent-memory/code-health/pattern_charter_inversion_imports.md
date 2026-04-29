---
name: Charter-inversion imports in ArchonDEX
description: When grep'ing cross-engine imports, look for cases where a "downstream" engine (A=alpha, B=risk) imports from an "upstream" engine (F=governance) — these are charter inversions and a leading indicator that a feature was added in the wrong package.
type: project
---

Per `engine_charters.md`, the data flow is roughly: **A (signals) → B (risk) → C (portfolio) → execution**, with **D (discovery)** producing edges into A's pool, **E (regime)** providing context to all, and **F (governance)** observing everything for lifecycle decisions. Imports should follow this direction.

**Inversions found 2026-04-28:**

1. **A imports F**: `engines/engine_a_alpha/signal_processor.py:27` imports `EDGE_CATEGORY_MAP` from `engines.engine_f_governance.regime_tracker`. Taxonomy lives in F because F was the first to need it; A grew a dependency after-the-fact.

2. **D imports B**: `engines/engine_d_discovery/wfo.py:12` and `engines/engine_d_discovery/discovery.py:620` import `RiskEngine`. Discovery should not depend on the production risk engine — it should use a stripped-down backtest harness.

3. **D imports A**: `engines/engine_d_discovery/wfo.py:11` imports `AlphaEngine`. Same reasoning. WFO uses the full AlphaEngine to evaluate candidates, which means any AlphaEngine change can break Discovery's WFO results.

4. **F doing D work**: `engines/engine_f_governance/evolution_controller.py` (existing finding) — runs WFO from F directory.

5. **F imports C**: `engines/engine_f_governance/governor.py:505` imports `AllocationEvaluator` from `engine_c_portfolio` — F observing C is fine in principle, but it's a cross-engine import worth noting.

**Why:** Features get added in the module where the author was already working. EDGE_CATEGORY_MAP was added during regime-tracker work (in F); WFO was added during discovery work but reuses A and B because rebuilding a backtest harness was too expensive.

**How to apply:** At every scan, run:
```
grep -rn "from engines.engine_<X> import\|from engines.engine_<X>\." engines/engine_<Y>/ --include="*.py"
```
for each pair (X, Y). Any cross-engine import is suspicious; compare against `engine_charters.md` Authority Boundaries table to see if it's a charter violation. A→F, B→A, B→D, C→A, C→D are all inversions worth flagging.

Recommend extracting shared taxonomies/contracts to `core/` rather than letting two engines depend on each other directly.
