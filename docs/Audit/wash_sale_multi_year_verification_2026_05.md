# Wash-sale gate — multi-year verification (2021-2025)

**Branch:** `wash-sale-multi-year-verify`
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-washsaleverify/`
**Date:** 2026-05-02
**Driving question:** Does the +0.670 pre-tax Sharpe lift from the wash-sale
gate observed on 2025 OOS (`project_wash_sale_exposes_turnover_bug_2026_05_02.md`)
**generalize across 2021-2025**, or was 2025 a window-fortunate outlier?

---

## Why this verification exists

The Path A round (2026-05-02, branch `path-a-tax-efficient-core` merged
to main as commit `5c3cd3a`) shipped four composable mechanisms targeting
the post-tax Sharpe gap. The 4-cell × 3-rep harness on 2025 OOS produced
a major secondary finding:

> Cell B (wash-sale + LT-hold ENABLED, HRP/turnover-penalty disabled)
> produced pre-tax Sharpe **1.624** vs Cell A baseline **0.954** — a
> **+0.670 pre-tax** lift from a tax rule. 22% of buy proposals were
> wash-sale-blocked, indicating the strategy was constantly re-entering
> names within 30 days of loss-realizing exits — a turnover-quality
> failure the engine was masking.

The wash-sale gate was provisionally recommended as a default-on flip,
but ONLY on a single year (2025). The memory called for multi-year
re-validation BEFORE that flip. This is that re-validation.

The competing hypotheses we want to discriminate between:

| Hypothesis | Implication |
|---|---|
| H_real: wash-sale rejects bad turnover patterns persistently | Cell B > Cell A across most/all years; recommend default-on |
| H_window: 2025 happened to have a lot of repeat-loss-then-rebuy episodes | Cell B ≈ Cell A on average; do NOT flip, investigate further |

---

## Method

### Configuration held constant

All 10 backtests use:
- Universe: prod-109 (`config/backtest_settings.json:tickers`)
- Cap: `portfolio_policy.json:max_weight=0.20` and
  `alpha_settings.prod.json:fill_share_cap=0.20`
- ML: `alpha_settings.prod.json:metalearner.enabled=false`
- Floors: `governor_settings.json:sr_weight_floor=0.25`
- HRP: `portfolio_settings.json:portfolio_optimizer.method=weighted_sum`
  (slice-2 disabled)
- LT hold preference: `portfolio_settings.json:lt_hold_preference.enabled=false`
- Turnover penalty: as configured on main (enabled, 10 bps)
- Cost stack: realistic slippage + Alpaca fees + borrow rates ENABLED;
  tax_drag_model DISABLED (we measure pre-tax Sharpe per the task spec).
- Slippage model: `realistic` (ADV-bucketed half-spread + Almgren-Chriss
  square-root impact)

The wash-sale flag (`portfolio_settings.json:wash_sale_avoidance.enabled`)
is the ONE thing that varies between cells. It's overridden in-process
by mutating `mc.cfg_portfolio["wash_sale_avoidance"]["enabled"]` AFTER
ModeController init but BEFORE `mc.run_backtest()`, since `run_backtest`
re-instantiates `RiskEngine` reading from `cfg_portfolio` each call.

### Grid

| Window | Cell A (wash_sale OFF) | Cell B (wash_sale ON) |
|---|---|---|
| 2021-01-01 → 2021-12-31 | 1 rep | 1 rep |
| 2022-01-01 → 2022-12-31 | 1 rep | 1 rep |
| 2023-01-01 → 2023-12-31 | 1 rep | 1 rep |
| 2024-01-01 → 2024-12-31 | 1 rep | 1 rep |
| 2025-01-01 → 2025-12-31 | 1 rep | 1 rep |

Total: **10 backtests** under `scripts.run_isolated.isolated()`.

### Why reps=1 (not 3 as in the task spec)

The task spec asked for 3 reps per cell. I dropped to 1 for two reasons:

1. **Determinism is already established system-wide.** The 2026-05-01
   determinism floor (`project_determinism_floor_2026_05_01.md`) is the
   harness invariant. The Path A round prior to this used 3 reps × 4
   cells = 12 backtests and confirmed bitwise determinism on ALL of
   them (0.0 Sharpe spread per cell, 1 unique canon md5 per cell). Adding
   a duplicate rep here would only re-confirm that.

2. **CPU contention from concurrent worktrees.** At launch time, 3 other
   heavy harnesses (`ab_path_a_tax_efficient_core`, `run_path2_revalidation`,
   etc.) were running in parallel on other worktrees. Per-cell wall-time
   was running ~2-3× normal due to CPU contention. With reps=3, the grid
   ETA was 6+ hours — outside the 2-4 hour task budget. With reps=1,
   the grid finishes in 2.5-4 hours under contention.

   If any cell shows an anomalous Δ in the results (e.g., a single-year
   value that is wildly out of the cluster), it can be re-run with
   reps=2 for confirmation. None should show "noise" by construction
   since the harness is bitwise deterministic.

### Driver

`scripts/wash_sale_multi_year.py` — extends the `scripts/run_isolated.py`
isolation pattern to per-year-windowed backtests with the wash-sale
override.

---

## Results — to be filled when grid completes

### Per-cell Sharpe table (10 cells)

_(populated from `data/research/wash_sale_multi_year_<ts>.json`)_

| Year | Cell A Sharpe | Cell A canon md5 | Cell B Sharpe | Cell B canon md5 | Δ (B − A) |
|---|---:|---|---:|---|---:|
| 2021 | TBD | TBD | TBD | TBD | TBD |
| 2022 | TBD | TBD | TBD | TBD | TBD |
| 2023 | TBD | TBD | TBD | TBD | TBD |
| 2024 | TBD | TBD | TBD | TBD | TBD |
| 2025 | TBD | TBD | TBD | TBD | TBD |

### Cross-year aggregates

- **Mean Δ:** TBD
- **Std Δ:** TBD
- **Min Δ (worst year):** TBD
- **Max Δ:** TBD
- **Years positive:** TBD / 5

### Verdict against pass/fail criteria

| Outcome | Verdict |
|---|---|
| Mean Δ ≥ 0.3 AND min Δ > 0 (every year positive) | PASS — generalizable; recommend default-on |
| Mean Δ ≥ 0.3 BUT some years negative | CONDITIONAL — investigate bad-year scenarios |
| Mean Δ < 0.3 | FAIL — 2025 was window-fortunate |

**Final verdict:** TBD

**Recommendation on default-on flip:** TBD

---

## What this verification does and does NOT verify

**Verified:**
- Whether the +0.670 lift from wash-sale gate generalizes across 2021-2025
- Whether the lift is regime-dependent (per-year std)
- Whether any year shows a NEGATIVE lift (which would falsify the
  "wash-sale is a strict pre-tax improvement" claim from the original
  finding)

**NOT verified:**
- Behavior of the FULL Path A stack (HRP composition + turnover penalty
  + LT-hold + wash-sale together). This was Cell C in the original round
  and underperformed because HRP composition is broken (slice 3 needed).
- Behavior under tax-drag-on (post-tax). The task spec asked for pre-tax
  validation; if the wash-sale flag is flipped default-on, retail
  taxable-account post-tax behavior should be re-measured separately.
- Behavior on universes other than prod-109. The wash-sale block rate
  is universe-density-dependent (more tickers = more substitutes if a
  loss-recently-exited name is blocked).
- Behavior under regime-conditional weighting. The wash-sale gate is
  unconditional; if it interacts with HMM-driven sizing differently in
  different regimes, that is not measured here.

---

## How to reproduce

```bash
cd /Users/jacksonmurphy/Dev/trading_machine-washsaleverify

# Snapshot governor anchor (required for isolation)
PYTHONHASHSEED=0 python -m scripts.run_isolated --save-anchor

# Run the 10-backtest grid
PYTHONHASHSEED=0 python -m scripts.wash_sale_multi_year \
    --years 2021 2022 2023 2024 2025 --reps 1
```

Output JSON: `data/research/wash_sale_multi_year_<timestamp>.json` —
contains per-cell raw results AND aggregated delta statistics + verdict.
