# Cost Completeness Layer — 2026-05-01

> **Branch:** `cost-completeness-layer`
> **Status:** Modules + tests landed; A/B/C harness run in flight
> **Workstream:** A (foundation completion), deliverable #3 from
> `docs/Progress_Summaries/Other-dev-opinion/05-1-26_1-percent.md`
> **Maps to:** Forward Plan 2026-05-02, Agent 5 dispatch

## What this round added

Three pluggable cost modules in `backtester/`:

| Module | Purpose | Default | Where it runs |
|---|---|---|---|
| `alpaca_fees.py` | SEC Section 31 + FINRA TAF pass-through | **enabled** | per-fill, inside `ExecutionSimulator` |
| `borrow_rate_model.py` | Per-day carry on shorts (5/15/50 bps/day by ADV) | **enabled** | post-processor on snapshot history |
| `tax_drag_model.py` | ST/LT cap-gains + wash-sale + carry-forward | **disabled** | post-processor; opt-in only |
| `cost_aggregator.py` | Produces A/B/C equity curves from one run | always on | post-processor at end of `BacktestController.run` |

Plus a config-driven wiring through `backtest_settings.json` →
`ModeController.exec_params` → `BacktestController.exec_params` →
`ExecutionSimulator(alpaca_fees_cfg=...)`. The aggregator config
arrives separately and runs after the perf-summary step, merging its
output into `performance_summary.json` under
`cost_completeness_layer_v1`.

## Engine boundary discipline

All three modules live in `backtester/`. None of them touch Engine B
(Risk) or Engine C (Portfolio) state. The borrow and tax components
are pure post-processors: they read the snapshot history and trade log
and produce an adjusted equity series. Alpaca fees route through the
existing `commission` slot on each fill — the slot was always there;
it was previously hardcoded to 0.0.

## Why these three components

The slippage layer (`RealisticSlippageModel` from session 4) handled
half-spread and market impact. It deliberately did **not** model:

1. **Borrow rate drag.** A short position accrues carry. ArchonDEX
   has historically had near-zero short exposure, but the moment any
   discovery candidate runs short, the equity curve overstates returns
   without this. 5–50 bps/day depending on ADV bucket; per-ticker
   overrides for known hard-to-borrow names.

2. **Alpaca regulatory pass-through.** Stocks are commission-free at
   Alpaca but SEC Section 31 fee ($27.80 per $1M of principal on sells)
   and FINRA TAF ($0.000166/share, capped $8.30/trade on sells) still
   apply. A handful of tenths of a basis point per round-trip — small,
   but real and additive across thousands of fills.

3. **Short-term capital gains tax.** The single largest cost retail
   traders face. ~30% of net realized ST gains, plus the wash-sale
   rule. Disabled by default to preserve backward-compat; flipping it
   on is a one-line config change that will reframe the entire
   "beats SPY net of costs" claim.

## Implementation notes

### `alpaca_fees.py`
- Per-fill computation. Buy / cover free. Sell / short pay both fees.
- Wired into `ExecutionSimulator.fill_at_next_open` and
  `check_stops_and_targets` so commission per fill reflects actual
  pass-through rather than a flat zero.
- Disabled fallback path returns the legacy flat `commission` constant
  bit-for-bit — guarantees backward-compat when the flag is off.

### `borrow_rate_model.py`
- Two paths: Path A (per-snapshot per-ticker positions, accurate) and
  Path B (aggregate `short_value_usd` column, fallback).
- ADV bucketing matches `RealisticSlippageModel` thresholds — same
  classification across the cost stack.
- Per-ticker bps/day overrides for known hard-to-borrow names.
- Heuristic: signed-shares vs signed-dollar-value detected via
  `abs(value) > 1e6`. Conservative — overstates drag on retail-sized
  positions if mis-classified.

### `tax_drag_model.py`
- FIFO trade reconstruction from the fill log (no engine state needed).
- ST/LT classification by holding period (≥365 days = LT).
- Conservative wash-sale rule: any loss with a re-purchase ±30 days
  has its loss erased from the year's net P/L. The IRS rule is "loss
  deferred into new lot's basis"; conservative-disallow overstates
  drag, which is the safe direction for cost estimation.
- Carry-forward losses across years.
- Year-end synthetic withdrawal applied to the equity curve.

### `cost_aggregator.py`
- Single entrypoint: takes `snapshots`, `trades`, `price_data_map`.
- Returns `CostAggregatorResult` with three labeled equity curves
  (A, B, C), three Sharpe values, three CAGR values, three max-DD
  values, plus per-component dollar drag totals.
