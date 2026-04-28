# Code Health Tracker

Living document tracking the current quality state of the codebase. 
Maintained by the `engine-auditor` and `code-health` subagents — they 
append findings as they discover them. Resolved items move to the 
"Resolved" section with a date.

This is the source of truth for SESSION_PROCEDURES.md Path 2 
("Critical findings"). When the user asks what's next, this file is 
checked before the roadmap.

If this file appears empty or stale, run the engine-auditor against 
recently-touched engines or the code-health subagent across the 
codebase to populate it.

---

## Active Issues

Findings are listed in priority order: HIGH first, then MEDIUM, 
then LOW. Within each severity, list newest at the top.

### HIGH

### [HIGH] Engine D Gate 3 (WFO) is silently disabled — interface mismatch with WalkForwardOptimizer
- Engine: D
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — rewired with correct interface
- Description: `discovery.py::validate_candidate` line 736 called `WalkForwardOptimizer()` with no args, but ctor requires `data_map`. Line 750 called `run_optimization(_WFOWrapper(edge), data_map, n_configs=1)` — wrong signature. Bare `except` swallowed everything; Gate 3 trivially passed for every candidate. No candidate was actually WFO-validated since this code was written.
- Fix: Rewrote Gate 3 block to use the correct interface — `WalkForwardOptimizer(data_map=data_map)`, then `run_optimization(candidate_spec, start_date=..., train_months=12, test_months=3)`. Removed the `_WFOWrapper` shim (candidate_spec already has `module`/`class`/`edge_id` keys, doubles as `strategy_spec`). The bare-except now re-raises `TypeError` and `AttributeError` so future interface drift surfaces immediately. Also fixed `wfo.py::run_optimization` deprecated `get_loc(method='nearest')` → `get_indexer(..., method='nearest')` (separate but related bug masked by another bare-except).

### [HIGH] Engine D Gate 5 (Universe-B) crashes silently — same datetime-index bug just fixed at Gate 1
- Engine: D
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — datetime index added at line 806
- Description: `discovery.py:806` built the universe-B equity curve as `pd.Series([h["equity"] for h in b_history])` with no datetime index. `MetricsEngine.cagr()` then crashed on `.days` of the integer RangeIndex. Bare-except set `universe_b_sharpe = float("nan")` and reported `Gate 5 skipped`. The Gate-5 logic `universe_b_passed = math.isnan(...) or > 0` gave every candidate a free pass.
- Fix: Same pattern as Gate 1 — `pd.Series([h["equity"] for h in b_history], index=pd.to_datetime([h["timestamp"] for h in b_history]))`. Exception logging now includes `type(e).__name__` so future schema drift is identifiable instead of being swallowed as "Gate 5 skipped".

### [HIGH] Engine D feature_engineering reads regime keys that don't exist on RegimeDetector output
- Engine: D
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — read from structured `*_regime["state"]` keys
- Description: `feature_engineering.py:347-358` did `regime_meta.get("correlation")`, but RegimeDetector's output only has `"correlation"` nested under `correlation_regime["state"]`. `Regime_CorrSpike` was hardcoded 0 for every bar of every TreeScanner hunt.
- Fix: Read all three regime states from the structured form (`trend_regime["state"]`, `volatility_regime["state"]`, `correlation_regime["state"]`) with fallback to the top-level backward-compat keys (`trend`, `volatility`). 6 new tests in `tests/test_discovery_regime_features.py` cover the fix path AND the legacy fallback path.

