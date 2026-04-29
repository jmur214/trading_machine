---
name: Edge fire-rate analysis 2026-04-28
description: Empirical per-condition fire rates on 109-ticker S&P universe vs designed-for fire rates; identifies which active edges are structurally near-dead under current thresholds
type: project
---

Date measured: 2026-04-28 against `data/processed/parquet/*_1d.parquet` for 2021-2024 (122 tickers loaded, 119,801 ticker-bars total). Reference run `data/trade_logs/10cbee3a-1148-410b-80cd-df27fcf7dbf8/` (21,848 fills, Sharpe 0.228, 989 trading days).

**Why:** explains the 14,445:7 fire-rate ratio between paused `momentum_edge_v1` and active `panic_v1`. Active edges aren't competing on alpha — they're not even at the table. Threshold miscalibration is real but only fully explains a subset; some edges are structurally untriggerable.

**How to apply:** when proposing edge changes, check whether the edge's gating conditions can plausibly fire >5% of the time on the actual universe. If not, the edge cannot accumulate enough trades for governance to evaluate, and the system gets passive trend-follow exposure by default.

Empirical rates (universe-wide, 2021-2024):
- breadth >= 0.80 (herding default): 23.7% of days — herding fires fine (343 entries observed; in spec)
- vol_z > 2.0 (volume_anomaly default): 5.93% of bars — fires fine (906 entries)
- vol_z > 2.5: 3.78%
- vol_z < -2.0 AND bb_width < 0.03 (dryup_breakout): ~0.001% intersection — structurally near-dead
- bb_width < 0.03 alone: 0.54% — mega-cap calibration; 109-universe wider
- bb_width < 0.05: 6.91%
- panic_v1 3-of-4 (rsi<20, vol_z>2.5, <BB_lower, atr_ratio>1.3): 0.4% of bars (~477 across 4yr); 7 trades observed = severe downstream filtering on top of already-tight join
- T10Y2Y > 0.50 (yield curve bullish): 27.9% of days; T10Y2Y < 0 (inverted): 54.1% — extreme regime split
- BAA-AAA stress threshold (mean+1std on full FRED history): 0% of days in 2021-2024 — full-sample mean=0.99/std=0.40 priced in 1980s stagflation; modern range never approaches +1std. Structurally dead.

Observed fills per edge (long backtest, 2021-2024):
- momentum_edge_v1 (paused): 14,445 entries, 1,850 closes, -$11,148
- atr_breakout_v1 (paused): 4,951 entries, 1,261 closes, -$4,255
- volume_anomaly_v1: 906 entries, 434 closes, +$10,394
- gap_fill_v1: 407 entries, 175 closes, +$683
- herding_v1: 343 entries, 201 closes, +$4,770
- low_vol_factor_v1: 288 entries, 43 closes, +$218
- macro_dollar_regime_v1: 272 entries, 93 closes, -$280
- pead_predrift_v1: 173 entries, 23 closes, -$117
- pead_v1: 24 entries, 2 closes, +$65
- macro_yield_curve_v1: 13 entries, 8 closes, +$110
- value_trap_v1: 8 entries, 3 closes, -$4
- panic_v1: 7 entries, 7 closes, -$16
- macro_credit_spread_v1: 4 entries, 1 close, -$1
- pead_short_v1: 2 entries, 2 closes, +$2

Punchline: the four edges with positive PnL that actually fire (volume_anomaly, herding, gap_fill, low_vol_factor) cumulatively net +$16,065 over 4yr but are out-voted in capital allocation by the two losing momentum edges. The "active" edges with academic pedigree (PEAD variants, panic, macro tilts) are essentially absent from the trade record.

Aggregate score plumbing: enter_threshold = 0.01 in prod, ensemble shrinkage 0.35x, weighted-mean across edges → no realistic threshold compression at the aggregate level. The bottleneck is per-edge condition rarity, not aggregate gating.
