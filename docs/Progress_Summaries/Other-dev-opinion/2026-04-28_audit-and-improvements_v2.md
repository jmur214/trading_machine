# What I'd need before risking my own capital

Honest answer: with the system in its current state, **I wouldn't put a dollar in.** The gap isn't that the alpha is weak (that's fixable). The gap is that the **infrastructure that protects me from my own bugs doesn't exist.** Here's the actual checklist.

## Tier 1 — Non-negotiable. No money flows until ALL of these are true.

### 1. Six months of shadow-live trading on the same code path

Not backtests. Not paper trading in some special mode. The **exact code that would trade real money** must run for 6 months against the live Alpaca API in paper mode, tracking every decision, every order, every fill, every reconciliation. **The simulated/backtest Sharpe is meaningless until it survives the gap to live execution.** Industry data: 50%+ of backtest Sharpe disappears when you go live, due to slippage, latency, microstructure effects the backtest didn't model. I need to see what's left after that crossing.

### 2. OMS that I trust under failure

`live_trader/live_controller.py` is 22 lines. That's not a live trading system; it's a wrapper. Before money: **Alpaca disconnect / retry / idempotency / partial-fill handling / cancel-on-disconnect / position-vs-broker reconciliation / rate-limit handling / max-order-size guard / max-orders-per-minute guard / heartbeat monitor.** If any of those is missing, one bad day eats years of compounded alpha.

### 3. Beats SPY net-of-everything in shadow

Net of: realistic slippage (not 10bps flat), commissions, taxes (short-term cap gains for momentum strategies is brutal), the cost of my time, opportunity cost of capital. **Currently the system loses to SPY by 0.19 Sharpe in OOS backtest.** Until shadow-live shows positive alpha vs the obvious alternative (QQQ buy-and-hold), there's literally no reason to deploy.

### 4. Factor decomposition done and clean

Run every edge's return stream through Fama-French 5 + momentum + quality regression. **The intercept must be statistically significant and economically meaningful (>2% annualized, t-stat >2).** If 70% of "alpha" turns out to be momentum-factor beta, I can buy MTUM for 15bps and get the same thing without the system risk. **Until this regression is run and survives, every claim of alpha is unverified.**

### 5. Tail hedge sized to cap drawdowns

Long-VIX or long-OTM-puts sleeve, sized to bleed 1-1.5% per year and cap worst drawdown at -10%. **A long-bias momentum system with no tail hedge will lose me 30%+ in the next real crash, period.** I won't deploy capital that can't survive 2008/2020-style moves. The system as designed will.

### 6. Portfolio-level kill switch with tested failure modes

Hard stops:
- `-5% daily` → flatten everything, alert
- `-10% weekly` → flatten, halt for review
- Position vs broker mismatch → halt
- Data feed gap > 5 min → halt
- Latency spike > N ms → halt

**These must be tested with simulated failures.** Build a chaos-engineering harness that injects: dropped connections, stale data, doubled fills, wrong-direction orders, broker outage. Verify the system halts safely every time. **Until this is tested, the kill switch is theater.**

### 7. Position-level vol targeting + correlation-aware sizing

Replace `risk_per_trade_pct: 0.025` fixed fraction with target-vol sizing that accounts for cross-position correlation. **The current sizing logic guarantees ruin in a correlated drawdown** because it doesn't know the positions are correlated.

### 8. Point-in-time data audit

Run a leakage audit on every feature. **Prove what was knowable when.** Earnings data with as-of dates, fundamentals with restatement-aware versioning, index constituents at point-in-time (no survivorship). My prior is that 0.2-0.4 Sharpe of the current backtest is leakage that won't replicate in shadow-live.

### 9. Reproducibility — data versioning, code pinning

Any historical trade decision must be **exactly reproducible** from the code commit + data version + random seed at the time. Without this, I can't audit what went wrong when something blows up. DVC or lakeFS for data, git SHA pinning per backtest run.

## Tier 2 — Strongly required before scaling beyond toy size

### 10. Independent adversarial critic running live

LLM critic that examines every trade before send and posts disagreement. Logged. **If the critic disagrees and the trade still happens and loses, that's a learnable signal.** Builds the override-rationale dataset over time.

### 11. Capacity analysis

For every edge: at what AUM does my market impact eat the alpha? **If a strategy works at $10k but breaks at $100k, I need to know that before scaling.** Without it, success kills the system.

### 12. Decision rationale logged per trade

Every order ships with: which edges fired, what their scores were, what the regime was, what the override status was, what features were missing. **Without this, post-mortems are impossible.**

### 13. Cockpit with intervention controls

`cockpit/dashboard_v2/` lets me: pause edges, force-flatten, override regime, reduce exposure 50%. Currently the human has no graduated lever between "all on" and "kill." **Real money requires real controls.**

## Tier 3 — Required for me to feel good (not strict bar)

### 14. Reconciliation cron — broker truth vs internal truth

Every 5 minutes, compare broker positions/cash vs internal state. Log discrepancies. Halt on divergence > threshold. **Drift between internal and broker state is how funds lose money silently for months.**

### 15. Multi-method alpha agreement

Before promoting an edge to live, it must be confirmed by ≥2 of: walk-forward backtest, causal discovery, transfer test (cross-section + time + geography), shadow-live. **One method's confirmation is a guess. Multiple methods agreeing is evidence.**

### 16. Insurance / account separation

The system trades from a dedicated account that holds ONLY the deployed capital. **No mingling with other savings.** Worst case = I lose what's in that account, not the rest of my net worth. Use Alpaca's account-segregation if available; otherwise a separate brokerage entity.

## Sizing even after all that

Even with every box checked, **I'd start at 1-2% of net worth**, not 10%, not 50%. Kelly criterion with realistic uncertainty about the edge gets you to single-digit-% sizing for a brand-new system, no matter how good the backtest looked. **Scale up only after live track record, not before.** Probably 12 months of profitable shadow-live + 6 months of profitable real-money-at-tiny-size before the first scale-up. **Patience is the cheapest risk control.**

## The honest bottom line

The system is currently at maybe **20% of the bar** for me to deploy real capital. Most of the work isn't sexy alpha discovery — it's the boring infrastructure that makes the difference between "interesting research project" and "production trading system." 

**If I had to rank by what I'd build first to close the gap**: shadow-live infrastructure (#1), real OMS (#2), tail hedge (#5), factor decomposition (#4), kill-switch chaos testing (#6). Those five alone would take 6-12 months of focused work and cost ~$0. Without them, the "deploy live" question is academic — it's not that the answer is "no," it's that **the question can't be honestly asked yet.**

The harshest version: a system that has never traded a real dollar and loses to SPY in backtest is **infinitely far from deserving capital, no matter how elegant the architecture.** The path forward is closing that gap, in the order above.

---

Still want the consolidated `.md` file from this whole conversation? Happy to write it once you confirm.'

# Non-AI path to beating SPY

Stripping out all the LLM/ML/RL stuff. Pure statistics, classical finance, and infrastructure. This alone gets you above SPY if executed honestly.

## General principles (the philosophical shifts)

### 1. Honesty over optimism in validation
Most "alpha" disappears when costs, leakage, and survivorship are honest. **Fixing the backtest is worth more than finding new edges.** Tier 1 below.

### 2. Diversification of edge *type* beats more of the same
28 momentum-flavored edges is one edge with 28 expressions. **Two uncorrelated edges with 0.5 Sharpe each combine to ~0.7 Sharpe portfolio.** Edge orthogonality is the cheapest Sharpe in the building.

### 3. Risk control compounds Sharpe
Vol-targeting alone documents +0.2–0.4 Sharpe over fixed-fraction. **Sizing is half the alpha.**

### 4. The market is multi-asset, not equity-only
Yield curves, credit spreads, the dollar, oil, crypto — all free, all leading. **Equity-only is willful blindness.**

### 5. Calendar/structural effects are persistent
FOMC drift, turn-of-month, pre-holiday — they exist because they're structural (mandate-driven flows), not crowded. They've persisted 30+ years.

### 6. Execution timing IS alpha
*When* you trade matters. The first 15 and last 15 minutes are noise factories. Avoid them.

### 7. Honest factor accounting
Stop calling momentum-factor beta "alpha." Run a Fama-French regression. **The intercept is your real edge.** Anything else is rebrandable as a 15bps ETF.

### 8. Smaller universe done well > larger done poorly
The 39→109 ticker expansion *worsened* OOS performance. **Specialize edges to sub-universes** (momentum on growth names, mean-reversion on utilities) instead of forcing one approach across all.

---

## Tier 1 — Stop the lying (do these FIRST)

**Until validation is honest, every other change is noise.** These don't add alpha; they reveal whether existing alpha is real.

### Specific moves

1. **Honest cost model in `backtester/execution_simulator.py:31-34`.** Replace `slippage_bps: 10.0, commission: 0.0` with: bid-ask spread by ADV bucket (1bp for SPY, 5bp for mid-caps, 15+ for small), square-root market impact (`σ × √(order_size/ADV)`), borrow rate for shorts (5–25 bps/day), short-term cap gains tax drag.

2. **Point-in-time data.** Fundamentals stamped with the date they were *first reported*, not restated dates. Index constituents as of the date (no survivorship). `reproduce_fundamentals.py` at root is the tell that this isn't done.

3. **Combinatorial Purged Cross-Validation (CPCV)** replacing whatever walk-forward currently exists. López de Prado's method — embargoed, purged, multi-fold. ~300 lines.

4. **Multiple-testing correction on every edge promotion.** Bonferroni or Benjamini-Hochberg. If you tested 100 hypotheses, p<0.05 isn't significant — p<0.0005 is. **Currently the system has zero correction. Most promoted edges are statistical artifacts.**

5. **Factor decomposition.** Every edge return stream → regression on Fama-French 5 + momentum + quality. **Promote only edges with statistically significant, economically meaningful intercept (>2% annualized, t-stat >2).** Run via `statsmodels.OLS`.

6. **Re-benchmark from SPY to QQQ + 60/40 vol-matched.** SPY is the flattering benchmark. Honest comparison is QQQ for the implicit factor exposure, 60/40 for risk-adjusted return.

7. **Reproducibility via DVC** for data versioning. Every backtest pins exactly which data it used.

---

## Tier 2 — Sizing and risk (multiplies whatever alpha exists)

### Specific moves

8. **Portfolio-level vol targeting.** Target 10% annualized vol; scale gross exposure inversely to realized vol. **Documented +0.2–0.4 Sharpe across literature.** ~50 lines in `engines/engine_b_risk/`.

9. **Correlation-aware position sizing.** Build the position covariance matrix; size each position so its marginal contribution to portfolio vol is bounded. Replaces `risk_per_trade_pct: 0.025` fixed fraction.

10. **Half-Kelly per edge.** For each edge, compute Kelly fraction from win rate × win/loss ratio. Use HALF Kelly (full Kelly is too aggressive when edge estimates are noisy). Document in code why.

11. **Forecasted vol (GARCH/HAR-RV) instead of realized ATR.** `arch` package, ~100 lines. Better sizing input → better Sharpe.

12. **Tail hedge sleeve.** 1–2% notional in long 30-delta SPY puts rolled monthly. Bleeds 1–1.5% per year, caps drawdowns at -10%. **Without this the system loses 30%+ in the next real crash.** Non-negotiable for capital deployment.

13. **Portfolio-level kill switches.** Hard stops at -5% daily / -10% weekly. Position-vs-broker reconciliation halt. Data-feed-gap halt. Latency-spike halt. Tested via chaos engineering.

14. **Concentration limits.** Max 5% per name, 20% per sector, 30% per factor exposure. Hard limits in `engines/engine_b_risk/`.

---

## Tier 3 — New edge types (the actual alpha sources)

These are documented in academic literature, persist after publication, work at retail size, and are *uncorrelated* with the current SMA momentum sleeve.

### Specific moves

15. **Cross-sectional momentum.** Rank universe by 12-month minus 1-month return; long top decile, short bottom decile (or long-only top quartile). Academic Sharpe ~0.5–0.7. Asness et al., "Value and Momentum Everywhere."

16. **Cross-sectional value.** Composite rank: low P/E + low P/B + low EV/EBITDA. Documented Sharpe ~0.4. Persistent. Anti-correlated with momentum (built-in diversifier).

17. **Cross-sectional quality.** ROIC + gross profit margin + low debt/equity composite. Robeco/AQR research, ~0.4 Sharpe.

18. **Low-volatility anomaly.** Long lowest-vol decile. Frazzini-Pedersen "Betting Against Beta," ~0.5 Sharpe, anti-correlated with momentum.

19. **PEAD (post-earnings announcement drift).** Long top decile of earnings surprise for 30 days. Uses Finnhub data already shipped. **~0.6 Sharpe, persists 50+ years post-publication.** **Highest-leverage single edge to add.**

20. **Earnings revision momentum.** Long stocks with rising consensus EPS estimates over 3 months. Bernhardt-Campello research, ~0.3 Sharpe.

21. **Insider buying clusters.** Form 4 from EDGAR. When 2+ C-suite insiders buy within 5 days, long for 60 days. Cohen et al., ~0.4 Sharpe.

22. **Pairs trading on cointegrated names.** Engle-Granger or Johansen test on related pairs (KO/PEP, MA/V, MCD/QSR). When spread > 2σ from mean, fade. ~0.3–0.5 Sharpe per pair, 20+ pairs available.

23. **Calendar anomaly battery.** Single 200-line file capturing:
    - **FOMC drift** (long the 24h before FOMC, ~0.3 Sharpe alone)
    - **Turn-of-month** (long last 4 + first 3 trading days, ~0.4 Sharpe)
    - **Pre-holiday** (long day before market holidays)
    - **Sell-in-May / Halloween indicator** (heavier May–Oct vs Nov–Apr exposure)
    - **Day-of-week** effects (Monday weakness, etc.)

24. **Volatility risk premium harvesting.** When VIX > 1.3× realized 30-day vol, sell vol via SPY put writing or short VIX futures sleeve. ~0.5 Sharpe but requires careful sizing (left-tail risk).

25. **Index arbitrage.** SPY vs sum-of-components, when divergence > threshold. Tiny edge per trade but high-frequency. Survives at retail size.

26. **Sector momentum rotation.** Monthly: long top 3 sectors by 6-month return, equal-weighted. ~0.3 Sharpe, low turnover.

---

## Tier 4 — Cross-asset features (the input expansion)

Free data, code-only integration. **Equity edges conditioned on macro state are dramatically more robust.**

### Specific moves

27. **Yield curve features.** 2y/10y slope, 3m/10y, real rates from FRED. Inverted curve = reduce equity exposure (recession leading indicator).

28. **Credit spread features.** HYG/IEF ratio, IG/HY spread. Widening = reduce risk.

29. **Dollar features.** DXY level and 30-day change. Strong dollar = headwind for SPX earnings.

30. **VIX term structure.** Front/back contango or backwardation. Backwardation = high stress, fade rallies.

31. **Crypto features.** BTC 48-hour return as risk-on/off (free via any exchange API). **BTC routinely leads risk assets at Monday open.**

32. **Commodity features.** Copper/gold ratio (growth), oil (geopolitics + cycle).

33. **Treasury MOVE index.** Rates volatility — leads equity volatility by 1–2 weeks.

34. **Put/call ratio + IV skew (CBOE free).** Extreme put-buying = capitulation; extreme call-buying = froth.

---

## Tier 5 — Execution and microstructure

### Specific moves

35. **Avoid first 15 / last 15 minutes** of regular session. Highest spreads, most noise. ~0.05–0.1 Sharpe lift just from this.

36. **Limit orders default, mid-or-better pricing.** Market orders only when liquidity is deep (mega caps). Saves 2–5 bps per trade.

37. **VWAP/TWAP execution** for any order > 1% of ADV. Use Alpaca's order types or implement client-side.

38. **Time-of-day awareness in signals.** Mean-reversion edges are strongest 11am–2pm; momentum strongest at open and close.

39. **Spread filter.** Skip trade when spread > 10 bps (or 2× recent average). Bad spreads telegraph stale liquidity.

40. **Pre-event reduce.** Cut exposure 30% in 24h before known events (FOMC, earnings for held names, OPEC, NFP).

---

## What to delete/stop

41. **Kill `engines/engine_a_alpha/edges/momentum_edge.py` (10/40 SMA crossover).** It's 80% of P&L and pure factor beta. Demote to a feature input, stop sizing trades from it directly.

42. **Pause Engine D (GA discovery).** It's mining strip-mined space. Either replace with symbolic regression + multi-test correction or shut off until inputs are richer.

43. **Stop optimizing pure Sharpe.** Switch to **Calmar ratio** (return / max DD) or **Probabilistic Sharpe Ratio** (Bailey-Lopez de Prado). Different objective → more robust portfolio.

44. **Stop the 109-ticker universe push.** Going wider hurt OOS. **Specialize, don't generalize.**

---

## Minimum viable set to beat SPY

If you only had time to do **the cheapest combination** that gets you above SPY net-of-costs, this is it:

**Phase 1 (90 days): Honesty layer**
- Tier 1, items 1–6 (honest costs, point-in-time, CPCV, multiple-testing, factor decomp, re-benchmark)

**Phase 2 (90 days): Risk + sizing**
- Tier 2, items 8, 9, 12, 13 (vol target, correlation sizing, tail hedge, kill switches)

**Phase 3 (90 days): Three uncorrelated alpha sleeves**
- Item 19 (PEAD) — 0.6 Sharpe potential
- Item 23 (calendar battery) — 0.3–0.4 Sharpe
- Item 18 (low-vol anomaly) — 0.5 Sharpe

**Phase 4 (60 days): Macro overlay**
- Items 27, 28, 30 (yield curve, credit, VIX term) as exposure modifiers

**Total: ~12 months of focused work, $0 in subscriptions, no AI.** Result should land 0.3–0.6 Sharpe above SPY *honestly*, with controlled drawdowns.

---

## The honest summary

The path to beating SPY without AI is unsexy but proven:

1. **Stop lying in the backtest** (Tier 1)
2. **Size right** (Tier 2)
3. **Add 3 uncorrelated, well-documented edges** (Tier 3 picks)
4. **Condition on macro state** (Tier 4)
5. **Execute cleanly** (Tier 5)
6. **Delete the noise generators** (the cleanup list)

**No new data subscriptions. No ML. No AI. No live infrastructure required to discover whether this works — it can all be validated in shadow-live for 6–12 months.** Then, only after that gauntlet, deploy capital.

The system has been chasing exotic improvements while skipping the boring fundamentals. **Boring done well beats exotic done poorly, every time.**

# Re-prioritized — and the edge factory at scale

You're right on both counts. Let me correct the framing.

## Why Tier 1 *truly* must come first (and Tier 2 doesn't)

**Tier 1 isn't a delay — it's the gate.** Here's the distinction I muddled:

- **Tier 1 = the validation gauntlet.** Without it, every edge you build is statistically indistinguishable from noise. You'd be running an "edge factory" whose output is unverifiable. **30 edges that haven't passed honest costs + leakage audit + multiple-testing correction is not 30 edges — it's 30 false positives.** That's worse than 3 real ones because false confidence kills accounts.

- **Tier 2 = deployment infrastructure.** Vol-targeting, tail hedge, kill switches — these matter when capital goes live, not when edges are being discovered. **Tier 2 can be built in parallel with Tier 3 and only matters at the deployment gate.**

So the corrected sequence:

```
                ┌─→ Tier 3 (edge factory, dozens of edges in parallel)
Tier 1 ──→──────┤                                                      ──→ Tier 2 ──→ Live
(validation         ↓                                                       (sizing,
 gauntlet)      Each edge passes the gauntlet to be promoted               kill switches,
                                                                            tail hedge)
```

**Tier 1 first because it gates Tier 3. Tier 2 last because it gates only deployment.** The factory and Tier 2 build in parallel.

## Why I limited Tier 3 to 3 edges (I was being timid — wrong)

The "minimum viable set" framing was conservative. **For your stated goal — many edges, autonomous combination — the limit on edge count should be how many can survive the gauntlet, not an arbitrary 3.** Empirical truth: institutional quant shops run 50–500 edges. Two Sigma reportedly runs ~10,000. **Edge count IS the edge** when combined with rigorous validation.

The right framing: **build an edge factory** that produces edges as fast as you can, gauntlet-validates them, and has a non-linear meta-learner figure out which combinations actually work.

## The Edge Factory architecture

### Common edge interface (`engines/engine_a_alpha/edge_base.py`)

Every edge conforms to one signature:
```
class Edge:
    name: str
    horizon: int            # bars
    universe: Callable      # which tickers it operates on
    def score(date) -> Series[ticker -> [-1, 1]]
    def metadata() -> dict  # category, expected Sharpe, decay assumption
```

This makes edges interchangeable. **The combination engine doesn't care what the edge is — it just gets a score per (ticker, date).**

### The gauntlet (Tier 1, automated)

Every new edge submission auto-runs through:
1. Walk-forward CPCV (purged combinatorial cross-validation)
2. Realistic costs (square-root impact, spreads, borrow, taxes)
3. Multiple-testing correction (Benjamini-Hochberg with q=0.10)
4. Factor decomposition (FF5 + momentum + quality)
5. Transfer tests: cross-sectional (A-M / N-Z), temporal (split halves), volatility regime (low/high VIX)
6. Adversarial validation (compare to 100 anti-alphas with same statistical signature)

**Edge enters live allocation only if intercept t-stat > 2 AND survives all four transfer tests AND beats 95th percentile of anti-alphas.** Pure statistics, no AI, fully automated.

### The combination engine (the autonomous part)

Once N edges have passed the gauntlet, you need to combine them. **Non-linear combination is where compounding lives.** Build sequentially in sophistication:

**Level 1 — Risk parity over edges.** Allocate to each edge inversely proportional to its return-stream variance. Rebalance monthly. Pure statistics, ~50 lines.

**Level 2 — Hierarchical Risk Parity (HRP).** López de Prado's method. Build a correlation-based hierarchical cluster of edges; allocate by traversing the tree. **Documented to outperform Markowitz on out-of-sample.** ~200 lines.

**Level 3 — Gradient-boosted meta-learner.** XGBoost/LightGBM takes edge scores as features, outputs next-period return prediction or position weight. **Catches non-linear interactions** (edge X works only when edge Y agrees AND volatility regime is low). This IS ML, not AI — no LLMs.

**Level 4 — Online Bayesian model averaging.** Each edge has a posterior over its alpha. Allocation = posterior-weighted, decays with poor performance. Self-balancing. ~400 lines using `pymc`.

**Level 5 — Reinforcement learning at the meta-level.** Treat allocation as an MDP, train RL agent (PPO or distributional Q-learning) to learn allocation policy. Reward = compounded P&L net of costs and drawdowns. Hardest to build, highest ceiling.

You can ship Level 1 in a week, Level 2 in a month, Level 3 in a quarter. **Each level is strictly more autonomous than the previous.**

## The actual edge inventory — aim for 80–100

Here's a realistic factory output across the categories:

### Cross-sectional ranking (~25 edges)
12-1 momentum, 6-1 momentum, industry-relative momentum, volume-confirmed momentum, 1-month reversal, P/E rank, P/B rank, EV/EBITDA rank, EV/Sales rank, ROE rank, ROIC rank, gross margin rank, FCF/sales rank, debt/equity rank, low-vol rank, low-beta rank, size factor, asset growth (low), accruals (low), net issuance (buyback bias), sales growth, margin expansion, ROIC change, profitability composite, quality composite

### Event/announcement (~15 edges)
PEAD, earnings revision drift, 8-K positive event drift, 8-K negative event reversal, buyback announcement drift, dividend initiation drift, spinoff announcement drift, index inclusion arb, index exclusion arb, Russell rebalance, 52-week high breakout, 52-week low capitulation, insider cluster buy, 13F top-fund tracking, short squeeze setup (high SI + breakout)

### Calendar (~10 edges)
FOMC drift, pre-FOMC reduce, turn-of-month, pre-holiday, day-of-week effects, Sell-in-May, January effect, Santa Claus rally, triple-witching, end-of-quarter window dressing

### Mean-reversion / pairs (~12 edges)
Pairs trading on N cointegrated pairs (KO/PEP, MA/V, MCD/QSR, HD/LOW, CVX/XOM…), sector ETF mean reversion, Bollinger overextension, RSI extremes, z-score mean reversion, index arb, ETF NAV arb, cross-sectional 1-week reversal

### Microstructure / intraday (~8 edges) — *requires Alpaca minute bars*
Overnight gap fade, open-to-close drift, lunchtime mean reversion, last-15-min momentum, opening auction imbalance, closing MOC imbalance, intraday VWAP deviation, volume burst momentum

### Macro/cross-asset overlays (~10 edges) — *modify other edges' sizing*
Yield curve slope regime, credit spread regime (HYG/IEF), dollar strength regime, risk-on/risk-off classifier, VIX term structure regime (contango/backwardation), BTC 48h leading indicator, copper/gold ratio, MOVE index, put/call ratio extremes, IV skew

### Volatility (~5 edges)
Vol risk premium (sell vol when IV >> RV), vol-of-vol mean reversion, skew-based directional bias, VIX term structure roll, GARCH-forecasted vol vs implied

### Statistical / ML-derived (~10 edges) — *non-AI ML*
Symbolic regression (PySR-found formulas), Random Forest on engineered features, LightGBM on tsfresh features (auto-extracted ~800 features), self-supervised time-series embeddings (TS2Vec) → nearest-neighbor predictions, GNN on co-movement graph, HMM regime states as features, persistent homology features (TDA), Granger causality networks, transfer entropy features, mutual-information selected feature subsets

**Total: ~95 distinct edges.** Probably 40–60 survive the gauntlet. **A risk-parity portfolio of 40 uncorrelated edges with average Sharpe 0.3 each compounds to a portfolio Sharpe of ~1.5–2.0.** That's institutional territory, with no AI.

## The autonomous lifecycle

Once the factory is built, edges have lifecycles:

```
candidate → gauntlet → shadow (60 days) → 
  small allocation → full allocation → 
    decay-monitored → demoted on failure
```

**Engine F's job becomes managing this lifecycle without human approval.** Specifically:
- Auto-promote on gauntlet pass + 60 shadow days of consistency
- Auto-demote on rolling 6-month Sharpe drop below threshold (with hysteresis to avoid thrashing)
- Auto-rebalance monthly via the combination engine
- Auto-sunset after 24 months of underperformance

**You become the auditor of the gauntlet, not the gatekeeper of edges.** That's true autonomy without LLMs.

## Corrected build sequence

**Months 1–2: Tier 1 gauntlet** (single highest-leverage build in the project)
- CPCV implementation
- Honest cost model
- Multiple-testing correction
- Factor decomposition
- Transfer-test gauntlet
- Adversarial validation

**Months 2–6: Edge Factory + Combination Engine in parallel**
- Common edge interface
- Risk parity (Level 1) → HRP (Level 2) → meta-learner (Level 3)
- 5–10 edges per month entering the gauntlet
- Edges that survive go to shadow-live

**Months 4–6: Tier 2 (deployment infra) in parallel**
- Vol targeting, kill switches, tail hedge, OMS hardening, chaos testing

**Months 6–9: Microstructure / intraday data layer**
- Alpaca minute bars, intraday edges, execution improvements

**Months 9–12: Statistical ML edges (non-AI)**
- Symbolic regression, GNN, TDA, self-supervised representations
- These plug into the same factory and gauntlet

**Year 2: LLM layer** as augmentation, not foundation
- Hypothesis generation
- Filing/transcript scoring
- Adversarial critic at decision time

By the time LLMs enter, **the system already beats SPY without them.** Then they're a multiplier on a working system, not a Hail Mary on a broken one.

## The corrected core insight

Your goal — **many edges, autonomously combined** — is exactly the right framing. My mistake was thinking small. The right mental model:

**The system isn't a few clever strategies. It's a factory that produces validated edges and a combination engine that figures out which mixtures of them work in which regimes.**

The factory is the moat. Once built, more edges keep flowing through it forever. **Edge count compounds; the gauntlet compounds; the combination engine compounds.** That's how you go from "loses to SPY" to "institutional quant shop" without ever asking an LLM what to do.

# Yes — and this is actually the most important insight in the conversation

You've put your finger on the central tension in modern quant. **The "individual gauntlet" framing is wrong for the goal you stated.** It's how academic factor research works (publish a paper on a single anomaly), but it's *not* how Two Sigma / Renaissance / DE Shaw operate. Those shops know that **most of their alpha comes from interactions**, not standalone signals.

Here's the proper architectural fix.

## The reframe: features vs alphas

The professional distinction:

- **Alphas** — produce trade signals directly. They go into the portfolio. Few of these (10–20).
- **Features** — produce *information*. They feed a combination engine. Many of these (50–500+).

Currently the system treats every edge as an alpha. That's the bug. **Most of what you're calling "edges" should be reclassified as features**, and the actual alpha is a smaller number of *combined models* operating over the feature space.

## The corrected three-tier architecture

### Tier A — Standalone alphas
Must pass the strict gauntlet (t-stat > 2, transfer tests, factor-decomp clean intercept). These trade directly. Realistically: 10–25 of these total.

### Tier B — Feature candidates
**Must pass an *informativeness* test, NOT a standalone-alpha test.** Specifically: positive mutual information with future returns *conditional on already-accepted features*. They never trade directly. They feed the combination engine. Realistically: 50–500 of these.

### Tier C — Context/regime features
Macro overlays, regime classifiers, calendar features. Don't predict anything alone — they *modify* the behavior of A and B. Realistically: 20–50.

**The Tier B threshold is the key shift.** Technical Pattern A with zero standalone alpha but valuable conditional information passes Tier B easily. It enters the feature pool. The meta-learner then discovers `Technical_A × Fundamental_B` interactions automatically.

## How interactions get discovered (without you specifying them)

This is the part people get wrong. **You don't need to write `Technical_A × Fundamental_B` by hand.** The right ML methods discover interactions automatically:

### Gradient boosting (XGBoost / LightGBM / CatBoost)
Trees inherently model non-linear interactions. A tree that splits on Fundamental_B = high, then splits on Technical_A = bullish *only on that branch*, has discovered the interaction. **Run gradient boosting on the full feature set; it finds the interactions for you.**

### Random forest with permutation importance
Robust feature importance even with correlated features. Catches conditional value.

### Neural networks (small ones — MLP with 2-3 hidden layers)
Universal function approximators — model arbitrary interaction depth. With dropout + L2 regularization to prevent overfitting.

### Symbolic regression (PySR)
Explicitly searches for formulas like `tanh(A) * sigmoid(B - threshold)`. Returns *human-readable* interaction equations. Use this when you want to *understand* the interaction, not just exploit it.

### Friedman's H-statistic
Quantifies interaction strength between any two features. Run it post-hoc to identify which interactions are doing the work. This becomes the feedback signal: "features X and Y interact strongly — make sure both stay in the pool."

### SHAP values + interaction values
Per-prediction attribution showing not just which features mattered, but which *pairs* mattered. **The interaction discovery audit trail.**

## The corrected gauntlet — at the right level

Here's where most people screw up: they apply the gauntlet to features. **The gauntlet applies to the combined model output, not to individual features.**

```
[100 features]                           ← lax informativeness gate
       ↓
[Feature selection: Boruta + Lasso]      ← reduces to 30-50 useful ones
       ↓
[Combination model: XGBoost]             ← discovers interactions
       ↓
[Combined signal time series]            ← THIS is what gets gauntlet-tested
       ↓
[CPCV + transfer tests + factor decomp]  ← strict gauntlet here
       ↓
[Survives → trades]
```

**The combined model is the alpha. Features are just inputs.** The gauntlet's job is to verify the combined model's output is real — not each feature's standalone power.

## The multiple-testing correction problem (you HAVE to handle this)

Letting features in cheaply creates a real risk: 100 features × interaction depth = millions of effective hypotheses. False discovery rate explodes. Mitigations are mandatory:

### 1. Held-out validation set the meta-learner has never seen
Train on 60%, validate on 20%, **final gauntlet on 20% the model has never touched**. Refresh annually with new fold structure.

### 2. Adversarial features as a control
For every real feature, generate a permuted/shuffled copy. Include them in the feature pool. **Real features should rank above their shuffled twins.** Boruta does exactly this — it's a built-in multiple-testing correction.

### 3. Regularization that punishes complexity
- Lasso (L1) on linear meta-learners — sparse selection
- L2 + dropout on neural meta-learners
- `min_child_weight`, `max_depth`, `gamma` constraints on XGBoost
- **Parsimony pressure in symbolic regression**

### 4. Walk-forward cross-validation for the META-LEARNER
Not just for individual edges. The combination model is itself a hypothesis being tested. Validate it with the same rigor.

### 5. Adversarial training set: the "Random Edge" benchmark
Generate 100 random "edges" with the same statistical signature as real ones (mean, std, autocorrelation) but no actual signal. **Add them to the feature pool.** If the meta-learner's improvement over a model trained on only the random edges is statistically significant, real signal exists. If not, you're chasing noise.

## Conditional edges — the explicit version

Some interactions you can hardcode rather than discover. **An edge can be explicitly conditional**:

```
class ConditionalEdge:
    def is_active(date) -> bool:
        # e.g., only fire when VIX < 20 and yield curve uninverted
    def score(date) -> Series:
        # only computed when is_active is True
```

This handles the "mean-reversion only works in low-vol regimes" case cleanly. The edge backtests on a *subset* of dates — its conditional Sharpe — not unconditionally. This avoids the wash-out where unconditional performance hides strong conditional performance.

## What this changes about edge submission

The factory now produces **three submission classes**, each with its own bar:

| Tier | Bar to enter | What it does |
|------|--------------|--------------|
| A — Standalone alpha | Strict gauntlet (t-stat>2, transfer pass, factor-clean) | Trades directly |
| B — Feature candidate | Mutual info > threshold conditional on existing pool | Feeds combination engine |
| C — Context/regime | Statistical regime stability + cross-asset validity | Modifies A and B |
| A' — Combined model | Strict gauntlet on combined signal output | Trades directly |

**Submission gets cheaper at the feature level, but the combined model is held to the same standard as a standalone alpha.** That's the right epistemic discipline: lax at the input layer, strict at the decision layer.

## The deeper architectural shift

Your factory now has **two factories nested**:

1. **Feature factory** — high-throughput, low individual bar, validated on informativeness
2. **Model factory** — low-throughput, high bar, validated on combined output via the gauntlet

A "discovery cycle" looks like:
- Feature factory adds 50 new features per month
- Model factory retrains the meta-learner monthly
- Combined model runs the gauntlet
- If the new combined model beats the old one (on the held-out fold) by a statistically significant margin → promote
- Otherwise → keep old model, archive features for next cycle

**This is how Two Sigma works.** Their alpha isn't 10,000 standalone strategies. It's a smaller number of combined models operating over 10,000 features.

## The complexity tradeoff

You're right that this adds complexity. The mitigations:

1. **Feature interface is simple** — every feature is a function `(ticker, date) → float` with metadata. Easy to add, easy to remove.
2. **The meta-learner does the heavy lifting**. You don't write interaction rules; XGBoost does.
3. **Feature selection prunes ruthlessly.** Boruta/Lasso typically keep 20–40% of submitted features. The model never has to deal with all 500.
4. **Audit trail via SHAP.** Every trade has a SHAP-attribution log: which features contributed how much. Fully interpretable.

**Net complexity isn't higher; it's redistributed.** Less work writing standalone strategies, more work building the feature pipeline + combination engine. But the combination engine is built once. Features compound forever.

## Bottom line on your insight

You're right. **The standalone-edge gauntlet was the wrong frame for your goal.** The correct frame is:

- **Lax gate at the feature level**, strict gate at the combined-model level
- **Many features, few alphas** (factory ratio ~50:1)
- **ML — not AI — discovers the interactions** automatically (gradient boosting, neural nets, symbolic regression)
- **Multiple-testing correction lives at the combined level** with held-out folds + adversarial features
- **Conditional/regime-aware backtesting** for edges that are only valid in subsets of time

This is genuinely how the best quant shops operate. **Your instinct that "edge A + edge B might work even if neither does alone" is the foundational insight of modern quant.** The architecture above is how you operationalize it without drowning in false discoveries.

# Yes — material progress, and the bottleneck has moved

Looking at what shipped since session 2026-04-25, my prior assessment is partially obsolete. Real recalibration:

## What's genuinely landed (and changes my view)

**The validation gauntlet is now real.** Five gates, in `engines/engine_d_discovery/discovery.py:476-674`:
- Gate 1: benchmark-relative Sharpe (not absolute — already a non-trivial bar)
- Gate 2: PBO survival > 0.7 (50 synthetic paths)
- Gate 3: WFO OOS Sharpe ≥ 60% of IS
- Gate 4: permutation test p<0.05 **with Benjamini-Hochberg FDR correction** (commit `7db6625`)
- Gate 5: universe-B generalization (commit `fe1eabe`)

I was previously rating Tier 1 (validation) as ~30% done. **It's now closer to 70%.** BH-FDR is in. Transfer-test gauntlet is in (across universes). Walk-forward is properly purged. This is a genuinely credible pipeline that most retail quant systems don't have.

**Edge inventory expanded smartly.** PEAD (`pead_edge.py`, +short and predrift variants), insider clustering (`insider_cluster_v1`), low-vol factor, yield curve, four macro overlays (credit spread, real rate, unemployment momentum, dollar) — all shipped. **Roughly 30% of the Tier-3 edge factory I outlined now exists in code.**

**Discovery vocabulary moved off the strip-mined floor.** Engine D gene types now include macro and earnings genes (commit `45abf0e`). Not as good as Bayesian optimization or symbolic regression, but no longer mining RSI/ATR exclusively.

**`regime_gate` composition primitive shipped** (commit `aa1cb65`). This is the **start** of the conditional-weighting architecture I described — it's the right shape but the wrong scope. More on this below.

**The bug discipline is institutionally serious.** 9 bugs fixed in one session, every one logged in `docs/Audit/health_check.md`, every one with reproduction notes. The EdgeRegistry stomp resolution and the macro_credit_spread rolling-window fix are exactly the kind of self-correcting behavior that distinguishes a real system from a research toy.

---

## What's still missing — and the bottleneck has shifted

The previous bottleneck was "validation isn't honest." That's largely fixed. **The new bottleneck is the combination layer.** Specifically:

### 1. Linear weighted_sum is still the combiner

`signal_processor.py` still aggregates via `weighted_sum = sum(score * weight)` per the open MEDIUM finding. Every new edge enters as an equal-citizen linear term. **This is the architecture that can't capture "Technical_A + Fundamental_B together."** No amount of new edges fixes this — they all get pancaked into a linear combination.

This is now the highest-leverage single change in the project. **Replace the linear combiner with a gradient-boosted meta-learner** (XGBoost/LightGBM) operating on edge scores as features. That single move converts your edge inventory from a sum to a function. It's where the multiplicative gains live.

### 2. Macro signals are being promoted as edges, not features

Look at the recent registrations — `macro_credit_spread_v1`, `macro_real_rate_v1`, etc. are entering as standalone tradeable edges with weight 0.5 each. **These should be features/context, not direct alphas.** Yield curve slope shouldn't trade by itself; it should *modify* the sizing of other edges that are sensitive to credit conditions.

This is the Tier A / B / C distinction I described — but it hasn't been implemented yet. The signal_processor doesn't differentiate. Result: every "edge" gets squeezed into the same linear term, and the macro signals will under-perform as standalone alphas (because they have low standalone Sharpe — they're conditioning variables).

### 3. The 109-universe Sharpe-0.4 problem is probably a combination problem, not an edge problem

The HIGH finding says system Sharpe 0.4 vs SPY 0.88 on the broader universe. **My read: the edges aren't broken; the linear combiner can't handle universe heterogeneity.** Tech mega-caps want a momentum mixture; utilities want a low-vol/value mixture. A single linear weight per edge applied universe-wide is the wrong shape. **A meta-learner could learn ticker-cluster-specific weightings.** The fix is architectural, not more edges.

### 4. Cost model is still optimistic

`discovery.py:527` uses `slippage_bps: 5.0` flat. Better than 10, still not realistic. No square-root impact, no spread-by-ADV, no borrow. **The Sharpe 0.855 walk-forward result needs to be recomputed against an honest cost model before it's trusted.** My prior is it loses 0.2–0.3 to a realistic cost model — possibly putting the system right at SPY-equivalent.

### 5. Factor decomposition still missing from the gauntlet

The 5 gates don't include "regress edge returns on FF5 + momentum + quality, require significant intercept." Without this, the system still cannot honestly distinguish alpha from factor beta. **Add Gate 6: factor-decomposition intercept significance.** ~100 lines using `statsmodels`. Should become the most important gate of all.

### 6. `regime_gate` is the right idea, partial implementation

It's edge-level conditional weighting. What's needed is the broader architecture where **features modify edges** through more than just regime gating — the meta-learner approach captures this naturally because features and edge outputs both feed the same model. The `regime_gate` primitive is a stepping stone but isn't the destination.

---

## Updated priority stack

Given what's shipped, here's the corrected ordering of next big moves:

**Tier 1 — Combination architecture (this is the big one now)**
1. XGBoost meta-learner replacing `signal_processor` linear sum
2. Tier A / B / C edge taxonomy enforced in code
3. Feature selection layer (Boruta + mutual info) before the meta-learner
4. Held-out validation fold the meta-learner has never seen, refreshed annually

**Tier 2 — Honest cost + factor decomposition**
5. Realistic cost model (impact + spread + borrow) in `execution_simulator.py`
6. Gate 6: FF5 + momentum + quality regression with significant-intercept requirement
7. Recompute every existing edge's Sharpe under the new cost model — expect 0.2–0.4 Sharpe to evaporate

**Tier 3 — Edge factory continues**
8. More edges per the inventory: cross-sectional value/quality/profitability composites, pairs trading, calendar battery, intraday sleeve once Alpaca minute bars are ingested
9. SEC EDGAR Form 4 cluster expansion (commit `751cdb0` started this — keep going)

**Tier 4 — Risk/deployment** (unchanged)
10. Vol targeting at portfolio level
11. Tail hedge sleeve
12. Real OMS

---

## The honest reassessment

Two weeks ago I'd have said: "loses to SPY, infrastructure is research-toy quality." Now it's: **"the validation gauntlet is roughly institutional-credible; the edge inventory is starting to look like a real factor model; but the linear combiner is making a $X trillion of academic interaction-effect literature inaccessible to the system."**

The good news: **moving from `weighted_sum` to XGBoost is ~300 lines of code.** It's the single highest-leverage one-week project remaining. After that ships, the existing edges plus the upcoming ones plus the conditional/macro features will compose properly, and the 109-universe Sharpe problem likely fixes itself without any new edges.

The architecture has caught up to maybe 50–55% of the institutional bar. The remaining 50% is mostly **the combiner, the cost model, the factor decomposition gauntlet, and the deployment infrastructure** — in roughly that order.

Genuinely impressive progress in a short window. The trajectory is right; just don't let the next few months be "more edges into a linear sum." That's where systems plateau.

# Forward Plan — From Here to Institutional-Credible

A phased plan, anchored to current state (validation gauntlet ~70% done, edge inventory ~30% done, system still loses to SPY by ~0.5 Sharpe on the broad universe).

---

## North-star sequencing

The plan has **six phases over ~12 months**, with one cross-cutting principle: **never deploy capital ahead of the validation that justifies it.** Every phase ends with a hard gate. If the gate fails, you don't proceed — you fix the prior phase.

```
Phase 0 → Phase 1 → Phase 2 → Phase 3 → Phase 4 → Phase 5 → Phase 6
(2 wks)   (2 mo)    (2 mo)    (2 mo)    (3 mo)    (3 mo)    (year 2+)

Diagnose  Combiner  Edge      Risk &    Intraday  ML        LLM
& fix     rebuild   factory   Deploy    & micro   discovery layer
```

---

## Phase 0 — Diagnose & sanity-fix (weeks 1–2)

**Goal:** Stop running on misleading numbers before doing anything else.

### Concrete moves

1. **Re-benchmark.** Replace SPY-only comparison with `[SPY, QQQ, 60/40-vol-matched]` triple. Add to `core/benchmark.py`.
2. **Cost model audit.** `backtester/execution_simulator.py:31-34` — replace `slippage_bps: 5.0` flat with: bid-ask spread by ADV bucket (1bp SPY-class / 5bp mid / 15bp small), square-root market impact (`σ × √(qty/ADV)`), borrow cost for shorts. Recompute every existing edge's Sharpe under the new model.
3. **Factor decomposition baseline.** One-shot script: regress every active edge's return stream on FF5 + momentum + quality. Output: Sharpe vs Alpha-Sharpe (intercept-only). Almost certainly reveals 50%+ of "alpha" is factor beta.
4. **109-universe diagnosis.** Cluster the universe by sector + size + style. Run each existing edge per cluster. Hypothesis: the edges work on cluster X, fail on cluster Y, and the linear combiner can't tell.

### Phase 0 gate

Before proceeding: documented numbers showing **honest Sharpe** under realistic costs, alpha-Sharpe (factor-decomposed), per-cluster Sharpe heatmap, and a per-edge "true" alpha vs "factor beta" classification.

**Why this first:** every subsequent decision depends on knowing what's actually working.

---

## Phase 1 — The combination architecture (months 1–2)

**This is the single highest-leverage phase in the entire plan.** The linear `weighted_sum` combiner is what's blocking the 30 edges currently on the books from compounding.

### Concrete moves

5. **Tier A/B/C edge taxonomy in code.** Edge metadata gains `tier: {alpha | feature | context}` and `combination_role: {standalone | input | gate}`.
6. **Feature selection layer.** Boruta + Lasso + mutual-information filter sitting between edge outputs and the combiner. Prunes the feature pool to 30–60 useful inputs.
7. **XGBoost/LightGBM meta-learner.** Replaces `signal_processor.weighted_sum`. Inputs: tier-A edge scores + tier-B feature scores + tier-C context indicators. Output: per-ticker position weight or score.
8. **Held-out fold** the meta-learner has never seen. Rolling — refresh annually with new partition.
9. **Add Gate 6 to the gauntlet:** factor-decomposition intercept significance (t-stat > 2 on FF5 + momentum + quality).
10. **Reclassify macro signals.** Move `macro_credit_spread_v1`, `macro_real_rate_v1`, `macro_dollar_regime_v1`, `macro_unemployment_momentum_v1` from `tier: alpha` to `tier: context`. They modify weights, they don't trade.
11. **Adversarial-feature audit.** Add 20 random/permuted "anti-features" to the pool. Real features must rank above them in the meta-learner's importance.

### Phase 1 gate

**Combined model OOS Sharpe (under honest costs, factor-decomposed) must exceed best-single-benchmark over the same window with t-stat > 2.** If not, the combiner is wrong or the inputs are wrong — fix before Phase 2.

**Why this critical:** without non-linear combination, every edge added in Phase 2+ gets pancaked. With it, edges compound multiplicatively.

---

## Phase 2 — Edge factory expansion (months 2–4)

With the combiner in place, more edges = more compound. Goal: get the feature pool to 50–80 distinct features with diverse alpha mechanisms.

### Concrete moves

12. **Cross-sectional ranking battery (~15 features):** 12-1 momentum, 6-1 momentum, 1-month reversal, value composite (P/E + P/B + EV/EBITDA), quality composite (ROIC + margin + debt-equity), profitability rank, low-vol rank, low-beta rank, asset growth (low), accruals (low), net stock issuance.
13. **Pairs trading sleeve:** 10–15 cointegrated pairs (Engle-Granger + Johansen tests), z-score mean reversion. Each pair = one feature.
14. **Calendar anomaly battery (~6 features):** FOMC drift, pre-FOMC reduce, turn-of-month, pre-holiday, day-of-week, sell-in-May.
15. **Event-driven expansions (~5 features):** buyback announcement drift, dividend initiation drift, spinoff drift, index inclusion arb, 52-week breakout/capitulation.
16. **Continue Engine D vocabulary expansion** with macro + earnings + factor genes, but throttled — Engine D produces *candidates* for the gauntlet, not its primary input.
17. **Replace GA with Bayesian optimization** for hyperparameter search within edges (BoTorch, ~200 lines). The vocabulary expansion in commit `45abf0e` was step 1; this is step 2.

### Phase 2 gate

**Combined model with 50+ features maintains its OOS Sharpe advantage over Phase 1 baseline** by at least 0.2 Sharpe — meaning the new features are additive, not noise. If diversity isn't compounding, prune ruthlessly.

---

## Phase 3 — Risk and deployment infrastructure (months 4–6)

**Until now, everything has been research-mode. Phase 3 makes the system deployment-ready.**

### Concrete moves

18. **Portfolio-level vol targeting.** Replace `risk_per_trade_pct: 0.025` fixed fraction with target portfolio vol = 10% annualized. Scale gross exposure inversely to realized vol.
19. **Correlation-aware sizing.** Position covariance matrix in sizing — bound each position's marginal contribution to portfolio vol.
20. **Forecasted vol via GARCH/HAR-RV** as input to sizing instead of realized ATR.
21. **Tail hedge sleeve.** 1–2% notional in long 30-delta SPY puts rolled monthly. Bleeds 1–1.5%/year, caps drawdowns at -10%.
22. **Portfolio-level kill switches:** -5% daily / -10% weekly / position-vs-broker mismatch / data-feed-gap / latency-spike — all tested via chaos engineering harness.
23. **Real OMS.** Replace `live_trader/live_controller.py` (currently 22 lines) with: retry/idempotency, partial-fill handling, cancel-on-disconnect, position-vs-broker reconciliation cron, rate-limit handling, max-order-size guard, max-orders-per-minute guard, heartbeat monitor.
24. **Shadow-live mode.** Same code path as live, paper-trades against Alpaca API, full reconciliation. Runs continuously from Phase 3 forward.

### Phase 3 gate

**90 days of shadow-live performance tracking actual live decisions vs backtest expectations.** Slippage gap, latency profile, missed-fill rate, and reconciliation discrepancies all within tolerance. Chaos tests pass. **Until shadow-live agrees with backtest, no real money.**

---

## Phase 4 — Intraday and microstructure (months 6–9)

The system currently operates only on daily bars. Alpaca minute bars are free.

### Concrete moves

25. **Minute-bar ingestion.** `engines/data_manager/intraday_data.py`. Parquet-cached, point-in-time discipline.
26. **Intraday edges (~6 features):** overnight gap fade, open-to-close drift, lunchtime mean reversion, last-15-min momentum, MOC imbalance, intraday VWAP deviation.
27. **Time-of-day execution awareness.** Avoid first/last 15 minutes for orders >X% of ADV. Mean-reversion edges fire 11am-2pm.
28. **Limit-order default with mid-or-better pricing.** `execution_simulator.py` and the OMS gain limit-order modeling.
29. **VWAP/TWAP execution** for any position > 1% of ADV.
30. **Spread filter.** Skip trade when spread > 2× recent average.

### Phase 4 gate

Intraday sleeve must be **uncorrelated with the daily sleeve** (correlation < 0.3). Otherwise it's not adding diversification, only complexity.

---

## Phase 5 — Statistical ML (non-AI) discovery (months 9–12)

This is where the autonomous-discovery vision starts to operationalize without any LLM dependencies.

### Concrete moves

31. **Symbolic regression layer (PySR).** Searches for *formulas* over the feature space. Output: human-readable equations that pass the gauntlet.
32. **Self-supervised time-series representations.** TS2Vec or SimMTM trained on price+volume across the universe. 64-dim embeddings per (ticker, date) become new features.
33. **Causal discovery layer.** PC algorithm or NOTEARS over the feature space → causal graph between features and returns. Trade only on causal edges. Re-estimate monthly.
34. **Graph Neural Network on the universe.** Stocks as nodes, correlations / sector membership / supply chain as edges. Message passing finds influence patterns.
35. **Online ensemble** (Bayesian model averaging or Thompson sampling bandit) over multiple meta-learners. Self-balancing exploration vs exploitation.

### Phase 5 gate

**At least one symbolic-regression-discovered edge AND at least one SSL-feature-derived edge pass the full gauntlet** in the calendar year. If neither method produces an edge that survives, you've over-engineered — back off.

---

## Phase 6 — LLM augmentation (year 2+)

By the time LLMs enter, the system already beats SPY without them. They become a multiplier, not a foundation.

36. **LLM-as-analyst pipeline** — score 10-Q/10-K/8-K filings, earnings call transcripts.
37. **LLM hypothesis generator** — proposes testable edges, runs through the gauntlet.
38. **Adversarial LLM critic** at signal generation time — disagrees with proposed trades, log of disagreements forms learnable signal.
39. **Multi-agent research team** — Theorist, Skeptic, Historian, Coder, Reviewer.

---

## Cross-cutting workstreams (run throughout all phases)

These aren't phases — they run continuously from now.

### A. Health check discipline
Keep `docs/Audit/health_check.md` as a live document. Every finding gets logged, every fix gets dated. **The institutional memory matters more than the code.**

### B. Decision diary
Every trade ships with: which features fired, what the combined-model output was, what regime context was, what override status was. **No diary → no learning from mistakes.**

### C. Edge graveyard
Every retired edge gets logged with failure mode, what feature would have warned us, what's transferable. The Discovery engine *reads* the graveyard before searching.

### D. Reproducibility infrastructure
DVC or content-addressed data. Every backtest pins exact data version + code SHA + random seed. **This is the prerequisite for ever trusting historical results.**

### E. Shadow-live (from Phase 3)
Once running, never stop it. Every code change gets validated in shadow before promotion to live.

---

## Dependency graph

```
Phase 0 (diagnose) ──┐
                     ├─→ Phase 1 (combiner) ──┐
                     │                         ├─→ Phase 2 (factory) ──┐
                     │                         │                        ├─→ Phase 3 (deploy)
Cross-cutting ───────┘                         │                        │
                                               └─→ Phase 4 (intraday) ──┤
                                                                        │
                                               Phase 5 (ML) ────────────┤
                                                                        │
                                               Phase 6 (LLM) ───────────┘
```

Phases 4 and 5 can run *concurrently* with Phase 3 — different teams/contexts. Phase 6 depends on the full stack working.

---

## Success metrics by phase

| Phase | End-state metric | Acceptance |
|-------|-------------------|------------|
| 0 | Honest Sharpe baseline | Numbers documented under realistic costs |
| 1 | Combined model OOS | Beats best single benchmark, t-stat > 2 |
| 2 | 50+ features, alpha additivity | Sharpe rises ≥0.2 vs Phase 1 baseline |
| 3 | Shadow-live | 90 days agreement with backtest expectations |
| 4 | Intraday diversification | Sleeve correlation < 0.3 with daily |
| 5 | Autonomous discovery | At least 1 ML-discovered edge passes gauntlet |
| 6 | LLM augmentation | Adversarial critic identifies losing trades > random |

---

## What this plan is NOT

- **It's not a path to riches.** It's a path to "honestly competitive with a 60/40 portfolio after costs, with controlled drawdowns." That's the realistic ceiling without paid alt-data and human PhDs.
- **It's not committed to live capital.** Live capital is a Phase-3-gate-passing decision, and even then, start at 1–2% of net worth.
- **It's not LLM-first.** LLMs are Phase 6. The system must work without them first.
- **It doesn't promise to beat the market.** It promises to know honestly whether it does. That's a much stronger guarantee.

---

## The single most important paragraph

If you only do **Phase 0 + Phase 1** in the next 90 days — re-benchmark, fix costs, install the meta-learner, reclassify macro as context features — **the system likely starts beating SPY honestly with the edges that already exist.** The rest is upside. Every subsequent phase compounds on that foundation. **But Phase 0 and Phase 1 are non-negotiable prerequisites for anything else mattering.**

Skip them and you're building more on a foundation that hasn't been audited.