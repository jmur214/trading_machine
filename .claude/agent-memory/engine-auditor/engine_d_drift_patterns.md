---
name: Engine D drift patterns
description: Common ways Engine D code drifts from charter — bare-except gates, interface mismatches, dead duplicate orchestrators
type: project
---

Engine D drifts faster than any other engine. Three observed patterns as of 2026-04-28:

**Pattern 1 — Bare-except + silent default.** `discovery.py::validate_candidate` has 6 separate `except Exception as e: print(...)` blocks, one per validation gate, each falling back to a permissive default (Sharpe 0, p-value 1.0, survival 0.0, universe_b nan-→-pass). When any gate's call site drifts (renamed method, changed signature, deprecated pandas API, missing datetime index), the gate goes silent and every candidate trivially passes. Three bugs found in one log read on 2026-04-28 (`detect()` typo, integer-index equity series, `check_signal` vs `compute_signals`); two more bugs found in this audit (Gate 3 WFO ctor + signature mismatch, Gate 5 same datetime-index bug as Gate 1). All five were sitting under bare-except blocks.

**Why:** D is the engine most exercised against external interfaces (RegimeDetector, AlphaEngine, BacktestController, MetricsEngine, edge templates). Each external call is a drift surface. Bare-except converts every drift into a silent gate-skip.

**How to apply:** When auditing D, grep for `except Exception as e:` and treat every block as suspect. Read the call inside it against the actual implementation of the called method. Verify the keys read from any external dict against the producer's actual output schema.

**Pattern 2 — Duplicate orchestrators.** As of 2026-04-28 there are two complete WFO-runner implementations: `discovery.py::validate_candidate` Gate 3 (broken, called in production) and `engine_f_governance/evolution_controller.py::run_wfo_for_candidate` (working, called by no production path). The former drifted because no one was running its tests. The latter is misplaced (charter-violation: F doing D's work).

**How to apply:** When auditing D, look for parallel implementations in adjacent engines. Check which one is actually invoked by `mode_controller` and treat the other as either dead code or an authority-boundary violation.

**Pattern 3 — Schema reads against drifted producers.** `feature_engineering._compute_regime_features` reads `regime_meta.get("correlation")` — a top-level key that doesn't exist in `RegimeDetector.detect_regime()` output (the key is `correlation_regime.state`). The `.get()` default of "unknown" hides the schema mismatch. The trend/volatility reads work only because RegimeDetector explicitly maintains backward-compat top-level keys for them.

**How to apply:** When auditing any engine that consumes E's regime output, cross-reference the keys read against `engines/engine_e_regime/regime_detector.py:178-219` (the output dict construction). `.get(key, default)` calls with no schema validation are silent drift accumulators.
