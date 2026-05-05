# Round-N+1 Dispatch Briefs (5 agents) — drafted 2026-05-04

**Status:** GATE-CONDITIONAL. Fire only after `scripts/run_multi_year.py`
reports `Gate status: PASS` (mean 2021-2025 Sharpe ≥ 0.5) in
`docs/Measurements/2026-05/multi_year_foundation_measurement.md`. If status is
AMBIGUOUS or FAIL, suppress this dispatch — the kill-thesis review
path takes over instead.

**Why these 5:** All context-agnostic improvements per the deployment-
context update in `forward_plan_2026_05_02.md` (Alpaca may not offer
Roth → tax-drag engineering deferred). All independent code surfaces,
none touch Engine B / live_trader, none require user approval beyond
"go." Briefs below are designed to paste directly into `Agent` tool
calls.

**Isolation pattern:** Use `isolation: "worktree"` on each `Agent`
call so the 5 run in genuinely parallel directories without write-
conflicts. Auto-cleanup if the agent makes no changes; otherwise the
agent returns the worktree path + branch in its result, and the
director can review/merge. This avoids the "create 5 worktrees by
hand" overhead of the prior round.

---

## Agent 1 — WS F: Fundamentals data scoping (research only)

```
description: WS F fundamentals data scoping
subagent_type: general-purpose
prompt:

Research only — no code merged this round. Goal: deliver a
recommendation on which fundamentals data source to integrate for
real point-in-time fundamentals (value / quality / accruals factors),
which would unblock the Path C compounder sleeve currently failing on
synthetic price-derived "factor proxies"
(see /Users/jacksonmurphy/.claude/projects/-Users-jacksonmurphy-Dev-trading-machine-2/memory/project_compounder_synthetic_failed_2026_05_02.md).

Three things to compare, in order of priority:

1. Compustat (S&P CapIQ) — gold standard, license cost, point-in-time
   availability, completeness for value + quality + accruals factor
   families. Note: probably out of budget but document the gap.

2. SimFin — free tier covers ~5000 US tickers, 10+ years history.
   Verify: point-in-time vs. restated, schema completeness, update
   lag, API rate limits. Most likely candidate.

3. EDGAR direct (SEC filings) — free, authoritative, but parsing cost
   is real. Reference https://github.com/datasets/edgar-financials and
   https://github.com/lukerosiak/pysec for parser quality.

Then audit https://github.com/noterminusgit/statarb. The repo claims
20+ alpha strategies + portfolio optimization. For each strategy:
does it depend on fundamentals (and which fields)? Could it drop into
our Foundry as a Feature without rewrite? Which portfolio optimizer
modules in there are usable as drop-in replacements for our
Engine C weighted_sum baseline?

Deliverables (no code merge expected):
- /Users/jacksonmurphy/Dev/trading_machine-2/docs/Measurements/2026-05/ws_f_fundamentals_data_scoping.md
  — comparison matrix + recommendation memo
- /Users/jacksonmurphy/Dev/trading_machine-2/docs/Core/Ideas_Pipeline/path_c_unblock_plan.md
  — concrete prerequisites to enable Path C compounder once data lands

Acceptance: a "do X next" recommendation with named source + named
factor family + named ticker universe scope (S&P 500 PIT panel?
Russell 1000?) that the next round can act on.

Time budget: 1-2 hrs. Read-only on the codebase.
```

---

## Agent 2 — WS E: Foundry batch 3 (5 features)

