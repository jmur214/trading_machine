# Spec — Substrate-Honest Re-Measurement (post-regression-fix, post-CSV-closure)

**Date drafted:** 2026-05-08
**Status:** SPEC for approval. No backtest has been run yet.
**Will be executed by:** Agent A or B once approved (8-12hr task budget).
**Output:** `docs/Measurements/2026-05/multi_year_substrate_honest_2026_05_08.{md,json}`

---

## Why now

Three things changed this week that invalidate every prior multi-year Sharpe number:

1. **Zero-trade regression FIXED** (commit `4b7a14e`, this session). Every backtest from 2026-05-07 01:39 through 2026-05-08 produced 0 trades because `EarningsVolEdge` raised a tz-comparison error caught silently by `backtest_controller.py:389`. Sharpes since were all 0.0 / canon-md5 of empty file.
2. **Missing-CSV gap CLOSED** (commit `d5af02e`, the other session). 48 of 48 legitimate 2021-2025 delisted S&P 500 names sourced via Alpaca v2. Prior universe-aware multi-year measurement (`project_universe_aware_collapses_2026_05_09`, mean Sharpe 0.5074) was an explicit upper bound under the missing names. Now actually measurable.
3. **Two new opt-in mechanisms shipped**: F11 journal-mode (`apply_journal_at_end=True`) routes governance decisions to a journal instead of mutating `edges.yml` mid-run; HMM Variant C wire (`feature_set="minimal_c"`) makes the LEADING-at-20d/60d HMM signal modulate Engine B's `risk_scalar`. Both default OFF — never measured ON.

The headline question this measurement answers: **what's the substrate-honest baseline TODAY, and how much does the lifecycle pruning + HMM wire we recommend this week change it?**

---

## Headline parameter spec

| Axis | Choice | Rationale |
|---|---|---|
| Universe | F6 historical S&P 500 union (UniverseLoader) | "Substrate-honest" requires names that existed at each historical date, not a current-mega-cap snapshot. Static-115 reproduces the artifact we're trying to escape. |
| Missing-CSV closure | INCLUDED | Per d5af02e: 48/48 legitimate delisted 2021-2025 names now on disk. Excluding them re-creates the same upper-bound caveat the prior 0.5074 measurement carried. |
| Window | 2021-01-01 → 2025-12-31 | Direct comparability to both prior baselines (1.296 static; 0.5074 universe-aware). 5 years × 5 yearly runs (each run is one calendar year, anchor-restored between them). |
| Reps per arm | 3 (deterministic harness pattern) | Confirms reproducibility (canon-md5 unique = 1/3) AND surfaces any residual non-determinism from the CSV closure or the new code paths. ~2.5x runtime cost; worth it. |
| Cost layer | realistic slippage ON, wash-sale OFF, lt-hold OFF, tax drag ON (informational only) | Defaults match prior baseline measurements. Wash-sale was falsified multi-year per `wash_sale_falsified_multiyear_2026_05_02`. Tax drag is a separate post-processing layer; doesn't affect pre-tax headline. |
| Lifecycle mode | `apply_journal_at_end=True` (journal-mode) | F11 Phase 2 invariant: edges.yml NOT mutated during run. Decisions journal to `data/governor/lifecycle_journal.jsonl`. After measurement, user reviews via `journal_apply --dry-run` and decides whether to apply. |
| Determinism harness | YES — `scripts/run_isolated.py --runs 3 --task multi_year` for each arm | Already-shipped pattern. Each rep restores anchor before run; mutable globals (PANEL_CACHE, etc.) reset between reps. |
| Discovery | OFF (`discover=False`) | Pure existing-edge ensemble measurement. Discovery would add ~30-60min/cycle and isn't part of the question. |

---

## Two-arm design

The measurement runs **two arms** so we can isolate "substrate-honest baseline today" from "what we'd deploy with this week's recommendations applied".

### Arm 1: Current production state (substrate-honest baseline)

Measures: what does the system do today, on a substrate-honest universe, post-CSV-closure, post-regression-fix?

