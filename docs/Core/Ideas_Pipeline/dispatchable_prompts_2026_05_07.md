# Dispatchable Prompts — 2026-05-07

User-approved workstreams that should fire in fresh `claude` sessions. Each prompt is self-contained — paste verbatim. The agent runs the full lifecycle (worktree setup → work → commit → merge → push → cleanup); user only approves destructive-op permission popups.

These four can run in parallel — they touch different file surfaces. Recommended firing order:

1. **E-rebuild** (substrate-independent, longest, highest research value)
2. **F11 journal** (architectural foundation; should land before Moonshot/Trend so sleeves are built on the new pattern)
3. **Trend-following sleeve Phase 0** (parallel-track defensive)
4. **Moonshot Sleeve Phase 0** (parallel-track Goal C)

---

## Dispatch 1 — E-rebuild Phase 1 (regime feature-engineering)

**User's stated framing (approved):** *"build it as background feature-engineering; don't ship until it falsifies-cleanly. Same shape as universe-loader and MetaLearner — built, parked, fired with clean falsification surface."*

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/e-rebuild-phase1 -b e-rebuild-phase-1
cd .claude/worktrees/e-rebuild-phase1
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/e-rebuild-phase1 -b e-rebuild-phase-1
cd .claude/worktrees/e-rebuild-phase1
```

## Background

The HMM regime classifier was empirically falsified 2026-05-06 (memory `project_regime_signal_falsified_2026_05_06.md`): AUC 0.49 on 20d-fwd drawdowns; cross-asset 2-of-3 gate had 0% TPR on -5% drawdowns over 1086 days. Root cause: HMM input features (spy_ret_5d, spy_vol_20d) are coincident by construction.

Subsequent cheap-validation Branch 3 (memory `project_cheap_input_validation_branch3_2026_05_06.md`) verified VIX term structure is also decisively coincident across all 4 tenor pairs. CBOE P/C historical is unobtainable in 2026 on free endpoints.

The 2026-05-07 R1 audit (`docs/Sessions/Other-dev-opinion/2-opinions+synthesis.md/code-access_audit.md` §4 item 2) flagged: HYG-IG OAS spread is already cached at `engines/data_manager/macro_data.py:102,105` but UNUSED. Plus the slice-1 work found yield_curve_spread + credit_spread_baa_aaa + dollar_ret_63d carry forward signal but get drowned by coincident features in the larger panel.

User decision (2026-05-07): build the regime-rebuild work as background feature-engineering. Don't ship into Engine B sizing until it falsifies-cleanly. Same shape as universe-loader (built 2026-04-24, parked 6 weeks, fired with clean falsification surface).

## Goal — five deliverables

### 1. Wire HYG-IG OAS spread into the macro feature panel

Read for orientation:
- `engines/data_manager/macro_data.py:102,105` — HYG-IG OAS already cached (BAMLH0A0HYM2 - BAMLC0A0CM)
- `engines/engine_e_regime/macro_features.py:40` — `FEATURE_COLUMNS` list (current panel members)
- `Archive/engine_e_regime/cross_asset_confirm.py:120` — archived primitive that had the right idea (see R1's audit)
- `data/macro/` — FRED feature CSVs

Implementation:
- Add `hyg_ig_oas` to `FEATURE_COLUMNS`
- Verify the data source returns a usable series (1989+ for FRED HY OAS series — much longer history than VIX)
- Add a unit test that the feature appears in the panel and has expected shape

### 2. Add additional leading-indicator candidates per R2's "what other leading indicators are we underweighting?"

Per R2 (no-code-access auditor) and the user's pushback:
- 2s10s yield curve (FRED: T10Y2Y) — 12-18 month recession lead, noisy
- copper-gold ratio (HG vs GC futures, OR yfinance JJC/GLD as a retail proxy)
- defensive-vs-cyclical relative strength (XLP vs XLY, or XLV vs XLI)

Add at least 2 of these to `data/macro/` and to `FEATURE_COLUMNS`. Document the ones you add.

### 3. Train minimal-HMM on the leading subset (3 variants)

Per `docs/Core/Ideas_Pipeline/regime_panel_slice_2_plan.md` and the cheap-validation Branch 3 finding:

Variant A: 4 leading FRED features alone (yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d, spy_vol_20d)
Variant B: A + HYG-IG OAS (the new wire)
Variant C: A + HYG-IG OAS + at least 1 additional leading indicator from #2

Output: a regime label time series for each variant saved to `data/macro/minimal_hmm_states_<variant>.parquet`. New script `scripts/train_minimal_hmm.py` (mirror the pattern of `scripts/train_hmm_vix_term.py`).

### 4. Validate vs forward drawdowns

Reuse `scripts/validate_regime_signals.py`:
- AUC vs SPY 20d-fwd drawdown ≤ -5%
- Coincident-vs-leading correlation flip (Pearson(forward 20d) > Pearson(trailing 20d) in absolute value)
- Per-state breakdown (which state precedes drawdowns; which is "stress")

Verdict criteria for each variant:
- LEADING: AUC > 0.55 AND |Pearson(fwd 20d)| > |Pearson(trail 20d)|
- COINCIDENT: AUC > 0.55 BUT |Pearson(fwd)| ≤ |Pearson(trail)| (informative but not predictive)
- INDETERMINATE: AUC ≤ 0.55 (no edge)

### 5. Wire-readiness assessment ONLY

If at least one variant clears LEADING, document the wire-into-Engine-B integration plan with file:line refactor map. **DO NOT wire into Engine B in this dispatch** — that's a separate propose-first per CLAUDE.md.

If no variant clears LEADING:
- Document explicitly that the leading-indicator subset (post-2026-05-07 expansion) does not predict drawdowns
- Recommend the next experiment: paid options-history provider (CBOE), or Schwab IV skew gated on historical-options-chain verification, or retire the regime-conditional sleeve infra entirely
- Clear next-step framing matters; "no signal found" is a valid + valuable outcome

## Acceptance

- 3 minimal-HMM variants trained
- AUC + coincident-leading correlation flip + per-state breakdown for each, on each forward-drawdown horizon (5d, 20d, 60d) — total 3 variants × 3 horizons = 9 measurement cells
- Audit doc at `docs/Measurements/2026-05/e_rebuild_phase1_<date>.md`
- Verdict: which variant (if any) clears LEADING; documented wire-readiness if yes; documented next-experiment framing if no
- New unit tests in `tests/test_minimal_hmm.py` + `tests/test_macro_features_extended.py`

## Hard constraints

- DO NOT modify Engine B / live_trader/ in this dispatch (separate propose-first per CLAUDE.md)
- DO NOT promote any HMM model to production
- READ-ONLY analysis on existing macro data + new wires for HYG-IG OAS and the 2 added features only
- Branch: `e-rebuild-phase-1`
- Time budget: 6-10 hours

## Honest interpretation guidance

The user explicitly approved building this as background work. The acceptable outcomes are:
1. Variant lands LEADING → wire-readiness plan documented, real next-step
2. No variant lands → "no signal found post-expansion" is a valid result that informs the next data-acquisition decision (Schwab options vs paid CBOE vs retire-the-sleeve)

Both outcomes ship. The discipline framework's value is producing clean falsification surfaces, not always producing positive signal.

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff e-rebuild-phase-1 -m "Merge branch 'e-rebuild-phase-1' — minimal-HMM on leading subset, verdict: <LEADING|COINCIDENT|INDETERMINATE>"
git push origin main
git worktree remove .claude/worktrees/e-rebuild-phase1
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

Variant verdicts (LEADING/COINCIDENT/INDETERMINATE per horizon), AUC table, coincident-leading correlation flip table, wire-readiness plan if any variant clears, next-experiment recommendation if not, final main commit hash.
```

