# The Path to 1% — Engineering Plan

For your dev team. General philosophy + specific workstreams + acceptance criteria + dependencies.

---

# Part 1: The General Plan

## Mental model — what we're building

**A self-improving alpha factory with rigorous validation infrastructure.** Three loops running in concert:

1. **Discovery loop** — generates candidate edges from multiple methods (genetic, Bayesian, symbolic, causal, ML)
2. **Validation gauntlet** — every candidate runs through honest gates that match deployment geometry
3. **Allocation engine** — combines validated features non-linearly via meta-learner; the linear `weighted_sum` is dead

Around these three loops: **infrastructure that makes adding things cheap and removing dead weight automatic.**

## The five non-negotiable rules

1. **Deterministic measurement always.** Every Sharpe number runs through the harness. Drifted readings are not data.
2. **Adversarial validation by default.** Every feature ships with a permuted twin. Real features must outperform their twins.
3. **One feature per PR.** Never batch. Each gets its own review, tests, ablation result.
4. **90-day archive rule.** Features without positive ablation contribution for 90 days auto-archive. The system actively prunes itself.
5. **Geometry of measurement matches deployment.** The Q3 false-negative bug taught this. Standalone tests for ensemble-deployed strategies are forbidden.

## What "top 1% retail quant" means in technical terms

- **Deterministic OOS Sharpe ≥ 1.0** sustained over a rolling 12 months under realistic costs (slippage + impact + borrow + tax)
- **Edge inventory ≥ 50 active features**, auto-pruned monthly
- **Discovery loop generates ≥ 4 promotion-ready candidates per quarter** without human handcrafting
- **Combination engine is non-linear** (gradient-boosted meta-learner minimum)
- **Three-layer architecture rigorously enforced** (lifecycle / tier / allocation as separate concerns)
- **All five gauntlet gates measure correctly** (no geometry mismatch)
- **Tail-hedged portfolio** with documented drawdown floor at -10% to -15%
- **Moonshot sleeve operating in parallel** capturing asymmetric upside on a separate universe
- **Shadow-live reproducibility verified** — backtest matches paper-traded reality within ±0.2 Sharpe over 90 days

## Track structure (high-level)

Ten parallel workstreams. Foundation work blocks everything; everything else is parallel. **A 6-developer team can run all 10 concurrently after foundation completes.**

```
A. Foundation completion         (BLOCKING)
B. Engine C rebuild              ─┐
C. Engine E rebuild              ─┤
D. Feature Foundry infra         ─┤── Parallelizable
E. Edge factory expansion        ─┤
F. External data sources         ─┤
G. Statistical ML upgrades       ─┤
H. Moonshot Sleeve              ─┤
I. Deployment infrastructure     ─┤
J. Cross-cutting infrastructure  ─┘
```

---

# Part 2: The Specific Plan

Each workstream has scope, deliverables, acceptance criteria, dependencies, and rough effort.

---

## Workstream A — Foundation completion (BLOCKING)

**Goal:** unblock everything else by fixing what's measurably wrong now.
**Effort:** 1 dev, 4-6 weeks
**Dependencies:** none
**Blocks:** all other workstreams

### Deliverables

1. **Gauntlet geometry-mismatch fix** at top of `validate_candidate`. Single architectural change repairs all 5 gates simultaneously.
2. **ADV floor replication** — verify under deterministic harness whether UB Sharpe 0.225 → 0.916 result holds.
3. **Cost completeness layer** in `RealisticSlippageModel`:
   - Borrow rate by ticker (5-25 bps/day)
   - Short-term capital gains tax drag (configurable rate, default 30%)
   - Alpaca fee tier model
4. **2025 OOS rerun under harness** with all fixes applied.

### Acceptance criteria

- All 5 gauntlet gates pass identical-input identical-output across 3 deterministic runs
- Cost model produces statistically-different (>3σ) results from prior 5-bps-flat baseline
- 2025 OOS Sharpe deterministic, reproducible, documented with full attribution
- Health check finding "geometry mismatch across 5 gates" marked RESOLVED

### Kill thesis

If 2025 OOS Sharpe < 0.4 net of all costs after geometry fix + ADV floors: **stop. Run structural review.** Do not proceed to other workstreams.

---

## Workstream B — Engine C rebuild