```
description: WS E Foundry batch 3 — 5 more features
subagent_type: edge-analyst
prompt:

Add 5 more features to /Users/jacksonmurphy/Dev/trading_machine-2/core/feature_foundry/features/
toward the 50-feature target. Cumulative current count is 11 (verified
via `ls`): beta_252d, cot_commercial_net_long, dist_52w_high,
drawdown_60d, ma_cross_50_200, mom_12_1, mom_6_1, realized_vol_60d,
reversal_1m, skew_60d, vol_regime_5_60. Pattern: each feature lives
in its own file named after what it computes; uses the @feature
decorator from ../feature.py with feature_id, tier, horizon, license,
source, description; pulls data via helpers in ../sources/ (local_ohlcv
for OHLCV; cftc_cot for COT data). See dist_52w_high.py as a clean
~30-LOC reference. Tests follow tests/test_feature_foundry.py.

This batch's theme: calendar / event-driven / pairs primitives.
Suggested set, but you can substitute equivalents if any of these are
duplicative or hard to compute:

1. days_to_quarter_end — integer 0..91 trading-day distance to next
   calendar-quarter close. Captures quarter-end portfolio
   rebalancing flow + window-dressing.
2. earnings_proximity_5d — binary or graded, fires when ticker is
   within 5 trading days of next earnings (use the yfinance-cached
   earnings data per `project_finnhub_free_tier_no_historical_2026_04_25`).
3. pair_zscore_60d — for 5 hand-picked sector pairs (e.g. JPM/BAC,
   XOM/CVX, KO/PEP, HD/LOW, V/MA), 60-day rolling z-score of price
   ratio. One feature, output is a per-ticker dict where pair-member
   tickers get z, others get 0.
4. month_of_year_dummy — categorical 1..12 (or 11 dummy columns
   dropping January). Captures seasonality (Sell in May, Santa Rally,
   etc.).
5. vix_term_structure_slope — VIX9D / VIX, or VIX / VIX3M, whichever
   is reliably available in your data. Negative slope = backwardation
   = stress signal.

Each feature MUST:
- Be ≤ 50 LOC (the substrate is supposed to make this trivial)
- Generate adversarial twin via the existing twin generator
- Run through ablation runner with output captured
- Have unit tests in tests/test_feature_foundry.py (or a sibling file
  if test count grows large)

Deliverable: branch `ws-e-third-batch`, 5 commits OR one bundled
commit, model card per feature in cockpit/dashboard_v2 if dashboard
auto-discovers them.

Acceptance:
- 5/5 features under 50 LOC
- Full Foundry test regression passes (existing test_feature_foundry.py
  + test_discovery_regime_features.py + your new ones)
- Twin generation succeeds for all 5
- Cumulative 14/10 — substrate is validated past the original goal

Hard constraints:
- DO NOT modify data/governor/ (the multi-year measurement may still
  be running and uses governor anchor)
- DO NOT run a full backtest (ablation runner only)
- Stay inside core/feature_foundry/ + tests + dashboard tab if needed

Time budget: 2-3 hrs.
```

---

## Agent 3 — WS C: Cross-asset confirmation + HMM smoke