---

## Dispatch 2 — F11 journal-and-apply implementation

**User-approved per `F11_journal_redesign_proposal_2026_05_07.md` (no concerns flagged).**

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/f11-journal -b f11-journal-and-apply
cd .claude/worktrees/f11-journal
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/f11-journal -b f11-journal-and-apply
cd .claude/worktrees/f11-journal
```

## Background

User-approved per `docs/Core/Ideas_Pipeline/F11_journal_redesign_proposal_2026_05_07.md`. The full design rationale, file inventory, and migration sequencing live there — read it carefully before coding. Triggered by R1 (codebase-access auditor) §8: F11 write-back smell is deeper than the snapshot harness suggests; real fix is journal + apply at next-cycle boundary.

User's stated alignment (verbatim): "we never ever want to overfit our system via backtest so it doesn't hold up live; the goal is that our system performs live as close to how it performs in backtest." This redesign is the structural fix that delivers that property — backtest mechanics become structurally identical to live mechanics (no special snapshot/restore only-in-backtest behavior).

## Goal — implement the proposal

Six deliverables per the proposal doc:

1. New `engines/engine_f_governance/journal.py` — `LifecycleJournal` class. Append-only writer, JSONL on-disk format, structured schema (timestamp, run_id, decision_type, edge_id, payload), thread-safe append.

2. New `scripts/journal_apply.py` — CLI driver. Reads journal entries since last apply, atomically updates `data/governor/edges.yml` (write to .tmp + os.rename for atomicity). Idempotent (re-applying with no new entries is a no-op). Dry-run mode (`--dry-run` shows planned changes without committing). File-locking on edges.yml to prevent concurrent applies.

3. Modify `engines/engine_f_governance/governor.py:592` — `StrategyGovernor.update_from_trades` writes through the journal instead of directly mutating edges.yml.

4. Modify `engines/engine_f_governance/lifecycle_manager.py:289` — `LifecycleManager.evaluate` writes through the journal.

5. Modify `orchestration/mode_controller.py::run_backtest` — add optional `apply_journal_at_end: bool = False` parameter (default False → backtest is pure measurement; explicit True for autonomous cycles that should apply lifecycle decisions at run completion).

6. Update `scripts/run_isolated.py` — once the new pattern is verified, the snapshot/restore harness can drop edges.yml + edge_weights.json from its 4-file set. **CRITICAL: keep the existing harness operational until the journal pattern is independently verified end-to-end** (the proposal's migration sequencing). Don't remove harness coverage in this dispatch — verify journal pattern works first; harness simplification is a follow-on step in a SEPARATE dispatch.

## Acceptance criteria

1. New unit tests in `tests/test_lifecycle_journal.py`:
   - Append schema validation
   - Idempotent apply (apply twice → second is no-op)
   - Atomic write (interrupt mid-apply → edges.yml not corrupted, journal still readable)
   - Dry-run mode shows planned changes without committing
   - Concurrent-apply rejection (file lock works)

2. Integration test: backtest run → journal entries → apply → edges.yml updated correctly. Includes assertion that edges.yml is byte-identical pre-apply during the backtest itself (the run does NOT mutate it).

3. Determinism harness 3-rep on populated main: identical canon md5 with the new pattern (the 4-file snapshot still active during this dispatch — the journal-pattern fix should be invisible to the harness).

4. Audit doc at `docs/Measurements/2026-05/f11_journal_implementation_<date>.md` documenting:
   - Files touched
   - Schema for journal entries
   - Apply transaction guarantees (atomicity, idempotency, locking)
   - Verification of "edges.yml unchanged during backtest"
   - Migration sequencing for harness simplification (proposed as follow-on dispatch)

5. Update `docs/Core/governance_lifecycle_journal_design.md` (new) — architecture-level doc for future readers explaining the journal-and-apply pattern.

## Hard constraints

- DO NOT remove harness coverage of edges.yml + edge_weights.json in this dispatch (the migration sequencing in the proposal is explicit: verify the journal pattern works in parallel with the existing harness before retiring redundant snapshots)
- DO NOT modify Engine A / B / C / D / E / live_trader/ (CLAUDE.md propose-first; the journal pattern is internal to Engine F + the orchestration layer)
- DO NOT promote any edge or change any edge's status during your verification runs
- Branch: `f11-journal-and-apply`
- Time budget: 18-29 hours (2-3 days focused per the proposal scope estimate)

## Honest interpretation guidance

This is foundational architecture work. Whether the determinism harness becomes simpler at the END is a follow-on; the GOAL of THIS dispatch is the journal pattern is implemented + verified working in parallel with the existing harness. Don't try to do the harness simplification in the same commit — that's the next dispatch, with a clean baseline established first.

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff f11-journal-and-apply -m "Merge branch 'f11-journal-and-apply' — Engine F journal pattern shipped; backtest no longer mutates edges.yml"
git push origin main
git worktree remove .claude/worktrees/f11-journal
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

Files created/modified, schema for journal entries, atomicity verification, integration test result (backtest → no-mutation + apply → correct mutation), 3-rep determinism harness still passes, follow-on dispatch sketch for harness simplification, final main commit hash.
```

