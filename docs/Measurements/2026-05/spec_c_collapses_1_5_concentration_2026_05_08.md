# Spec — C-collapses-1.5: Concentration-Equivalent Capital Test

**Date drafted:** 2026-05-08
**Status:** SPEC for approval. Sequenced AFTER `spec_substrate_honest_remeasurement_2026_05_08.md` Arm 1 completes.
**Will be executed by:** Agent A or B once approved (~2-3 hr post-processing task; no new backtest run).
**Output:** `docs/Measurements/2026-05/c_collapses_1_5_concentration_verdict_2026_05_08.{md,json}`

---

## Why now

The headline question this answers: **is there any per-name signal independent of the sizing chain's concentration effects, or is the system's apparent alpha riding on accidental concentration?**

Engine B's sizing chain (`risk_engine.py:740-790`) takes signal strength + governor weight + advisory risk_scalar + optimizer_weight and multiplies them into `risk_scaler`. Names with stronger signals get more dollar exposure. The result is that headline Sharpe reflects both:
- **Selection skill**: which names get long/short
- **Sizing skill**: how much capital flows to each (signal-conviction-weighted)

If the system's alpha is in selection, equal-weighting all signaled names should give similar headline Sharpe. If the alpha is in sizing (concentration accident), equal-weight should perform materially worse.

This test interacts directly with the substrate-honest re-measurement's verdict interpretation: a positive Arm 2 lift could be real edge or could be the sizing chain better-distributing concentration accident. C-collapses-1.5 disambiguates.

---

## Method: post-processing the substrate trade log (not a new backtest)

Rather than a separate backtest with Engine B modifications (which would require user approval per CLAUDE.md), this test is a post-processing pass on the substrate-honest measurement's Arm 1 trade log.

**Algorithm:**

1. Load Arm 1's `trades.csv` and `portfolio_snapshots.csv` from
   `data/trade_logs/<arm1_run_id>/`.
2. Reconstruct the time series of open positions:
   - For each bar `t`, compute the set of currently-held tickers `H_t`
     (positions opened ≤ `t` and not yet closed).
3. For each closed trade, compute its hypothetical equal-weight quantity:
   ```
   hypothetical_qty = (initial_capital × per_position_target) / fill_price
   per_position_target = 1.0 / |H_t|  at the trade's entry bar t
   ```
   `per_position_target` floors at `1/MAX_CONCURRENT_POSITIONS` (use the prevailing `max_positions` from `risk_settings` ≈ 5 in current config).
4. Re-compute hypothetical realized PnL per trade:
   ```
   pnl_eq = (exit_price - entry_price) × hypothetical_qty × side  (long=+1, short=-1)
   ```
5. Build a hypothetical equity curve:
   ```
   equity_eq[t] = initial_capital + cumsum(pnl_eq for trades closed ≤ t)
   ```
6. Compute hypothetical metrics: Sharpe, Sortino, MDD, win-rate, bootstrap CI on Sharpe.

**Two variants to compute simultaneously** (both cheap; both useful):

| Variant | Hypothetical sizing rule | Question answered |
|---|---|---|
| **EW-1** | Equal weight = 1/N at entry bar (N = concurrent open positions) | What if conviction-weighting were removed entirely? |
| **EW-2** | Equal weight = 1/MAX_POSITIONS (constant) | What if the sleeve always held a fixed-N portfolio at uniform weight? |

EW-1 preserves the system's choice of WHEN to be in market; EW-2 also normalizes for that.

---

## Reporting

### Headline metrics (each variant)

| Metric | Arm 1 actual | EW-1 | EW-2 | Δ vs Arm 1 |
|---|---|---|---|---|
| Mean Sharpe | | | | |
| Mean Sortino | | | | |
| Bootstrap Sharpe 95% CI | | | | |
| Mean MDD | | | | |
| Win rate | | | | |
| Avg winner / avg loser | | | | |

### Per-edge contribution under EW-1

Re-run the per-edge attribution analysis using hypothetical PnL instead of actual PnL. Report whether the same 4 surviving / 2 net-drag pattern holds when sizing is uniform.

### Verdict framing

- **EW-1 Sharpe ≥ Arm 1 Sharpe (within bootstrap CI overlap)**: per-name signal is real and the conviction-weighting chain isn't load-bearing. The substrate-honest measurement reflects genuine selection alpha. Implication: Arm 2's lift (if any) attributes more cleanly to edge-pruning + HMM, not to any sizing-chain interaction.
- **EW-1 Sharpe materially below Arm 1 (Δ ≤ −0.2)**: conviction-weighting is part of the alpha. Selection alone isn't enough; the sizing chain is doing real work. Implication: any deployment recommendation must account for the conviction → sizing pipeline being intact.
- **EW-1 Sharpe materially above Arm 1 (Δ ≥ +0.2)**: surprising — conviction-weighting is HURTING. The sizing chain is over-fitting to noise. Implication: investigate the strength → risk_scaler curve and the optimizer_weight pass-through; likely a small refactor would lift the headline materially.
- **EW-2 Sharpe ≥ EW-1 Sharpe**: timing/selection isn't load-bearing — a static fixed-N portfolio captures the same alpha. Implication: simpler architecture is viable.
- **EW-2 Sharpe ≪ EW-1 Sharpe**: timing matters — the system's choice of when to be in market is part of the value.

### Caveats to document

- Post-processing assumes a counterfactual Engine B that would have produced the same trades but with different sizing. Real Engine B might also have produced different SIGNALS at different sizing levels (e.g., advisory exposure cap interacts with conviction → fewer signals when conviction is uniform). Post-processing doesn't capture that interaction. This is the chief limitation; flag it explicitly in the audit doc.
- Trade-by-trade re-sizing assumes no transaction-cost feedback. Real Engine B with realistic slippage would charge more per trade at higher sizing; post-processing leaves slippage at actual trade size. Bias is small for the 5-position cap config but non-zero. Acceptable for first-pass.
- 5-position max-positions is the current config; if Arm 1 ran under a different cap, use Arm 1's actual `max_positions` value.

---

## Hard constraints for the executing agent

- DO NOT modify Engine B or any other engine code.
- DO NOT run a new backtest — this is purely post-processing on existing logs.
- Use `feature/c-collapses-1-5-concentration` branch.
- Read inputs from the substrate-honest run's UUID directory in `data/trade_logs/<uuid>/`. Director will provide the UUID via inbox after substrate measurement completes.
- Bootstrap CI on hypothetical Sharpe: use `MetricsEngine.bootstrap_distribution` (already shipped). 1000 iterations.
- Push to feature branch only; director merges.

---

## Acceptance

- Audit doc + JSON written to `docs/Measurements/2026-05/c_collapses_1_5_concentration_verdict_2026_05_08.{md,json}`
- Both variants (EW-1, EW-2) computed
- Verdict framing applied; one of the four buckets selected
- Caveats section in the audit doc explicit about post-processing limitations
- Reproducible: the script (`scripts/post_process_concentration_test.py`) committed; second run on the same trade log produces bit-identical outputs

---

## Dependencies

- **Hard:** substrate-honest re-measurement Arm 1 must complete first. Director provides `<arm1_run_id>` in the inbox.
- **Soft:** `MetricsEngine.bootstrap_distribution` (already shipped), pandas, numpy.

## Estimated runtime

~2-3 hr (post-processing is fast; most of the time is on building the hypothetical equity curve correctly + writing the audit doc + writing the script + tests).
