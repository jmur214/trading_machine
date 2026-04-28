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

### [HIGH] System Sharpe 0.4 on 109-ticker universe vs SPY 0.88 in-sample
- Engine: System-level (Alpha + Risk + Portfolio composition)
- First flagged: 2026-04-25
- Status: **partially resolved — 0.855 figure is pre-lifecycle, not a stable baseline**
- Description: Universe expansion from 39 to 109 tickers exposed that the system underperforms SPY by ~0.5 Sharpe on a broader equity universe. The previously-reported Sharpe 0.979 was a curated-mega-cap-tech artifact. Existing edges don't generalize beyond the original 39 names; lifecycle correctly paused 2 of 14 (`atr_breakout_v1`, `momentum_edge_v1`) but no replacement alpha was queued.
- 2026-04-27 Phase 2.10 full backtest result: **Sharpe 0.855** (run d134e488) — but this was the run that GENERATED the lifecycle pause decisions. `atr_breakout_v1` (weight 2.5) and `momentum_edge_v1` (weight 1.5) were still at full weight during this run and contributed +$2,694 and +$1,569 respectively. Post-pause, subsequent in-sample runs show Sharpe 0.161–0.677 depending on governor learned-affinity state.
- 2026-04-28 in-sample re-run with paused edges at 0.25x soft-pause: **Sharpe 0.161** (run daf4ad4d). Per-edge breakdown shows `momentum_edge_v1` went from +$1,569 to -$888 at reduced weight; `gap_fill_v1` went from +$151 to -$1,080; "Unknown" exit losses went from -$3,681 to -$11,241. Governor learned-affinity state is a significant contributor to variance between runs.
- Remaining gap: true post-lifecycle Phase 2.10 Sharpe needs to be established with `--no-governor` to isolate the pure alpha contribution. The 0.855 figure should be treated as the pre-governance upper bound, not the operational Sharpe.
- Recommended next step: (1) Run `--no-governor` in-sample to establish alpha-only baseline; (2) walk_forward_phase210.py year-by-year validation; (3) consider retiring atr_breakout/momentum_edge entirely instead of soft-pausing to avoid signal contamination.
- See: `docs/Progress_Summaries/2026-04-27_session.md`, commits dfb0627, f06afb2-b1928c9, aa1cb65, da196b1, 1600e45, 53d5c07, 7db6625, 45abf0e. Also `scripts/walk_forward_phase210.py`.

### MEDIUM

### [MEDIUM] Soft-paused edges with high alpha_settings weights still dominate signal ensemble
- Engine: A (AlphaEngine / SignalProcessor) + F (lifecycle soft-pause design)
- First flagged: 2026-04-28
- Status: **resolved 2026-04-28** — `PAUSED_MAX_WEIGHT = 0.5` cap added (commit 93411be)
- Description: The soft-pause 0.25x multiplier is applied to the edge's pre-pause alpha_settings weight. `atr_breakout_v1` at weight 2.5 → 0.625 after soft-pause, still above most active edges at 0.5-1.0. Caused atr_breakout to generate 2371 trades in the 2026-04-28 in-sample run (vs 51 for volume_anomaly at weight 1.0) and drive "Unknown" exit losses to -$11K. Fix: added `PAUSED_MAX_WEIGHT = 0.5` cap in `mode_controller.py` after the multiplier — paused edges can now be at most `min(weight × 0.25, 0.5)`. For atr_breakout: min(0.625, 0.5) = 0.5, below active edges at 1.0. Does not affect edges whose pre-pause weight was ≤ 2.0 (they stay below 0.5 after multiplier).

### [MEDIUM] Governor learned-affinity from OOS runs contaminates subsequent in-sample backtests
- Engine: F (Governor — `data/governor/edge_weights.json` persistence)
- First flagged: 2026-04-28
- Status: not started
- Description: `edge_weights.json` (the governor's learned SR-based affinity per edge) persists across runs. When OOS backtests run first (especially on adversarial windows like 2025 data), the governor downgrades edge weights that underperform in OOS. Loading those downgraded weights into a subsequent in-sample run injects forward-looking signal: the governor "knows" which edges struggled in 2025 and suppresses them in the 2021-2024 window where they were profitable. Observed 2026-04-28: governor-enabled in-sample run got Sharpe 0.161 vs 0.264 with `--no-governor` — the difference is -0.103 Sharpe from stale/wrong affinity. Resetting to neutral (all weights = 1.0) before in-sample runs restores correct behavior.
- Recommended next step: The backtest should always start with neutral governor weights (1.0) and train from scratch during the run. Add a `--reset-governor` flag or reset automatically when `--fresh` is used. This is the backtesting-as-measurement analogue of `lifecycle_readonly` — the governor's persistent state is production state, not measurement state.

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