---

## Dispatch 3 — Trend-following sleeve Phase 0

**User decision:** "build it and see where it lands. If it works, all my hesitation is gone."

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/trend-sleeve-phase0 -b trend-following-sleeve-phase-0
cd .claude/worktrees/trend-sleeve-phase0
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/trend-sleeve-phase0 -b trend-following-sleeve-phase-0
cd .claude/worktrees/trend-sleeve-phase0
```

## Background

R2 (no-code-access auditor) recommended trend-following on diversified futures as the single biggest strategic addition for the bear/chop regime gap. Specifically: it has positive expected return AND works in the regimes the surviving-6 equity stack fails. AQR / Hurst-Ooi / Moskowitz public papers cover the academic case. Synthesis-by-primary-dev pushed this hardest as the strategic recommendation.

User decision: build it as a sleeve. Existing sleeve scaffolding at `engines/engine_c_portfolio/sleeves/sleeve_base.py:80` is currently an abstract design artifact — this dispatch makes it concrete by being the FIRST real sleeve.

User's hesitation captured (verbatim): "some hesitations about trend-following itself, but we should build it and then see where it lands. If it works, all my hesitation is gone." The deliverable is enough infrastructure + edge to MEASURE whether trend-following adds positive contribution; not a full production sleeve.

## Goal — three deliverables

### 1. Concrete sleeve infrastructure on top of `sleeve_base.py`

- `engines/engine_c_portfolio/sleeves/trend_following_sleeve.py` — `TrendFollowingSleeve(SleeveBase)` class
- Sleeve has its own: universe (futures), data layer (continuous-front-month series), edge logic, sizing model (vol-targeted at strategy level), risk model (margin + roll handling), capital allocation interface
- Sleeve aggregator pattern at top of `engine_c_portfolio/policy.py` — combines core book signals with sleeve allocations
- The sleeve's measurement is independent: its own Sharpe, Sortino, Calmar, drawdown, etc., separate from the core book

### 2. Futures data layer

This is the load-bearing data work. Pick free or near-free sources:
- For continuous-front-month: yfinance has `^GSPC, ^IRX, ^TNX, GC=F, CL=F, ZB=F, NQ=F, ES=F, ZN=F, ZS=F` — start there
- Alternative: Stooq's continuous-futures data (free)
- New module `engines/data_manager/futures_data.py` — `FuturesDataManager` class, mirrors the equity DataManager interface, handles roll mechanics (or front-month-only for Phase 0; explicit roll handling is Phase 1)

Universe for Phase 0 (10 contracts; diversified):
- Equity indices: ES (S&P), NQ (Nasdaq) — could use SPY/QQQ as Phase 0 stand-ins if futures data acquisition is too slow
- Bonds: ZB (30y), ZN (10y) — or TLT/IEF as stand-ins
- Currencies: 6E (EUR), 6J (JPY) — or FXE/FXY as stand-ins
- Commodities: GC (gold), CL (oil), ZS (soybeans), HG (copper) — or GLD/USO/CORN/CPER as stand-ins

If futures data acquisition is hard, **use ETF stand-ins for Phase 0** (the time-series momentum logic transfers; use real futures in Phase 1).

### 3. First trend edge: time-series momentum

`engines/engine_c_portfolio/sleeves/edges/ts_momentum_v1.py` (or wherever sleeve-edges go in your design):
- Classic time-series momentum signal (Moskowitz/Ooi/Pedersen 2012)
- Signal: sign(12-month price change) — go long if positive, short if negative (use long-only ETF stand-ins if shorts unavailable)
- Volatility-targeted at the contract level (target = 10% annualized; size = target_vol / realized_vol_60d)
- Rebalance monthly
- Optional: 1-month or 3-month signal as variations

### 4. Backtest harness for the sleeve

- 2010-2025 backtest on the chosen universe
- Per-year Sharpe, Sortino, max drawdown
- Correlation to the core book's surviving-6 results (key metric for "is this real diversification")
- Bootstrap distribution on the headline Sharpe (1000 reps with autocorrelation preservation)

## Acceptance criteria

- `TrendFollowingSleeve` instantiable + measurable
- Phase 0 universe of at least 6 instruments (equity-indices + bonds + commodities + currencies)
- Time-series momentum signal computed + sized per-instrument
- 2010-2025 backtest produces per-year Sharpe + Sortino + MDD table
- Correlation matrix between sleeve PnL and core-book PnL on overlapping window
- Audit doc at `docs/Measurements/2026-05/trend_sleeve_phase0_<date>.md` with verdict bucket:
  - WORKS: Sleeve Sharpe > 0.5 over 2010-2025 AND correlation to core book < 0.3 → user's hesitation gone; scale to Phase 1 (real futures, more contracts, full vol-targeting)
  - WEAK: Sleeve Sharpe 0.2-0.5 OR correlation 0.3-0.5 → marginal; consider Phase 1 conditional on regime mix
  - FAILS: Sleeve Sharpe < 0.2 OR correlation > 0.5 → trend-following on this universe doesn't deliver; document why
- 5+ unit tests in `tests/test_trend_following_sleeve.py`
- Bootstrap distribution on Sharpe with 95% CI

## Hard constraints

- DO NOT modify Engine B / live_trader/ (CLAUDE.md propose-first)
- DO NOT change capital allocation in the core book (the sleeve runs at PHANTOM allocation for Phase 0 — measurement only, no real capital effect)
- DO NOT touch `data/governor/` outside the harness's snapshot scope
- Branch: `trend-following-sleeve-phase-0`
- Time budget: 12-20 hours

## Honest interpretation guidance

The user's hesitation is a feature, not a bug — they want to see real measurement before committing. The dispatch's deliverable is a clean Phase 0 verdict that informs Phase 1 priority:
- If WORKS → trend-following becomes a major workstream; user's hesitation is gone
- If WEAK or FAILS → cleanly informs the user that R2's strategic recommendation didn't deliver on this implementation; pivot to other defensive primitives (R1's sizing fixes)

Both outcomes are valuable. Don't soften the verdict. The trend literature has been published for 30+ years; if it doesn't work in measurable form on a small Phase 0 universe, it probably won't work at scale.

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff trend-following-sleeve-phase-0 -m "Merge branch 'trend-following-sleeve-phase-0' — first concrete sleeve, verdict: <WORKS|WEAK|FAILS>"
git push origin main
git worktree remove .claude/worktrees/trend-sleeve-phase0
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

Universe used (futures vs ETF stand-ins), per-year Sharpe table, correlation to core book, bootstrap CI on Sharpe, verdict bucket, recommendation for Phase 1, final main commit hash.
```