```
description: WS C cross-asset confirmation layer + HMM smoke
subagent_type: regime-analyst
prompt:

Build the cross-asset confirmation layer for HMM regime transitions.
Currently HMM is shipped at /Users/jacksonmurphy/Dev/trading_machine-2/engines/engine_e_regime/hmm_classifier.py
(also see multires_hmm.py from the WS C continuation work) but defaults
off and has no cross-asset confirmation gate. This work
is a prerequisite for the regime-conditional wash-sale gate when
tax-drag work unfreezes
(see project_wash_sale_falsified_multiyear_2026_05_02.md).

Three deliverables:

1. Add HYG/LQD spread, DXY, and VVIX (vol-of-vol) as Foundry features
   in core/feature_foundry/features/. Use yfinance for HYG, LQD, DXY;
   VVIX from CBOE if available, else proxy via realized-vol-of-VIX
   over 30d. Each feature follows the existing batch pattern, ≤ 50 LOC.

2. Add a cross-asset confirmation function in
   engines/engine_e_regime/. Signature roughly:
       confirm_regime_transition(
           hmm_signal: dict,         # current HMM state + transition probs
           cross_asset_state: dict,  # HYG/LQD spread, DXY, VVIX values
       ) -> dict  # {'confirm': bool, 'veto_reason': str|None, 'confidence': float}

   Logic: HMM transition into "stress" regime is CONFIRMED if at least
   2 of 3 cross-asset signals also show stress (HYG/LQD spread widening,
   DXY rallying, VVIX elevated). Single-signal transitions get vetoed
   as likely false positives.

3. Smoke run with hmm_enabled: true AND cross-asset confirmation ON,
   single year (2024) under harness via:
       PYTHONHASHSEED=0 python -m scripts.run_isolated --runs 3 --task q1
   But you'll need to add a 2024 task variant or use `run_multi_year`
   with --years 2024 once it's free. Capture per-rep Sharpe + canon md5
   to verify within-year determinism.

Acceptance:
- 3 cross-asset Foundry features pass tests
- Confirmation function unit-tested (test the AND/OR logic + edge cases
  like 1 of 3 signals)
- Smoke run completes deterministically: 3/3 reps bitwise-identical
  canon md5
- docs/Measurements/2026-05/ws_c_cross_asset_confirmation.md captures: cross-asset
  feature sources + confirmation logic + smoke Sharpe (with HMM on
  vs. baseline HMM-off equivalent)

Hard constraints:
- Default OFF on main: hmm_enabled stays false, cross-asset gate
  function exists but isn't wired into the live decision path until
  user approves (propose-first for the wiring step)
- Branch: ws-c-cross-asset-confirm
- Ensure the Foundation Gate measurement has finished before kicking
  off the smoke backtest — concurrent harness runs race per the
  find_run_id known-issue memory

Time budget: 2-3 hrs.
```

---

## Agent 4 — WS D: Foundry close-out

```
description: WS D Foundry close-out — auto-ablation + adversarial CI gate + 90-day archive
subagent_type: ml-architect
prompt:

Close out Workstream D (Feature Foundry) from ~60% to "complete per
named deliverables" in /Users/jacksonmurphy/Dev/trading_machine-2/docs/State/forward_plan.md.

The three remaining deliverables:

1. AUTO-ABLATION CRON — when a PR / commit touches
   core/feature_foundry/features/*.py, automatically run the ablation
   runner against the changed feature and write the model card.
   IMPORTANT CONTEXT: this repo currently has NO .github/workflows/
   directory and NO .pre-commit-config.yaml. You are creating CI
   infrastructure from scratch. Start with .pre-commit-config.yaml
   (lighter weight, no GitHub Actions runner cost) and add a single
   .github/workflows/feature_ablation.yml that runs the same hook on
   PRs as a backup. Document the choice in the audit doc.

2. ADVERSARIAL FILTER AS HARD CI GATE — the ablation runner already
   generates a permuted twin and computes feature-vs-twin lift. Wire
   it as a fail-the-build condition: feature must beat twin by ≥ 30%
   margin (conservative default; document why). If twin ≥ 70% of
   feature lift, feature is statistical noise and CI rejects.

3. 90-DAY ARCHIVE ENFORCEMENT — features whose last-90d ablation lift
   trends negative get a `status: review_pending` tag in their model
   card and surface on the dashboard tab. NOT auto-deleted (per
   CLAUDE.md "archive don't delete" rule), just flagged for human
   triage. Schema change to model card frontmatter is fine.

Acceptance:
- A test commit that adds a deliberately-bad feature (random noise
  feature) gets REJECTED by the CI gate
- A test commit that adds a real feature passes
- 90-day archive flag mechanism works end-to-end (create a synthetic
  90d-old failing feature, verify it gets `review_pending`)
- docs/Measurements/2026-05/ws_d_foundry_closeout.md lists what is now AUTO vs. what
  still requires human in the loop

Hard constraints:
- Do not auto-delete any feature, even one flagged for review
- Branch: ws-d-closeout
- The CI gate must not block the multi-year-measurement merge if it's
  already in progress — coordinate with the run before triggering CI
- DO NOT run a full backtest (ablation runner only)

Time budget: 3-4 hrs.
```

