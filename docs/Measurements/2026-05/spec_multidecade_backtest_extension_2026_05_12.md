# Spec — T-2026-05-12-050: Multi-decade backtest extension (1990+ minimum, 2010-2024 → 1990-2024)

**Date drafted:** 2026-05-12 LATE (director-side, post-research-synthesis + MBL math)
**Status:** SPEC DEFERRED 2026-05-12 LATE per user directive — "still not ready to pay for data before this thing is making money or even close to it." Same Norgate dependency as T-056; both held until the system demonstrates meaningful alpha first. Spec retained for fast dispatch once that gate clears. **DO NOT dispatch in this state.** Caveat: the MBL math (`docs/Audit/honest_n_mbl_computation_2026_05_12.md`) still holds — without multi-decade extension, no deployment decision is statistically valid; the deferral means we will not have a DSR-clearing measurement until paid data lands.
**Will be executed by:** Agent A or B once Norgate credentials in `.env` (~16-24 hr).
**Sequencing:** can run in parallel with T-056 (both share Norgate but touch different substrate scopes).
**Output:** extended substrate-honest universe (1990-2024) + cost model recalibrated for older eras + smoke validation against known historical anomalies + audit doc.

---

## Why this is the metrics-dive precondition for deployment

Per the 2026-05-16 metrics research dive's load-bearing formula:

> **MBL_years ≈ 2 · ln(N_effective) / SR_target²**

Applied to our project (per `docs/Audit/honest_n_mbl_computation_2026_05_12.md`):

| Window | Required SR to clear DSR at N=75 |
|---|---|
| 5 yr (current) | **1.55** (corrected baseline 0.598 cannot reach) |
| 10 yr | 1.10 (engine-completion lift might reach) |
| 15 yr | 0.89 (corrected baseline within reach) |
| 20 yr | 0.78 |
| 25 yr | 0.70 |

**At the current 5-year window, no realistic Sharpe target can clear DSR given accumulated N_trials.** Engine completion's projected +0.55-1.25 lift doesn't fix this alone. The multi-decade extension is the load-bearing precondition for any deployment decision — not an optional improvement.

All three other research dives also referenced multi-decade extension as a critical need:
- Dive 1 (Alpha): "extend the backtest history on factor edges to 1962+"
- Dive 2 (Compound): implied via DSR penalty math
- Dive 3 (Regime): implied via real-time-evaluation evidence

---

## Prerequisites (USER ACTION before dispatch)

Same as T-056: Norgate Data subscription + credentials in `.env` (`NORGATE_API_KEY`).

Norgate's "Stock Histories: US Indices" includes survivorship-bias-free history back to ~1990 for delisted + active names. **Going pre-1990 requires CRSP Standard** (academic-tier, ~$5K/yr — overkill for retail unless we explicitly target 1962+).

For T-050 v1: 1990-2024 (34 years) is the target. Adequate per MBL math even at SR=0.5 (which is below our current baseline).

---

## What

### Phase 1 — Universe extension (~3-4 hr)

`scripts/extend_substrate_universe_1990_2024.py`:

- Norgate adapter (from T-056) → bulk-load S&P 500 component history 1990-2024
- Point-in-time membership tracking: who was in the S&P 500 at each historical year-end
- Output: `data/universes/sp500_pit_1990_2024.parquet` with (ticker, date_in_universe, date_out_of_universe, market_cap_at_inclusion)

Universe stats expected:
- ~3,500 unique tickers entering/exiting over 34 years
- ~500-550 in universe at any given year-end
- ~60-70% delisting/replacement rate over 34 years
- Critical for survivorship-honesty: the 1995 S&P 500 has ~140 names that no longer exist by 2024

### Phase 2 — Cost-model historical calibration (~3-4 hr)

Spreads, commissions, and market structure changed dramatically 1990-2024. A naive cost model calibrated for the current era understates costs in earlier years:

- Pre-2001 (decimalization): bid-ask half-spreads on S&P 500 names were 6-12 cents typical (~25-100 bps), not the 1-5 bps of today
- 2001-2007: post-decimalization but pre-HFT: 3-8 bps half-spreads
- 2008-2015: HFT era + Reg-NMS: 1-3 bps half-spreads
- 2015-2024: continued tightening; mega-caps at <1 bps

