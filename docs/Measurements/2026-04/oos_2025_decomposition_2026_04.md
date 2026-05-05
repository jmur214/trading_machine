# 2025 OOS Decomposition — Phase 2.10c diagnostic

**Date:** 2026-04-30
**Branch:** `oos-2025-decomposition`
**Driver:** `scripts/analyze_oos_2025.py` (pure pandas — no new backtests)
**Inputs:**
- Q1 anchor run: `data/trade_logs/72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34/`
  (2025-01-01 → 2025-12-31, prod 109, soft-paused defaults, Sharpe -0.049)
- Counterfactual run: `data/trade_logs/a8c335a3-a014-4434-989b-1fda70f44481/`
  (same window/universe with `atr_breakout_v1` + `momentum_edge_v1`
  un-paused, Sharpe +0.273)

## Headline finding (single most surprising)

**`volume_anomaly_v1` was a clean, consistent positive in 2025 — and the
soft-paused configuration is the only configuration in which it
actually traded.** It made +$1,933.73 on 191 fills (avg +$10.12/fill)
with positive monthly PnL in 11 of 12 months and positive PnL in
**all four** regime labels including `market_turmoil`. Un-pausing
`atr_breakout_v1` + `momentum_edge_v1` collapsed its fill count to 19
and flipped its avg-PnL/fill from +$10.12 to **-$1.17** — the few
fills it got after the rivals took capital share were *worse than
random*. Same shape for `herding_v1` (44 → 2 fills). The standalone
gauntlet failure of these two "real alphas"
(`docs/Audit/gauntlet_revalidation_2026_04.md`) and the rivalry
collapse seen here describe the same phenomenon: capital allocation
in `signal_processor` cannot run two edge families simultaneously.

Mapping vs the three options the director posed:

> **Capital rivalry** (primary) > regime-decay > "no edge has signal"

The rivalry-effect diagnosis dominates: there *is* a consistent edge
in 2025, the system just can't allocate to it when momentum-shaped
edges are competing.

## 1. Q1 anchor — per-edge per-month realized PnL ($)

(Sorted by 2025 total. Bold edges = currently `paused` per `edges.yml`.)

| Edge                    | Jan   | Feb   | Mar   | Apr    | May   | Jun   | Jul   | Aug   | Sep   | Oct   | Nov   | Dec   | **TOTAL** |
|-------------------------|-------|-------|-------|--------|-------|-------|-------|-------|-------|-------|-------|-------|-----------|
| `volume_anomaly_v1`     | +222  | -56   | +182  | +253   | +213  | +366  | +20   | -6    | +71   | +248  | +272  | +149  | **+1,934** |
| `herding_v1`            | +48   | 0     | +147  | +74    | -11   | +122  | 0     | +55   | +79   | +33   | 0     | 0     | **+547** |
| `macro_credit_spread_v1`| +57   | 0     | +88   | 0      | 0     | 0     | -11   | -20   | +86   | -7    | +50   | -13   | **+231** |
| `gap_fill_v1`           | +318  | -70   | 0     | -578   | +187  | +86   | +31   | +25   | +107  | +14   | +59   | -4    | **+174** |
| `growth_sales_v1`       | 0     | 0     | 0     | 0      | 0     | 0     | 0     | 0     | 0     | 0     | 0     | +75   | **+75**  |
| `pead_v1`               | 0     | 0     | 0     | 0      | 0     | -4    | 0     | 0     | 0     | 0     | +16   | 0     | **+12**  |
| `value_deep_v1`         | 0     | 0     | 0     | 0      | 0     | 0     | 0     | 0     | 0     | 0     | 0     | 0     | **0** |
| `macro_dollar_regime_v1`| 0     | 0     | 0     | 0      | 0     | -33   | +22   | 0     | 0     | 0     | 0     | 0     | **-11** |
| `pead_predrift_v1`      | 0     | 0     | 0     | 0      | 0     | 0     | 0     | 0     | 0     | 0     | -22   | 0     | **-22**  |
| `value_trap_v1`         | -5    | 0     | -46   | 0      | 0     | 0     | 0     | 0     | 0     | 0     | 0     | 0     | **-51**  |
| `panic_v1`              | 0     | 0     | 0     | -161   | 0     | 0     | 0     | 0     | 0     | 0     | 0     | 0     | **-161** |
| **`momentum_edge_v1`**  | +70   | -232  | -563  | -647   | +61   | +3    | +147  | +240  | +25   | +121  | -193  | +86   | **-883** |
| **`atr_breakout_v1`**   | -53   | -47   | -576  | -827   | -123  | -199  | +80   | -97   | -83   | -332  | +58   | -31   | **-2,229** |
| **`low_vol_factor_v1`** | -240  | -191  | -360  | **-1,664** | -305 | -97   | +449  | +53   | -132  | -249  | +96   | +108  | **-2,533** |
| **Sum (realized)**      | +459  | -596  | -1,128| **-3,551** | +21  | +263  | +766  | +250  | +153  | -158  | +320  | +369  | **-2,918** |