### [MEDIUM] Engine D has duplicate, drifting WFO orchestrators (evolution_controller and validate_candidate)
- Engine: D + F (charter boundary issue — `evolution_controller.py` lives in `engine_f_governance/` but does Engine D work)
- First flagged: 2026-04-28
- Status: not started
- Description: `engines/engine_f_governance/evolution_controller.py` implements a complete validate-from-registry-with-WFO pipeline (`run_cycle`, `run_wfo_for_candidate`) that wires `WalkForwardOptimizer` correctly with `data_map` ctor and the right `run_optimization(spec, start_date, train_months, test_months)` signature. Meanwhile `discovery.py::validate_candidate` (the path actually called from `mode_controller._run_discovery_cycle`) wires WFO incorrectly (see HIGH finding above) and the active production path silently passes Gate 3. The `evolution_controller.py` module is a maintained, working alternative — but nothing in the live `--discover` flow calls it. It is dead code from the live trading perspective. Worse, its module location violates the charter: it does Engine D work (running WFO on candidates) inside the `engine_f_governance/` package. Per engine_charters.md, "F never... edge discovery, parameter optimization, or walk-forward testing (that's D's job)."
- Charter reference: engine_charters.md Engine F Forbidden Inputs: "Edge discovery, parameter optimization, or walk-forward testing (that's D's job)." Authority Boundaries table: "What new edges might exist | D | A, B, C, E, F cannot hunt for or generate new edges."
- Recommended next step: Either (a) consolidate — move `evolution_controller.py` to `engines/engine_d_discovery/` and delete the broken `validate_candidate` WFO block, calling the controller's method instead; or (b) delete `evolution_controller.py` entirely if `validate_candidate` is meant to be canonical (then fix the WFO bug). Currently both exist, both compute the same thing, and only the broken one runs in production.

### [MEDIUM] Engine D bare `except Exception` blocks routinely mask interface-drift bugs
- Engine: D
- First flagged: 2026-04-28
- Status: not started
- Description: `discovery.py::validate_candidate` contains 6 bare `except Exception as e: print(...)` blocks at lines 680, 727, 758, 769, 812, 871 — one for each gate plus the outer wrapper. Each catches programmer errors (TypeError, AttributeError, missing-method) on equal footing with legitimate runtime issues (data unavailability, file IO). This pattern is what hid all three bugs the user just fixed in commit dda474c, AND it is hiding the two HIGH findings above (Gate 3 and Gate 5). The print messages do not include exception type or traceback, so the user cannot distinguish "Gate 3 had no data this run" from "Gate 3 has been broken for weeks." `tree_scanner.py:178, 233, 257` and `wfo.py:48-53` (also `try: get_loc(method='nearest') except: start_idx = 0`) follow the same pattern — bare except, default value, silent continuation.
- Charter reference: Charter Invariant 5 (Engine D): "D's research is fully reproducible given the same data and random seeds." Silent gate-skip violates reproducibility — outcome depends on whether the masked exception fires.
- Recommended next step: Replace each bare `except Exception` with `except (RuntimeError, KeyError, FileNotFoundError) as e:` (or a similar narrow set), and add a final `except Exception:` at the top level that logs the traceback. Programmer errors should propagate; data errors should fail the gate explicitly with `result["gate_X_passed"] = False` not silently default to a passing value. Also, `wfo.py:49` uses the deprecated `get_loc(method='nearest')` API which has been removed in pandas ≥1.4 — the bare except masks an `InvalidIndexError` and falls back to `start_idx = 0`, meaning every WFO run starts from bar 0 regardless of `start_date`.

### [MEDIUM] Engine D wfo.py uses deprecated `get_loc(method='nearest')` API
- Engine: D
- First flagged: 2026-04-28
- Status: not started
- Description: `wfo.py:49` calls `full_timeline.get_loc(start_dt, method='nearest')`. The `method` parameter was deprecated in pandas 1.4 and removed in pandas 2.0+. On any recent pandas, this raises `TypeError: get_loc() got an unexpected keyword argument 'method'`. The bare `except: start_idx = 0` at line 52 catches it, so every WFO call starts at bar 0 of the timeline — `start_date` is silently ignored. Combined with the Gate 3 interface mismatch above, the production discovery path never reaches this line, so the bug has been latent. But `evolution_controller.run_wfo_for_candidate` (the working orchestrator) DOES reach it — meaning when that path is exercised, all WFO runs use full-history training despite the caller specifying a recent start date.
- Charter reference: "Walk-forward optimization, OOS/IS degradation ratio" (engine_charters.md, Engine D Modules table). Walk-forward by definition requires honoring the rolling window start.
- Recommended next step: Replace with `full_timeline.get_indexer([start_dt], method='nearest')[0]` (or `np.argmin(np.abs(full_timeline - start_dt))` for clarity). Remove the bare except — if the date is unparseable, the run should fail loudly.