---

## Dispatch 4 — Moonshot Sleeve Phase 0

**User-approved per `moonshot_sleeve_scoping_2026_05_07.md` (all 7 recommendations approved).**

### SETUP

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git worktree add .claude/worktrees/moonshot-phase0 -b moonshot-sleeve-phase-0
cd .claude/worktrees/moonshot-phase0
claude
```

### PROMPT

```
You are working on the ArchonDEX trading system. Read CLAUDE.md first. Full autonomous cycle.

## Setup

```bash
git worktree add .claude/worktrees/moonshot-phase0 -b moonshot-sleeve-phase-0
cd .claude/worktrees/moonshot-phase0
```

## Background

User-approved per `docs/Core/Ideas_Pipeline/moonshot_sleeve_scoping_2026_05_07.md` — all 7 design decisions accepted at recommended defaults. Read the scoping doc carefully before coding; it contains the design rationale.

Decision summary (from scoping):
1. Universe: (e) mix — (b) LEAPS-eligible w/ binary catalysts + (c) special situations + (d) concentrated thematic theses (overlay)
2. Edge candidates Phase 1: leaps_catalyst_edge_v1, spinoff_edge_v1, post_bankruptcy_equity_edge_v1
3. Objective: Sortino + skewness + tail ratio + upside capture
4. Sizing: 1-2% per bet, 30-50 max concurrent, 50% trailing stop, 5% max-name, 25% max-sector
5. Capital allocation: dynamic — start 10%, scale to 25% if Phase 1 produces positive Sortino + cleared gauntlet
6. Architectural placement: first concrete sleeve in `engines/engine_c_portfolio/sleeves/`
7. Success/kill criteria: Sortino > 1.5, skewness > 0.5, ≥1 ≥3x bet, DSR > 0.80 / kill at Sortino < 0.3, MDD > 35%, flat skewness, hit-rate < 25% w/ avg-winner < 2x