---

## Agent 5 — WS J: Cross-cutting trio

```
description: WS J cross-cutting trio — decision diary + edge graveyard tagging + leakage detector
subagent_type: quant-dev
prompt:

Three small high-leverage cross-cutters that compound on every future
agent's reporting. All in one branch ws-j-cross-cutting-batch.

1. DECISION DIARY — structured log entries for each significant
   config flip / merge to main. Format: YAML or JSON entries appended
   to data/governor/decision_diary.jsonl with fields:
       timestamp, decision_type (flag_flip|merge|edge_status_change|...),
       what_changed, expected_impact, actual_impact (post-hoc fillable,
       can be null at write time), rationale_link (memory file or PR).
   IMPORTANT CONTEXT: core/observability/ does NOT exist yet — you
   are creating it as a new package. Add helper at
   core/observability/decision_diary.py for callers to append entries. Wire it into ModeController.run_backtest at
   the post-run hook for "this run produced X Sharpe under Y config"
   (low-friction emit, not a big change).

2. EDGE GRAVEYARD STRUCTURED TAGGING — schema change to
   data/governor/edges.yml. Edges with status: failed gain two new
   optional fields:
       failure_reason: free-text but structured (regime_conditional
                       | universe_too_small | data_quality | overfit | other)
       superseded_by: edge_id of replacement edge if any, null if none
   Backward-compatible — existing entries without these fields still
   parse fine. Migrate existing failed edges using their memory-file
   context (momentum_factor_v1: universe_too_small, low_vol_factor_v1:
   regime_conditional, etc. — see project memories).

3. INFO-LEAKAGE DETECTOR SKELETON — function in
   core/observability/leakage_detector.py that takes a feature
   definition (the @feature-decorated function or its source) and
   identifies common lookahead patterns:
   - Uses `close.shift(-N)` for any positive N
   - Uses future-dated index slice
   - Uses pandas resample().last() without explicit closed='left'
   - Uses returns computed from t to t+N
   Wire as ADVISORY (warning, not error) into the Foundry feature
   loader. Each warning includes the line number and why it's
   suspicious.

Acceptance:
- Diary writes successfully on a real backtest run, file is valid JSONL
- 3+ existing failed edges in edges.yml get migrated to the new schema
  with correct failure_reason values
- Leakage detector flags at least one obvious test case (a feature
  that does `df['close'].shift(-1)`) and passes a clean feature
- All three have unit tests
- docs/Measurements/2026-05/ws_j_cross_cutting_trio.md describes each component +
  how it integrates

Hard constraints:
- Schema change to edges.yml is BACKWARD COMPATIBLE — existing tooling
  must still load edges.yml fine
- Decision diary is APPEND-ONLY — never edit prior entries
- Leakage detector is ADVISORY this round, not enforcing (next round
  upgrades to CI gate after we trust it)
- Branch: ws-j-cross-cutting-batch
- DO NOT run a full backtest — synthetic test data only
- DO NOT modify data/governor/ during a measurement run (check first)

Time budget: 2-3 hrs.
```

---

## Dispatch sequencing (when measurement returns PASS)

The 5 are independent code surfaces but two depend on the harness
being free:

- **Free immediately:** Agent 1 (research-only), Agent 2 (no
  backtest), Agent 5 (no backtest, with hard constraint)
- **Wait for measurement to finish:** Agent 3 (smoke run), Agent 4
  (ablation runs may be heavier than expected)

Recommended single-message dispatch: fire 1+2+5 in parallel
immediately after measurement returns PASS, then fire 3+4 in a
second wave.

If measurement returns AMBIGUOUS or FAIL: do not fire any of these.
Switch to a kill-thesis review session — measure where the 2021 vs
2025 gap comes from, decide whether to retain alpha thesis or
restructure.
