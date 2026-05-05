# Strategic Assessment & Pivot — 2026-04-24

> Triggered by user question: "After all of your findings, where are we at? It's still underperforming SPY. How do we get it to actually beat the market? Where are our real problems? Would better data help? What else should we look into?"
>
> This is the honest answer captured in full so the reasoning is not lost. The infrastructure work in this session arc (determinism floor → walk-forward audit → autonomous lifecycle) is necessary but not sufficient. This doc captures the diagnosis, the action ranking, and the explicit anti-actions before pivoting to alpha work.

## Executive summary

The system is, today, a **half-beta SPY sleeve with better drawdown control**. It matches SPY on risk-adjusted return out-of-sample on average, wins on drawdown, and loses badly on raw return. The autonomy machinery just shipped is necessary plumbing — it doesn't create alpha, it just lets us measure honestly which alpha is real. After honest measurement, the answer is: **the edges and the data are too generic to beat SPY**. Real improvement requires either (a) data the market isn't already fully pricing, or (b) well-validated academic factors the current edge roster ignores. Not infrastructure work anymore. Alpha work.

## Where we actually are (post-autonomy baseline)

Canon `d3799688ad14921a3e27e70231013d70`. All advisory features active, `atr_breakout_v1` autonomously paused at 0.25x weight by lifecycle.

| Window | System Sharpe | SPY Sharpe | System CAGR | SPY CAGR | System MDD | SPY MDD |
|---|---|---|---|---|---|---|
| In-sample 2021-2024 | **0.979** | 0.875 | 7.14% | 13.94% | -12.39% | -24.50% |
| Split A eval 2023-2024 | 1.92 | 1.87 | 11.08% | 25.93% | -5.76% | -9.97% |
| Split B eval 2024-2025 | 1.025 | 1.31 | 6.07% | 22.16% | -4.61% | -18.76% |
| Split C eval 2025 | 0.66 | 1.00 | 4.42% | 19.13% | -5.54% | -18.76% |

**OOS averages: system Sharpe ≈ 1.20, SPY Sharpe ≈ 1.39.** SPY wins by 0.19 Sharpe on held-out data. Risk-adjusted parity at best, raw-return loss across the board, drawdown win across the board.

Per-edge contribution from the verified Sharpe-0.98 baseline run:

| Edge | Closes | Total P&L | Mean | WR | Per-trade Sharpe |
|---|---|---|---|---|---|
| **momentum_edge_v1** | 465 | **+$14,823** | +$31.88 | 53.3% | +2.23 |
| atr_breakout_v1 | 1274 | **-$5,365** | -$4.21 | 42.2% | -0.33 |
| Unknown | 71 | -$154 | -$2.16 | 42.3% | -0.25 |
| others combined | 6 | +$79 | — | — | tiny sample |

**~80% of the trading P&L comes from a single edge** (`momentum_edge_v1` — a 10/40 SMA crossover). The other 12 edges are either small-sample noise or active drag.

Aggregate-level decomposition (from session A/B audits): of the 0.98 baseline Sharpe, roughly half is leverage amplification from the advisory stack (`risk_advisory` +0.24, `vol_target` +0.12, `exposure_cap` +0.16). The underlying signal alpha is closer to 0.5 Sharpe — barely positive, and below SPY buy-and-hold.

## Diagnosis — five root causes, ranked by severity

### 1. The raw edges are too well-known to produce alpha (severity: critical)

ATR breakouts, RSI mean reversion, moving-average crossovers, gap fills, day-of-week seasonality, volume anomalies. These are the same technical indicators retail and institutional quants have been mining since the 1980s. Forty years of the same patterns being traded by everyone has driven their edge to ~zero (and below, after costs). The audit confirms this: the only edge with material per-trade Sharpe (`momentum_edge_v1` at +2.23) is itself a basic SMA crossover that any trend-following ETF replicates.

**Implication:** No amount of better validation, better risk overlays, or better regime detection will rescue an edge roster that's exclusively classical-technical. The infrastructure can't manufacture alpha that isn't in the signals.

### 2. The data is thin (severity: critical, fixable)

The system sees price, volume, and 5 fundamental ratios (PE, PS, PB, PFCF, Debt-to-equity). That's it. What it doesn't see, in approximate order of expected alpha contribution:

