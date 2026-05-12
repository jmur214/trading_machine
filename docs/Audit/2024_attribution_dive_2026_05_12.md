---
title: 2024 Attribution Dive — what drove the corrected -0.613 Sharpe
date: 2026-05-12
author: director (post-T-035)
data_source: T-035 corrected trade logs (cockpit-bug-free), rep 1 of each year (3/3 reps bitwise identical so any rep is canonical)
status: director-side analysis (not an agent dispatch)
---

# 2024 Attribution Dive — why the corrected Arm 1 Sharpe is -0.613

## TL;DR

T-035 corrected 2024 from a reported Sharpe of +0.236 (cockpit-bug-contaminated) to **-0.613 (true)**. The corrected number is real fragility, not statistical noise. The post-hoc attribution surfaces **two findings of materially different severity than the raw "bad year" framing**:

1. **3 of the 6 active edges are net-negative over 5 full years**, not just 2024. The cockpit bug had been hiding this for the entire engines-first arc. (`value_earnings_yield_v1`, `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1` are 5-year-cumulative LOSERS in dollar PnL.)
2. **2024 was a regime event (value-vs-growth divergence) compounded by a single black-swan day (Aug 5 yen carry unwind).** ~60% of August's loss and ~22% of the annual loss came from one trading day.

The right next-step interpretation is therefore split: (a) Engine F lifecycle should see this data and autonomously retire the 3 net-negative edges (do NOT manually edit; Engine F is the authority per CLAUDE.md), and (b) the regime-conditional defensive layer (Engine E HMM + Engine B regime-driven de-grossing) just became urgent — not speculative future work — because the system has a documented failure mode in 2024-style regimes.

## Per-edge PnL, all 5 years ($, rep 1)

```
                              2021  2022  2023  2024  2025  5-yr cum
volume_anomaly_v1             1733  1239   626   -66   995    +4527  ← winner, 4/5 yrs +
gap_fill_v1                   1158  1202   225   205   620    +3410  ← winner, 5/5 yrs +
value_book_to_market_v1       3006   -78   306  -992  -161    +2081  ← mixed; 2021 carried it
news_sentiment_edge              0     0     0  -119     0     -119  ← paused 0.25x, immaterial
Unknown                        -84    21     0    23    31       -9  ← noise
accruals_inv_asset_growth_v1   -36  -535   843  -487  -444     -659  ← 5-yr LOSER
accruals_inv_sloan_v1          536  -790   800  -856 -1314    -1624  ← 5-yr LOSER
value_earnings_yield_v1       -357 -1179  1215 -1752  -280    -2353  ← 5-yr BIGGEST LOSER
```

Total realized PnL 5-yr (rep 1, single-arc, ~$100K starting capital each year): **+$5,254** across all edges.

If the 3 net-negative edges had been retired going into 2021: **+$10,018** (86% lift in dollar PnL). The 3 losers consumed nearly half of what the 3 winners produced.

## Per-edge win-rate trajectory (rep 1)

```
                              2021  2022  2023  2024  2025
volume_anomaly_v1              75%   71%   73%   60%   72%    consistently >60%
gap_fill_v1                    80%   66%   62%   73%   65%    consistently >60%
value_book_to_market_v1        59%   45%   53%   35%   50%    deteriorated in 2024
value_earnings_yield_v1        49%   38%   53%   35%   49%    never above 53%; 4/5 yrs sub-50%
accruals_inv_sloan_v1          53%   36%   55%   41%   38%    high variance, 3/5 yrs sub-50%
accruals_inv_asset_growth_v1   52%   41%   60%   41%   48%    only 2021+2023 above 50%
```

**Winners have stable >60% win rates across regimes. Losers cluster in the 35-55% band and are regime-dependent.**

The three losers' only material winning year was **2023** — a broad-based recovery year where 6/6 edges were positive. They produce real PnL in benign regimes and bleed in everything else. That's the definition of an edge that doesn't generalize.

## 2024 monthly cumulative PnL (rep 1)