Phase 0 = scaffolding + first edge. Edges 2 + 3 are subsequent dispatches.

## Goal — four deliverables

### 1. Concrete `MoonshotSleeve` on top of `sleeve_base.py`

- `engines/engine_c_portfolio/sleeves/moonshot_sleeve.py` — `MoonshotSleeve(SleeveBase)` class
- Implements the sizing rules per decision #4
- Implements the gauntlet criteria per decision #7 — these are SLEEVE-LEVEL, not core-book; objective function is Sortino + skewness + tail ratio + upside capture (NOT Sharpe)
- Capital allocation hook respects decision #5 (10% → 25% dynamic scaling)

### 2. First moonshot edge: `leaps_catalyst_edge_v1`

`engines/engine_a_alpha/edges/leaps_catalyst_edge.py`:
- Long-dated 25-delta calls on names with quantifiable upcoming catalysts
- Catalyst sources for Phase 0: FDA AdComm + PDUFA dates (free public data; FDA calendar), federal contract awards (SAM.gov), earnings dates (yfinance/Finnhub), M&A speculation (heuristic from rumor data — placeholder for Phase 0)
- Position entry: 18-month 25-delta call sized to 1% of sleeve capital
- Exit: 50% trailing from peak OR catalyst date + 14 days OR 30 days before expiry (whichever first)
- Backtest data: needs historical options chains. **Phase 0 stand-in:** synthetic options pricing via Black-Scholes on the underlying's close + IV from VIX/ATR proxy (clearly flagged as PHASE 0 STAND-IN; real OPRA via Schwab is Phase 1).