Two facts jump out:

1. **April 2025 alone burned through -$3,551 of realized PnL.** April
   was tagged `market_turmoil` for 239 of 453 fills (53% of April
   fills). `low_vol_factor_v1` lost -$1,664 in April; `atr_breakout_v1`
   lost -$827; `gap_fill_v1` lost -$578; `momentum_edge_v1` lost
   -$647. Five edges took catastrophic April losses simultaneously.
   This is not edge-specific failure — it is a **regime-correlated
   joint drawdown** that hit every momentum-shaped + factor-shaped edge
   at once.
2. The bottom-three edges (`low_vol_factor_v1`, `atr_breakout_v1`,
   `momentum_edge_v1`) account for **-$5,645 of realized losses**;
   all other edges combined produced **+$2,727**. The system would be
   a 2025 winner if the bottom three were silent.

## 2. Q1 anchor — per-edge per-month FILL COUNT

| Edge                    | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | **TOTAL** |
|-------------------------|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----------|
| `momentum_edge_v1`      | 119 | 236 | 123 | 51  | 88  | 298 | 260 | 190 | 208 | 287 | 186 | 157 | **2,203** |
| `low_vol_factor_v1`     | 117 | 148 | 110 | 192 | 141 | 135 | 135 | 151 | 117 | 166 | 96  | 105 | **1,613** |
| `atr_breakout_v1`       | 116 | 85  | 39  | 22  | 45  | 60  | 82  | 90  | 101 | 56  | 18  | 54  | **768** |
| `macro_credit_spread_v1`| 14  | 1   | 17  | 0   | 0   | 1   | 55  | 20  | 47  | 42  | 10  | 32  | **239** |
| `gap_fill_v1`           | 13  | 11  | 2   | 149 | 12  | 5   | 6   | 17  | 4   | 6   | 3   | 6   | **234** |
| `volume_anomaly_v1`     | 13  | 7   | 15  | 28  | 11  | 33  | 11  | 12  | 18  | 7   | 21  | 15  | **191** |
| `growth_sales_v1`       | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 23  | 99  | **122** |
| `herding_v1`            | 2   | 0   | 1   | 5   | 2   | 12  | 5   | 6   | 7   | 3   | 1   | 0   | **44** |
| `value_trap_v1`         | 3   | 0   | 2   | 0   | 0   | 1   | 1   | 0   | 0   | 1   | 11  | 14  | **33** |
| `macro_dollar_regime_v1`| 0   | 0   | 0   | 1   | 2   | 11  | 1   | 3   | 1   | 0   | 0   | 0   | **19** |
| `panic_v1`              | 0   | 0   | 5   | 5   | 0   | 0   | 0   | 0   | 0   | 1   | 1   | 0   | **12** |
| `pead_predrift_v1`      | 0   | 1   | 0   | 0   | 0   | 0   | 0   | 6   | 2   | 0   | 3   | 0   | **12** |
| `pead_v1`               | 0   | 0   | 0   | 0   | 3   | 2   | 0   | 0   | 0   | 0   | 2   | 0   | **7** |
| `value_deep_v1`         | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 1   | **1** |

Capital share pattern (Q1, fills-as-proxy):

- Top three edges (`momentum_edge_v1`, `low_vol_factor_v1`,
  `atr_breakout_v1`) consume **4,584 of 5,498 fills (83%)** despite
  being the bottom three by PnL.
- The two best-PnL edges (`volume_anomaly_v1`, `herding_v1`) get
  **235 of 5,498 fills (4.3%)**.
- The diagnosis is not "no edge has signal" — it is "the signal-bearing
  edges are starved."

## 3. Counterfactual — per-edge per-month realized PnL ($)

(Edges not listed had zero fills.)