```
month        n_closes   pnl    win%    cum
2024-01         168     -29   45.2     -29
2024-02         128    +232   50.0    +204
2024-03          58    +423   72.4    +626    ← Q1 +$626 (clean)
2024-04         151  -1,350   25.8    -724    ← rate-cut expectations pushed out
2024-05         160    -936   25.6  -1,660    ← value-vs-growth widens
2024-06          52    -119   36.5  -1,779
2024-07         183    +885   61.7    -894    ← July recovery
2024-08         152  -2,880   16.4  -3,774    ← Aug 5 yen carry unwind
2024-09          97    +396   53.6  -3,378
2024-10          96    -234   41.7  -3,612
2024-11         158    +606   62.7  -3,006
2024-12         148  -1,038   18.9  -4,043    ← Fed hawkish dot plot 12/18
```

**Q1: +$626** (clean). **Q2: -$2,405**, **Q3: -$1,598**, **Q4: -$666**. 3 of 4 quarters negative. Not a "Q4 election fear" story; this is **persistent multi-quarter pain** with two acute days.

## The two worst days

| Date | Event | SPY return | Our PnL |
|---|---|---|---|
| 2024-08-05 | Yen carry trade unwind, VIX intraday to 65, Nikkei -12% | -2.91% | **-$2,440** (single worst day; 76 closes, 6.6% win rate) |
| 2024-12-18 | Fed dot-plot showed only 2 cuts in 2025 vs expected 4 | -2.98% | **-$844** |

Aug 5 alone = 60% of August's -$2,880 and 22% of the annual -$4,043. SPY recovered from both days within weeks. **Our system did not** — the post-Aug rally was AI/Mag-7 driven and our value/quality positions stayed bid-less.

## Tracking error vs SPY 2024

SPY 2024 return: **+25.59%** (Q1 +11.01, Q2 +4.38, Q3 +5.75, Q4 +2.49).
Our system 2024 CAGR: **-2.68%**.
**Tracking gap: -28.27 percentage points.**

This is the largest annual tracking error in the 5-year T-035 panel. 2024 was a Mag-7-AI-rally / growth-dominated regime where value + quality factors structurally lagged. **Our 6-edge active set is 4 V/Q/A edges.** We were essentially long-the-anti-Mag-7 in a Mag-7-driven year, with no regime gating to recognize the misalignment.

## Per-year edge-survival count

How many of the 6 active edges had positive PnL each year (rep 1)?

| Year | Survivors | Total PnL | Story |
|---|---|---|---|
| 2021 | 4/6 | +$5,956 | Strong bull, broad-based winners |
| 2022 | 3/6 | -$120 | Bear, mixed; flat overall |
| 2023 | 6/6 | +$4,015 | Recovery year — every edge worked |
| 2024 | 2/6 | -$4,044 | Value-vs-growth divergence; only gap_fill + volume_anomaly survived |
| 2025 | 3/6 | -$553 | Mixed; only volume + gap + book-to-market positive |

2024 is the worst-survival year (2/6) and the worst-PnL year (-$4,044). 2023 (6/6) is the only year where the 3 losing edges all produced.

## What changed (and didn't) from this analysis

### What CHANGED

1. **3 of 6 active edges are 5-year losers in dollar PnL.** The cockpit bug had been hiding this — peak_equity in the equity slot made the cumulative losses invisible in the Sharpe summaries. With the fix landed, Engine F lifecycle can now see the true per-edge contribution.

2. **2024's -0.613 is not noise.** It's the visible manifestation of a regime where 4 of our 6 edges are systematically wrong-side of the dominant factor flow, with no defense layer. Removing the cockpit bug uncovered a real failure mode.

3. **Engine E (regime detection) + Engine B (regime-conditional de-grossing) work just became urgent**, not future engines-first scope. The corrected baseline has a documented failure mode the system has no current defense against.

### What DID NOT CHANGE

1. **The engines-first directive holds.** Engines C/D/E are still scaffolding; the response to 2024-style fragility IS engine completion. This audit doesn't suggest abandoning the directive — it sharpens which engine work is most urgent.

2. **The 0.598 corrected baseline holds.** It's still the comparison point for engine-completion lift. The fact that 3 edges contribute negatively over 5 years doesn't move the headline (those losses are already baked in to 0.598).

3. **CLAUDE.md governor rules hold.** Engine F manages lifecycle autonomously. We do NOT manually edit `edges.yml` to retire `value_earnings_yield_v1` etc. We dispatch Engine F lifecycle to re-evaluate per-edge contribution under cockpit-fixed measurement. Per the existing `lifecycle_manager.py` retirement gate (sharpe < benchmark - 0.3), these edges should naturally fall out.

