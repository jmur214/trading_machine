# Realistic Slippage Diagnostic

Generated: 2026-04-28T18:25:20
Trade log: `data/trade_logs/05e37cad-f1a0-4152-ba72-35c0b7813cee/trades.csv`
Fills analyzed: **10000** (legacy assumed: 10.0 bps flat)

## What this measures

Re-prices each historical fill from the most recent backtest run using the
`RealisticSlippageModel` (Phase 0.1 cost-model fix from
`docs/Core/forward_plan_2026_04_28.md`). The legacy model charged a flat
10.0 bps per side regardless of order size, ticker liquidity, or
volatility. The realistic model uses ADV-bucketed half-spread plus
Almgren-Chriss square-root market impact.

**Numbers below are estimates:** they apply the realistic model to the
backtest's actual fills, but do NOT account for the second-order effect that
under realistic costs the system would have made different sizing/entry
decisions. To get that, the backtest must be re-run with the realistic
model wired into `ExecutionSimulator` (deferred per v2 plan Phase 0.1).

## Cost by ADV bucket

| Bucket | Fills | Legacy avg bps | Realistic avg bps | Δ bps | Legacy total $ | Realistic total $ | Δ$ |
|--------|-------|----------------|-------------------|-------|-----------------|--------------------|-----|
| mega | 7174 | 10.00 | 1.05 | -8.95 | $4,728 | $512 | $-4,216 |
| mid | 2822 | 10.00 | 5.08 | -4.92 | $2,018 | $1,035 | $-983 |
| small | 4 | 10.00 | 15.37 | +5.37 | $1 | $1 | $+0 |

**Total legacy slippage cost (analyzed sample):** $6,746
**Total realistic slippage cost (analyzed sample):** $1,548
**Net additional cost under realistic model:** $-5,198 (-77.1%)

## Cost by side

| Side | Fills | Legacy total $ | Realistic total $ | Δ$ |
|------|-------|-----------------|--------------------|-----|
| exit | 1834 | $2,361 | $532 | $-1,828 |
| long | 6016 | $3,367 | $772 | $-2,595 |
| short | 2150 | $1,018 | $243 | $-775 |

## Realistic bps range by bucket

| Bucket | Min realistic bps | Max realistic bps |
|--------|-------------------|-------------------|
| mega | 1.00 | 1.41 |
| mid | 5.01 | 5.52 |
| small | 15.20 | 15.65 |

## Interpretation

The realistic model charges **-77.1%** LESS than the legacy
flat-bps model on this trade log. Most of the universe falls in the
mega-cap bucket (1 bps half-spread) — the legacy 10 bps was punishing
liquid names for cost they wouldn't actually pay. Reported Sharpe is
modestly understated under the legacy model.

Either way, the per-bucket breakdown above is the actionable takeaway:
the legacy model provides one number for everyone; the realistic model
differentiates SPY-class fills (~1 bps) from small-cap fills (15+ bps).
That differentiation is what enables size-aware position sizing in the
Phase 1 meta-learner.

## Cross-run validation

Re-ran the diagnostic on three other recent backtest trade logs
(10k-fill samples each) to verify the finding is not a single-run
artifact:

| Run ID (truncated) | Fills sampled | Legacy total $ | Realistic total $ | Δ% |
|--------------------|---------------|-----------------|--------------------|-----|
| 05e37cad…35c0b7813cee | 10000 | \$6,746 | \$1,548 | **-77.1%** |
| 10cbee3a…df27fcf7dbf8 | 10000 | \$6,467 | \$1,462 | **-77.4%** |
| 27c2a23e…e449ed60a24f | 10000 | \$6,644 | \$1,587 | **-76.1%** |

The over-charge is consistently around -77% across runs that span
different parameter configurations and lifecycle states. The 1–2pp
spread is run-to-run noise from sampling and edge composition, not a
structural difference. Conclusion: the legacy 10 bps flat is a genuine
~75% over-statement of the cost the system would have actually paid on
this universe; the realistic model is a Phase 0.1 fix worth wiring into
ExecutionSimulator when you're back at the keyboard.

Caveat (repeated): these comparisons re-price the fills that *did*
happen under the legacy model. Under realistic costs the system would
have made different sizing/entry decisions — the second-order effect
can only be measured by re-running the backtest with the realistic
model wired in.