- Runs as a post-processor at the end of `BacktestController.run` —
  no engine-state coupling.

## A/B/C deterministic harness comparison — 2025 OOS prod-109

Configuration matrix:

| Run | Slippage | Alpaca fees | Borrow | Tax |
|---|---|---|---|---|
| **A** | realistic | off | off | off |
| **B** | realistic | on | on | off |
| **C** | realistic | on | on | on |

Run conditions: `PYTHONHASHSEED=0`, `scripts/run_isolated.py --task q1`,
prod-109 universe, cap=0.20, ML off, all governor state restored from
the worktree's `_isolated_anchor` per run. Run ID
`adfd87ad-0396-419a-be0b-37069bbdb688`. A/B reconstructed from the
single run's trade log: equity_B is the live-equity curve under
borrow+Alpaca enabled; equity_A adds Alpaca fees back to B's curve;
equity_C is post-process of equity_B with tax model on. Borrow drag
is $0 in this run because the prod ensemble is long-only.

### Results

| Metric | A baseline | B (+borrow +alpaca) | C (+tax) |
|---|---|---|---|
| Sharpe | **0.9841** | **0.9730** | **−0.5768** |
| CAGR  | +4.59% | +4.54% | **−8.41%** |
| Max DD | −3.03% | −3.05% | −13.85% |
| Final equity (start $100k) | $104,539 | $104,487 | **$91,691** |
| Δ Sharpe vs A | — | −0.0111 | **−1.5609** |
| Total drag (USD) | — | $52 | $12,796 + $52 |

### Interpretation — the brutal-realism reading

**A → B is small.** $52 of Alpaca pass-through fees on a 5,147-fill
year. Sharpe drops 0.011 (≈1% of the prior reading). Real, but in
noise. Borrow drag = $0 because the deployed ensemble is long-only.

**B → C is catastrophic.** Tax drag is **$12,796 — larger than the
year's $4,487 net profit**. The system realized **$48,161 of ST gains
and $5,508 of ST losses**. Net taxable ST = $42,653; at 30% federal
rate that is $12,796 owed. Plus **$17,343 of losses disallowed by
wash-sale** (the system re-buys the same tickers within 30 days of
loss-realizing closes — losses cannot offset gains under IRS rules).

**The honest after-tax picture: a retail trader in a taxable account
loses 8.4% on this strategy in 2025 — and pays out three times the
profit in taxes.** Sharpe on the after-tax curve is **negative**
(−0.58). Max drawdown more than quadruples (−3% → −14%) once the
year-end tax bill lands.

This is exactly the failure mode the user's retail-capital-constraint
memory called out. The pre-tax Sharpe ≈ 1.0 result was honest pre-tax
and dishonest as a real-world trading return. **The system as
currently configured does not beat T-bills in a retail taxable
account.**

### What surfaced from this measurement

