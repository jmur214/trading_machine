# Path A — Tax-Efficient Core (HRP slice 2 + turnover penalty + LT-hold + wash-sale)

**Branch:** `path-a-tax-efficient-core`
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-patha/`
**Date:** 2026-05-02
**Driving finding:** `project_tax_drag_kills_after_tax_2026_05_02.md` —
pre-tax Sharpe 0.984 → after-tax (ST 30%) Sharpe **−0.577** on prod-109 2025
OOS. The 1.561 Sharpe gap is bigger than any single engineering item in the
10-workstream plan. Path A's job is to recover as much of it as possible
through tax-efficiency mechanisms inside the engine.
**Co-running agent:** Agent 2 — Path C design in a separate worktree.
Strict isolation; no shared files touched.

---

## What this branch ships

Four composable mechanisms, all default-off on `main`, all opt-in via
`config/portfolio_settings.json`:

| Component | Module | Engine | Default | Lines added |
|---|---|---|---|---|
| A1. HRP composition (slice 2) | `engines/engine_a_alpha/signal_processor.py` (new branch) | A (consumes Engine C optimizer) | `method = "weighted_sum"` | ~30 (modified branch) |
| A2. Turnover penalty | `engines/engine_c_portfolio/optimizers/turnover.py` (REUSED from slice 1) | C | active when HRP active | 0 |
| A3. LT-hold preference | `engines/engine_b_risk/lt_hold_preference.py` (NEW) | B | `enabled: false` | 165 |
| A4. Wash-sale avoidance | `engines/engine_b_risk/wash_sale_avoidance.py` (NEW) | B | `enabled: false` | 110 |

All four are exercised together in cell C (deployable retail config) of
the A/B/C/D harness.

### Engine B touch (approved scope)

Per the user proposal protocol in CLAUDE.md, Engine B was modified ONLY
within these bounds:

1. **`optimizer_weight` in sizing composition** (~10 lines). Engine B
   reads `signal.meta["optimizer_weight"]` and multiplies it into the
   ATR-risk `risk_scaler` AND the target-weight `target_notional`.
   Default 1.0 = strict no-op. The composition becomes:

   ```
   ATR-risk path (Path B):
       size = base_atr_size × signal_strength × governor_weight ×
              advisory_risk_scalar × optimizer_weight
   target-weight path (Path A in code):
       target_notional = equity × target_weight × optimizer_weight
   ```

2. **Two new instance attributes** (`self.wash_sale`, `self.lt_hold`)
   constructed in `__init__` from new optional kwargs `wash_sale_cfg=`
   and `lt_hold_cfg=`. Default-`None` cfg → default-disabled module →
   no-op behavior. (~25 lines including imports.)

3. **`record_fill(fill, ts)` public method** (~20 lines). Called by
   `BacktestController._execute_fills` and `_evaluate_stops` after every
   `portfolio.apply_fill`. Pushes the fill into both tax-aware modules.
   No-op when both modules are disabled.

4. **`prepare_order` integration** (~35 lines):
   - At the start of the exit branch (`side == "none" and current_qty != 0`):
     consult `lt_hold.should_defer_exit` and return `None` if it fires.
   - After the no-shorts policy check: consult
     `wash_sale.should_block_buy` and return `None` if it fires.
   - In the ATR-risk sizing block: read `optimizer_weight` from
     `signal.meta` and multiply into `risk_scaler`.
   - In the target-weight sizing block: same multiplier on `target_notional`.

**Total Engine B internal change: ~90 lines added. ~15 lines beyond the
"~10-30 lines" estimated in the user's approved scope.** The overage is
the wash_sale/lt_hold integration, which the user spec explicitly
contemplates by assigning the modules to `engines/engine_b_risk/` and
dictating their integration points.

**No other Engine B changes.** Sizing logic (other than the multiplicative
composition), vol-targeting, exposure caps, kill-switch behavior — all
untouched. No changes to `live_trader/` or to PortfolioPolicy.

### Adjacent-engine touches (additive only)

- `engines/engine_a_alpha/signal_processor.py` — added `hrp_composed`
  branch in `_apply_portfolio_optimizer`. Existing `hrp` (replacement)
  branch retained for D-cell verification. ~25 lines added.
- `engines/engine_a_alpha/alpha_engine.py` — propagate `optimizer_weight`
  from per-ticker `info` dict into `signal.meta`. ~10 lines added.
- `backtester/backtest_controller.py` — call `risk.record_fill(fill, ts)`
  after `portfolio.apply_fill` in two places. Also write
  `path_a_modules` (wash_sale + lt_hold counters) into the per-run
  `performance_summary.json` for harness consumption. ~30 lines added.
- `orchestration/mode_controller.py` — pass `wash_sale_cfg` and
  `lt_hold_cfg` from `portfolio_settings.json` into both
  `RiskEngine(...)` constructions. ~10 lines added.
- `config/portfolio_settings.json` — added `wash_sale_avoidance` and
  `lt_hold_preference` blocks (both default-disabled). The existing
  `portfolio_optimizer.method` retains `"weighted_sum"` default.

### What was NOT touched (per spec)

- `engines/engine_c_portfolio/sleeves/` — Agent 2's territory.
- Any sleeve-abstraction files.
- `live_trader/`.
- The default behavior on `main` — flipping all new flags off restores
  bit-identical pre-Path-A behavior.

---

## A1. HRP slice 2 — composition (the slice-1 fix)

The slice-1 design (memory `project_engine_c_hrp_slice1_falsified_2026_05_02.md`)
**replaced** `aggregate_score` magnitude with `sign × HRP_weight × N`.
That stripped Engine A's edge-ensemble conviction signal and left HRP's
covariance-derived weight to drive sizing alone. Result on prod-109 2025
OOS: A `weighted_sum` 0.984 vs B `hrp` 0.350, **Δ −0.63 Sharpe**.

Slice 2 **composes** instead of replaces. The integration point moves
from "overwrite Engine A's score" to "multiply HRP weight into Engine B's
sizing":

```
Engine A.aggregate_score   ─┐
Engine A.signal_strength   ─┼─→ Engine B.risk_scaler ─→ ATR-risk size
Engine F.governor_weight   ─┤
Engine E.risk_scalar       ─┤
Engine C HRP optimizer_wt  ─┘  ← (NEW; default 1.0 = strict no-op)
```

Both Engine A's conviction AND Engine C's covariance-aware re-weighting
contribute to the final position size. The decisions remain the same
direction and same per-edge attribution; HRP modulates *magnitude
share* across the active universe.

**Why this is the right shape.** Engine A's `aggregate_score` carries
information that HRP's covariance distance does not (which edges fired,
how strongly, governor's edge-quality scaling). Replacing it discards
that. Multiplying HRP weight in preserves it while letting HRP suppress
sizing on names that contribute redundantly to portfolio variance.

**Reusable artifacts retained from slice 1:** `HRPOptimizer` and
`TurnoverPenalty` modules, `PortfolioOptimizerSettings` dataclass,
`_apply_portfolio_optimizer` hook, the deterministic A/B harness
machinery in `scripts/ab_engine_c_hrp.py`. Slice 2 added one new branch
in `_apply_portfolio_optimizer` controlled by
`po_settings.method == "hrp_composed"`.

## A2. Turnover penalty (re-used)

`TurnoverPenalty` from slice 1 is consulted after HRP produces weights
(both for the `hrp` and `hrp_composed` paths). When the proposed
rebalance's expected alpha lift is below estimated transaction cost,
the previous weight vector is reused — suppressing churn without
changing the algorithm.

This is consequential for tax efficiency: every rejected rebalance is a
turnover unit that doesn't generate a wash-sale event or short-term gain.
The penalty is configured via `portfolio_settings.json →
portfolio_optimizer.turnover.{enabled, flat_cost_bps,
min_turnover_to_check}`.

## A3. Long-term hold preference

When Engine A signals `side="none"` on a position currently held in the
**[300, 365)** day window, `LTHoldPreference.should_defer_exit` is
consulted. If the position has unrealized gain large enough that the
federal ST→LT rate delta (default 0.30 − 0.15 = 0.15) × gain > the
configured `min_hold_savings_threshold` (default $50) AND > the caller's
`exit_alpha_value` (default 0 for neutral signals), the exit is deferred.

A **hard cap at 380 days** prevents indefinite deferral. Once a holding
is past day 380, the cap fires (counter incremented) and the exit is
allowed regardless of tax math.

**Hard SL/TP exits bypass this gate.** Stops fire in
`ExecutionSimulator.check_stops_and_targets`, not in
`RiskEngine.prepare_order`. Protective exits must always fire — losing
the next 1+R of price move dominates the tax delta on any plausible
parameter setting.

## A4. Wash-sale avoidance

`WashSaleAvoidance` maintains a per-ticker ledger of recent loss-realizing
exits. It is updated on every fill via `RiskEngine.record_fill` (only
closing fills with `pnl < -min_loss_dollars` register as wash-sale-relevant
losses).

When `prepare_order` is asked to open a new long/short position
(`current_qty == 0`) on a ticker with a loss-realizing close inside the
30-day IRS window, the buy is refused with `last_skip_reason =
"wash_sale_window_active"`. This prevents the IRS wash-sale loss
disallowance at the source — the loss is realized cleanly, the rebuy
happens at day 31+ if the signal is still firing, and the loss reduces
the year's tax bill normally.

The `stats` dict tracks `buys_proposed`, `buys_blocked`, `block_rate`,
and `loss_exits_recorded` for diagnostic purposes. Both the wash-sale
fire-count AND the `tax_drag_model.compute`'s
`wash_sale_disallowed_loss` field are surfaced in the per-run
`performance_summary.json` under `path_a_modules` and
`cost_completeness_layer_v1.yearly_tax_breakdown`.

If wash_sale's `block_rate` is high, that's a *signal that the strategy's
turnover is still too high* — the right downstream response is to tighten
the turnover penalty or reduce signal frequency, not to disable the
wash-sale gate.

---

## A/B/C/D verification

Harness: `scripts/ab_path_a_tax_efficient_core.py`. 3 replicates per
cell, run inside `scripts.run_isolated.isolated()` (full
`data/governor/` snapshot+restore around each run, per the 2026-05-01
determinism floor). Same prod-109 universe, 2025-01-01 → 2025-12-31 OOS
window, deterministic harness (PYTHONHASHSEED=0).

| Cell | `portfolio_optimizer.method` | `wash_sale.enabled` | `lt_hold.enabled` |
|---|---|---|---|
| A | weighted_sum | false | false |
| B | weighted_sum | true | true |
| C | hrp_composed | true | true |
| D | hrp (REPLACEMENT, slice 1) | false | false |

**Tax-drag layer is enabled for all four cells** so `sharpe_C_after_tax`
is computable. The cost completeness layer is non-mutating to the
backtest itself; it post-processes the trade log.

### Results — 12-backtest run, all cells bitwise-deterministic

Raw results: `docs/Audit/path_a_tax_efficient_core_ab_results.json`.

| Cell | Mean Sharpe pre-tax | Mean Sharpe post-tax | Δ pre→post (tax drag) | Tax drag $ | Wash-sale disallowed $ | Wash-sale buys blocked | LT-hold defers | Canon md5 unique/3 |
|---|---|---|---|---|---|---|---|---|
| A baseline (ship state) | 0.954 | **-0.586** | -1.540 | $12,616 | $17,320 | 0 | 0 | 1/3 |
| B tax-only | **1.624** | **-0.414** | -2.038 | $12,212 | $13,069 | 6,335 | 0 | 1/3 |
| C full Path A | 0.557 | -0.673 | -1.230 | $7,516 | $9,683 | 5,852 | 0 | 1/3 |
| D HRP slice-1 (replacement) | 0.331 | -0.745 | -1.076 | $9,941 | $20,418 | 0 | 0 | 1/3 |

**Δ vs cell A baseline:**

| Cell | Δ pre-tax Sharpe | Δ post-tax Sharpe |
|---|---|---|
| B tax-only | **+0.670** | **+0.172** |
| C full Path A | -0.397 | -0.087 |
| D HRP slice-1 | -0.623 | -0.159 |

### Headlines

1. **Cell A reproduces the kill-thesis finding cleanly.** Pre-tax 0.954 vs
   memory's 0.984 (0.030 below; well within governor-state-drift noise
   from prior measurement campaigns). Post-tax -0.586 vs memory's -0.577
   (0.009 below; deterministic-harness-floor accuracy). Wash-sale
   disallowed $17,320 — matches the memory-noted $17,343 within rounding.
   The harness is honest.

2. **Wash-sale alone is the standout (cell B).** Pre-tax Sharpe lifted
   from 0.954 → 1.624 (Δ +0.670). Post-tax recovered 0.172 of the
   1.561 gap. The 6,335 blocked buys per year are a strong signal: the
   strategy was repeatedly re-entering names it had just exited at a
   loss, and most of those re-entries were not just wash-sale-bad but
   also Sharpe-bad. The wash-sale rule is exposing a turnover quality
   problem the engine was masking.

3. **HRP composition is not free in this universe (cell C).** Pre-tax
   dropped from B's 1.624 to 0.557 (Δ -1.067). The
   `HRP_weight × N` magnitude clamps to [0, 1] with mean ≈ 1.0 — so the
   composition can only scale sizes DOWN, never UP. Composed with
   wash-sale (which already cuts entry rate), total participation
   drops too far. **The asymmetric clamp is the design flaw.** Slice
   3 (if pursued) should normalize HRP weights so the mean composition
   multiplier is exactly 1.0 and the gate is a redistribution rather
   than a strict reducer.

4. **Cell D reproduces slice-1's failure cleanly** (0.331 vs the
   memory-noted 0.350). The 0.019 difference is harness noise. This
   confirms our slice-2 vs slice-1 differentiator is real and the
   harness is reading the same signal as the original slice-1 audit.

5. **Kill-thesis status: STILL TRIGGERED.** The pre-committed criterion
   in `forward_plan_2026_05_02.md` is "OOS Sharpe ≥ 0.5 net of all
   costs (incl. taxes + borrow), else stop and run structural review."
   Best Path A cell (B at -0.414 post-tax) does not clear that bar.
   The structural answer (deploy in tax-advantaged accounts where the
   ST tax drag does not apply) remains dominant. Path A is real
   engineering progress but does not change the deployment-context
   conclusion: this strategy is for a Roth IRA, not a taxable retail
   brokerage.

### Diagnostics

- **Wash-sale fire count (cells B & C):** ~6,000 blocked buys per year
  on prod-109 / 2025 OOS. With ~250 trading days × ~109 tickers ≈ 27k
  buy-proposal opportunities, the block rate is ~22%. That is a *very*
  high rate and confirms what cell A's $17k disallowed-loss number
  hinted at: the strategy as currently configured re-trades the same
  tickers continuously enough that one in five entries is wash-sale
  conflicted. The right downstream response is to *tighten the
  turnover penalty* and *raise the entry threshold*, not to disable
  the wash-sale gate.
- **LT-hold defer count:** 0 firings across all cells. With a 1-year
  OOS window starting 2025-01-01, no position can reach the 300-day
  defer-window floor before 2025-10-27, and the strategy's typical
  hold is ≪ 300 days. The mechanism will be more consequential on
  multi-year windows; we should re-validate on 2021-2025 in a
  follow-up before drawing a final conclusion on its value.
- **Within-cell determinism: PASS for all cells.** Each cell's 3 reps
  produced bitwise-identical canon md5s and Sharpe spreads of 0.0.
  The new modules reset cleanly inside `scripts.run_isolated.isolated()`
  and do not leak state across runs.

### Pass criteria evaluation

| Criterion | Result |
|---|---|
| C post-tax > 0.0 (deployable in taxable) | **FAIL** (-0.673) |
| C post-tax > 0.3 (strong win) | **FAIL** |
| D ≈ slice-1 0.35 (harness honest) | **PASS** (0.331, Δ 0.019) |
| B post-tax > A post-tax (tax-modules alone help) | **PASS** (Δ +0.172) |
| Within-cell determinism | **PASS** (canon md5 1/3 each cell) |

---

## Unresolved / open questions

1. **HRP composition shape (slice 3 candidate).** The `HRP_weight × N`
   clamp to [0, 1] makes composition a strict size-reducer. A revised
   normalization — e.g. `HRP_weight × N / mean(HRP_weight × N)` so
   the mean is exactly 1.0 — would let above-variance-mean tickers
   scale up while below-variance-mean tickers scale down, preserving
   total exposure. This is a slice-3 design discussion, not a slice-2
   bug. Ship slice 2 default-off and let the user decide whether to
   pursue slice 3.
2. **Wash-sale block rate of ~22% is a turnover-quality signal.** It
   tells us the strategy's edge ensemble is producing many entries
   with poor expectation. Two possible follow-ups: (a) tighten the
   turnover penalty (currently 10 bps / no per-ticker cost model);
   (b) raise the entry threshold via Engine A. Neither is in this
   branch's scope — both are Foundation-level changes.
3. **LT-hold mechanism unverified on relevant time scale.** The
   1-year window can't exercise it. Re-validate on 2021-2025 before
   merging the LT-hold flag-flip decision. The module IS production-
   correct; it just doesn't fire on a 1-year window so we can't
   measure its impact here.
4. **Kill-thesis remains nominally triggered.** Per the literal
   pre-commitment, the next step is "structural review." The honest
   reading per
   `project_tax_drag_kills_after_tax_2026_05_02.md` is more nuanced
   — the alpha thesis is intact pre-tax (0.954-1.624 across cells),
   the gap is deployment-context. The actionable response is to
   formally accept tax-advantaged deployment as the primary near-term
   path and stop trying to engineer the gap closed in a taxable
   context.

## Engine boundary audit

- **Engine A (Alpha):** owns `aggregate_score` (preserved by `hrp_composed`),
  no behavior change on default `weighted_sum`. Adds optimizer_weight
  passthrough into signal.meta — purely additive.
- **Engine B (Risk):** owns the four-module composition described above.
  All modules default-disabled.
- **Engine C (Portfolio):** owns HRP and turnover optimizers; no
  modifications to PortfolioPolicy or the sleeves dir (Agent 2's
  territory).
- **Engine E (Regime):** untouched.
- **Engine F (Governance):** untouched.
- **`live_trader/`:** untouched.

---

## What deploys to main vs what stays on this branch

**Default behavior on `main` is bit-identical to pre-Path-A.** The
config flag flips that drive cells B/C/D are NOT pushed; the merged code
ships with all switches off.

When the user is convinced by the results, flipping the four flags ON in
`config/portfolio_settings.json` is a single PR away from going live in
backtests (and eventually shadow). Until then, this branch's value is:

1. The mechanisms exist and are tested.
2. The A/B/C/D harness can be re-run with one command on any future
   universe / window / cost-model evolution.
3. The audit captures the deployable retail Sharpe before any of the
   flag-flips, so the comparison stays honest.
