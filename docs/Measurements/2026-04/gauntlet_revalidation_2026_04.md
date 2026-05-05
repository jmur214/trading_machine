# Gauntlet Re-validation — Phase 2.10b Q3 (2026-04-29)

Re-running the full 6-gate `DiscoveryEngine.validate_candidate` pipeline
against the two edges that the in-sample factor-decomposition (commit
`b918e08`) flagged as `tier=alpha`:

- `volume_anomaly_v1` — intercept t = **+4.36**, annualized α = **+6.1%**
- `herding_v1` — intercept t = **+4.49**, annualized α = **+10.1%**

The factor decomposition ran under the legacy fixed-5bps slippage. The
realistic-cost backtest (commit `9546937`, Almgren-Chriss + ADV-bucketed
spread, in-sample Sharpe 1.063) was the basis for the claim that those
two intercepts represent real alpha rather than factor beta. **This run
answers the load-bearing question:** do these edges still clear all six
gates of `validate_candidate` when the same realistic cost model is
applied during the per-edge backtest itself?

Per the Phase 2.10b plan in `docs/Core/forward_plan_2026_04_29.md`, the
pass criterion is *both edges pass all 6 gates with intercept t > 2 and
annualized α > 2%* — that is the bar for the "two real alphas" claim to
survive.

## Run configuration

- **Window**: 2021-01-01 → 2024-12-31 (4 years, in-sample)
- **Universe**: 109 of 109 production tickers (CSV cache, ≥100 bars)
- **Slippage**: `model=realistic`, base 10.0 bps + impact_coefficient
  0.5, ADV-bucketed half-spreads (1/5/15 bps mega/mid/small)
- **Edge code path**: `engines.engine_a_alpha.edges.volume_anomaly_edge.VolumeAnomalyEdge`
  and `engines.engine_a_alpha.edges.herding_edge.HerdingEdge`, registry
  params unchanged
- **Significance threshold**: 0.05 (uncorrected — two edges, BH-FDR is a
  near-no-op at this batch size)
- **Driver**: `scripts/revalidate_alphas.py`, calling
  `DiscoveryEngine.validate_candidate(spec, data_map, exec_params=...)`
  with the realistic-cost `exec_params` block built from
  `config/backtest_settings.json`. (The `exec_params` argument is new on
  this branch — `validate_candidate` previously hardcoded
  `slippage_bps=5.0`; that hardcode is the precise reason this
  re-validation matters.)

## Headline — both edges FAIL

| edge | gate-1 Sharpe | benchmark threshold | gate-1 verdict | passes all 6 gates? |
| --- | ---: | ---: | --- | --- |
| `volume_anomaly_v1` | **0.32** | 0.68 | **FAIL** | **No** |
| `herding_v1` | **-0.26** | 0.68 | **FAIL** | **No** |

**Neither edge survives the cheap-filter benchmark-relative gate under
realistic costs.** Both fall below the threshold of (SPY-Sharpe − 0.2) =
~0.68 for the 2021-2024 window. Gates 2-6 did not execute — the
function short-circuits on Gate 1 failure. Their "FAIL"/"SKIP" markers
in the per-edge tables below are mechanical defaults, not evidence.

The factor-decomposition claim of t = +4.36 and t = +4.49 was a
**cost-model confound**: when the per-edge backtest is run at fixed 5
bps slippage but the integration backtest uses realistic Almgren-Chriss,
the integration backtest's overall Sharpe (1.063) survives only because
other edges and risk-engine sizing carry the result. The two edges
themselves, run standalone under the same realistic costs the
integration uses, do not produce benchmark-competitive returns.

## Per-edge gate detail

### `volume_anomaly_v1`

| Gate | Metric | Value | Pass? |
| --- | --- | --- | --- |
| 1. Quick backtest (benchmark-relative) | Sharpe (threshold ≈ 0.68) | **0.32** | **FAIL** |
| 2. PBO robustness | survival (≥ 0.70) | not run (Gate 1 short-circuit) | — |
| 3. WFO degradation | OOS / IS Sharpe ratio | not run | — |
| 4. Statistical significance | permutation p (< 0.05) | not run | — |
| 5. Universe-B transfer | Sharpe (> 0) | not run | — |
| 6. Factor-decomp alpha | t > 2 & α > 2% annualized | not run | — |

- Sortino under realistic costs: **0.33**.
- Run artifact: `/tmp/discovery_validation/a1f30e25-fa90-4a9c-87b0-683c3dacee9e/`
  (Gate 1 trade log + portfolio snapshots).
- Plain interpretation: the spike-reversal mode trades produce returns
  that the realistic cost model eats. The factor-decomp's "+6.1%
  annualized α" was measured against the FF5+Mom factor cube on returns
  that did NOT include realistic per-trade impact; replaying the same
  signal under honest costs leaves +3.2% Sharpe-equivalent return, well
  below SPY's ~0.88 over the same window.

### `herding_v1`

| Gate | Metric | Value | Pass? |
| --- | --- | --- | --- |
| 1. Quick backtest (benchmark-relative) | Sharpe (threshold ≈ 0.68) | **-0.26** | **FAIL** |
| 2. PBO robustness | survival (≥ 0.70) | not run (Gate 1 short-circuit) | — |
| 3. WFO degradation | OOS / IS Sharpe ratio | not run | — |
| 4. Statistical significance | permutation p (< 0.05) | not run | — |
| 5. Universe-B transfer | Sharpe (> 0) | not run | — |
| 6. Factor-decomp alpha | t > 2 & α > 2% annualized | not run | — |

