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
- Status: open — diagnostic complete, remediation depends on Engine D rework + new alpha sources
- Description: Universe expansion from 39 to 109 tickers exposed that the system underperforms SPY by ~0.5 Sharpe on a broader equity universe. The previously-reported Sharpe 0.979 was a curated-mega-cap-tech artifact. Existing edges don't generalize beyond the original 39 names; lifecycle has correctly paused 2 of 14 (`atr_breakout_v1`, `momentum_edge_v1`) but no replacement alpha is queued.
- Recommended next step: integrate the parallel agent's FRED + earnings data layers into actual edges (PEAD, yield-curve, etc.); re-architect Engine D to search factor space instead of random technical genes (per the strategic pivot doc).
- See: `docs/Progress_Summaries/2026-04-24_strategic_pivot.md`, `memory/project_lifecycle_vindicated_universe_expansion_2026_04_25.md`.

### MEDIUM

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
- Status: open — architectural design needed
- Description: `signal_processor.py` aggregates edge signals via `weighted_sum = sum(score * weight)` — every edge is treated as unconditionally additive. This blocks deploying edges whose alpha is regime-conditional. Concrete evidence (today): `low_vol_factor_v1` walk-forward — in-sample +0.23 Sharpe (driven by 2022 bear), OOS -0.22 to -0.36 (in bull periods). The factor signal IS real (40+ years academic validation, USMV/SPLV ETFs deliver Sharpe 0.7-1.0); it just can't deploy as a constant-weight contributor because the alpha is concentrated in adverse regimes. Same architectural gap likely blocks: low-vol generally, defensive value strategies, momentum strategies that work in trending regimes only, mean-reversion strategies that work in chop. The 2026-04-23 per-edge per-regime kill-switch attempt was a binary version of this primitive that was falsified — the underlying need is real, the implementation needs to be soft-weighted not binary.
- Recommended next step: design either (a) edge-level `regime_gate` metadata read by signal_processor — e.g., `regime_gate: {"recession": 1.0, "expansion": 0.2}` mapped against Engine E advisory, OR (b) Engine E advisory output a per-edge weight multiplier that signal_processor applies. Either is multi-day design + implementation. Requires the FRED-driven regime classifier (see other MEDIUM finding) to be in place first so the regime signal is reliable.
- See: `memory/project_low_vol_regime_conditional_2026_04_25.md`, `docs/Progress_Summaries/2026-04-25_session.md` "What needs adding" section.

### [MEDIUM] Engine D's GA gene vocabulary searches a strip-mined space
- Engine: D (Discovery)
- First flagged: 2026-04-24
- Status: open — strategic decision, no code work yet
- Description: Engine D's `_create_random_gene` mutates random combinations of technical-indicator genes (RSI thresholds, ATR multipliers, day-of-week, intraday range). The space has been mined to ≈zero alpha by 40+ years of professional quant work. Yesterday's Engine D run produced 132 failed candidates. Adding new technical-pattern genes won't help; the space is the problem.
- Recommended next step: re-architect the gene vocabulary to search across (a) factor-space (which factors / windows / weighting / sector-neutralization), (b) macro-feature space (FRED-driven signal compositions now that the data layer exists), and (c) earnings-event space (PEAD parameters, surprise-magnitude thresholds). Per the strategic pivot doc, this is item #6 — substantial work, ~1-2 weeks.
- See: `docs/Progress_Summaries/2026-04-24_strategic_pivot.md` items #5 (Engine D fitness function fix) + future restructuring; `memory/project_factor_edge_first_alpha_2026_04_24.md`.

### [MEDIUM] Lifecycle audit-trail / registry-state divergence detection missing
- Engine: F (Governance)
- First flagged: 2026-04-25
- Status: open — refinement; not blocking, but would have caught the registry stomp bug earlier
- Description: `lifecycle_history.csv` records `<edge>: active → paused` events. The 2026-04-25 registry stomp bug accumulated multiple identical pause events for the same edge across consecutive runs (because the bug reverted the pause between runs). Nothing in the system flagged this anomaly — under correct behavior, the second run should see the edge already paused. A sanity check at lifecycle startup that flags `<id>: <prev> → <new>` events where `prev` doesn't match the registry's actual current value would catch this entire bug class.
- Recommended next step: add a check in `LifecycleManager.evaluate()` startup that compares the most recent audit-trail entry per edge_id against current registry status; log a warning when they disagree. Cheap, high-signal.
- See: `memory/project_registry_status_stomp_bug_2026_04_25.md` methodology rule #4.

### LOW

*No active LOW-severity findings.*

---

## Resolved (last 90 days)

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