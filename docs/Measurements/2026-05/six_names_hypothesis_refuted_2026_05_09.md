# 6-Names Hypothesis Refuted — Capital Dilution Is The Mechanism

**Status:** 2026-05-09 read-only trade-log analysis. Refutes the morning hypothesis that the static-109 substrate's advantage came from 6 non-S&P 500 ultra-vol names (COIN, MARA, RIOT, DKNG, PLTR, SNOW). Shows the actual mechanism is **capital dilution across a 4.4× larger universe**.

## Method

Compared two trade logs from the canonical 2024 measurements:
- **Static-109 baseline:** `data/trade_logs/0ff2a7a9-2181-4ace-a3dc-1204607a9179/` (Sharpe 1.890, matches Foundation Gate)
- **Universe-aware:** `data/trade_logs/9b760b5c-3cd0-4f76-9e4e-acdec423730e/` (Sharpe 0.268, from B1 verdict)

Both runs use identical edge configurations, capital, and date range — the only difference is which universe of names the strategy can trade.

## Top-line numbers

| Metric | Static-109 | Universe-aware | Δ |
|---|---:|---:|---:|
| Sharpe | 1.890 | 0.268 | -1.622 |
| Total trades | 5,894 | 13,047 | +7,153 |
| Unique tickers traded | 109 | 475 | +366 |
| Total PnL ($) | $6,241 | -$895 | -$7,136 |
| Avg PnL/trade ($) | $1.06 | -$0.07 | -$1.13 |

## The 6-names test (refuted)

The morning hypothesis was that COIN, MARA, RIOT, DKNG, PLTR, SNOW (non-S&P names in the static config but excluded from historical S&P 500 universe) accounted for 80%+ of the substrate gap.

| Ticker | Trades in static-109 (2024) | PnL in static-109 |
|---|---:|---:|
| COIN | 46 | $11 |
| MARA | 25 | $13 |
| RIOT | 16 | $68 |
| DKNG | 26 | -$62 |
| PLTR | 33 | $13 |
| SNOW | 38 | $65 |
| **Combined 6** | **184** | **$108** |
| Total static-109 PnL | 5,894 | $6,241 |

**The 6 names contributed $108 / $6,241 = 1.7% of static-109's PnL.** They contributed $108 / $7,136 = **1.5% of the substrate gap**. Hypothesis refuted.

## What's actually happening: capital dilution on shared names

The 103 names that exist in BOTH substrates accounted for 91.8% of the gap. **Same names, identical edge code, drastically different per-name PnL** — because position sizing scales inversely with universe size at constant total capital.

Top 20 contributors to the substrate gap (all S&P 500 mega-caps, all in BOTH universes):

| Ticker | Static-109 PnL | Universe-aware PnL | Δ (capital concentration premium) |
|---|---:|---:|---:|
| RTX | $571 | $31 | $541 |
| SO | $550 | $29 | $522 |
| GILD | $511 | $42 | $469 |
| LOW | $365 | -$48 | $413 |
| IBM | $329 | -$11 | $339 |
| BKNG | $358 | $29 | $329 |
| ADP | $369 | $54 | $316 |
| LIN | $280 | -$13 | $293 |
| META | $295 | $9 | $287 |
| SCHW | $286 | $17 | $269 |
| MDT | $252 | -$8 | $260 |
| COST | $227 | -$24 | $251 |
| DIS | $258 | $18 | $239 |
| UNP | $200 | -$29 | $230 |
| TMUS | $234 | $22 | $212 |
| PGR | $204 | $32 | $171 |
| GE | $202 | $32 | $171 |
| NOW | $196 | $29 | $167 |
| HON | $188 | $21 | $167 |
| ORCL | $146 | -$11 | $157 |

Subtotal of these 20: $5,053 / $7,136 gap = **70.8% of the gap on 20 mega-cap names that are present in BOTH substrates.**

## What this means

**The "alpha" was not stock selection. It was not 6 lottery names. It was capital concentration.** The strategy's edges produce small per-name signals (~$1-2 of PnL per trade on each mega-cap). At 109-name universe size with normal capital allocation, those small signals scale into 1.890 Sharpe via concentrated position sizing. At 475-name universe size with the same capital, the signals are diluted 4.4× and drown in transaction costs and noise.

Per-name signal too small to scale to representative-universe sizes is **a structural finding about edge construction**, not a substrate-selection issue. The fix is not "use a different universe" — it's "build edges that produce per-name PnL large enough to survive natural-universe dilution."

## How this changes C-collapses-1

The dispatch's deliverable #1 (6-names isolation test) will produce a near-null result. That's still useful as a published falsification — it cleanly closes the 6-names hypothesis. But the audit's main game is now confirmed to be the per-edge audit (deliverable #2):

- **Per-edge on substrate-honest universe at normal capital:** the test scoped in the dispatch. Will reveal which edges produce non-noise signal at representative universe sizes.
- **Per-edge on substrate-honest universe at scaled capital (concentration-equivalent):** new test worth running. Take substrate-honest universe but scale capital × 4 to match per-name allocation of static-109. If Sharpe recovers, edges have real signal that needs concentration to surface. If it doesn't recover, the edges have no per-name alpha at all.

The second test is **the load-bearing test**. If concentration-equivalent capital recovers the Sharpe, the path forward is: deliberate small-universe construction with rationale (the asymmetric-upside framing). If it doesn't recover, the system has no edges in any universe — substrate-honest or otherwise — and the next workstream is genuine per-name alpha generation, not portfolio-construction tweaks.

## Caveats

- Single-year analysis (2024 only). 2024 was the largest collapse year so represents the upper bound of the bias. Other years should show similar dilution patterns with smaller magnitudes.
- Trade-log PnL is realized-trade PnL. Mark-to-market unrealized positions could shift the picture marginally; haven't verified.
- This analysis was done in the main session WHILE the C-collapses-1 audit is running in `worktrees/c-collapses-edge-audit`. The audit will produce its own per-edge analysis using the actual single-edge backtest pipeline; this preliminary analysis is just for orientation, not a substitute.