- **Earnings calendar + surprise magnitudes.** PEAD (post-earnings announcement drift) is the most robust single-factor alpha in academic literature — ~2% monthly excess for 2-3 months after a positive surprise. Free from Finnhub.
- **Macro indicators (FRED API).** Yield curve (DGS10/DGS2), credit spreads (HY-IG OAS), Fed funds (DFF), CPI, unemployment claims, UMich consumer sentiment (UMCSENT — substitutes for ISM PMI which is no longer free on FRED). Free. Drives both standalone signals and a much better regime classifier than the price-only one we have. **Status (2026-04-24 late): scaffold landed via parallel session as `engines/data_manager/macro_data.py`; integration into edges or Engine E is the next step.**
- **VIX term structure.** Single best crash predictor in volatility space. Free from CBOE.
- **Insider transactions.** Net insider buying historically predicts 3-12 month returns. Free scraping from OpenInsider.
- **Options surface (IV, skew).** Drives event-driven and vol-regime strategies. Moderate cost.
- **Alternative data** (web traffic, credit card, app downloads). Where institutional alpha increasingly lives. Expensive.

**Implication:** Price-only systems compete with thousands of quant funds on the same inputs. That's negative expected alpha before costs. **Yes — better data would help enormously.** It's the single highest-leverage axis after raw-edge selection.

### 3. The universe is too narrow (severity: high, trivial to fix)

39 hand-picked tickers, almost all mega-cap US (AAPL, MSFT, NVDA, etc.). These are the **most covered, most arbitraged stocks in the world**. Cross-sectional strategies — long top-decile vs short bottom-decile by momentum/quality/etc. — need breadth. Russell 1000 (currently de facto top ~1000 US stocks) is the minimum credible universe for factor work. S&P 500 constituents alone is ~12x the current count.

**Implication:** Even good cross-sectional signals can't fire well on 39 names. The universe is a structural cap on what factor strategies can produce here.

### 4. Daily bars are an awkward timeframe for retail-scale alpha (severity: medium, structural)

HFTs eat intraday edges (price-improvement, microstructure). Quant ETFs eat monthly factor edges (momentum, value, quality at scale). Daily technical patterns sit in between — most exposed to crowding, least exposed to a structural moat. Real retail-scale alpha tends to live at:

- **Monthly rebalance for factor tilts** (momentum, quality, low-vol — 40 years of academic support, retail-replicable via ETFs like MTUM/USMV)
- **Event windows** (earnings drift, Fed meetings, guidance changes — multi-day to multi-week)

**Implication:** Daily bars aren't wrong, but they're the hardest timeframe to extract alpha at. Adding monthly-rebalance factor strategies would put us in a less crowded part of the space.

### 5. Engine D searches the wrong space (severity: medium)

The genetic algorithm evolves random combinations of technical-indicator genes (RSI thresholds, ATR multipliers, day-of-week, intraday-range ratios, etc.). It's mining a region that's been strip-mined. Even when it finds in-sample winners, the 132 auto-failures in `edges.yml` show the candidates can't pass walk-forward (now that Phase γ plumbing actually validates them). **The space being searched has no alpha left.**

**Implication:** Re-architecting Engine D to search the **factor space** (which factors, which lookback windows, which weighting schemes, which universe slices) instead of random technical-gene combinations would have a higher hit rate and produce more principled candidates.

## What's NOT the problem (anti-list — do not re-litigate)

- **The infrastructure** isn't the problem. The lifecycle machinery (β/γ/α/α-v2), determinism floor (Phase 0), walk-forward harnesses, and audit trail are all working and necessary. Keep them.
- **The advisory overlays** (`risk_advisory`, `vol_target`, `exposure_cap`) aren't the problem. Three were walk-forward-confirmed as net-positive on OOS data. They contribute ~50% of current Sharpe.
- **Determinism / reproducibility** isn't the problem. Canon-md5 stable across runs; we can A/B reliably.
- **Regime classifier accuracy** isn't the dominant problem. The regime-conditional kill-switch was falsified under walk-forward, and per-edge-per-regime conditioning was the wrong shape regardless. The classifier itself is fine for the limited use cases that survived audit (advisory-driven exposure cap, risk_scalar).

## What's fundamentally doubtful (no further investment)

- **Raw technical-indicator edges generating alpha at daily timeframes.** Strong prior against. Don't iterate parameters or evolve combinations of these — diminishing returns to zero.
- **Engine D's GA evolving compositions of technical genes finding new alpha.** Same reason. The search space is exhausted.
- **Per-edge per-regime conditioning via the current 4-regime label classifier.** Falsified under 3-split walk-forward. Don't re-attempt without redesigning the regime signal source (continuous features, coarser groupings, or portfolio-level overlay).