**Goal:** real portfolio construction. Currently this engine is dramatically underbuilt; most of its job happens implicitly in `signal_processor.weighted_sum`.
**Effort:** 1 dev, 4-6 weeks
**Dependencies:** Workstream A (foundation)
**Parallel with:** C, D

### Deliverables

1. **Hierarchical Risk Parity (HRP) optimizer** as the primary allocation method (López de Prado).
2. **Optional mean-variance with shrinkage** (Ledoit-Wolf) as alternative.
3. **Turnover penalty** in the optimizer — reject rebalances where expected alpha < transaction cost.
4. **Tax-aware rebalancing** — wash sale rule enforcement, prefer long-term over short-term gains realization.
5. **Capital efficiency layer** — gross exposure scales with meta-learner confidence (1.0× to 1.3× range).
6. **Multi-asset class scaffolding** — engine accepts non-equity inputs (bonds, commodities) for future expansion.

### Acceptance criteria

- HRP optimizer integrated, replaces `weighted_sum` as default
- Backtest shows ≥0.1 Sharpe improvement from HRP vs linear sum on identical signals
- Turnover penalty reduces fill count by ≥15% with ≤5% Sharpe degradation
- Wash sale rule: zero violations in backtest
- Multi-asset interface documented even if only equities active

---

## Workstream C — Engine E rebuild

**Goal:** confidence-aware probabilistic regime detection feeding all other engines.
**Effort:** 1 dev, 4-6 weeks
**Dependencies:** Workstream A
**Parallel with:** B, D

### Deliverables

1. **Hidden Markov Model (HMM) regime classifier** — 3-state baseline (benign / stressed / crisis), expandable to 4-5 states.
2. **Probabilistic outputs** — `{regime: prob}` not binary. K-state validated via likelihood-ratio test.
3. **Multi-resolution regime detection** — daily, weekly, monthly classifications running in parallel.
4. **Cross-asset confirmation** — equity regime confirmed against rates regime (yield curve slope), credit regime (HYG/IEF), FX regime (DXY).
5. **Transition-warning detector** — fires alerts when regime is *changing*, not just when it has changed.
6. **Reclassify macro signals** — `macro_credit_spread_v1`, `macro_real_rate_v1`, `macro_dollar_regime_v1`, `macro_unemployment_momentum_v1` move from `tier=alpha` to regime-input features.

### Acceptance criteria

- HMM 3-state classifier trained, validated via OOS log-likelihood
- Engine B sizing API consumes regime-confidence (not just regime label)
- Multi-resolution outputs available
- Macro signals removed from active edge set, available as regime inputs
- Transition warnings backtested against historical regime changes (March 2020, October 2022) — must fire ≥48 hours ahead in ≥80% of cases

---

## Workstream D — Feature Foundry infrastructure

**Goal:** make adding features cheap, validating them automatic.
**Effort:** 1-2 devs, 6-8 weeks
**Dependencies:** Workstream A
**Parallel with:** B, C
**Blocks:** E, F, G, H

### Deliverables

1. **Generic ingestion plugin architecture** — `DataSource` base class with `fetch`, `schema_check`, `freshness_check`, point-in-time validation.
2. **Feature interface** — every feature is a function `(ticker, date) → float | None` with metadata decorator.
3. **Auto-ablation cron** — monthly job that drops each feature, reruns the deterministic harness, measures portfolio impact, archives non-contributors.
4. **Adversarial twin generator** — for every real feature, auto-creates permuted/shuffled version with same statistical signature. Both go into meta-learner.
5. **Feature audit dashboard** — single view in `cockpit/dashboard_v2`: feature name, importance, ablation contribution, last validated date, age, schema-drift status, twin comparison. Color-coded.
6. **Feature lineage YAML / model cards** — git-tracked metadata per feature: source URL, license, point-in-time discipline, expected behavior, known failure modes.
7. **Adversarial filter** — feature must outperform its twin in meta-learner importance to remain active.

### Acceptance criteria

- New feature can be added to Foundry with <50 lines of code (plugin + decorator)
- Auto-ablation runs monthly without manual intervention
- Adversarial twins automatically generated for every real feature
- Dashboard shows current state of all features at-a-glance
- 90-day archive rule enforced automatically

---

## Workstream E — Edge factory expansion

