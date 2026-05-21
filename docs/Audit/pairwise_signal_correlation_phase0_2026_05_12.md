---
title: Phase 0 — Pairwise raw-signal correlation diagnostic
date: 2026-05-12
author: director (post-research-synthesis)
data_source: existing PerTickerScoreLogger output at data/research/per_ticker_scores/695b0b21-18f0-4493-b593-e62abf091519.parquet
status: director-side analysis (no agent dispatch); the highest-leverage single diagnostic per all four 2026-05-16 research dives
gate_decision: SIGNAL-DIVERSITY PROBLEM CONFIRMED — fire follow-up actions
---

# Phase 0 — Pairwise Raw-Signal Correlation Diagnostic

## TL;DR — the gate FIRED

The 2026-05-16 multi-strategy research dive specified the highest-leverage single diagnostic: pairwise rank correlation matrix of the active edges' RAW SIGNAL SCORES (not return streams). Decision tree:

- If max ρ > 0.5 OR avg ρ > 0.3 → **signal-diversity problem; no aggregator change can rescue this stack**
- Otherwise → substrate or sample-size is the binding constraint

**Result on existing per-ticker score logs (1.85M rows, 10 actively-firing edges from a 2024-era snapshot, 2021-2024 substrate):**

| Approach | avg \|ρ\| | max \|ρ\| | Gate decision |
|---|---|---|---|
| **Per-day cross-sectional mean** | 0.156 | **0.947** | **FIRED** |
| **Per-(ticker, date) panel (Spearman)** | 0.098 | **0.622** | **FIRED** |

The avg-|ρ| threshold of 0.3 is NOT exceeded under either approach, but the **max-|ρ| threshold of 0.5 is exceeded under both**. This satisfies the dive's "OR" trigger. **Signal-diversity problem confirmed.**

## The high-correlation pairs (per-(ticker, date) panel)

| Pair | ρ | Interpretation |
|---|---|---|
| `bollinger_reversion_v1` ↔ `rsi_bounce_v1` | +0.622 | **Technical mean-reversion twins** — same dynamic, different oscillator |
| `pead_predrift_v1` ↔ `pead_v1` | +0.588 | **PEAD twins** — same earnings-drift signal, different timing windows |
| `momentum_edge_v1` ↔ `rsi_bounce_v1` | -0.494 | Momentum vs mean-reversion (anti-correlation expected; still co-determined) |
| `bollinger_reversion_v1` ↔ `momentum_edge_v1` | -0.416 | Same anti-correlation dynamic |
| `gap_fill_v1` ↔ `volume_anomaly_v1` | +0.314 | Both react to single-day volume/price anomalies |

## What this means

The system's "10 actively-firing edges" in this snapshot are mathematically **~6-7 distinct signal clusters**, not 10. Specifically:

- PEAD has 3 sibling variants (`pead_v1`, `pead_predrift_v1`, `pead_short_v1`) → effective standalone PEAD count ≈ 1 (the highest at ρ=0.59 is duplicative; pead_short is anti-correlated)
- Technical mean-reversion has 2 (`bollinger`, `rsi_bounce`) at ρ=0.62 → effective count ≈ 1
- Momentum (`momentum_edge_v1`) is anti-correlated with both mean-reversion variants — it's a real third bucket but co-determined with the mean-reversion bucket
- Gap fill / volume anomaly cluster lightly (ρ=0.31)

## What the research dive says happens at these correlation levels

From the dive's Grinold-Kahn math:

| ρ (avg pairwise) | Combined IR for 6 edges at IR₀=0.316 (t=1 individual) | Combined 10-yr t |
|---|---|---|
| 0.0 | 0.775 | 2.45 |
| 0.2 | 0.548 | 1.73 |
| 0.4 | 0.450 | 1.42 |
| 0.5 | 0.414 | 1.31 |

At max ρ ≈ 0.6 between technical-mean-rev pairs, the effective combined t-stat for that cluster is **mechanically capped well below the t=2 deployment bar regardless of aggregator topology**. Linear weighted sum cannot save it. Gradient boosting cannot save it. Bayesian opt cannot save it.

**The literature is unanimous: at correlation levels these high, the fix is signal diversity, NOT aggregator method.**

## Important caveats

### 1. The captured log has the OLDER edge set, not the current 6 actives

