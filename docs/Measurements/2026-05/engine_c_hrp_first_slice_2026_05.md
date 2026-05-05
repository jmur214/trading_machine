# Engine C — HRP optimizer first slice (Workstream B)

**Branch:** `engine-c-hrp-optimizer`
**Date:** 2026-05-02
**Workstream:** B (Engine C rebuild) — slice 1 of multi-week effort
**Reviewer mandate:** [`forward_plan_2026_05_02.md`](../Core/forward_plan_2026_05_02.md), [`05-1-26_1-percent.md`](../Progress_Summaries/Other-dev-opinion/05-1-26_1-percent.md), [`05-1-26_a-and-i_full.mf`](../Progress_Summaries/Other-dev-opinion/05-1-26_a-and-i_full.mf)

---

## Why

The 1-percent doc Part 2 / Workstream B and the full review's Engine C
gap analysis converge: real portfolio construction (mean-variance, HRP,
risk parity, turnover-aware rebalancing) is missing from this codebase.
Most of what would normally live in Engine C happens implicitly inside
`signal_processor.process` — a per-ticker linear weighted_sum across
edges, with no cross-ticker covariance, no diversification logic, and
no turnover gating. The reviewer flagged this as the "highest single
ROI engine investment in the project."

Engine C is the thinnest engine in the system. This commit ships the
first slice of the rebuild.

## Scope of this slice

Three components, opt-in by config, default behavior unchanged.

### 1. HRP optimizer — `engines/engine_c_portfolio/optimizers/hrp.py`

López de Prado's three-step Hierarchical Risk Parity:

1. **Tree clustering** on the correlation distance matrix
   `d_ij = sqrt(0.5 * (1 - corr_ij))` using single-linkage agglomerative
   clustering (`scipy.cluster.hierarchy.linkage`).
2. **Quasi-diagonalization** — reorder leaves so that strongly-correlated
   tickers sit adjacent in the matrix.
3. **Recursive bisection** — at each level, split the cluster in two and
   allocate variance-proportionally:
   `α = 1 - V_left / (V_left + V_right)`, with
   `V_cluster = w_ivp.T · Σ_cluster · w_ivp`.

Covariance estimated from the trailing `cov_lookback` (default 60) bars
of returns via Ledoit-Wolf shrinkage (`sklearn.covariance.LedoitWolf`),
with sample-cov fallback if sklearn isn't importable.

**Why HRP and not mean-variance.** At the 3-active-edge / ~100-ticker
scale this codebase runs at, mean-variance's matrix-inversion is the
dominant failure mode under near-singular covariance. HRP avoids
inversion entirely and produces stable, interpretable weights. MVO
with shrinkage remains as a follow-up workstream item.

### 2. Turnover penalty — `engines/engine_c_portfolio/optimizers/turnover.py`

Stateful gate that compares the proposed weight vector to the most
recently committed one:

    Δα   = Σ_i (w_new_i - w_old_i) · μ_i           # alpha lift
    cost = Σ_i |w_new_i - w_old_i| · cost_bps_i    # transaction cost

If `Δα < cost`, the proposal is rejected and the previous committed
weights are returned. This implements the "reject rebalances where
expected alpha < transaction cost" requirement from Workstream B.

Cost model uses a flat `flat_cost_bps` (default 10 bps) by default,
with an optional injectable `cost_fn(ticker, delta) -> bps` callback so
that `RealisticSlippageModel.calculate_slippage_bps` can plug in once
the gross-capital signal volume is plumbed through (deferred to slice 2
because the slippage model needs `qty` in shares, not weight delta).

### 3. SignalProcessor dispatch — `engines/engine_a_alpha/signal_processor.py`