**Goal:** populate Foundry with diverse alpha sources.
**Effort:** 1-2 devs, ongoing 6+ weeks
**Dependencies:** Workstream D (Foundry must be live)
**Parallel with:** F, G, H, I

### Deliverables (target ~50 features)

**Cross-sectional ranking primitives (~15):**
- 12-1 momentum, 6-1 momentum, 1-month reversal
- Industry-relative momentum
- Volume-confirmed momentum
- Value composite (P/E + P/B + EV/EBITDA + EV/Sales)
- Quality composite (ROIC + margin + debt-equity + accruals)
- Profitability rank, asset growth (low), accruals (low), net stock issuance, low-vol, low-beta, size, sector momentum

**Event-driven (~10):**
- PEAD variants (already exist), earnings revision drift
- Spinoff drag (60-day short)
- Buyback announcement drift
- Russell rebalance front-running
- Dividend initiation drift
- M&A risk arb
- Index inclusion/exclusion arb
- 52-week breakout with volume confirmation
- Insider cluster (small-cap expansion of existing edge)

**Calendar anomaly battery (single ~200-line file, ~6 features):**
- FOMC drift, pre-FOMC reduce, turn-of-month, pre-holiday, day-of-week, sell-in-May

**Pairs / mean-reversion (~10):**
- 10-15 cointegrated pairs (Engle-Granger + Johansen tested)
- Bond/equity divergence reversal
- Closed-end fund discount mean reversion
- VIX term-structure trades
- Dispersion proxy

**Auto-engineered (via tsfresh):**
- ~800 features extracted automatically
- Most pruned by adversarial twin filter
- Survivors integrated as Tier-B features

### Acceptance criteria

- Each feature ships with model card + tests + adversarial twin
- Each feature passes 90-day adversarial filter to remain active
- Combined system Sharpe (under harness) increases with each batch of additions
- No feature ships without ablation contribution >0 in walk-forward

---

## Workstream F — External data sources

**Goal:** ingest underused free data into Foundry as Tier-B features.
**Effort:** 1 dev, parallel ongoing
**Dependencies:** Workstream D
**Parallel with:** E, G, H, I

### Deliverables (~12 sources)

1. **CFTC Commitments of Traders (COT)** — weekly, futures positioning by trader category
2. **USPTO patents + trademarks** — bulk data, patent grant velocity, trademark filings
3. **FDA approvals + PDUFA dates** — real-time, biotech/pharma binary events
4. **Polymarket / Kalshi prediction markets** — macro event probabilities (use `warproxxx/poly_data` repo as reference)
5. **OpenSky Network** — corporate jet tracking, M&A signal
6. **TreasuryDirect auction results** — bid-to-cover, indirect bidder %
7. **EIA petroleum/gas reports** — weekly, oil/gas event-driven
8. **USAspending.gov federal contracts** — government spending by ticker
9. **Wikipedia page views API** — attention spikes
10. **DNS / Certificate Transparency logs** — pre-launch corporate signals
11. **Container shipping rates** — Baltic Dry, Drewry indices
12. **Glassdoor + LinkedIn job posting velocity** — hiring proxy (legitimately scrapable)

### Acceptance criteria

- Each source: parquet-cached, point-in-time validated, schema-drift detected, freshness-monitored
- Each source feeds at least 1 Foundry feature
- Each feature passes adversarial twin filter
- Documentation: license, freshness expectations, known failure modes

---

## Workstream G — Statistical ML upgrades (no LLMs)

**Goal:** graduate Engine D from genetic algorithm to genuinely productive autonomous discovery.
**Effort:** 1 dev, 8-12 weeks
**Dependencies:** Workstream D
**Parallel with:** E, F, H, I

### Deliverables

1. **Bayesian optimization** replacing GA for hyperparameter search (BoTorch, ~200 lines).
2. **Symbolic regression** (PySR) — searches for human-readable formulas over feature space. Output: equations that pass the gauntlet.
3. **Self-supervised time-series representations** (TS2Vec or SimMTM) — 64-dim embeddings per (ticker, date), used as features.
4. **Causal discovery layer** — PC algorithm or NOTEARS over feature space → causal graph between features and returns. Trade only on causal edges.
5. **Graph Neural Network** — stocks as nodes, sector/correlation/supply-chain as edges. Message passing finds influence patterns.
6. **Online ensemble** (Bayesian model averaging) over multiple meta-learners.
7. **Migrate Engine D's primary candidate generation** off GA onto Bayesian optimization + symbolic regression.

