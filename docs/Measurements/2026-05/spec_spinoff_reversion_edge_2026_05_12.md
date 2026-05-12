# Spec — T-2026-05-12-041: Spin-off reversion edge (`spinoff_reversion_v1`)

**Date drafted:** 2026-05-12 (director-side, ~45 min)
**Status:** SPEC for approval. Engine A only — autonomous-improvement category per CLAUDE.md (no propose-first required for new Engine A edges), but spec drafted for user visibility before dispatch given novelty.
**Will be executed by:** Agent A or B (~10-14 hr).
**Sequencing:** can run in parallel with T-040 (different file surfaces). After A's current measurement chain lands.
**Output:** New edge + spin-off event detector + universe-honest backtest harness integration + gauntlet validation + audit doc.

---

## Why now

The current Engine A alpha library is 100% institutional-quant patterns: RSI bounces, value/quality/momentum factors, calendar anomalies, earnings vol, short-term reversal. T-029 factor decomp found **0/11 active edges clear FF5+Mom α at t > 2** — every edge we've measured is essentially re-expressing known factors, which is exactly where institutions have already arbitraged the easy money. At our AUM ($5-15K range per the retail-capital-constraint memory entry), trying to compete with institutional quants on their home turf is the wrong objective function.

**The structural retail advantage is in places institutions cannot or will not trade.** Spin-offs are the cleanest example:

- **Forced institutional selling.** When a parent spins off a subsidiary, index funds tracking the parent's index automatically dump the spin-off (it's not in their index until the next rebalance). Active managers benchmarked to the parent's index do the same. This is mechanical, non-fundamental selling pressure that drives the spin-off below fair value in the weeks immediately post-distribution.
- **Documented anomaly with academic backing.** Cusatis-Miles-Woolridge (1993) found spin-offs outperform their industry peers by ~10% annualized in the 3 years post-distribution. Greenblatt (1997, *You Can Be a Stock Market Genius*) popularized the trade for retail readers — still works because the structural cause (index-fund forced selling) hasn't changed.
- **Data is free.** SEC EDGAR has every Form 10 / 10-12B filing. yfinance's `Ticker.actions` captures stock-split-style distributions. No expensive data vendor needed.
- **Holding period is tax-friendly.** 90-180 day holds with intent to hit long-term cap gains. Wash-sale gate (already in Engine B) cleanly compatible.
- **Capacity-friendly.** Spin-offs are typically small-to-mid cap. Institutions can't trade them at size; retail at $15K can. Inversely, this same property means the edge does NOT scale to institutional capital, which is why it survives.

Adding ONE retail-only edge to the alpha library is a different bet than the current "more value/quality/momentum variants" trajectory. It opens a category we have zero exposure to. The downside: novel implementation work (event detection, point-in-time universe handling) is harder than another momentum tweak. The upside: the math is doing something institutions structurally can't.

---

## What

Six components:

### 1. Spin-off event detector

`engines/engine_a_alpha/edges/_helpers/spinoff_detector.py`