| Setting | Value |
|---|---|
| Active edges | 6 (current `edges.yml` actives): `gap_fill_v1`, `volume_anomaly_v1`, `value_earnings_yield_v1`, `value_book_to_market_v1`, `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1` |
| HMM | OFF (`hmm_enabled=False`, `feature_set="legacy"`) |
| Lifecycle gates | enabled (default), but journal-mode (no edges.yml mutation) |
| Vol-target clamp | default (asymmetric clamp shipped this week is regime-aware; in the absence of stressed/crisis advisory, falls back to legacy 2.0 ceiling — so neutral here unless regime fires) |
| Drawdown kill switch | OFF (default) |
| Sleeves | none (trend / moonshot not wired into `PortfolioEngine.allocate`) |

### Arm 2: Recommended deployment state

Measures: what does the system do if we apply the two recommendations from this week's work — lifecycle-prune the 2 net-drag edges, AND turn on the HMM Variant C wire?

| Setting | Value |
|---|---|
| Active edges | 4 (drop the 2 net-drags found in `per_edge_contribution_2026_05_08.md`): `gap_fill_v1`, `volume_anomaly_v1`, `value_book_to_market_v1`, `accruals_inv_sloan_v1`. **Drop:** `value_earnings_yield_v1` (−$1,192 drag), `accruals_inv_asset_growth_v1` (−$111 drag). |
| HMM | **ON** (`hmm_enabled=True`, `feature_set="minimal_c"`, `model_path="engines/engine_e_regime/models/hmm_minimal_C_v1.pkl"`) |
| Lifecycle gates | enabled, journal-mode |
| Vol-target clamp | default (same as Arm 1) |
| Drawdown kill switch | OFF (default) |
| Sleeves | none |

**Edge-pruning mechanism for Arm 2:** the spec uses `exact_edge_ids` parameter on `mode_controller.run_backtest` to restrict to the 4-edge set without mutating `edges.yml`. (No manual edits to the registry — per CLAUDE.md.)

---

## Reporting

### Per-arm headline metrics