### Acceptance criteria

- ≥1 symbolic regression-discovered edge passes gauntlet within 90 days of methodology going live
- ≥1 SSL-feature-derived edge passes gauntlet
- Replacement of GA shows zero degradation in candidate-pass rate
- Causal edges have higher post-promotion stability than correlational edges (measured over 6 months)

---

## Workstream H — Moonshot Sleeve

**Goal:** asymmetric upside capture via separate engine with different mandate.
**Effort:** 1 dev, 8-12 weeks
**Dependencies:** Workstream D, A
**Parallel with:** E, F, G, I

### Deliverables

1. **Universe definition module** — Russell 2000 + IPOs (last 5 years) + theme-tagged equities (AI, space, biotech, EV, semis). Refreshed quarterly.
2. **Edge set:**
   - Long-term momentum (12-month + 24-month)
   - 52-week breakout with volume confirmation
   - Earnings beat + raised guidance
   - Insider cluster buying (small-cap)
   - Short-interest squeeze setups
   - Sentiment velocity (free sources)
   - FDA approval drift
   - Federal contract win signal
3. **Asymmetric sizing engine** — many small bets, each capped at 1-2% of sleeve, uncapped upside, 50% trailing stop.
4. **Trailing stop infrastructure** — 50% from peak, configurable.
5. **Different gauntlet criteria** — skewness > 0.5, upside capture > 1.2× downside capture, hit rate ≤ 30% acceptable.
6. **Sleeve-level allocation:** 15-20% of total portfolio capital.
7. **Different objective function** — Sortino + skewness + upside capture (NOT Sharpe).

### Acceptance criteria

- Backtest 2010-2024 shows ≥1 5x+ winner per year on average
- Hit rate ≥5% (positions returning ≥2x)
- Sleeve CAGR ≥15% under realistic costs
- Sleeve drawdown profile separately stress-tested through 2008/2020/2022
- Sleeve volume sized to ≤1% of sleeve impact at expected ADV

---

## Workstream I — Deployment infrastructure

**Goal:** make the system deployment-ready when alpha is proven.
**Effort:** 1 dev, 8-12 weeks
**Dependencies:** Workstream A
**Parallel with:** B, C, D, E, F, G, H

### Deliverables

1. **Real OMS** replacing 22-line `live_trader/live_controller.py`:
   - Retry / idempotency
   - Partial-fill handling
   - Cancel-on-disconnect
   - Position-vs-broker reconciliation
   - Rate-limit handling
   - Max-order-size guard
   - Max-orders-per-minute guard
   - Heartbeat monitor
2. **Portfolio-level vol-targeting** — target 10% annualized vol, scale gross exposure inversely.
3. **Correlation-aware sizing** — covariance matrix in sizing.
4. **Forecasted vol via GARCH/HAR-RV** as sizing input (replaces realized ATR).
5. **Tail hedge sleeve** — long 30-delta SPY puts rolled monthly, sized to 1-2% notional.
6. **Portfolio-level kill switches** — -5% daily, -10% weekly, position mismatch, latency spike, data-feed gap.
7. **Chaos engineering harness** — simulated broker outages, doubled fills, dropped connections, stale data.
8. **Reconciliation cron** — every 5 minutes, broker truth vs internal state.
9. **Shadow-live mode** — same code path as live, paper-trades against Alpaca API, full reconciliation.

### Acceptance criteria

- All chaos tests pass: simulated failures don't propagate beyond OMS
- Reconciliation discrepancies < 0.5% sustained
- Kill switches activate within 1 second of trigger condition
- Shadow-live runs continuously from week 4 of workstream onward

---

## Workstream J — Cross-cutting infrastructure

**Goal:** observability + discipline mechanisms running forever.
**Effort:** 1 dev, ongoing
**Dependencies:** none
**Parallel with:** all others

### Deliverables