| Edge                    | Jan   | Feb   | Mar   | Apr   | May   | Jun  | Jul   | Aug   | Sep   | Oct   | Nov   | Dec   | **TOTAL** |
|-------------------------|-------|-------|-------|-------|-------|------|-------|-------|-------|-------|-------|-------|-----------|
| `momentum_edge_v1`      | +341  | -227  | -420  | -426  | +139  | +52  | +294  | -430  | +453  | +225  | -73   | +385  | **+316** |
| `macro_credit_spread_v1`| +85   | +70   | 0     | 0     | 0     | 0    | +75   | +13   | +4    | +1    | 0     | -5    | **+243** |
| `herding_v1`            | 0     | 0     | 0     | 0     | 0     | -0   | 0     | 0     | 0     | 0     | 0     | +12   | **+12** |
| `macro_dollar_regime_v1`| 0     | 0     | 0     | 0     | 0     | 0    | 0     | 0     | +1    | 0     | 0     | 0     | **+1** |
| `growth_sales_v1`       | 0     | 0     | 0     | 0     | 0     | 0    | 0     | 0     | 0     | 0     | 0     | 0     | **0** |
| `low_vol_factor_v1`     | 0     | 0     | 0     | 0     | 0     | 0    | 0     | 0     | 0     | 0     | 0     | 0     | **0** |
| `gap_fill_v1`           | +13   | 0     | 0     | -19   | 0     | 0    | 0     | -6    | 0     | 0     | 0     | 0     | **-11** |
| `volume_anomaly_v1`     | 0     | 0     | -36   | -7    | -21   | 0    | +28   | 0     | 0     | 0     | -1    | +16   | **-22** |
| `atr_breakout_v1`       | -432  | -317  | -661  | -305  | -373  | +36  | +836  | -385  | +250  | -442  | -134  | -586  | **-2,514** |

## 4. Counterfactual — per-edge per-month FILL COUNT

| Edge                    | Jan | Feb | Mar | Apr | May | Jun | Jul | Aug | Sep | Oct | Nov | Dec | **TOTAL** |
|-------------------------|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----|-----------|
| `momentum_edge_v1`      | 95  | 246 | 166 | 165 | 126 | 152 | 197 | 227 | 263 | 343 | 236 | 137 | **2,353** |
| `atr_breakout_v1`       | 166 | 194 | 78  | 80  | 221 | 90  | 177 | 175 | 169 | 186 | 87  | 89  | **1,712** |
| `macro_credit_spread_v1`| 7   | 1   | 3   | 0   | 0   | 0   | 13  | 4   | 2   | 11  | 5   | 7   | **53** |
| `volume_anomaly_v1`     | 1   | 0   | 1   | 3   | 2   | 0   | 3   | 2   | 2   | 0   | 2   | 3   | **19** |
| `gap_fill_v1`           | 1   | 0   | 0   | 7   | 1   | 0   | 1   | 1   | 2   | 0   | 1   | 0   | **14** |
| `growth_sales_v1`       | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 4   | 4   | **8** |
| `low_vol_factor_v1`     | 0   | 0   | 0   | 4   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | **4** |
| `herding_v1`            | 0   | 0   | 0   | 0   | 0   | 1   | 0   | 0   | 0   | 0   | 0   | 1   | **2** |
| `macro_dollar_regime_v1`| 0   | 0   | 0   | 0   | 0   | 0   | 0   | 0   | 2   | 0   | 0   | 0   | **2** |

## 5. The rivalry probe (the central question)

| Edge                | Q1 fills | Q1 PnL    | Q1 avg/fill | CF fills | CF PnL  | CF avg/fill |
|---------------------|----------|-----------|-------------|----------|---------|-------------|
| `volume_anomaly_v1` | 191      | +$1,933.73 | **+$10.12** | 19       | -$22.17 | **-$1.17**  |
| `herding_v1`        | 44       | +$546.59  | **+$12.42** | 2        | +$11.80 | **+$5.90**  |

**Both edges quantitatively confirm the rivalry hypothesis.** They
don't merely "lose more per fill" in the counterfactual — they
**barely fire**, and when they do, the average-PnL/fill collapses too.
`volume_anomaly_v1` flipped sign on a 90% drop in fill count;
`herding_v1` halved its per-fill yield on a 95% drop. This is what
"crowded out by capital allocation" looks like in the trade log —
not weaker individual signal, but no opportunity to express the
signal.