### [LOW] Engine D save_candidates uses print() instead of structured logger; conflicts with DiscoveryLogger
- Engine: D
- First flagged: 2026-04-28
- Status: not started
- Description: `discovery.py:475, 492, 513` and the gate-result lines at 678, 685, 728, 759, 770, 813, 852, 854 use `print()` for diagnostic output, while the module already has `DiscoveryLogger` (jsonl audit trail) and a module-level `logger = logging.getLogger("DISCOVERY")`. Inconsistent emission means the gate failures we just diagnosed are visible only as stdout in the discovery cycle log file, not in the structured `discovery_log.jsonl` that downstream tools (and the cockpit) consume. The user's diagnosis of the three bugs in commit dda474c required reading the raw stdout — DiscoveryLogger only sees the final pass/fail, not the gate-skip reason.
- Charter reference: Engine D index.md: "JSONL audit logging of all discovery activity" (`discovery_logger.py` purpose).
- Recommended next step: Route gate-result diagnostics through `DiscoveryLogger.log_validation` (extend the schema with `gate_skipped_reason: Optional[str]`), or at minimum through `logger.warning(...)` so it lands in `evolution.log`. Stop printing.

### [HIGH] System Sharpe 0.4 on 109-ticker universe vs SPY 0.88 in-sample
- Engine: System-level (Alpha + Risk + Portfolio composition)
- First flagged: 2026-04-25
- Status: **partially resolved — 0.855 figure is pre-lifecycle, not a stable baseline**
- Description: Universe expansion from 39 to 109 tickers exposed that the system underperforms SPY by ~0.5 Sharpe on a broader equity universe. The previously-reported Sharpe 0.979 was a curated-mega-cap-tech artifact. Existing edges don't generalize beyond the original 39 names; lifecycle correctly paused 2 of 14 (`atr_breakout_v1`, `momentum_edge_v1`) but no replacement alpha was queued.
- 2026-04-27 Phase 2.10 full backtest result: **Sharpe 0.855** (run d134e488) — but this was the run that GENERATED the lifecycle pause decisions. `atr_breakout_v1` (weight 2.5) and `momentum_edge_v1` (weight 1.5) were still at full weight during this run and contributed +$2,694 and +$1,569 respectively. Post-pause, subsequent in-sample runs show Sharpe 0.161–0.677 depending on governor learned-affinity state.
- 2026-04-28 in-sample re-run with paused edges at 0.25x soft-pause: **Sharpe 0.161** (run daf4ad4d). Per-edge breakdown shows `momentum_edge_v1` went from +$1,569 to -$888 at reduced weight; `gap_fill_v1` went from +$151 to -$1,080; "Unknown" exit losses went from -$3,681 to -$11,241. Governor learned-affinity state is a significant contributor to variance between runs.
- **2026-04-28 operational baseline established**: `--no-governor` (0.264) and neutral-governor + weight-cap (0.256) both confirm post-lifecycle Sharpe of **~0.26**. SPY 2021-2024 Sharpe is 0.875 — gap is **-0.619**. This is larger than the pre-Phase-2.10 gap (0.875 - 0.403 = 0.472), because the Phase 2.10 macro edges barely fire in-sample (macro_credit_spread: 0 trades, most others 0-3 trades) and some lose (macro_yield_curve: -$784 from 157 trades). The alpha is concentrated in atr_breakout (soft-paused) and volume_anomaly/herding (unchanged from before Phase 2.10).
- Per-edge breakdown of neutral-governor run (e5055f4e): atr_breakout +$7,988 (2188 trades at 0.5 cap), volume_anomaly +$5,176 (77 trades), herding +$2,119 (49 trades). "Unknown" exit losses: -$14,832 (885 exits, likely atr_breakout stops). All Phase 2.10 macro edges either silent or losing.
- **2026-04-28 (session 3) walk-forward year-by-year results** (`walk_forward_phase210.py`): 0/4 years beat SPY. 2021: sys 0.455 vs SPY 2.133 (delta -1.678); 2022: sys -0.844 vs SPY -0.735 (delta -0.109, worse in bear); 2023: sys 1.167 vs SPY 1.896 (delta -0.729); 2024: sys 1.048 vs SPY 1.882 (delta -0.834). Mean delta: **-0.837**. No year-specific anomaly — uniform structural underperformance. 2022 result is particularly damning: system loses MORE than SPY in the bear year (no defensive value). Paused edges (atr_breakout, momentum_edge) dominate portfolio even at soft-pause weight, with active macro/PEAD edges contributing near-zero.
- **2026-04-28 (session 3) attribution bug fixed**: "Unknown" exit losses (-$14,832) were attribution failures from soft-paused edges where `norm*weight < min_edge_contribution=0.05`. Fixed `_prepare_orders` in `backtest_controller.py` to fall back to signal's top-level `edge` field when `edges_triggered` is empty. Also fixed double version suffix bug in `alpha_engine.py::_edge_meta_from_detail`. Loss is real (momentum_edge_v1 at soft-pause weight); fix only corrects governance metrics reporting, not Sharpe.
- **2026-04-28 (session 3) autonomous discovery cycle launched**: `PYTHONHASHSEED=0 PYTHONPATH=. python -m scripts.run_backtest --discover` running. Discovery phase begins after in-sample backtest completes. Expected: hunt + generate candidates + 5-gate validation with BH-FDR. Prior cycle had 132/133 failures — GA fitness was optimizing for in-sample Sharpe which the gauntlet kills. This run uses same GA fitness (ROADMAP plan item 6B — OOS fitness — not yet implemented). Not expecting promotions.
- Remaining gap: **-0.837 mean Sharpe delta vs SPY (year-by-year)**. The edge pool has no alpha that fires reliably at deployment weights across multiple years. Gap is uniform, not year-specific. Closing it requires new alpha sources, not weight tuning. Autonomous discovery cycle is the next mechanism.
- Recommended next step: (1) Wait for discovery cycle results; (2) implement ROADMAP item 6B (GA fitness = 0.5*OOS_Sharpe + 0.3*(1-PBO) + 0.2*(OOS/IS)) so the next cycle optimizes for what the gauntlet rewards; (3) discovery is generating candidates but the fitness function needs to align with the validation gauntlet.
- See: `docs/Progress_Summaries/2026-04-27_session.md`, commits dfb0627, f06afb2-b1928c9, aa1cb65, da196b1, 1600e45, 53d5c07, 7db6625, 45abf0e, efbdf8d. Also `scripts/walk_forward_phase210.py`.