Added `PortfolioOptimizerSettings` dataclass and an `_apply_portfolio_optimizer`
hook that runs *after* the per-ticker loop completes. When
`method == "weighted_sum"` (default), this is a strict no-op. When
`method == "hrp"`:

  1. Filter `out` to tickers with non-zero `aggregate_score`.
  2. Build a returns panel from `data_map[t]['Close'].pct_change()`.
  3. Run `HRPOptimizer.optimize(returns, active_tickers)`.
  4. Run the proposed weights through `TurnoverPenalty.evaluate`.
  5. For each ticker, **preserve sign of `aggregate_score`** (long/short
     direction is Engine A's call) and replace |aggregate_score| with
     `HRP_weight × N`, clamped to [-1, 1]. This keeps the magnitude in
     the same range Engine B's existing sizing logic expects.

**Engine boundaries respected:** no Engine B (Risk) modifications. The
reshape touches only Engine A's per-ticker `aggregate_score` field;
sizing remains Engine B's responsibility per the charter.

## Config wiring

`config/portfolio_settings.json` gains a `portfolio_optimizer` block:

```json
"portfolio_optimizer": {
    "method": "weighted_sum",
    "hrp": {
        "cov_lookback": 60,
        "min_history": 30,
        "use_ledoit_wolf": true,
        "linkage_method": "single"
    },
    "turnover": {
        "enabled": true,
        "flat_cost_bps": 10.0,
        "min_turnover_to_check": 0.01
    }
}
```

Default `method: "weighted_sum"` ensures existing backtests are
strictly unaffected — HRP machinery is bypassed entirely (no HRP
imports executed, no turnover state instantiated).

## Tests — `tests/test_engine_c_hrp.py`

18 tests, all pass:

- **HRP weight invariants**: sum to 1, non-negative, finite, single-
  ticker → 1.0, insufficient history → equal-weight fallback,
  block-correlated synthetic data → non-uniform output.
- **Turnover gate**: first proposal accepted unconditionally, low-α
  rebalance rejected, high-α rebalance accepted, zero-cost always
  accepts, below-min-turnover bypass, disabled passes through, reset.
- **SignalProcessor dispatch**: `method="weighted_sum"` produces
  strictly identical output to a SignalProcessor with no PO settings,
  HRP path preserves signs, HRP path reshapes magnitudes (≠ uniform),
  HRP is deterministic across re-instantiated processors.

## A/B harness comparison

**Cell A:** `method=weighted_sum`, ML-off, floors-on (current ship state)
**Cell B:** `method=hrp`, ML-off, floors-on
**Universe:** prod-109, full-year 2025 OOS
**Replicates:** 3 each cell, under `scripts.run_isolated` deterministic harness
**Pass criterion:** B mean Sharpe ≥ A mean Sharpe + 0.10

**Results table:**

| Cell | Run | Sharpe | CAGR % | MDD % | Canon md5 |
|------|-----|--------|--------|-------|-----------|
| A1 (weighted_sum) | 7510d1af | **0.984** | 4.57 | -3.03 | 0d552dd1 |
| A2 (weighted_sum) | 1eea4667 | **0.984** | 4.57 | -3.03 | 0d552dd1 |
| A3 (weighted_sum) | ae788bb0 | **0.984** | 4.57 | -3.03 | 0d552dd1 |
| B1 (hrp)          | b5e2c479 | **0.350** | 1.64 | -3.24 | bb73f94b |
| B2 (hrp)          | 0b3e2603 | **0.350** | 1.64 | -3.24 | bb73f94b |
| B3 (hrp)          | 0f2c3bad | **0.350** | 1.64 | -3.24 | bb73f94b |

**Mean Sharpe (A):** 0.984
**Mean Sharpe (B):** 0.350
**Δ (B − A):** **−0.634** (HRP costs 0.634 Sharpe vs the ship-state baseline)
**Within-cell determinism:** A canon-unique = 1/3 (bitwise identical), B canon-unique = 1/3 (bitwise identical)
**Verdict:** **FAIL** — HRP does not clear the +0.1 Sharpe bar. As wired, it is destructive.

Raw results in [`engine_c_hrp_ab_results.json`](engine_c_hrp_ab_results.json); harness in [`scripts/ab_engine_c_hrp.py`](../../scripts/ab_engine_c_hrp.py).

## Diagnosis — why HRP failed in this configuration

The within-cell bitwise determinism on both arms is itself diagnostic:
this is not a noise / instability problem; HRP is producing a real,
reproducible -0.63 Sharpe drag.

The architectural mistake is in **how HRP weights are folded back into
the per-ticker `aggregate_score`**. The current reshape:

    new_magnitude = clamp(HRP_weight × N, 0, 1)
    new_aggregate_score = sign(orig_aggregate_score) × new_magnitude

throws away the per-ticker conviction information that the edge ensemble
just produced. Two pathologies follow:

1. **Conviction-vs-allocation conflation.** The original `aggregate_score`
   encodes both *direction* (sign) and *conviction* (magnitude derived
   from edge ensembling). Replacing the magnitude with a covariance-
   derived weight × N silently strips out the conviction signal. Engine
   B's downstream sizing (which scales position size with `strength`)
   then sizes large positions in low-conviction tickers and vice versa.

2. **Clamp-to-1 nonlinearity.** With ~20 active tickers per bar, the
   "average" HRP weight is ~0.05 → `weight × N = 1.0`. Tickers above
   that threshold get magnitude clamped to 1.0, those below get
   compressed. The result is a noisy bimodal distribution where the
   ranking inside each mode is dominated by covariance rather than
   alpha.

The negative result here doesn't falsify HRP itself — it falsifies the
*drop-in magnitude replacement* design. The right composition is to
use HRP as a *multiplicative overlay* on top of the existing strength,
i.e. `new_strength = orig_strength × normalized_HRP_factor`, not a
replacement. That redesign is slice 2.

## Architectural follow-up (slice 2)

The first slice's value is the **scaffolding**: optimizer module,
turnover gate, config knob, dispatch hook, deterministic A/B harness.
All of that is reusable. What needs to change before HRP can clear the
Sharpe bar:

- **Compose, don't replace.** `aggregate_score` keeps the conviction
  magnitude. HRP produces a *risk-budget multiplier* per ticker that
  multiplies into Engine B's sizing input, not Engine A's score.
- **HRP target = qty share, not strength.** Move the HRP integration
  point downstream — into Engine B's sizing path (with explicit user
  approval since Engine B is in propose-first mode), or into a thin
  Engine C "post-Engine-A, pre-Engine-B" stage that translates
  conviction-weighted portfolio targets into per-ticker qty hints.