Both arms report:
- Mean Sharpe across 5 years (with per-year breakdown)
- Mean Sortino, mean MDD, mean win-rate
- Bootstrap 95% CI on headline Sharpe AND Sortino (1000 iterations, block-bootstrap, the helper I shipped — `MetricsEngine.bootstrap_distribution`)
- 3-rep determinism: list of canon md5s; PASS if 1 unique, FAIL if >1
- Per-edge realized PnL contribution (re-running the analysis from `per_edge_contribution.py` on this run's trade logs)
- Inter-edge correlation matrix on the active set (re-running `inter_edge_correlation.py`)

### Cross-arm comparison

| Metric | Arm 1 | Arm 2 | Δ (A2 − A1) |
|---|---|---|---|
| Mean Sharpe | | | |
| Mean Sortino | | | |
| Mean MDD | | | |
| Mean win-rate | | | |
| Bootstrap Sharpe CI | | | |

### Important caveat: $-PnL drag ≠ Sharpe-net drag

The 2 edges dropped in Arm 2 (`value_earnings_yield_v1`, `accruals_inv_asset_growth_v1`) were dropped on **net realized $-PnL** per `per_edge_contribution_2026_05_08.md`. That's a cash metric, not a risk-adjusted one. There is a non-trivial chance these edges contribute diversification benefit (low/negative correlation with the other 4) that *helps* portfolio Sharpe even when their standalone PnL is negative. If Arm 2 − Arm 1 < 0, that's the most likely explanation — be ready to interpret a "dropping the cash drags made things worse" result as evidence the diversification was load-bearing.

The follow-up 2x2 decomposition below isolates this question.

### Verdict framing (NOT pre-committed kill thresholds; decision points)

The measurement isn't a pass/fail gauntlet — it's a decision-informer. The verdict bucket interprets the result:

- **Arm 1 mean Sharpe ≥ 1.0**: substrate-honest baseline is healthy at current 6-active config. The prior 0.5074 was the missing-CSV-gap upper bound; the closure recovered the gap.
- **Arm 1 mean Sharpe in [0.5, 1.0]**: substrate-honest baseline is moderate. Lifecycle pruning + HMM wire (Arm 2) become more important.
- **Arm 1 mean Sharpe < 0.5**: prior universe-aware result was real, not a missing-CSV artifact. Closure didn't recover the headline. Substrate concerns stand.
- **Arm 2 − Arm 1 Sharpe ≥ +0.2**: the recommendations are worth deploying — but FIRST run the contingent 2x2 decomposition below to attribute the lift cleanly. Don't deploy on a bundled signal.
- **Arm 2 − Arm 1 Sharpe near zero**: pruning + HMM didn't materially help. Either the 2 dropped edges were less of a drag than per-edge $-PnL implied, or HMM modulation produced near-baseline behavior. No recommendation to flip flags.
- **Arm 2 − Arm 1 Sharpe < 0**: most likely the diversification benefit of the 2 dropped edges was load-bearing. The 2x2 decomposition isolates this. Don't deploy.

### Contingent: 2x2 decomposition follow-up

If Arm 2 − Arm 1 Sharpe ≥ +0.2 (lift threshold) OR < 0 (regression threshold), pre-commit a follow-up 2x2 dispatch to isolate which change drove the result:

| Cell | Edges | HMM |
|---|---|---|
| A | 6 | OFF |
| B | 4 | OFF |
| C | 6 | ON (minimal_c) |
| D | 4 | ON (minimal_c) |

Arm 1 = Cell A; Arm 2 = Cell D. Cells B and C run only on the contingent. Adds ~7 hr if triggered. The deployment recommendation (which flag to flip, in which order) requires the 2x2 attribution; bundled lift is not a deployment signal.

---

## Hard constraints for the executing agent

- DO NOT modify Engine B (Risk) or `live_trader/` code paths
- DO NOT manually edit `data/governor/edges.yml` or `edge_weights.json` (use `exact_edge_ids` and the `apply_journal_at_end` flag)
- DO NOT push to main; push to a feature branch (`feature/substrate-honest-remeasurement`); director merges
- USE the deterministic harness — don't run a one-off invocation that bypasses isolation
- After Arm 2 completes, leave the journal at `data/governor/lifecycle_journal.jsonl` for user review; do NOT call `journal_apply` (that's a director decision)

---

## Estimated runtime

| Step | Wall time |
|---|---|
| Arm 1, 3 reps × 5 yearly runs | ~3-5 hr |
| Arm 2, 3 reps × 5 yearly runs | ~3-5 hr |
| Per-edge attribution + bootstrap CIs + correlation matrix | ~30 min |
| Audit doc + verdict bucket assignment | ~30 min |
| **Total** | **~7-11 hr** |

Well within agent-dispatch range. Should be one continuous session for the agent.

---

## What this spec does NOT cover

- **Discovery cycle.** Discovery is OFF for this measurement. Whether to also re-run discovery on the substrate-honest universe is a separate question (more candidates → more curve-fitting risk; needs its own Gate 8 / DSR design).
- **2026-Q1 OOS extension.** Window is fixed at 2021-2025 for direct comparability. Adding 2026-Q1 is a follow-up if Q1 data is on disk and the user wants fresh-OOS confirmation.
- **Sleeve verdicts.** Trend + Moonshot sleeve Phase 0 verdicts already shipped (both FAIL). They're not measured here.
- **Engine B drawdown kill switch.** Shipped INERT this week. Measuring it ON is a separate spec — needs threshold sweeps.

---

## Spec checklist — APPROVED 2026-05-08 by user via dev review

All 4 decisions confirmed:

1. ✅ **Universe**: F6 historical + closure-included
2. ✅ **Two-arm design**: current 6 + HMM-OFF vs deployable 4 + HMM-ON, with contingent 2x2 follow-up if |Δ| ≥ 0.2
3. ✅ **Cost-layer defaults**: slippage on, wash-sale off, lt-hold off, tax informational
4. ✅ **Agent**: either; pick whichever is free first

## Sequencing decision (added 2026-05-08 per second dev review)

**Run yfinance tz-bug audit FIRST**, BEFORE the substrate measurement. Reasoning: any zero-trade-class bug found by the audit would silently contaminate the substrate measurement. 1-2 hr audit delay is rounding error on 7-11 hr substrate runtime.

Audit covers: `pead_v1`, `pead_short_v1`, `pead_predrift_v1`, `news_sentiment_edge`. Same pattern as the 2026-05-08 `earnings_vol_v1` bug.

## Parallel context dispatches (after audit, alongside substrate)

Per the second dev review, two additional measurements interact with how Arm 1/Arm 2 results should be interpreted:

- **C-collapses-1.5**: concentration-equivalent capital test — answers "is there per-name signal at all, or is everything concentration accident?"
- **C-collapses-1.25**: factor decomp on `volume_anomaly_v1` + `herding_v1` under substrate-honest universe — answers "do the t>4 alphas survive at t>2 on unbiased substrate?"

Either or both can run on the second agent in parallel with the substrate measurement (substrate-independent; no conflict).