`engines/engine_b_risk/cost_model_historical.py` (NEW):
```python
class HistoricalCostModel:
    """
    Era-aware cost model for 1990-2024 backtests.

    Pre-decimalization (1990-2001): half-spread ~50 bps S&P 500 names
    Post-decimalization (2001-2007): half-spread ~5 bps
    HFT era (2008-2015): half-spread ~2 bps
    Modern (2015-2024): half-spread ~1 bps mega-cap, ~5 bps mid-cap

    Commissions:
    Pre-2003: ~$10-$30 per trade flat (Schwab/Fidelity historical)
    Post-2003: gradual decline to $5-$10
    Post-2019 (PFOF era): $0 commission, but PFOF = 5-15 bps adverse selection
    """
```

### Phase 3 — Smoke validation against known historical anomalies (~5-6 hr)

Run the existing 6-active edge set on the 1990-2024 substrate. Compare results to known historical anomaly performance from the academic literature:

- 1990-2000: value should outperform growth post-1990 (Fama-French original test period)
- 2000-2003: momentum strategies should underperform (momentum crash)
- 2003-2007: long-only equities up ~70% nominal (housing bubble)
- 2008-2009: max-drawdown stress test (-50% S&P 500 peak-to-trough)
- 2010-2019: low-vol "Goldilocks" decade
- 2020 March: COVID crash (V-shaped recovery; tests trend-following whipsaw)
- 2022: rates-driven bear market (-25% S&P 500)
- 2024: Mag-7-AI rally (factor strategies underperform)

**Expected outcome**: with deeper history + survivorship-honesty + recalibrated costs, the realized Sharpe of the existing 6-active set will be MATERIALLY LOWER than the 5-year corrected 0.598 — probably 0.2-0.4 range. This is INFORMATIVE: it tells us the corrected 0.598 baseline benefits from a 5-year bull-tilted window.

### Phase 4 — MBL recompute + DSR (~2-3 hr)

After Phase 3, recompute MBL given the new effective window length and N_trials accumulated. Compute DSR on the 34-year multi-decade Sharpe. Compare to the under-powered 5-year DSR.

**This is THE moment-of-truth: does any current edge set survive deep-history DSR?**

### Phase 5 — Audit doc + state updates (~2-3 hr)

`docs/Audit/multidecade_extension_smoke_2026_05_12.md`:
- Universe build statistics
- Per-era performance breakdown
- Cost-model calibration evidence (compare bid-ask synth to historical TAQ data if available)
- MBL + DSR recompute on 34-year window
- The HONEST verdict: what was previously claimed as a 0.598 baseline, on the deeper substrate, is...?

---

## Acceptance

1. **`engines/data_manager/norgate_adapter.py`** extended (or new) to handle 1990-2024 universe queries.
2. **`scripts/extend_substrate_universe_1990_2024.py`** produces the universe parquet.
3. **`engines/engine_b_risk/cost_model_historical.py`** with era-aware calibration.
4. **Smoke A/B**: 6-active set on 5-year (current) vs 34-year (extended) substrate. 3 reps per cell. Bootstrap CI per CLAUDE.md.
5. **Per-era performance table**:
   | Era | Description | 6-active mean Sharpe | ci_low | MDD | Year-by-year (mean Sharpe) |
   |---|---|---|---|---|---|
   | 1990-2000 | Pre-decimalization | ? | ? | ? | ... |
   | 2001-2007 | Post-decimalization | ? | ? | ? | ... |
   | 2008-2015 | HFT + GFC + recovery | ? | ? | ? | ... |
   | 2015-2024 | Modern | ? | ? | ? | ... |
   | **Full 1990-2024** | | ? | ? | ? | |