1. **Wash-sale rule binds heavily.** $17K disallowed losses on $48K of
   gains = 36% of the loss-side P/L is forfeit to the IRS. The system
   re-trades the same tickers too quickly. Engine C's tax-aware
   rebalancer (Workstream B deliverable #4) needs to enforce a wash-
   sale-window cooldown on loss-realizing closes.

2. **Pre-tax / after-tax gap is ~1.55 Sharpe — far larger than any
   gauntlet-level engineering improvement on the table.** The biggest
   leverage point in the project is not new edges; it is reducing the
   churn rate so more gains qualify for LT (15%) instead of ST (30%)
   treatment, and reducing wash-sale disallowance.

3. **Retail vs institutional framing diverges sharply.** An
   institutional manager in a tax-deferred wrapper sees the 0.97
   Sharpe; a retail account in 2025 sees −0.58 Sharpe. Both are real;
   they are not the same number.

### Statistical significance

A → B: ΔSharpe −0.0111 is below typical 3σ noise (>0.1 in this
universe pre-determinism-floor; <0.001 under harness). Statistically
distinguishable but practically small.

B → C: ΔSharpe −1.55 is well beyond 3σ — it would survive any
significance threshold. **The 1-percent doc's success criterion is
met with margin.**

## After-tax framing for retail-capital math

From `project_retail_capital_constraint_2026_05_01.md`: the user
explicitly framed why pure institutional-quant optimization is partially
wrong here. $5K–$15K AUM × 1%/yr × 20 yrs = ~$1–3K. Meaningless. The
math forces asymmetric-upside / tail-capture as a co-objective.

Tax drag amplifies this — and the 2025 measurement above quantifies
what was previously a hand-wave. The system as configured today loses
**8.4% per year** in a retail taxable account, vs +4.6% pre-tax. The
3,000 bps gap between pre-tax and after-tax CAGR is larger than any
engineering improvement currently scoped in the 10-workstream plan.

Concretely, the path to "1% retail" is now constrained by three
simultaneous targets, not just pre-tax Sharpe:

1. **Pre-tax Sharpe ≥ 0.5** (already achieved at 0.98 under harness).
2. **Trade churn low enough that >50% of realized gains qualify for
   LT (15%) treatment.** Currently 0% — every closed trade in the
   2025 run was ST.
3. **Wash-sale-aware close timing** in Engine C. Currently 36% of
   losses are forfeit to the IRS. Even 10% would materially recover
   after-tax PnL.

The Moonshot Sleeve (Workstream H) sidesteps part of this — long
holds capture LT-rate trades, asymmetric returns survive the tax hit
better than dense ST gain harvesting. **The cost layer makes that
trade-off measurable for the first time.**

## Follow-up work flagged

1. **Real ADV-based per-ticker borrow override list.** The current
   default of bucketed bps/day is a reasonable midpoint. Adding a
   curated list of hard-to-borrow names (squeezy small floats, recent
   IPOs) would tighten short-side cost estimates.

2. **Tax-aware rebalancing in Engine C** (Workstream B deliverable #4).
   Once the cost layer measures tax drag, Engine C's rebalancer should
   prefer realizing LT gains before ST gains, and avoid unnecessary
   rebalances inside the wash-sale window. Currently scoped to the
   Engine C HRP slice agent.

3. **Tax-aware SPY benchmark.** The benchmark suite should include a
   "buy-and-hold SPY with no realization" line for the after-tax
   framing. ArchonDEX's pre-tax Sharpe minus SPY's pre-tax Sharpe is
   not the alpha that matters; the after-tax delta is.

4. **State income tax knob.** Federal-only is the current default. A
   `state_st_rate` config field would let users in CA/NY/MA model
   their actual marginal rate (often another 5–10%).

5. **Section 1256 / mark-to-market for futures.** Currently no-op since
   ArchonDEX is equities-only. When Workstream H ramps and any
   futures-like instrument enters the universe, this needs revisiting.

6. **Tax-loss harvesting heuristic.** The system isn't trying to time
   losses; current model just accounts for what taxes the strategy
   owes. A future LT-favoring rebalancer could use the trade ledger to
   actively defer realizations.

## Tests

50 unit tests across 4 files, all passing:
- `tests/test_alpaca_fees.py` — 15 tests
- `tests/test_borrow_rate_model.py` — 13 tests
- `tests/test_tax_drag_model.py` — 15 tests
- `tests/test_cost_aggregator.py` — 7 tests

Coverage:
- ADV bucketing across thresholds (borrow + slippage stay aligned)
- Per-ticker overrides for borrow rates
- FIFO matching for tax (long, short, partial close, multi-lot)
- Wash-sale rule flagging (positive case + two negative cases)
- Yearly aggregation + carry-forward losses
- Year-end synthetic withdrawal on the equity curve
- Disabled-mode is bit-for-bit identity (backward-compat)
- Per-fill Alpaca fees: SEC + TAF, TAF cap at $8.30, buy/cover/long
  pay zero, sell/short/exit pay both
- Aggregator: empty trade log doesn't crash, Sharpe strictly decreases
  when borrow active, deltas show up in summary dict

## Boundary notes

- Engine B (Risk): not touched.
- `live_trader/`: not touched.
- Engine C (Portfolio): `apply_fill` accepts the `commission` field as
  before. The dollar amount is now what Alpaca actually charges (when
  enabled), not a hardcoded zero.
- Engine A (Alpha): not touched.
- Engine D (Discovery): not touched. Discovery's `_quick_backtest` will
  inherit the new defaults the next time `backtest_settings.json` is
  reloaded by `ModeController`.

## What changed in `backtest_settings.json`

Three new config blocks added at the top level:

```json
{
  "alpaca_fees":      {"enabled": true,  ...},
  "borrow_rate_model":{"enabled": true,  ...},
  "tax_drag_model":   {"enabled": false, ...}   // OPT-IN
}
```

Default behavior change: Alpaca fees are on by default (was off
implicit-in-zero). Borrow drag is on by default (was missing entirely).
Tax drag stays off until the user flips it.