- **Cap exposure to mid-vol tickers.** HRP gives equal risk budget to
  high-vol and low-vol names; in this universe (which spans `COIN`,
  `MARA` at 80%+ annual vol and `KO`, `JNJ` at 20%) that flat risk
  share fights the existing `vol_target_enabled` policy in Engine C's
  policy.py. The two need to compose, not duplicate.
- **Investigate turnover gate behavior.** With a flat 10 bps cost
  estimate the gate may be rejecting too aggressively / too rarely;
  the next slice should add per-bar accept/reject telemetry and
  tune `flat_cost_bps` from realized fill costs.

## Follow-up work flagged

Workstream B is multi-week. This slice is component 1 of 6 from the
1-percent doc Workstream B deliverables list. Remaining:

1. **Mean-variance with Ledoit-Wolf shrinkage** as alternative method
   (`config method: "mvo_lw"`). The skeleton exists in
   `engines/engine_c_portfolio/optimizer.py` but uses scipy SLSQP and
   needs to integrate with the same dispatch hook.
2. **Per-ticker turnover cost** via `RealisticSlippageModel.calculate_slippage_bps`
   — needs gross-capital plumbing so `weight_delta → qty (shares)`
   conversion is meaningful.
3. **Tax-aware rebalancing** — wash sale rule, prefer long-term
   over short-term gains realization. Requires position-history hook
   into the Ledger Layer (Engine C internal), not in scope yet.
4. **Capital efficiency layer** — gross exposure scales 1.0× to 1.3×
   with meta-learner confidence. Blocked on meta-learner being
   re-validated under harness (currently disabled per
   `project_metalearner_drift_falsified_2026_05_01`).
5. **Multi-asset class scaffolding** — non-equity inputs (bonds, commodities)
   for future expansion. Documented even if only equities active.
6. **Replace `weighted_sum` as the default** — gated on the +0.1 Sharpe
   bar AND the geometry-mismatch architectural fix (Workstream A) so we
   don't conflate Engine C's effect with the Discovery / gauntlet bug.

## Boundaries enforced

- No Engine B (Risk) modifications.
- No `live_trader/` modifications.
- No Discovery / Engine D / Engine E / backtester cost-layer changes.
- Default config remains `weighted_sum` on main — flipping to HRP is a
  separate decision after acceptance.
- Branch not pushed to main without user approval.