## Forward implications for the spec dispatch decision

The 4 specs from earlier today (T-039, T-040, T-041, T-042) all remain valid. This audit adds **one more candidate spec to consider**:

- **T-043 candidate**: Engine F lifecycle re-evaluation on cockpit-fixed trade logs. ~2-3 hr. Re-runs `lifecycle_manager.evaluate_retirement()` with the corrected per-edge Sharpes. Expected outcome: `value_earnings_yield_v1`, `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1` are flagged for auto-retirement. Engine F still makes the call — director just makes sure the corrected data reaches it.

This is the cleanest forward action from this audit. It does NOT modify Engine F logic, does NOT modify edges.yml manually, just re-runs the existing retirement-evaluation logic on data that's no longer corrupted by the cockpit bug.

Sequencing this against the other 4 specs:

| Spec | Effort | Unblocks | Priority post-2024-attribution |
|---|---|---|---|
| T-040 (Parquet migration) | 6-8 hr | Disk pressure structural fix | **high** — disk pressure recurs every measurement; T-036 in flight will refill what Phase 1 cleared |
| T-043 (Engine F lifecycle re-eval) | 2-3 hr | Autonomous retirement of 3 losing edges | **HIGH — net most-leverage action from this audit** |
| T-041 (spin-offs) | 10-14 hr | First retail-only structural edge | medium — opens a new alpha category |
| T-039 (observability relocation) | 4-6 hr | Cleans up post-T-034 structural debt | medium |
| T-042 Phase 1 (input audit) | 3 hr | Surveys insider/short-interest/GDELT | medium |

The cleanest sequence (post A's chain completing):

1. T-043 (~2-3 hr) — let Engine F retire the 3 losing edges with corrected data.
2. T-040 (~6-8 hr) — Parquet migration; one-time canon rebaseline event.
3. T-039 + T-042 Phase 1 in parallel (no overlap).
4. T-041 + T-042 Phase 2 after user reviews Phase 1 audit.

## Open questions surfaced

1. **Should T-043 be expanded into a Phase 2 that re-runs Arm 1 with the 3-edge "surviving set" to see the corrected-baseline lift?** Probably yes — that's the "did engine work matter" baseline for the 3-edge case. ~3-4 hr extra. Document as T-043b.

2. **Is `value_book_to_market_v1` a real winner or just a 2021 fluke?** It carries a 5-year cumulative +$2,081 but $3,006 of that came from 2021 alone. Without 2021, it's net -$925 over 4 years. Worth re-examining in a separate dispatch — possibly it's regime-conditional like the 3 losers but with a different threshold. Document as T-044 candidate.

3. **Why is `gap_fill_v1` so robust across regimes?** 5/5 positive years, win rate 62-80% always above 60%. Different signal mechanism than the V/Q/A bucket (it's a mean-reversion / microstructure edge, not a fundamentals edge). Worth understanding what made it work in 2024 when everything else failed — possible template for what a "retail-survival" edge looks like in our framework.

4. **Should regime detection (Engine E HMM) input panel rebuild jump to highest priority?** Per the 2026-05-06 memory entry, HMM was found COINCIDENT not predictive. The required unblock was rebuilding the input panel with leading features. T-042 Phase 2's GDELT feature is on that path. After T-035 made the failure mode visible, HMM-panel work should arguably accelerate. Worth a director-side memory note + forward_plan update.

## Files referenced

- T-035 results: `/Users/jacksonmurphy/Dev/trading_machine-agent-a/data/measurements/substrate_arm1_cockpit_fixed_2026_05_12/arm1_results.json`
- 2024 rep-1 trade log: `data/trade_logs/66bbaecc-2f40-4c90-b79f-4828fa234237/trades.csv`
- 5-year trade logs (rep 1): 2021 `e5e95c32-...` (gzipped), 2022 `48d8fb51-...`, 2023 `c9a5dbd0-...`, 2024 `66bbaecc-...`, 2025 `01f06c0a-...`
- T-035 audit: `docs/Measurements/2026-05/substrate_honest_arm1_cockpit_fixed_2026_05_12.md`
- SPY price source: `data/processed/SPY_1d.csv`