## Action ranking — what to do, in priority order

### Short-term (days to 1-2 weeks, high ROI)

1. **Run Phase ε.** Demote the 13 base edges to `candidate` via `scripts/reset_base_edges.py --confirm`, let the autonomous validation pipeline (now working post-Phase γ) re-validate each. Outcome: a clean evidence-based active roster, probably 2-4 edges. Trims dead weight, makes the system coherent. ~6-8 hours of autonomous validation; minimal human oversight needed.
2. **Expand universe to S&P 500 constituents.** Single config change in `backtest_settings.json`. Unlocks breadth for cross-sectional strategies. No new code. Half a day max including a regression run.
3. **Add a factor-tilt edge: 12m-minus-1m momentum + low-vol filter, monthly rebalance, sector-neutral.** This is the **single highest-probability Sharpe contributor** of any item on the list. 40+ years of academic validation; retail-replicable ETFs (MTUM, USMV) deliver Sharpe 0.8-1.2 net of costs on this. New file `engines/engine_a_alpha/edges/momentum_factor_edge.py`. ~1 week. Walk-forward A/B against current stack — if it adds 0.3+ OOS Sharpe, the system starts looking competitive.

### Medium-term (1-4 weeks, changes the picture)

4. **Add FRED macro data pipeline.** `engines/data_manager/macro_data.py` — daily fetch + cache for yield curve (DGS10, DGS2), credit spreads (BAMLH0A0HYM2), Fed funds (DFF), CPI, unemployment claims, ISM PMI. **Free.** Two uses: (a) features for new edges (e.g., a "yield curve inversion ahead → reduce equity exposure" signal), (b) inputs to a redesigned regime classifier (price-only is the core reason the current classifier mislabels). Plumbing-heavy, alpha-rich.
5. **Add earnings calendar + surprise data (Finnhub free tier or scrape).** Unlocks PEAD edge. Most robust single-factor alpha in academic literature. New edge `engines/engine_a_alpha/edges/pead_edge.py` — signal magnitude = (actual EPS − consensus) / |consensus|, hold 60 trading days. Expected standalone Sharpe 1.0+, well-documented degradation across decades.
6. **Re-architect Engine D around factor discovery, not random technical mutations.** Search space becomes: which factors (momentum, value, quality, low-vol, size), which lookback windows (1m, 3m, 6m, 12m, 24m), which weighting (equal, vol-weighted, quality-tilted), which sector-neutralization. Same GA scaffolding, different gene vocabulary. Higher hit rate, more interpretable winners.

### Longer-term (1-3 months, transforms the system)

7. **Alternative data.** Web traffic (Similarweb API ~$500/mo), credit card aggregates (Second Measure — institutional), app store rankings, satellite parking-lot counts. Where real institutional alpha lives now. Costs money and takes integration work, but the alpha is there if you can pay for it.
8. **Options surface (IV term structure, skew).** Edge in volatility-regime detection (VIX term structure inversion is a strong recession signal) and event-driven strategies. Moderate cost ($100-500/mo from CBOE or via OptionMetrics academic).
9. **Intraday or weekly cross-sectional strategies.** Requires backtest-loop refactoring. Different timeframe = different alpha = different infrastructure. Substantial, low priority until the current daily strategies are proven.

## What I would specifically NOT do (anti-action list)

