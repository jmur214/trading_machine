# Moonshot Sleeve Phase 0 Verdict — 2026-05-07

## ⚠️ Phase 0 caveat

_PHASE 0 SYNTHETIC OPTIONS STAND-IN. The leaps_catalyst_edge_v1 uses Black-Scholes pricing on the underlying close + IV proxy from realized vol. This is good enough to validate sleeve plumbing but is NOT a substitute for real OPRA options PnL. Real OPRA via Schwab is Phase 1 work. Treat the verdict bucket as a SLEEVE-PLUMBING signal, not a real strategy verdict._

## Verdict bucket

**FAIL** — 2/4 success criteria met — failed: skewness, tail_ratio — kills: skewness -0.028 ≤ kill-floor 0.0

- Success criteria met: 2 / 4
- Failed: skewness, tail_ratio
- Kill triggers: skewness -0.028 ≤ kill-floor 0.0

## Sleeve metrics

| metric | value | success threshold | kill threshold |
|---|---:|---:|---:|
| Sortino | +1.599 | ≥ 1.5 | < 0.3 |
| Skewness | -0.028 | ≥ 0.5 | ≤ 0.0 |
| Tail ratio | 0.996 | ≥ 1.5 | — |
| Upside capture | 0.904 | ≥ 0.7 | — |
| Sharpe (xref) | +1.158 | — | — |
| Max drawdown | -21.283% | — | > +35% (abs) |
| n observations | 1309 | ≥ 120 | — |

### Bootstrap Sortino (block-bootstrap, 300 resamples)

point=+1.599 95%CI=[+0.342, +2.920] P(>0)=0.98 block_length=11

## Configuration

- Window: 2021-01-01 → 2025-12-31
- Cadence: monthly
- Universe loaded: 110 tickers
- Rebalances executed: 40
- Daily return observations: 1309
- Per-position cap: 0.05

## Honest caveats

- This harness drives the sleeve in PHANTOM ALLOCATION mode against real OHLCV. No cost layer applied (no slippage, no commission, no advisory cap). Edges that fail pre-cost are dead at any layer; edges that pass pre-cost still need the cost layer to clear before any capital deployment.
- The sleeve is NOT YET wired into PortfolioEngine.allocate. Verdict here informs whether to invest engineering time in the wire-up — not whether to deploy capital.
- Returns are next-bar close-to-close on the held weights; rebalancing happens at month boundary at the close. Real production would have execution lag; this measurement does not.

## What success unlocks

- **SUCCESS**: schedule the wire-up dispatch — add the opt-in path through `PortfolioEngine.allocate` so the sleeve can be A/B'd against the core book.
- **PARTIAL**: the sleeve has signal but doesn't clear all gates. Tweak parameters (top_n, max_position_weight, lookback) and re-run before considering the wire.
- **FAIL**: don't wire. Either the sleeve concept is wrong for this substrate, or the sleeve's parameters need a fundamental rework.
- **INDETERMINATE**: insufficient data. Extend window or universe.