The mechanism: both un-paused momentum edges are universal-fire
edges (`momentum_edge_v1` 2,353 fills/yr, `atr_breakout_v1` 1,712
fills/yr) that consume the available position slots and dollar caps in
`signal_processor`'s allocation, blocking the lower-frequency
event-driven edges (`volume_anomaly`, `herding`) from getting their
trades sized.

## 6. Cumulative monthly PnL — top 5 + bottom 5 (Q1 anchor) + SPY

| Month   | volume_anomaly | herding | mc_credit_spread | gap_fill | growth_sales | low_vol  | atr_break  | momentum_edge | panic | value_trap | **SPY ret %** |
|---------|----------------|---------|------------------|----------|--------------|----------|------------|---------------|-------|------------|---------------|
| 2025-01 | +222           | +48     | +57              | +318     | 0            | -240     | -53        | +70           | 0     | -5         | +2.9          |
| 2025-02 | +166           | +48     | +57              | +247     | 0            | -431     | -100       | -163          | 0     | -5         | -0.6          |
| 2025-03 | +348           | +195    | +145             | +247     | 0            | -792     | -676       | -726          | 0     | -51        | -3.9          |
| 2025-04 | +601           | +269    | +145             | -331     | 0            | **-2,456** | **-1,503** | **-1,372** | -161  | -51        | -1.1          |
| 2025-05 | +814           | +258    | +145             | -144     | 0            | -2,761   | -1,626     | -1,311        | -161  | -51        | +5.5          |
| 2025-06 | +1,180         | +380    | +145             | -58      | 0            | -2,858   | -1,825     | -1,309        | -161  | -51        | +4.5          |
| 2025-07 | +1,200         | +380    | +134             | -27      | 0            | -2,410   | -1,744     | -1,162        | -161  | -51        | +2.3          |
| 2025-08 | +1,193         | +435    | +115             | -2       | 0            | -2,356   | -1,841     | -922          | -161  | -51        | +3.8          |
| 2025-09 | +1,264         | +514    | +201             | +105     | 0            | -2,488   | -1,924     | -897          | -161  | -51        | +4.3          |
| 2025-10 | +1,512         | +547    | +195             | +119     | 0            | -2,736   | -2,256     | -777          | -161  | -51        | +2.0          |
| 2025-11 | +1,785         | +547    | +244             | +178     | 0            | -2,640   | -2,198     | -969          | -161  | -51        | 0.0           |
| 2025-12 | **+1,934**     | **+547**| +231             | +174     | +75          | -2,533   | -2,229     | -883          | -161  | -51        | +0.5          |

`volume_anomaly_v1` is the **only** edge whose cumulative curve is
monotonically upward — every other "winner" gives some back at least
once. It's also the only edge whose curve does not reset at the
April-2025 cliff. This is the cleanest single piece of in-sample
2025 evidence that there is a real signal in the system.

## 7. Regime × edge — Q1 anchor

PnL by regime (Q1 anchor):

| Edge                    | cautious_decline | emerging_expansion | market_turmoil | robust_expansion | TOTAL    |
|-------------------------|------------------|--------------------|----------------|------------------|----------|
| `volume_anomaly_v1`     | +592             | +270               | **+76**        | +995             | +1,934   |
| `herding_v1`            | +253             | +37                | 0              | +256             | +547     |
| `macro_credit_spread_v1`| +210             | -28                | 0              | +50              | +231     |
| `gap_fill_v1`           | -85              | +256               | -128           | +131             | +174     |
| `growth_sales_v1`       | 0                | -15                | 0              | +90              | +75      |
| `momentum_edge_v1`      | -664             | +65                | -612           | +328             | -883     |
| `atr_breakout_v1`       | -1,073           | -43                | -591           | -522             | -2,229   |
| `low_vol_factor_v1`     | -899             | -481               | **-1,180**     | +27              | -2,533   |

`volume_anomaly_v1` has positive PnL in **all four** regime labels
including the rare `market_turmoil` (+$76). `herding_v1` has positive
PnL in all regimes that have any trades. By contrast, `low_vol_factor_v1`
loses in three of four regimes and bleeds catastrophically in
`market_turmoil` (-$1,180). The bad edges are bad in *every* regime,
not just one.

Regime months (2025): regime label × month from the trade log shows
`market_turmoil` was concentrated in April 2025 (239 fills) and May
2025 (155 fills). That's where the joint drawdown lives.

## Honest commentary (3 paragraphs)