1. **Capital allocation diagnostic dashboard** (already built — evolve)
2. **Continuous shadow portfolios** — N parallel paper portfolios with different parameter sets, comparing actual to best-shadow weekly.
3. **Edge ablation studies, monthly, automated** — drop each edge, measure portfolio impact, flag negative-contribution edges.
4. **Decision diary** — every trade logged with: which features fired, model output, regime, override status, expected outcome distribution.
5. **Edge graveyard with structured failure-mode tagging** — failed candidates archived with WHY they failed in YAML.
6. **Information-leakage detector** — compare in-sample vs OOS slope per feature, auto-quarantine steep degradation.
7. **Data quality monitoring** (Great Expectations or similar) — auto-pause edges when source breaks.
8. **CI for backtests** — every commit triggers full backtest, results posted to dashboard, drift detected pre-merge.
9. **Engine-level versioning** — each engine carries semver, every trade tagged with engine versions used.
10. **Synthetic data testing harness** — fake market data with known properties, verify system detects them.

### Acceptance criteria

- Dashboard accessible at any time, updated daily
- Auto-ablation flags non-contributing edges within 48 hours of measurement
- Decision diary searchable by feature / regime / outcome
- Information leakage detector quarantines suspect features autonomously

---

## Phase gates (when do we advance)

### Foundation Gate (after A)
- 2025 OOS Sharpe ≥ 0.4 deterministic, net of all costs
- All 5 gauntlet gates measure correctly
- 3-run reproducibility verified

### Architecture Gate (after B + C)
- Combined system Sharpe (under harness) ≥ Foundation baseline + 0.2
- Macro signals removed from active edges, in regime inputs
- Engine C real optimizer in production

### Factory Gate (after D + E + F)
- ≥50 active features in Foundry
- Auto-ablation pruning < 5 features/month
- Combined Sharpe ≥ 0.7

### Discovery Gate (after G)
- ≥1 symbolic regression edge in production
- ≥1 SSL-derived edge in production
- GA replacement complete

### Deployment Gate (after I)
- All chaos tests pass
- Shadow-live for 90 days, Sharpe gap < 0.2 vs backtest
- Sustained Sharpe ≥ 1.0 over the 90 days

### Moonshot Gate (after H, separate from above)
- Backtest validation of asymmetric strategy passes
- Sleeve operates independently of core
- 15-20% allocation defined

---

## Effort summary

| Workstream | Devs | Weeks | Parallel-with |
|-----------|------|-------|---------------|
| A. Foundation | 1 | 4-6 | (blocks all) |
| B. Engine C | 1 | 4-6 | C, D |
| C. Engine E | 1 | 4-6 | B, D |
| D. Foundry | 1-2 | 6-8 | B, C |
| E. Edge factory | 1-2 | 6+ ongoing | F, G, H, I |
| F. Data sources | 1 | parallel ongoing | E, G, H, I |
| G. Statistical ML | 1 | 8-12 | E, F, H, I |
| H. Moonshot Sleeve | 1 | 8-12 | E, F, G, I |
| I. Deployment infra | 1 | 8-12 | B-H |
| J. Cross-cutting | 1 | ongoing | all |

**With 6 developers**, the entire plan completes in roughly 6-8 months calendar time. **With 2-3 developers**, 12-18 months. **With 1 developer**, 18-24+ months.

---

## What "done" looks like

When all workstreams ship and all gates pass:

- Sharpe ≥ 1.0 sustained 90 days deterministic, OOS, net of all costs
- 50+ active features in Foundry, auto-pruned
- Multiple discovery methods (Bayesian opt, symbolic regression, SSL, causal) producing candidates
- Real-time observability via dashboards
- Shadow-live verified
- Tail hedged, vol-targeted, regime-aware
- Moonshot Sleeve operating in parallel
- Cross-cutting discipline mechanisms (ablation, leakage detection, data quality) running autonomously

**That's the technical state of top 1% retail quant.** No AI, no LLMs (those are layered later as Phase 6 augmentation, not foundation).

---

## Single most important guidance for the team

**Build the infrastructure first, then the features.** The Feature Foundry + auto-ablation + adversarial twins is what makes adding 50 features tractable instead of overwhelming. Most teams skip the infrastructure investment and end up drowning in feature debt by feature #15. **Don't.** Build A, B, C, D first — those four workstreams are the foundation. Then E, F, G, H, I can run in parallel because the substrate makes it safe.

The other rule: **deterministic harness for every measurement, always.** The Sharpe 1.063 → 0.905 (drift) → 0.315 (OOS) → 0.984 (under harness) sequence taught the team this. **Don't unlearn it.**