6. **MBL recompute**: T_years now 34; SR_required = √(2·ln(N)/T) at N=75 = 0.51 (clears 0.598 corrected baseline if it holds on the deeper substrate).
7. **DSR computation** on the 34-year Sharpe with bootstrap CI.
8. **Tests** in `tests/test_multidecade_extension.py`:
   - Universe adapter loads 1995 S&P 500 component list correctly (validate against publicly-known constituent changes)
   - Cost model produces era-appropriate spreads on synthetic trades
   - No look-ahead in universe-membership transitions
9. **Audit doc** at `docs/Audit/multidecade_extension_smoke_2026_05_12.md`.
10. **State doc updates**: forward_plan (the substrate truth shifts again), health_check, lessons_learned.
11. **Branch:** `feature/multidecade-backtest-extension`. Push only; director merges.

---

## Hard constraints

- DO NOT modify the existing S&P 500 substrate or cost model. Era-aware is PARALLEL infrastructure.
- DO NOT use yfinance for pre-2010 data. Norgate is required for survivorship-bias-free.
- DO NOT bridge the 5-year and 34-year measurements without explicit cost-model alignment. Different eras need different cost models.
- Per CLAUDE.md 6th non-negotiable: bootstrap CI on every Sharpe headline.
- Per CLAUDE.md 7th non-negotiable (MBL Gate 0): document the new MBL-vs-window ratio explicitly.

---

## Time budget

- Phase 1 (universe extension): 3-4 hr
- Phase 2 (cost model historical): 3-4 hr
- Phase 3 (smoke A/B): 5-6 hr (60+ backtests on 34-year substrate; vectorized at T-013 speed; cost-model overhead may slow)
- Phase 4 (MBL + DSR recompute): 2-3 hr
- Phase 5 (audit doc + state updates): 2-3 hr
- **Total: 16-24 hr**

---

## Open questions for implementing agent (surface in audit doc)

1. **Pre-2001 decimalization: how do we handle the bid-ask spread denominated in 1/16ths or 1/8ths?** Historical SIP data may show prices on fractional ticks. The cost model should round positions to the prevailing tick size for the era. Document.

2. **Corporate actions for delisted pre-2010 names**: Norgate provides delisting returns, but historical splits + mergers + spin-offs need careful handling. Document any discrepancies vs CRSP if available.

3. **What about the 2008 GFC stress?** The 6-active set has 4 V/Q/A edges that may have been hammered in 2008. This is the load-bearing test of regime fragility. Report 2008 separately + analyze whether the gauntlet's per-regime decomp would have caught it.

4. **Should T-050 also do per-era factor decomp?** Per dive 3: factor regime changed significantly 1990-2024. The 1990s V/G regime was different from 2010-2024. **Recommend YES** — adds 2-3 hr but is the most informative cut.

5. **What if the 34-year smoke shows 6-active mean Sharpe near zero or negative?** That's the genuinely informative outcome — it tells us the 0.598 corrected baseline is a 5-year-window artifact. Per the user "bones must be PERFECT" directive, that's a load-bearing finding worth knowing.

---

## Forward-look (after T-050 lands)

If 34-year mean Sharpe ≈ 0.2-0.4 (expected per priors):
- Engine completion's projected +0.55-1.25 lift is the only path to deployment-clearance
- Substrate diversity (T-056 microcap) becomes MORE important — same edges on a different substrate
- Multi-decade DSR at SR=0.4 at N=75 needs the 34-year window to be honest — we now have it

If 34-year mean Sharpe ≈ 0.6+ (surprise upside):
- The 5-year window wasn't a bull-tilt artifact
- Engine completion + non-factor edges have a clear path to deployment-clearance
- Multi-decade extension is the headline number going forward

Either outcome is load-bearing. **The current 5-year window doesn't let us distinguish these scenarios.** T-050 is the discriminating measurement.

---

## Director note + cascade

T-050 and T-056 are the two Norgate-gated dispatches. Both unblock once user subscribes + adds credentials. Recommended sequencing:

1. T-056 (microcap substrate, smaller scope) — establishes the Norgate adapter + cost model framework
2. T-050 (multi-decade extension) — reuses T-056's adapter + cost model + extends to S&P 500 1990-2024

Total agent work: 28-40 hr across the two dispatches; substrate truth becomes deeply informed for the first time in the project's history.