Sources, in priority order:
1. **yfinance** `Ticker.actions` — flags "stock split" distributions including spin-offs (the spin-off is treated as a special dividend distribution to the parent's holders). Free, fast.
2. **SEC EDGAR** Form 10 / 10-12B filings — definitive registration-statement source. Slower (HTTP scrape EDGAR API) but authoritative.
3. **Manual override list** at `data/spinoff_events_curated.yml` — known historical spin-offs for backfill validation (Ferrari from Fiat 2016, KBR from Halliburton 2007, Yum Brands → Pizza Hut 2016, etc.). User-maintainable.

Detector output schema:
```python
@dataclass
class SpinoffEvent:
    parent_ticker: str
    child_ticker: str
    distribution_date: pd.Timestamp  # day-of-spinoff
    distribution_ratio: float        # shares of child per share of parent
    source: str                      # 'yfinance' | 'edgar' | 'curated'
    confidence: float                # 1.0 for curated/edgar, 0.7 for yfinance-only
```

### 2. Universe-honest backtest integration

Critical correctness:
- A spin-off only becomes tradeable on `distribution_date`. Backtest universe must include the child ticker FROM that date, not retroactively.
- Parent ticker continues trading throughout (don't accidentally drop the parent).
- Spin-off events outside the backtest window are filtered out.

Wire into `data_manager/universe_resolver.py` (or equivalent) — when resolving the daily universe, check the spin-off-event table and ADD the child ticker on its distribution_date.

### 3. Edge implementation

`engines/engine_a_alpha/edges/spinoff_reversion_v1.py`:

```python
class SpinoffReversionEdge(Edge):
    """Long the spin-off child in the post-distribution selling window.

    Signal: every spin-off event in the universe → BUY child ticker at
    distribution_date + entry_offset days, hold for holding_period days,
    then EXIT.

    Hyperparameters (initial guess; subject to Discovery refinement):
      entry_offset = 3 days   # let initial dumping start; avoid the day-of chaos
      holding_period = 90 days
      max_concurrent_positions = 5  # diversification across concurrent spin-offs
      stop_loss_pct = 0.15           # mechanical floor (Engine B will refine)
    """
```

Signal generation:
- On each bar, check if (distribution_date + entry_offset) == today for any event in detector output.
- If yes, emit a BUY signal for child ticker with score=1.0 (binary, not magnitude — there's no "stronger" or "weaker" spin-off in this model).
- Track open positions; emit EXIT signal at (entry_date + holding_period).

### 4. Substrate-honest universe handling

Test that pre-existing tickers in the universe (parent) don't suddenly disappear or change behavior on distribution_date. The parent should trade normally; only the child is added.

Edge case: re-listings, ticker symbol changes post-spinoff. Document expected handling.

### 5. Backtest evidence

Standalone Gate 1 + 8-gate Discovery gauntlet (same path every new edge goes through):

- Backtest 2015-2024 substrate-honest, journal-mode (no auto-promotion)
- 3-rep deterministic harness via `scripts.run_isolated`
- Bootstrap 95% CI on Sharpe + Sortino (per CLAUDE.md 6th non-negotiable)
- FF5 + Mom factor decomp on returns; report α + t-stat
- Substrate-transfer test (universe-B Gate 5): does edge generalize beyond F6 historical S&P 500?
- Permutation null test (Gate 4): is the Sharpe materially above randomized-trigger baseline?

### 6. Audit doc + state-doc updates

- `docs/Measurements/2026-05/spinoff_reversion_v1_backtest_2026_05_12.md`
- If gauntlet PASSES: append entry to `docs/State/health_check.md` and `lessons_learned.md`.
- If gauntlet FAILS: document the failure mode and the next-step hypothesis (hold longer? entry earlier? size by parent index-membership strength?). Edge stays in `data/governor/edges.yml` at `status='failed'`, NOT deleted.

---

## Acceptance

1. **Spin-off detector:**
   - `spinoff_detector.py` produces ≥40 spin-off events on 2015-2024 in S&P 1500 universe.
   - 5+ known events (Ferrari, KBR, Yum, etc.) appear in the detector output (validation set).
   - Distribution dates within ±2 trading days of authoritative source (EDGAR or news archive).

2. **Universe integration:**
   - On a synthetic test substrate, child tickers appear in universe ON their `distribution_date`, not before.
   - Parent ticker continues trading throughout.

3. **Edge implementation:**
   - `spinoff_reversion_v1.py` matches the `Edge` base class interface.
   - 3-rep bitwise deterministic via `scripts.run_isolated --runs 3`.
   - Generates ≥40 BUY + ≥40 EXIT signals on the 2015-2024 substrate.

4. **Gauntlet:**
   - Edge runs through 8-gate Discovery gauntlet.
   - Pass/fail decision per usual gates. **No goalpost-moving**: t > 2 α threshold applies the same as every other edge.
   - If FAIL on FF5+Mom α: do NOT lower the threshold. Document the failure; the edge stays in archive for future Discovery re-evaluation under different hyperparameters.

5. **Sharpe headline:**
   - Reports `ci_low`, not just `point_estimate`, per CLAUDE.md.
   - Compared head-to-head with `momentum_factor_v1` (closest analog: cap-weighted single-name long bet) on same window.

6. **Tests** in `tests/test_spinoff_reversion_edge.py`:
   - `test_detector_finds_ferrari_2016` — Ferrari (RACE) appears in detector output on 2016-01-04
   - `test_detector_finds_kbr_2007` — KBR appears on 2007-04-05
   - `test_universe_adds_child_on_distribution_date` — synthetic test
   - `test_universe_does_not_add_child_before_distribution_date` — look-ahead guard
   - `test_edge_emits_buy_on_entry_offset` — signal timing
   - `test_edge_emits_exit_after_holding_period` — exit timing
   - `test_edge_handles_zero_events_in_window` — empty-input case
   - `test_curated_overrides_yfinance_disagreement` — manual list takes precedence
   - 3-rep determinism integration test

7. **Audit doc** at `docs/Measurements/2026-05/spinoff_reversion_v1_backtest_2026_05_12.md`:
   - Event-detector validation table (5+ known events checked)
   - Backtest Sharpe + Sortino + ci_low + FF5+Mom α + t-stat
   - Gauntlet per-gate verdict
   - Trade-level diagnostics: win-rate, avg holding period, avg PnL per trade, drawdown profile
   - Comparison vs `momentum_factor_v1` on same window
   - Forward-look: hyperparameter sensitivity (entry_offset ∈ {1, 3, 5, 7}, holding_period ∈ {60, 90, 120, 180})

8. **Branch:** `feature/spinoff-reversion-edge`. Push only; director merges.

---

## Hard constraints

- DO NOT modify Engine B, Engine C, Engine D, Engine E, or Engine F. Pure Engine A addition.
- DO NOT auto-promote to `status='active'` even if gauntlet passes. Journal-mode only; user reviews + decides activation.
- DO NOT use look-ahead data. Spin-off events must only be visible to backtest AT and AFTER `distribution_date`.
- DO NOT extend the universe to include OTC / pink sheets — spin-offs sometimes list there briefly before getting an NYSE/NASDAQ symbol. Out of scope.
- Bootstrap CI on every Sharpe/Sortino headline per CLAUDE.md 6th non-negotiable.
- Substrate honesty: F6 historical S&P 500 union universe (existing) plus spin-off children added at distribution date. NOT retroactive.

---

## Time budget

10-14 hr total:
- Detector implementation (yfinance + EDGAR + curated): ~3 hr
- Universe-honest integration: ~2 hr
- Edge implementation: ~2 hr
- Tests: ~2 hr
- Gauntlet run + measurement: ~2 hr
- Audit doc + state-doc updates: ~2 hr
- Debugging buffer: ~1-3 hr

---

## Open questions for the implementing agent

1. **EDGAR rate limiting.** EDGAR's API allows 10 req/sec. Building a full 2015-2024 spin-off list requires ~500+ filings. Implementer should rate-limit via a queue + sleep. Document the wall-time cost.

2. **What if yfinance and EDGAR disagree on `distribution_ratio`?** RECOMMEND: prefer EDGAR (authoritative); flag the disagreement in the detector output for manual review; default to curated list if user has added an override. Document the policy.

3. **Holding period default: 90 or 180 days?** Greenblatt's classic recommendation is 6-12 months. 90 is more conservative. RECOMMEND 90 for v1; sensitivity sweep in audit doc shows whether longer helps. Document the choice.

4. **`max_concurrent_positions = 5` — is this the right cap?** Spin-offs cluster around tax year-ends. Without a cap, the edge could go from 0% to 80% of portfolio in one week. With cap=5 and equal weighting, each position is 20% of edge allocation (Engine C will further scale by edge weight). RECOMMEND keep at 5 for v1; sensitivity in audit doc.

5. **Should the edge hedge with a parent short?** Greenblatt-style trade is unhedged (spin-off long only). Pair-trade variant (long child / short parent) is more complex; not v1. Document as forward-look (T-041b).

6. **What about distribution-ratio noise?** Some spin-offs distribute 0.5 shares per parent share, others 0.1, etc. Does this matter for sizing? RECOMMEND: ignore for v1 — Engine C handles position sizing post-signal. Document.

---

## Forward-look (T-041b candidates)

After T-041 lands:

- **T-041b**: Long-child/short-parent pair-trade variant if v1 shows positive but volatile single-side returns. ~4-6 hr.
- **T-041c**: IPO lockup expiry edge (similar mechanic: forced-selling supply shock with known calendar). ~6-8 hr.
- **T-041d**: Index reconstitution edge (S&P 600/Russell rebalance). ~8-10 hr — calendars from S&P + FTSE Russell.

These three retail-only edges together establish a "retail-structural" alpha category, complementing the existing institutional-quant-flavored library.

---

## Director note

This is a NEW alpha edge in Engine A — per CLAUDE.md autonomous-improvement allowance, this category does NOT require user propose-first sign-off. Drafting spec for visibility because it's a categorically different bet than the existing alpha library (retail-only edge category).

When ready to dispatch:
1. Director writes the brief to an agent's inbox using this spec as the canonical source.
2. Agent executes; director merges + pushes after review.
3. If gauntlet passes, user decides activation timing (journal-mode default).
