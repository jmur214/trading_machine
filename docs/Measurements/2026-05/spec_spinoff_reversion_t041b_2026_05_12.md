# Spec — T-2026-05-12-041b: Spin-off reversion edge — universe-resolver wiring + EDGAR + 8-gate gauntlet

**Date drafted:** 2026-05-12 LATE (director-side; A's natural follow-up after T-054)
**Status:** SPEC for queue. Engine A continuation of T-041 (paused/feature → tier='alpha' candidate).
**Will be executed by:** Agent A (best context, wrote T-041) once T-054 completes (~8-12 hr).
**Sequencing:** dispatchable as A's chain after T-054.
**Output:** universe-resolver integration + EDGAR Form 10/10-12B scraping pipeline (~30 more events) + 8-gate gauntlet pass/fail + audit doc.

---

## Why this is A's natural next task

T-041 (merged eff4362 2026-05-12) shipped the spin-off edge as paused/feature tier with HONEST scope deferral. A's outbox: "T-041 ships the detector + edge + tests but defers universe-resolver wiring, EDGAR scraping (+~30 more events), and the full 8-gate gauntlet to T-041b — together they need universe-pipeline plumbing that exceeded session budget. No threshold-lowering: the edge will face the same α t > 2 gauntlet bar in T-041b that every other edge faces."

A has full context on T-041's detector + edge + curated event list. T-041b is the natural deepening: take the v1 components from "paused feature" to "gauntlet-validated promotion candidate."

**Per the research convergence**: spin-offs are the cleanest non-factor retail-only category. If T-041b passes gauntlet, it's a real candidate for activation (subject to user approval per CLAUDE.md). If not, the failure tells us something specific about the spin-off-anomaly's tradability at our scale.

---

## What

### Phase 1 — Universe-resolver wiring (~2-3 hr)

The T-041 detector returns `SpinoffEvent` objects with `(parent_ticker, child_ticker, distribution_date, distribution_ratio, source, confidence)`. The universe resolver must:

1. **At each bar date**, check `distribution_date == current_bar_date` events. ADD the child ticker to the tradeable universe FROM that date onward.
2. **Parent ticker continues trading** — don't drop the parent on spin-off.
3. **Re-listings / ticker symbol changes** post-spin-off — document handling.
4. **Filter events outside the backtest window** — don't add spin-offs that occurred 2025+ to a 2020-2024 backtest.

Wire into `engines/data_manager/universe_resolver.py` (or equivalent — A will know the right file).

### Phase 2 — EDGAR Form 10 / 10-12B scraper (~3-4 hr)

The T-041 detector relies on yfinance + curated list (13 events). To get to ≥40+ events on 2015-2024 substrate, add EDGAR as the authoritative source.

- EDGAR API: free, rate-limited 10 req/sec, returns Form 10 / 10-12B filings (initial registration statements for spin-off subsidiaries)
- Parse out: filer (parent), subject (spin-off entity), filing date, expected distribution date
- Cross-reference with yfinance to confirm actual trading commenced

Add to `engines/engine_a_alpha/edges/_helpers/spinoff_detector.py`:
```python
def detect_spinoffs_edgar(start_date, end_date, rate_limit_seconds=0.1):
    """Pull Form 10/10-12B filings from EDGAR for the window. Returns
    SpinoffEvent list. Cached at data/spinoff_events_edgar.parquet to
    avoid re-fetching."""
```

Combine with the existing yfinance + curated sources via the existing precedence logic in T-041 (curated > EDGAR > yfinance).

Expected result: 40-60 spin-off events on 2015-2024 substrate (vs T-041's 13 curated).

### Phase 3 — 8-gate gauntlet validation (~3-4 hr)

Run the spinoff_reversion_v1 edge through the full Discovery validation pipeline:

- Gate 1: Sharpe-contribution-to-ensemble
- Gate 2: PBO via CSCV
- Gate 3: WFO walk-forward
- Gate 4: Permutation null
- Gate 5: Universe-B substrate transfer
- Gate 6: FF5+Mom factor decomposition (t > 2 α REQUIRED)
- Gate 7: DSR
- Gate 8: Adversarial twin filter

Per CLAUDE.md 6th non-negotiable: bootstrap CI on every Sharpe.
Per CLAUDE.md 7th non-negotiable (Gate 0): MBL check given honest N.

**No threshold-lowering.** T-041b faces the same gates as every other edge.

### Phase 4 — Decision + audit (~1-2 hr)

If gauntlet PASSES:
- Document with full per-gate pass evidence
- Update edges.yml status='paused' tier='feature' → tier='alpha' (still paused; user reviews + approves activation in a separate journal_apply)
- Mark as candidate for next promotion review

If gauntlet FAILS at any gate:
- Document the failure mode (which gate, what the verdict was, t-stats)
- Edge stays at paused/feature tier
- Forward-look: what would need to change (longer holding period? earlier entry? size by parent-index-membership strength? hedge with parent short?)

Audit doc: `docs/Audit/spinoff_reversion_v1_gauntlet_2026_05_12.md`

---

## Acceptance

1. **Universe-resolver wiring** in `engines/data_manager/universe_resolver.py` (or equivalent):
   - Child tickers added to universe on distribution_date
   - Parent ticker continues trading
   - 3 tests: synthetic add, no-add-before-distribution, parent-continuity

2. **EDGAR scraper** in spinoff_detector.py:
   - Free EDGAR API integration with rate limit
   - Cached output at `data/spinoff_events_edgar.parquet`
   - Test on a small date range (e.g. 2020-01 → 2020-03)
   - Validates against known 2020 spin-offs (e.g., Otis from UTX 2020-04, Carrier from UTX 2020-04, Raytheon Tech from UTX/Raytheon merger)

3. **Combined detector output** ≥ 40 spin-off events on 2015-2024 S&P 1500.

4. **8-gate gauntlet** run on spinoff_reversion_v1:
   - All 8 gates evaluated, pass/fail recorded
   - Sharpe + Sortino + ci_low + FF5+Mom α + t-stat reported
   - Per CLAUDE.md 6th + 7th non-negotiables (CI + MBL)
   - **No threshold-lowering** — if Gate 6 fails at t > 2, document and accept

5. **Trade-level diagnostics** in audit doc:
   - Win-rate, avg holding period (should be ~90 days), avg PnL per trade
   - Per-spin-off-event PnL distribution (lumpy expected)
   - Comparison vs `momentum_factor_v1` on same window

6. **Tests** in `tests/test_spinoff_reversion_edge.py` extended:
   - All 16 T-041 tests still pass
   - 3+ new universe-resolver integration tests
   - 1+ EDGAR-cache tests

7. **Audit doc** at `docs/Audit/spinoff_reversion_v1_gauntlet_2026_05_12.md`.

8. **Edges.yml update** ONLY IF gauntlet passes: tier='alpha' (still paused; user approves activation separately).

9. **Branch:** `feature/spinoff-reversion-t041b-gauntlet`. Push only; director merges.

---

## Hard constraints

- DO NOT lower any gate threshold. Spin-offs face t > 2 like every edge.
- DO NOT auto-promote to status='active'. tier change to 'alpha' is the highest auto-action; activation requires user approval per CLAUDE.md.
- DO NOT skip the EDGAR rate limit (10 req/sec). Use exponential backoff if rate-limited.
- DO NOT cache stale EDGAR data — invalidate cache after 30 days OR on universe range changes.
- Per CLAUDE.md 6th non-negotiable: bootstrap CI on every Sharpe.
- Per CLAUDE.md 7th non-negotiable (Gate 0): include MBL check; report N_trials_consumed.

---

## Time budget

- Phase 1 (universe-resolver wiring): 2-3 hr
- Phase 2 (EDGAR scraper): 3-4 hr
- Phase 3 (8-gate gauntlet): 3-4 hr (gauntlet itself is fast; per-gate analysis takes time)
- Phase 4 (decision + audit): 1-2 hr
- **Total: 8-12 hr** (chains naturally after T-054's 2-4 hr)

---

## Open questions for implementing agent (surface in audit doc)

1. **EDGAR pulls 2015-2024 in one shot or stream?** 9 years × ~100 filings/yr ≈ 900 filings. At 10 req/sec = 1.5 min of pure throughput; with parsing overhead probably 5-10 min. Stream-write the parquet to avoid memory bloat.

2. **What if Gate 6 (FF5+Mom α t > 2) fails?** Document why. The spin-off anomaly is well-documented academically — if it fails on our substrate, possible causes: (a) academic 1990s-era result that decayed; (b) S&P 500 substrate ceiling (microcaps may be different per T-056); (c) hyperparameter mistuning (try 60d or 180d holding period in T-041c). Recommend documenting failure mode without auto-firing T-041c.

3. **Should T-041b include the spinoff-PnL-vs-parent-PnL diagnostic?** Yes — distinguishes "spinoff drift exists" from "spinoff parent also drifted same direction" (which would be a portfolio-correlation issue, not an alpha). Add to trade-level diagnostics.

4. **Universe-B substrate transfer (Gate 5)?** Spin-offs naturally vary by universe — small-cap spinoffs are different from large-cap. Recommend testing on Russell 1000 subset of S&P 1500 events as the Universe-B. Document.

5. **DSR with what trial count?** Per the MBL math: include T-041's prior 13-curated test as N=1; T-041b is N=2. The DSR penalty is modest at small N. If T-041b passes, T-041c hyperparameter sweeps would bloat N — keep those for separate dispatches.

---

## Forward-look

If T-041b passes gauntlet:
- T-041 lifecycle: paused/feature → paused/alpha → (user approval) → active/alpha
- First retail-only structurally-non-factor active edge in the project's history
- Validates the alpha-research dive's substrate-agnostic event-driven thesis
- Template for T-056b (spinoffs on microcap substrate) + future event-driven sleeves (CEF discount + Saba piggyback, hand-curated merger arb)

If T-041b fails gauntlet:
- Informative — spin-off anomaly on liquid US substrate may be priced
- Re-test on microcap substrate (T-056b after T-056 lands) before declaring the strategy dead
- Adjust hyperparameters (T-041c) only if there's a specific hypothesis (e.g., "150-day hold vs 90-day captures more drift")

---

## Director note

This is A's natural chain follow-up to T-054. Recommend dispatching as a SECOND task in A's chain (T-054 → T-041b) IF the user wants continuous agent throughput. Alternative: hold T-041b until T-054 lands and Phase 0/MBL/T-043 implications are reviewed.

The user's "bones must be PERFECT before LLM" directive supports dispatching T-041b — it's bones-level work (validation pipeline) for a structurally-different edge category.
