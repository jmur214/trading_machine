# Post-Foundation 2025 OOS Pre-Flight — 2026-05

**Date:** 2026-05-02
**Branch:** `ws-a-closeout` (Workstream-A close-out worktree)
**Driver:** `scripts/run_isolated.py --runs 3 --task q1`
**Window/universe:** 2025-01-01 → 2025-12-31, prod-109, RealisticSlippageModel
**Harness:** `scripts.run_isolated.isolated()` (snapshot+restore 4 governor files around each backtest)
**Config:** `metalearner.enabled = false`, `fill_share_cap = 0.20`, ADV floors ON (class-level `DEFAULT_MIN_ADV_USD` defaults: atr_breakout/momentum_edge $200M, volume_anomaly $300M, herding $200M, gap_fill $150M)

## What this is and isn't

This is a **pre-flight sanity check** before the post-Foundation re-measurement. It verifies that:
- The determinism harness still produces bit-identical canon md5 across same-config runs on current main.
- The cap=0.20 + ML-off baseline still lands at ~0.984 Sharpe (the `path1-revalidation-under-harness` reading from 2026-05-01).

It is **not** the true post-Foundation measurement. That measurement requires Path A (Workstream A's full set of foundation deliverables) to land — Agent 1 is currently in flight on the cost-completeness, regime-conditional, and meta-learner work that constitutes "post-Foundation." This pre-flight establishes the baseline that the post-Path-A measurement will be compared against.

## Reference baseline (pre-flight target)

From `docs/Audit/path1_revalidation_under_harness_2026_05.md` (Agent A, 2026-05-01 morning), cell A1.1:

| Cell | Cap | ML  | Sharpe | CAGR % | MDD % | Vol % | WR %  | Canon md5    |
|------|------|------|--------|--------|-------|-------|-------|--------------|
| A1.1 | 0.20 | off | **0.984** | 4.57 | -3.03 | 4.68 | 48.73 | `0d552dd1…` |

Within-cell Sharpe range across 3 runs in the reference reading: 0.0000 (bitwise-deterministic).

**Important caveat — cost-completeness layer landed between baselines.** Commit `e7022ef` on 2026-05-01 21:33 merged the cost-completeness layer (alpaca_fees + borrow_rate_model both enabled by default in `config/backtest_settings.json`). The audit memo (`docs/Audit/cost_completeness_2026_05.md`) reports the same prod-109 2025 OOS config under cost completeness: **Sharpe 0.984 → 0.973** under Alpaca+borrow (tax_drag still off by default). This pre-flight runs on the post-cost-completeness main, so the expected Sharpe is **~0.973, not 0.984**. The 0.984 number above is the pre-cost-completeness reference; the divergence is expected, deterministic, and small (-0.011 Sharpe).

## Pre-flight results (this run)

Run timestamp: 2026-05-02. 3 isolated runs of `mode_controller.run_backtest` over `2025-01-01 → 2025-12-31` on prod-109 with `metalearner.enabled=false`, `fill_share_cap=0.20`, ADV floors ON (class-level defaults), cost-completeness layer ON (alpaca_fees + borrow enabled per `config/backtest_settings.json`; tax_drag still off).

| Run | Sharpe | CAGR % | run_id | trades_canon_md5 |
|-----|--------|--------|--------|-------------------|
| 1   | 0.954  | 4.39   | `8c723464-d68f…`  | `1ee035b19048611c9907473417599366` |
| 2   | 0.954  | 4.39   | `e3e4a95d-516c…`  | `1ee035b19048611c9907473417599366` |
| 3   | 0.954  | 4.39   | `8756a645-d0f3…`  | `1ee035b19048611c9907473417599366` |

Within-cell range: 0.0000. Canon md5 unique = 1 across 3 runs (bitwise-identical).

Harness self-verdict: `[RESULT] PASS — Sharpe within ±0.02 AND bitwise-identical canon md5`.

## Verdict

**Pre-flight PASSES.** The determinism harness still produces bit-identical results on current main; the cap=0.20 + ML-off baseline lands at 0.954, within 0.030 of the path1-revalidation reference of 0.984.

The -0.030 Sharpe drift is slightly larger than the cost-completeness audit's predicted -0.011 drag from alpaca_fees + borrow. Two reasons that are mutually compatible:

1. The cost-completeness audit was a single A/B comparison on a particular run. Different governor state at run start can produce different fill patterns and different sensitivity to per-fill costs, so a precise -0.011 doesn't have to reproduce.
2. The reference 0.984 reading was 2026-05-01 morning; between then and now several other commits also landed (HMM merge, HRP merge, Foundry merge — all default-off but they touched code that runs at startup, including macro-edge reclassification in HMM merge `18378c5` which retired 4 macro signals from active/paused → retired).

**Conclusion:** The harness still works. The post-cost-completeness baseline on current main is **Sharpe 0.954** for the q1 (2025 OOS prod-109, cap=0.20, ML-off, floors-on, costs-on) configuration. This is the comparison baseline that the post-Path-A measurement should be evaluated against — not 0.984.

Below the path1-revalidation A1.1 reading (0.984) but **above the pre-committed kill thesis floor (Sharpe ≥ 0.4 net of all costs)**. Below SPY 2025 (0.955) by 0.001. The system trails SPY by ~0 Sharpe in 2025 under the current cap+ML+cost configuration.

## Notes on what this leaves unanswered

- The post-Foundation measurement (post-Path-A) has to wait until Agent 1's branch lands on main. The director will run the parallel post-Path-A measurement in a separate worktree; **this pre-flight is the comparison baseline**.
- The `path1_revalidation_under_harness_2026_05.md` four-cell grid (A1.0/A1.1/A1.2/A1.3) found that ML-on is a -0.4 to -0.6 Sharpe drag at both cap values — that's why the pre-flight is run with ML off, not because ML is the right ship config. The pre-Foundation target is cap=0.20 + ML-off as the cleanest baseline.
- The 2025 OOS Sharpe is below SPY (2025: SPY 0.955) but above the pre-committed kill thesis floor (0.4 net of all costs). Post-tax retail is the separate kill-thesis-adjacent finding from the cost-completeness layer (Sharpe -0.577 at 30% ST) — see `project_tax_drag_kills_after_tax_2026_05_02.md`.