- **Don't keep iterating regime classifiers without new data.** We've spent multiple sessions on this. The walk-forward evidence is decisive: per-edge-per-regime conditioning with price-only features doesn't generalize. Adding more axes or finer hysteresis won't fix it. Add macro data first (item #4), then revisit.
- **Don't fine-tune existing technical edge parameters.** Diminishing returns to zero. The edges are the problem, not their hyperparameters. `atr_breakout_v1`'s losses at `2.5x` weight are not fixed by tuning to `2.3x`.
- **Don't build more advisory overlays on top of the existing three.** Vol_target, exposure_cap, risk_advisory are near the ceiling of what price-derived runtime features can give. A fourth overlay won't add another 0.16 Sharpe. The yield is exhausted at this layer.
- **Don't add another technical-pattern edge** (e.g., "channel breakout v2", "MACD divergence"). Same space, same crowding, same expected alpha (zero).
- **Don't re-enable the per-edge per-regime kill-switch.** Falsified under 3 walk-forward splits, currently disabled. Don't re-litigate without first redesigning the regime signal source.
- **Don't push toward live deployment** while OOS Sharpe is below SPY. The "Bones before Paper" principle applies — fix the alpha problem before the broker integration problem.
- **Don't optimize for in-sample Sharpe.** The audit established that in-sample A/B is unreliable for anchor-fit features. Every change needs walk-forward verification before claiming improvement.

## What I'd start tomorrow if it were my money

In strict order:

1. **Run `python -m scripts.reset_base_edges --confirm`** — kicks off Phase ε. Background-able, ~6 hours of autonomous validation. Wakes me when done with a clean, evidence-based active edge roster.
2. **Edit `config/backtest_settings.json`** — replace the 39-ticker universe with current S&P 500 constituents. Half a day including regression run, deterministic verification, and an A/B Sharpe measurement to confirm no regression.
3. **Write `engines/engine_a_alpha/edges/momentum_factor_edge.py`** — long top-decile by 12m-minus-1m momentum, sector-neutralized, monthly rebalance. Walk-forward A/B against the current stack on the now-broader universe. **This is the moment-of-truth test** for whether factor-style alpha can rescue the system. If it adds 0.3+ OOS Sharpe across walk-forward splits, we're competitive. If it doesn't, the alpha problem is deeper than "factors weren't included" and we need data expansion (item #4) before anything else.
4. **Based on #3 result**, either push harder on factors (add quality, low-vol, size) or pivot to data-source expansion (FRED macro, earnings surprises). Both paths are mapped above.

## Bottom line

The problem isn't infrastructure. The problem is **the inputs and the search space**. The infrastructure work that just shipped is the prerequisite for honestly measuring future alpha experiments — without it, everything would be in-sample fitting noise. With it, we can A/B real changes (factor edges, new data sources) under a deterministic harness with benchmark-relative validation gates and autonomous lifecycle management. The system can now correctly tell us "this works" or "this doesn't" — which it couldn't a week ago.

What it cannot do is invent alpha that doesn't exist in the inputs. That's the next problem to solve, and it's not a code problem — it's a data and edge-design problem.

---

## Pick up next time

The user's specific instruction at the end of this conversation: "Then we'll start working on the highest-leverage item." Highest-leverage = **Phase ε (item #1) immediately, in parallel with universe expansion (item #2)**, leading into the factor-edge build (item #3) which is the moment-of-truth alpha test.

Concrete next action when this session resumes: run `python -m scripts.reset_base_edges --confirm` to demote the 13 base edges, then expand the backtest universe to S&P 500 constituents, regression-verify, then start the factor-edge implementation.

---

## POST-EXPERIMENT UPDATE — factor edge attempt (same day)

Attempted item #3 (`momentum_factor_v1`) on the existing 39-ticker universe to see if it would deliver alpha before doing the universe expansion. Result: **in-sample +0.13 Sharpe lift looked promising, walk-forward across 2 OOS splits decisively falsified the result** (Split B -0.19, Split C -0.62 Sharpe). Edge has been marked `failed` and weight set to 0; code retained for re-test once universe is expanded.

The action ranking from this doc is **revised** based on the data:

1. **Item #2 (universe expansion to S&P 500) is now a hard prerequisite**, not "nice to have." Cross-sectional factor work on 39 names = top-quintile of 8 = concentration risk masquerading as factor exposure. Don't add any more factor edges on this universe — they'll all fail the same way.
2. **Item #4 (FRED macro data) becomes the highest-leverage parallel track.** Macro context (yield curve, credit spreads, VIX term structure) is orthogonal to whatever the price-only stack can see. Even without universe expansion, FRED-driven signals can produce alpha that doesn't depend on cross-sectional breadth.
3. **Item #1 (Phase ε — demote and re-validate base edges) remains valuable** but is no longer the highest-leverage item; it's an internal-cleanup pass that doesn't add alpha.
4. After universe expansion lands, **re-test `momentum_factor_v1`** (code is retained). If it works at 100-name top-quintile, expand into low-vol / quality / value factor family. If it still fails, the issue is deeper than universe size and we lean harder on data sources.

**Methodology validation:** the walk-forward harness caught a 0.75 Sharpe overfitting gap between in-sample and OOS. Without it, this edge would have shipped as a win. The infrastructure built in the prior session arc (determinism floor, walk-forward harnesses, autonomous lifecycle) is now demonstrably earning its keep — every alpha experiment goes through this filter and either holds up or doesn't.

**Updated highest-leverage next action when this session resumes**: parallel-track universe expansion (item #2) and FRED macro pipeline (item #4). The FRED work is best handled by a separate session/instance since it doesn't conflict with anything; the universe expansion needs careful coordination because it affects backtest runtime and data pipelines.

---

## What needs adding (status as of 2026-04-25)

User actions (only the user can do — all infrastructure is in place):

- **`FRED_API_KEY`** in `.env` + bootstrap command → activates `macro_yield_curve_v1` edge
- **`FINNHUB_API_KEY`** in `.env` + bootstrap → activates `pead_v1` edge
- **`scripts/fetch_universe.py` invocation** (parallel-agent design) → activates survivorship-aware S&P 500, unblocks proper factor work

Architectural work (substantive, not autonomous-loop-sized — see today's session summary for full framing):

- **Conditional-weight composition primitive** in signal_processor — the single most important architectural answer to today's low_vol failure. Cross-sectional factor edges with regime-conditional alpha cannot deploy as constant-weight contributors; need either edge-level `regime_gate` metadata or engine-E-driven per-edge multipliers.
- **Engine D rework** to search factor/macro/earnings space (instead of technical-only genes).
- **Macro-aware regime classifier** (Engine E redesign) — replace price-only with FRED-driven, requires the FRED cache populated first.

The user-side actions are unblocking; the architectural items are about RE-DEPLOYING what we already built. Empirically: the autonomy machinery, walk-forward harnesses, lifecycle, and edge templates are all working. What's missing is real data flowing through them, plus the composition layer that lets regime-conditional factors actually contribute.

---

## SECOND POST-EXPERIMENT UPDATE — universe expansion + FRED scaffold (same day, late)

**FRED scaffold landed** via parallel session — see `2026-04-24_session_fred_pipeline.md`. New module `engines/data_manager/macro_data.py` with 18-series registry, parquet cache, 23 passing tests, documented. Stale note in this doc about "ISM PMI" — FRED's `NAPMPMI` is discontinued; the parallel agent substituted `UMCSENT` (UMich consumer sentiment) as the closest free growth proxy. Update item #4 expectations accordingly. The macro layer is foundation-ready; integration into edges or Engine E is the next handoff, not more data-layer work.

**Universe expansion landed** in `config/backtest_settings.json`: 39 → 109 tickers (2.79x). Data was already present in `data/processed/` (113 files, ETF subset excluded). Backup at `config/backtest_settings.json.pre-universe-expansion`.

**Methodology correction (autonomy-first):** After expanding the universe, the right next step is NOT to manually re-tune existing edge weights to fit the new universe. Per `feedback_no_manual_tuning.md`, the system should autonomously rebalance via the lifecycle machinery shipped in Phase α/α-v2. Specifically: run a full backtest WITHOUT `--no-governor` so `governor.evaluate_lifecycle()` fires; let it pause/retire any edge that no longer beats benchmark on the wider universe; observe what survives. If the lifecycle can't handle a 2.79x universe expansion cleanly (cycle caps too tight, evidence thresholds wrong, etc.), that's a gap in the autonomy machinery to fix in code — not a license to hand-tune. The right test is "what does the system decide to do?" not "how should I decide for it?"

This is the first real stress-test of the autonomy machinery. atr_breakout's pause was on a single losing edge in an unchanged universe. Universe expansion changes which edges work and which don't (some edges may have implicit large-cap-tech bias; small/mid-cap names break those assumptions). The lifecycle should respond.

## Files touched (this strategic-pivot session segment)

```
docs/Progress_Summaries/2026-04-24_strategic_pivot.md  (new — this file)
engines/engine_a_alpha/edges/momentum_factor_edge.py   (new — retained, weight 0, status failed)
scripts/walk_forward_factor_edge.py                    (new — reusable for future factor edges)
config/alpha_settings.prod.json                        (added then zeroed momentum_factor_v1 weight)
data/governor/edges.yml                                (registered then marked failed)
```

## Subagents invoked

None this session. Future factor-related work (universe expansion, additional factor edges after universe expansion lands) should route through `quant-dev` and `edge-analyst` subagents per the `.claude/agents/` infrastructure. FRED data integration work (run in parallel) routes through a separate Claude session per the user's coordination plan.