### MEDIUM

### [MEDIUM] Soft-paused edges with high alpha_settings weights still dominate signal ensemble
- Engine: A (AlphaEngine / SignalProcessor) + F (lifecycle soft-pause design)
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — `PAUSED_MAX_WEIGHT = 0.5` cap added (commit 93411be)
- Description: The soft-pause 0.25x multiplier is applied to the edge's pre-pause alpha_settings weight. `atr_breakout_v1` at weight 2.5 → 0.625 after soft-pause, still above most active edges at 0.5-1.0. Caused atr_breakout to generate 2371 trades in the 2026-04-28 in-sample run (vs 51 for volume_anomaly at weight 1.0) and drive "Unknown" exit losses to -$11K. Fix: added `PAUSED_MAX_WEIGHT = 0.5` cap in `mode_controller.py` after the multiplier — paused edges can now be at most `min(weight × 0.25, 0.5)`. For atr_breakout: min(0.625, 0.5) = 0.5, below active edges at 1.0. Does not affect edges whose pre-pause weight was ≤ 2.0 (they stay below 0.5 after multiplier).

### [MEDIUM] Governor learned-affinity from OOS runs contaminates subsequent in-sample backtests
- Engine: F (Governor — `data/governor/edge_weights.json` persistence)
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — `--reset-governor` flag shipped
- Description: `edge_weights.json` (the governor's learned SR-based affinity per edge) persists across runs. When OOS backtests run first (especially on adversarial windows like 2025 data), the governor downgrades edge weights that underperform in OOS. Loading those downgraded weights into a subsequent in-sample run injects forward-looking signal: the governor "knows" which edges struggled in 2025 and suppresses them in the 2021-2024 window where they were profitable. Observed 2026-04-28: governor-enabled in-sample run got Sharpe 0.161 vs 0.264 with `--no-governor` — the difference is -0.103 Sharpe from stale/wrong affinity. Resetting to neutral (all weights = 1.0) before in-sample runs restores correct behavior.
- Fix: `StrategyGovernor.reset_weights()` clears `_weights` and `_regime_weights` to empty (→ all edges default to 1.0 in `get_edge_weights()`). Does NOT write to disk — persisted production state is unchanged. Exposed as `--reset-governor` flag in `scripts/run_backtest.py` and `reset_governor=True` parameter in `run_backtest_logic()`. 4 tests in `tests/test_governor_reset.py` cover: clears in-memory weights, does not touch disk, clears regime weights, idempotent. Use: `PYTHONHASHSEED=0 python -m scripts.run_backtest --reset-governor` for clean in-sample measurement.

### [MEDIUM] Soft-paused edges at 0.25x are primary driver of 2025 OOS underperformance
- Engine: F (Governance — lifecycle soft-pause weight policy)
- First flagged: 2026-04-28
- Status: **partially resolved 2026-04-28** — paused→retired path added (commit 1dca4a5)
- Description: 2025 OOS backtest (2025-01-01 → 2026-04-17) shows Sharpe 0.173 vs SPY 0.975. Root cause: `atr_breakout_v1` and `momentum_edge_v1` are soft-paused at 0.25x weight, but still generate 3082 + 1642 = 4724 fills and lose -$3,357 + -$1,208 = -$4,565 combined. The positive Phase 2.10 edges generate only +$3,556 total. The paused edges had no lifecycle exit path — they could only revive or stay paused forever.
- 2026-04-28 partial fix: `LifecycleManager` now has a `paused → retired` transition gate. After `paused_retirement_min_days` (default 90 days), if an edge remains benchmark-negative and is not currently reviving, it gets retired rather than accumulating 0.25x losses indefinitely. 4 new tests, 19/19 lifecycle tests pass.
- Remaining gap: The 2025 OOS backtest result won't change until the in-sample run fires the retirement (next run with lifecycle=True against 2021-2024 data). After that run, both edges will retire at the 2024-12-31 evaluation point and won't be loaded in the 2025 OOS at all.

### [MEDIUM] Earnings backend swapped Finnhub → yfinance — PEAD now has training data
- Engine: A (data_manager — `engines/data_manager/earnings_data.py`)
- First flagged: 2026-04-25
- Status: resolved-but-noted — swap done, cache re-bootstrapped
- Description: Finnhub's free tier was confirmed (2026-04-25) to return 0 historical earnings — per-symbol queries return empty regardless of window, and the unfiltered calendar exposes only the last ~30 days. With Finnhub as the backend, `pead_edge.py` had no historical training data and was functionally inert. Swapped backend to yfinance which exposes ~25 quarters per ticker with `EPS Estimate`, `Reported EPS`, and computed surprise %. Re-bootstrapped on 115-ticker universe → 109 with events, 6 empty (ETFs / BRK.B), 0 failed, 2698 total events. PEAD edge confirmed live (NVDA 2024-02-21 +13% surprise → signal 0.127 day +1, decays linearly to 0 at day 90). `FINNHUB_API_KEY` retained in `.env` for possible real-time use during paper trading; no longer consumed by `EarningsDataManager`. Old Finnhub cache archived at `data/Archive_earnings_finnhub_2026_04_25/`.
- Recommended next step: monitor — yfinance scraping has known reliability issues; if it degrades, the manager already falls back to cache so backtests stay reproducible. No further action unless cache rebuilds start failing.
- See: `memory/project_finnhub_free_tier_no_historical_2026_04_25.md`, `tests/test_earnings_data.py`.

### [MEDIUM] signal_processor lacks conditional-weight composition for regime-conditional edges
- Engine: A (signal_processor)
- First flagged: 2026-04-25
- Status: **resolved 2026-04-27** — regime_gate primitive shipped (commit aa1cb65)
- Description: Resolved. `SignalProcessor` now accepts `regime_gates: Dict[str, Dict[str, float]]` in its constructor. Per-edge gate maps Engine E `regime_summary` labels ("benign", "stressed", "crisis") to weight multipliers [0,1]. Gate multiplies `w` in the weighted-mean aggregation; missing labels default to 1.0; `regime_meta=None` defaults to "benign". `low_vol_factor_v1` re-enabled at weight 0.5 with gate `{benign:0.15, stressed:1.0, crisis:1.0}`. 8 new tests in `tests/test_signal_processor_regime_gate.py` covering all edge cases.
- See: commit aa1cb65, `tests/test_signal_processor_regime_gate.py`, `data/governor/edges.yml` (low_vol_factor_v1 entry).

### LOW

### [LOW] Lifecycle must not modify edge statuses during OOS backtesting
- Engine: F (Governance) + backtesting methodology
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — `lifecycle_readonly` mode shipped
- Description: Running lifecycle on the same OOS window multiple times caused a cascade: each run retired more edges that underperformed in that window, making the result non-reproducible. Fixed by adding `LifecycleConfig.readonly: bool = False`. When `True`, all gate evaluations run and events are returned, but `_save_registry()` and `_append_history()` are skipped — the same OOS window always produces the same result regardless of how many times it's run.
- Wire-up: `GovernorConfig.lifecycle_readonly: bool = False` added; `governor_settings.json` carries the key. Set `lifecycle_readonly: true` in governor_settings to enter OOS measurement mode. 2 new tests in `tests/test_lifecycle_manager.py` (21/21 pass): `test_readonly_mode_does_not_write_registry`, `test_readonly_mode_does_not_append_history`.

---

## Resolved (last 90 days)

### [MEDIUM] Lifecycle audit-trail / registry-state divergence detection missing (2026-04-25)
- Engine: F (Governance)
- Resolved: 2026-04-27
- Description: `LifecycleManager._audit_registry_divergence_check()` was shipped as part of "Phase α v3" (committed before 2026-04-27 session). At the top of `evaluate()`, it reads `lifecycle_history.csv`, extracts the most recent `new_status` per edge via `groupby("edge_id").last()`, then compares against the current registry status in `edges.yml`. Any disagreement logs a `WARNING` with edge_id, audit_trail value, registry value, and a bug-class label (`status_reverted` or `missing_from_registry`). The check is wrapped in `try/except` so it cannot break the lifecycle loop — observability only, not gating. 6 unit tests in `tests/test_lifecycle_manager.py` cover: no-op on empty history, no-op when audit and registry agree, flags status_reverted, flags missing_from_registry, uses most-recent-event correctly, runs silently when evaluate() is called with divergence present.
- See: `engines/engine_f_governance/lifecycle_manager.py::_audit_registry_divergence_check` (lines 357-449), `tests/test_lifecycle_manager.py` lines 292-420.

### [MEDIUM] Engine D's GA gene vocabulary searches a strip-mined space (2026-04-24)
- Engine: D (Discovery)
- Resolved: 2026-04-27
- Description: `CompositeEdge` now evaluates `"macro"` (10% probability — T10Y2Y yield curve, VIX level, UNRATE unemployment delta) and `"earnings"` (5% — EPS surprise % look-back) gene types. Both use lazy instance-level caching. Gene vocabulary weights: technical 40%→35%, regime 10%→5%, fundamental 15%→10%. GA now discovers macro-conditional and earnings-event combinations.
- See: commit 45abf0e, `tests/test_composite_edge_macro_earnings.py`.

### [HIGH] EdgeRegistry.ensure() silently overrode lifecycle status (2026-04-25)
- Engine: A (EdgeRegistry, used by F's lifecycle)
- Resolved: 2026-04-25
- Description: Auto-register-on-import code (`momentum_edge.py:64`, `momentum_factor_edge.py:113`) called `EdgeRegistry().ensure(EdgeSpec(..., status="active"))`. Pre-fix `ensure()` had `if spec.status: s.status = spec.status` — the comment claimed "keep status as-is unless provided" but `EdgeSpec.status` defaults to `"active"` so callers always provided it. Effect: every backtest startup imported `momentum_edge.py` → reverted any lifecycle-applied pause/retire on `momentum_edge_v1` back to `active`. Visible only as repeated identical pause events in `lifecycle_history.csv` across runs. `atr_breakout_v1` escaped because `atr_breakout.py` has no auto-register block, which is why the "first autonomous pause" finding from 2026-04-24 felt real (it was — for atr_breakout). Discovered today via the methodology rule "bitwise-identical canon md5 when expecting change is diagnostic evidence."
- Fix: `EdgeRegistry.ensure()` now write-protects `status` for existing specs, per the `edges.yml` Write Contract documented in `PROJECT_CONTEXT.md` ("F writes: status field changes — neither engine deletes the other's fields"). Added `tests/test_edge_registry.py` with 12 tests including `test_repro_momentum_edge_import_does_not_revive_paused` as a permanent regression check.
- See: `memory/project_registry_status_stomp_bug_2026_04_25.md`, `docs/Progress_Summaries/lessons_learned.md` 2026-04-25 entry, `tests/test_edge_registry.py`.

---

## Archived (older than 90 days)

When resolved items pass 90 days, move them here. Keep this section 
trimmed — if it grows beyond ~50 items, archive the oldest to 
`docs/Archive/audits/health_check_resolved_<year>.md`.

*No archived findings yet.*

---

## Severity guide

- **HIGH**: Actively breaks things or causes silent harm. Examples: 
  broken imports still being called, deprecated paths in active use, 
  bugs that produce wrong outputs, code that bypasses charter 
  boundaries in ways that affect runtime behavior.
- **MEDIUM**: Structural debt that doesn't break the system today 
  but compounds. Examples: god classes (>500 lines), duplicate 
  implementations, oversized functions (>200 lines), missing test 
  coverage on critical paths, charter drift that hasn't yet caused 
  visible problems.
- **LOW**: Hygiene issues. Examples: stale TODOs (>90 days), unused 
  imports, empty test stubs, formatting inconsistencies, outdated 
  comments.

## Format

Findings appended by subagents follow one of two formats:

**From engine-auditor:**
```
### [SEVERITY] <one-line summary>
- Engine: <A/B/C/D/E/F>
- First flagged: <YYYY-MM-DD>
- Status: not started
- Description: <what's wrong>
- Charter reference: <quote or section from engine_charters.md>
- Recommended next step: <specific action>
```

**From code-health:**
```
### [SEVERITY] <one-line summary>
- Category: <duplicate/god-class/dead-code/stale-todo/other>
- Files: <path(s)>
- First flagged: <YYYY-MM-DD>
- Status: not started
- Recommended next step: <specific action>
```

When a finding is resolved, move the entry to the Resolved section 
and add a `- Resolved: <YYYY-MM-DD>` line.