- Sortino under realistic costs: **-0.18**.
- Run artifact: `/tmp/discovery_validation/27fac5fb-50da-4981-af11-52fcc8b83687/`.
- Plain interpretation: a NEGATIVE standalone Sharpe means herding_v1 is
  not just unprofitable under realistic costs — it actively destroys
  capital when run in isolation. The factor-decomp's "+10.1% annualized
  α" was the largest claimed standalone alpha in the active edge set,
  and is the most starkly contradicted by this re-validation. Whatever
  the FF5+Mom regression saw at t = +4.49, it was not robust to honest
  per-trade costs.

## What this means for the "real alpha" claim

The Phase 2.10b plan stated:

> **Q3 pass criterion**: BOTH edges pass ALL 6 gates — that's the bar
> for confirming the "two real alphas" claim.

That criterion is **not met**. Both edges fail at Gate 1, the cheapest
filter in the gauntlet.

Three possible interpretations of the gap between the factor-decomp
t-stats and these gate-1 results:

1. **Cost-model confound (most likely).** The factor decomposition
   regressed daily *integration backtest* returns on the FF5+Mom factor
   cube; the resulting intercept reflected the residual after factor
   exposure, not the standalone profitability of either edge. When
   `volume_anomaly_v1` and `herding_v1` run alone with realistic per-trade
   costs, that residual collapses. The intercept was real — but it was
   the residual of the integration's portfolio-level signal mixing,
   risk sizing, and timing benefits, not a property of either edge in
   isolation.

2. **Cost-model double-counting in the integration backtest is
   compensated by other edges' alpha.** If true, the integration's
   1.063 Sharpe is held up not by these two edges but by the rest of
   the active stack. That makes the "two real alphas" claim positively
   misleading: those two edges may be the largest factor-decomp residual
   *and* contribute negatively to standalone Sharpe.

3. **Standalone backtest mis-loads the edge.** Possible, but the driver
   instantiates `VolumeAnomalyEdge()` and `HerdingEdge()` from the same
   module/class the integration uses, with the same registry params. The
   per-edge `RiskEngine({"risk_per_trade_pct": 0.01})` and 100k initial
   capital are conservative; if anything, they should produce smoother
   Sharpe than the integration's leverage-aware sizing. This explanation
   is unlikely.

The honest read is interpretation #1 + #2: the in-sample 1.063
realistic-cost Sharpe is not driven by these two edges as standalone
signals. The factor-decomp t-stat is a portfolio-level decomposition
artifact, not edge-level alpha.

## Implications for Phase 2.10b's gate

The plan called for the OOS validation gate to PASS or FAIL based on
three orthogonal questions:

1. 2025 OOS Sharpe under realistic costs (Agent 1, branch
   `oos-validation`, doc `oos_validation_2026_04.md`)
2. Universe-B Sharpe under realistic costs (Agent 1)
3. **`volume_anomaly_v1` + `herding_v1` pass all 6 gates** ← this run

**Q3 is a clean FAIL.** Per the plan's own logic ("Pass → unblock Phase
2.11+. Fail → revert to gauntlet-rigor mode, no new features.") this
result alone is sufficient to block Phase 2.11 (per-ticker meta-learner)
and Phase 2.12 (growth-profile config) until the discrepancy between
factor-decomp residuals and standalone gate-1 Sharpe is reconciled.

Specifically: the `tier=alpha` classification on these two edges in
`data/governor/edges.yml` should be reviewed — the TierClassifier
promoted them on factor-decomp t-stat alone, but the gauntlet rejects
them on standalone profitability. Either:

- the TierClassifier should require gate-1 standalone Sharpe ≥
  benchmark threshold *as well as* factor-decomp t > 2 (more
  conservative — would have blocked these promotions); or
- factor-decomp must be run on standalone-edge return streams under
  realistic costs (matching this re-validation's setup), not on
  integration-portfolio returns. The current implementation regresses
  integration returns on factors and assigns the residual to the edge
  whose row is being decomposed — which is what produces the apparent
  +6.1% / +10.1% alpha in the first place.

## Run artifacts

| edge | trade log dir | timing |
| --- | --- | --- |
| volume_anomaly_v1 | `/tmp/discovery_validation/a1f30e25-fa90-4a9c-87b0-683c3dacee9e/` | 6.5 min |
| herding_v1 | `/tmp/discovery_validation/27fac5fb-50da-4981-af11-52fcc8b83687/` | 8.3 min |

Driver log: `logs/revalidate_alphas.log` (full stdout including all
trade fills under the realistic-cost simulator). Both runs short-circuit
after Gate 1 → no PBO/WFO/significance/universe-B/factor-decomp
artifacts were produced this round.

## Branch & code

- Branch: `gauntlet-revalidation` (off `main` at `7fb5b7d`)
- New driver: `scripts/revalidate_alphas.py`
- Engine D extension: `validate_candidate` now accepts an optional
  `exec_params` dict (was hardcoded `slippage_bps=5.0`). Default
  preserves prior behavior for the in-discovery generation loop.
- Both files committed in `072ce79`.
