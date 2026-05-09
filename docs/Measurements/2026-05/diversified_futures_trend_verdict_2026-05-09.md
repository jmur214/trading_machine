# Diversified-Futures Trend Sleeve — Phase 0 Verdict (2026-05-09)

**Task:** T-2026-05-08-007
**Universe:** SPY, TLT, GLD, USO, UUP, EEM, IEF, DBC (8 ETFs)
**Window:** 2021-04-09 → 2026-04-17
**Cadence:** monthly
**Config:** lookback=252, vol_window=63, top_n=4, max_pos_weight=0.30

## Verdict bucket

**FALSIFIED**  (gauntlet: `FAIL`)

- Gauntlet criteria met: 0 / 4
- Failed: sortino, skewness, tail_ratio, upside_capture
- Kill triggers: skewness -0.913 ≤ kill-floor -0.5
- Correlation to SPY: +0.432  (diversification target: < 0.30)

### Verdict-bucket logic (per spec)

- `FALSIFIED`: `sortino_ci_low < 0.5` OR `|MDD| > 35%`
- `VIABLE_MOONSHOT_SLEEVE`: 3+ of 4 gauntlet criteria pass AND correlation to SPY < 0.3
- `POSITIVE_SHARPE_NOT_ASYMMETRIC`: Sharpe > 0 but skewness ≤ 0 OR tail-ratio < 1.0
- Otherwise: passes through the gauntlet bucket

## Sleeve gauntlet metrics

| metric | value | success threshold | kill threshold |
|---|---:|---:|---:|
| Sortino | +1.068 | ≥ 1.2 | < 0.5 |
| Skewness | -0.913 | ≥ 0.0 | ≤ -0.5 |
| Tail ratio | 0.843 | ≥ 1.2 | — |
| Upside capture | 0.371 | ≥ 0.7 | — |
| Sharpe (xref) | +0.871 | — | — |
| Max drawdown | -18.048% | — | > +35% (abs) |
| n observations | 1220 | ≥ 120 | — |

### Bootstrap Sortino (block-bootstrap, 1000 resamples)

- point = +1.068
- 95% CI = [+0.027, +2.337]
- P(>0) = 0.98
- block_length = 11

Per CLAUDE.md non-negotiable rule (Sharpe/Sortino headlines must report `ci_low`): **Sortino ci_low = +0.027**.

## Headline interpretation

Point-estimate Sortino is **+1.068** with P(Sortino > 0) = 0.98 across the bootstrap. The mean is fine; the 95% CI lower bound is **+0.027**, barely above zero. We can't statistically distinguish this from a zero-skill strategy on a 5-year sample. The spec's `sortino_ci_low ≥ 0.5` requirement (the deployment confidence floor) fires the FALSIFIED verdict — that's the right call.

Skewness is **-0.913** — strongly negative. This is exactly the property R2 was selling diversified-futures trend on as DIFFERENT-FROM equity-trend: positive skew, asymmetric upside capture. The 5-year ETF substrate doesn't deliver it. Tail ratio 0.843 (target ≥1.2) and upside capture 0.371 (target ≥0.7) point the same direction: this is a positive-Sharpe return-stream with worse-than-symmetric tails.

Correlation to SPY is **+0.432** — above the 0.30 diversification target. The hypothesis was that diversified-futures trend should be near-zero correlated with the equity book. It's not, on this window. The per-asset-class contribution shows why: the sleeve concentrated in commodities and equities (EEM ranks like SPY), with effectively zero participation from bonds and currencies. Trend-following picked the asset classes that *had* trend, and those happened to co-move with SPY.

**This isn't a refutation of trend-following at large.** It's a refutation of *trend-following on this 8-ETF basket over this 5-year window with these parameters*. AQR's century-of-evidence claim assumes (a) actual futures, not ETFs; (b) long/short, not long-only; (c) decades, not 5 years; (d) ~50+ markets, not 8. Each of (a)-(d) is a Phase-2 follow-up if anyone wants to pursue this further. Phase 0 says: don't deploy this sleeve as-is.

## Per-asset-class contribution (arithmetic sum of per-bar weighted returns)

| Class | Tickers | Contribution | Share of total |
|---|---|---:|---:|
| commodities | DBC, GLD, USO | +0.3228 | +65.5% |
| equities | EEM, SPY | +0.1658 | +33.7% |
| bonds | IEF, TLT | +0.0031 | +0.6% |
| currencies | UUP | +0.0011 | +0.2% |
| **TOTAL** | — | **+0.4928** | **100%** |

**Method:** for each held basket, sum per-bar `weight_i × bar_return_i` across tickers in each asset class. Arithmetic-sum decomposition; the sum across classes equals the sleeve's arithmetic daily-return total (not compounded). Share-of-total tells you which classes drove the result. **Ignore the *signed* shares for low-magnitude classes (close to zero share has unstable sign)** — this is for directional attribution, not pinpoint accounting.

## Configuration

- Universe loaded: 8 / 8 ETFs (all required)
- Rebalances executed: 42
- Daily return observations: 1220
- Per-position cap: 0.3

## Honest caveats (open questions surfaced from the spec)

1. **ETF proxies ≠ futures.** USO / UUP / DBC are ETFs that proxy futures but aren't the futures themselves. Roll cost / contango drag is baked into the ETF NAV but the leverage profile differs. A real CTA deployment needs futures-specific cost modeling — this Phase-0 result is the upper bound on what an ETF substrate can deliver.

2. **5-year sample is short for trend-following.** AQR's *Century of Evidence* claim is built on 100+ years across multiple regimes. Our 2021-04 → 2026-04 window includes one decisively trending macro environment (2022 rate-rise / commodities bull) plus ranging conditions on either side. One good or bad year on a 5-year sample is meaningful; treat the headline as a single point-estimate, not regime-conditional.

3. **Long-only loses half the alpha thesis.** TrendFollowingSleeve as written is long-only (filtered on `momentum > min_momentum=0`). Classical CTAs go long when momentum is positive AND short when negative on each name. The downside-momentum half is silently discarded. If Phase 0 results justify continuation, a long/short extension (`enable_short=True` flag in the sleeve, gated by spec) is the obvious Phase-2-of-Phase-2 follow-up.

4. **No cost layer.** Phantom allocation; no slippage, no commission, no spread. The dispatch's verdict brackets are tight enough that a pre-cost edge that fails won't survive the cost layer either, but a pre-cost pass should not be interpreted as deployable until cost-modeled.

## What this verdict bucket unlocks

- `VIABLE_MOONSHOT_SLEEVE`: schedule the wire-up — opt-in path through `PortfolioEngine.allocate` for an A/B against the core book. Gate the wire on cost-layer validation first.
- `POSITIVE_SHARPE_NOT_ASYMMETRIC`: same outcome as equity-trend (115-name and 722-name tests). Reframe — diversified-futures trend on this ETF substrate gives positive Sharpe but not the asymmetric-upside property R2 was selling. Either pivot the objective or attempt long/short extension.
- `FALSIFIED`: R2's recommendation doesn't survive on this substrate. Don't deploy. Document and move on.