This particular per-ticker score parquet was generated 2026-04-30, so it predates several edge-set changes that landed in May 2026 (C-collapses cleanup, paused-tier retirements). It contains 10 actively-firing edges of a 17-edge snapshot, of which only **2 are in the current 6 active set**:
- `volume_anomaly_v1`
- `gap_fill_v1`

The current 6 actives include 4 V/Q/A fundamental edges (`value_earnings_yield_v1`, `value_book_to_market_v1`, `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1`) NOT present in this captured panel.

### 2. The current 6 actives are almost certainly MORE correlated than what this panel shows

By construction:
- All 4 V/Q/A edges derive from SimFin fundamentals (same data source)
- The 2 accruals variants share most of their computation (different denominator)
- The 2 value variants share most of their computation (different denominator: earnings yield vs book-to-market)
- T-036's per-regime factor decomp already showed all 4 are UNIFORMLY NEGATIVE on factor-adjusted α — strong indication they're all loading on the same factor exposures

**Prior**: the current 6-edge raw-signal correlation matrix is at least as bad as the 0.622 max in this panel, plausibly with the 4 V/Q/A edges clustering at ρ > 0.7 among themselves.

### 3. The structural finding is established regardless

The 10-edge panel here gives a real, quantitative measurement of how the system's signals cluster. The fact that even this 10-edge older snapshot fires the gate is sufficient evidence that:

- The multi-edge architecture's central thesis (combining weak signals produces alpha) has been operating against signal substrates with effective standalone count < raw count
- The 0/11 factor-α verdict makes mechanical sense at these correlation levels
- All aggregator iteration on this signal substrate has been wasted DSR budget

## Forward actions per the research dive's decision tree

The dive specified the action when the gate fires:

> "Replace the worst-correlated pair with one orthogonal signal — most plausibly a regime feature (VIX level, term spread, 200-day SMA slope) or a fundamentally different substrate (futures trend, options-vol-crush, event-driven) — BEFORE changing the aggregation function."

Mapped to our project's current dispatch queue:

| Action | Status |
|---|---|
| **Prune redundant signal pairs from active set** | NEW — should be queued. Either pead_predrift_v1 OR pead_v1 (keep one). Either bollinger_reversion_v1 OR rsi_bounce_v1 (keep one). This is Engine F lifecycle territory — T-043 should add this to its scope. |
| **Add orthogonal regime features to Foundry** | T-052 (B's chain second task) does exactly this: VIX/VIX3M, EBP+HY OAS, ANFCI, Faber multi-asset trend. Confirmed correctly prioritized. |
| **Pivot to a different substrate (microcap)** | First alpha dive's #1 recommendation. NOT in current dispatch queue. Pending user approval on Norgate $80/mo. |
| **Pause aggregator iteration (Bayesian opt, MetaLearner variants, HRP slices)** | Already paused per B's T-038-CONT brief; the Engine D infrastructure work (vectorize seed_from_foundry) is durable regardless. |
| **Re-run this diagnostic on current 6 actives** | NEW — should be queued. Requires fresh substrate-honest backtest with `PerTickerScoreLogger` enabled. ~2-3 hr. Confirms or refines the prior above. |

## Recommendation to user

**Phase 0 verdict: signal-diversity problem CONFIRMED on the available panel. The current actives are almost-certainly worse.**

Two immediate forward actions are independent and can be done in parallel:

1. **T-043's scope expands** — in addition to factor-α gate, Engine F lifecycle should consider signal-correlation as a retirement criterion. If two active edges have raw-signal ρ > 0.6, the lower-Sharpe one is the prune candidate.

2. **A fresh per-ticker-score-log capture on the current 6 actives** is worth ~2-3 hr to confirm the strong prior. Could be a director-side smoke run OR added to one of the in-flight chains.

The big strategic answer (microcap substrate? LLM unpark? more event-driven sleeves?) is a USER decision; this diagnostic just confirms the mathematical necessity that those decisions become urgent.

## Files

- Input: `data/research/per_ticker_scores/695b0b21-18f0-4493-b593-e62abf091519.parquet`
- This audit: `docs/Audit/pairwise_signal_correlation_phase0_2026_05_12.md`
- Cited research: `docs/Sources/Alpha/Retail-algo-alpha_follow-up_multi-strat.md` §11 ("The single most consequential finding for your situation")