### 3. Sleeve-level gauntlet

Different from the core gauntlet (which is Sharpe-aware). This sleeve gauntlet:
- Sortino computation
- Skewness computation
- Tail ratio (avg top 5% / |avg bottom 5%|)
- Upside capture (during-up-period return / SPY-during-up-period return)
- DSR with appropriate n_trials
- Kill criteria check (Sortino < 0.3, MDD > 35%, etc. per decision #7)

New module `engines/engine_d_discovery/moonshot_gauntlet.py` (or wherever sleeve gauntlets live in your design).

### 4. Backtest + measurement

- 2010-2025 backtest on the catalyst universe (note: needs historical FDA + contract data going back; Phase 0 may be more limited window if data acquisition is slow — explicitly document the window used)
- Per-year Sortino + skewness + tail ratio + upside capture
- Per-bet hit-rate + average winner / average loser
- Bootstrap distribution on headline Sortino
- Correlation to core book (key for "is this independent")

## Acceptance criteria

- `MoonshotSleeve` instantiable + measurable
- `leaps_catalyst_edge_v1` produces signals on a documented universe + window
- Sleeve gauntlet runs the 5 measurements above on the edge's PnL
- Verdict bucket against decision-#7 thresholds:
  - SUCCESS: clears all 5 success criteria → Phase 1 (add edges 2+3)
  - PARTIAL: clears 3+ criteria → consider Phase 1 conditional on which
  - FAIL: clears < 3 OR triggers any kill criterion → reject Phase 1
- Audit doc at `docs/Measurements/2026-05/moonshot_phase0_<date>.md`
- 8+ unit tests in `tests/test_moonshot_sleeve.py` + `tests/test_leaps_catalyst_edge.py`

## Hard constraints

- DO NOT modify Engine B / live_trader/
- DO NOT touch `data/governor/edges.yml` to register the new edge as `tier=alpha` until Phase 1 (Phase 0 measurement only)
- The sleeve runs at PHANTOM allocation in Phase 0 — measurement, not real capital effect
- Synthetic options pricing is acceptable for Phase 0 but must be CLEARLY FLAGGED in the audit doc + the sleeve's internal logging
- Branch: `moonshot-sleeve-phase-0`
- Time budget: 16-24 hours

## Honest interpretation guidance

This is the first concrete asymmetric-upside work in the project. The gauntlet criteria are deliberately tight (Sortino > 1.5 + skewness > 0.5 + ≥1 ≥3x bet) — meeting all of them is hard. A PARTIAL or FAIL verdict on Phase 0 is a valuable result, not a project failure. R2's specific reframe (LEAPS + special-sit + thematic theses, not small-cap factor) is being tested here for the first time — the test deserves to be honest.

## End-of-cycle

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-2
git checkout main
git merge --no-ff moonshot-sleeve-phase-0 -m "Merge branch 'moonshot-sleeve-phase-0' — Moonshot scaffolding + leaps_catalyst_edge_v1, verdict: <SUCCESS|PARTIAL|FAIL>"
git push origin main
git worktree remove .claude/worktrees/moonshot-phase0
```

Co-Authored-By in commit(s): Claude Opus 4.7 (1M context) <noreply@anthropic.com>

## Report

Catalyst data acquired (FDA + contracts + earnings windows), backtest window used, per-year Sortino/skewness/tail-ratio/upside-capture, hit-rate, verdict bucket, recommendation for Phase 1 (edges 2 + 3 — spinoff, post-bankruptcy), final main commit hash.
```