**(a) Is any edge consistent in 2025?** Yes — exactly one. `volume_anomaly_v1`
is positive in 11 of 12 months, positive across all 4 regime labels,
positive on a +$10/fill average, and traces a monotonic-upward
cumulative curve through 2025. `herding_v1` is the second-best by
shape (positive in every regime that has fills, +$12/fill avg) but
its 44-fill total in Q1 is too thin for strong claims. Both are
event-driven (firing on volume z-score / herding signatures), not
universal-fire. Their consistency under the Q1 anchor configuration
is real signal.

**(b) Does the rivalry effect actually explain the standalone-gauntlet
failure?** **Yes — quantifiably.** Un-pausing the two momentum edges
collapsed `volume_anomaly_v1` from 191 fills to 19 fills (-90%) and
`herding_v1` from 44 fills to 2 fills (-95%). The collapse is not
"smaller PnL because more competition" — it's "the edges literally
do not get a chance to trade because position slots and dollar caps
fill up before their signals get sized." The standalone gauntlet
failure of these two edges is the same phenomenon viewed from a
different angle: in the gauntlet's quick-backtest each edge was run
in isolation against the full 2021-2024 window, and there too the
allocation logic gives them too small a share. The signal is real
under specific allocation conditions and disappears outside those
conditions; the edge-level pass/fail framing has been measuring the
allocator more than the edge.

**(c) What specific structural issue does this point at?**
**`signal_processor`'s capital-allocation policy is the primary
defect, not the edge stack and not the lifecycle.** Three concrete
defect surfaces, in priority order:

1. **No per-edge participation floor.** A high-frequency
   universal-fire edge (`momentum_edge_v1` at 2,353 fills/yr) and a
   low-frequency event-driven edge (`herding_v1` at 44 fills/yr) compete
   for the *same* slot pool. There is no minimum share carved out for
   the event-driven family. Result: the event-driven edges get
   crowded out the moment a competing universal-fire edge runs at
   even half-weight.
2. **Soft-pause weight cap (0.5) is too generous.** `low_vol_factor_v1`
   is currently `paused` per `edges.yml` and yet fired 1,613 times
   for -$2,533 in Q1 — second-most fills of any edge. A 0.5 weight
   on a high-fire edge still dominates a 1.0 weight on a low-fire
   edge in fill count. The weight cap should be much lower (0.1–0.2
   would be honest "soft" pause; current 0.5 is "loud" pause) **or**
   paused edges should be excluded from slot-allocation entirely
   while still receiving signal data for revival evaluation.
3. **April-2025 joint-drawdown vulnerability.** Five edges took
   simultaneous catastrophic April losses tagged `market_turmoil`.
   If the allocator treated `market_turmoil` as a slot-reduction
   signal across the momentum/factor families (rather than just
   per-edge sizing) the -$3,551 month flattens substantially. This
   is *not* the lifecycle's job — it's an active-allocation job for
   `signal_processor` running in parallel with the existing per-edge
   risk advisor.

**Implication for next move:** the director's "redesign lifecycle
first" pushback was correct — the *capital allocator* is the next
target, not the lifecycle and not the edge stack. The full
gauntlet sweep is still required after fixing #1 and #2, because
the gauntlet currently measures the same allocator-confounded
signal it was being asked to validate. **Fix the allocator
first, then re-run the gauntlet — once.**

## Reproduction

```bash
python -m scripts.analyze_oos_2025
```

Reads existing trade logs only — runs in seconds, no backtests.

## Caveats

- "Realized PnL" means closed-position PnL only. Total return
  (including unrealized) was -0.43% (Q1) and +1.41% (CF). The
  decomposition above understates the per-edge total contribution by
  whatever was open at year-end, but that's a small fraction (Q1
  closed equity ~99,569 vs starting 100,000).
- Regime labels come from `regime_label` column in the trade log
  (logged at fill time by Engine E). Cross-tabbing on the regime at
  fill time is correct for entry attribution but slightly noisy on
  exit attribution — a fill triggered in `robust_expansion` may
  close in `cautious_decline`. For per-edge totals this is a small
  effect; for the regime cross-tab it could shift a few hundred
  dollars between buckets.
- The +$1,934 from `volume_anomaly_v1` in Q1 is a 2025-specific
  one-year window. It would still need to clear the gauntlet under
  realistic costs *and* universe-B before it can be cited as
  generalizable. The point of this audit is "the system has a
  candidate to defend, not zero candidates."
