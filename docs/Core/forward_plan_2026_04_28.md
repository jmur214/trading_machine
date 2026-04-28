# Forward Plan — 2026-04-28

Synthesis of `docs/Progress_Summaries/2026-04-28_audit-and-improvements_v2.md`
with the work shipped this session. Anchors all subsequent work to a single
phased sequence with hard gates between phases.

## Where we actually are

| Layer | Pre-2026-04-28 | After today |
|-------|----------------|-------------|
| Validation gauntlet | ~70% (5 gates spec'd, but Gates 3/5 silently disabled, regime context broken) | **~85%** — gates actually run, regime context flows, real Sharpe values produced |
| Edge inventory | ~30% (~10 edges, several inert) | ~30% — same count but `macro_credit_spread` no longer 0% fire-rate, hunters now structured to validate (still feature-availability-blocked) |
| Combination layer | Linear `weighted_sum` | **Unchanged** — this is now the bottleneck |
| Cost model | Flat 5 bps | **Unchanged** — Phase 0 priority |
| Factor decomposition | Not in gauntlet | **Unchanged** — Phase 1 (Gate 6) priority |
| Deployment infrastructure | Research-toy | **Unchanged** — Phase 3 |

**The bottleneck moved.** It used to be "validation isn't honest" and "discovery loop is broken." Both got addressed materially. The new bottleneck is exactly what v2 names: **the linear combiner can't capture cross-edge interactions, and the cost model can't tell the difference between alpha and slippage.**

## What v2 says, terse

> If you only do Phase 0 + Phase 1 in the next 90 days — re-benchmark, fix
> costs, install the meta-learner, reclassify macro as context features —
> the system likely starts beating SPY honestly with the edges that
> already exist. The rest is upside. Every subsequent phase compounds on
> that foundation. But Phase 0 and Phase 1 are non-negotiable
> prerequisites for anything else mattering.

I agree, with one amendment: today's discovery-loop bug-fix work is a Phase 0 prerequisite that wasn't in v2. v2 was written assuming the loop worked. We had to make it work first. **Now the v2 sequence applies.**

---

## Phase 0 — Honesty layer (next ~2 weeks)

Every Phase 0 item is a structural fix, not tuning. After this phase, every Sharpe
number we look at is comparable to a real-money outcome.

### 0.1 Honest cost model — `backtester/execution_simulator.py`
- [ ] Replace flat `slippage_bps: 5.0` with: bid-ask spread by ADV bucket, square-root market impact (`σ × √(qty/ADV)`), borrow cost for shorts.
- [ ] Tests + docstrings explaining the formulas and citations.
- [ ] Recompute baseline in-sample Sharpe with the new model — expect 0.2-0.3 to evaporate from prior 0.26.

### 0.2 Multi-benchmark — `core/benchmark.py`
- [ ] Replace SPY-only with `[SPY, QQQ, 60/40-vol-matched]` triple.
- [ ] All gates that compare against benchmark use the strongest of the three.
- [ ] Document why: SPY is a flattering benchmark for a long-bias system.

### 0.3 Factor decomposition baseline (one-shot diagnostic)
- [ ] Script: `scripts/factor_decomposition_baseline.py`. Pulls FF5 + momentum + quality from Ken French's data library (free).
- [ ] Regresses every active edge's return stream → outputs Sharpe vs alpha-Sharpe table.
- [ ] Output goes to `docs/Audit/factor_decomposition_baseline.md`.
- [ ] **This isn't yet Gate 6** — it's the diagnostic that proves Gate 6 is needed. Reveals which "alphas" are factor beta in disguise.

### 0.4 109-universe cluster diagnosis
- [ ] Cluster the 109-ticker universe by `[sector, size_bucket, style_bucket]`.
- [ ] Run each existing edge per cluster — output per-edge per-cluster Sharpe heatmap.
- [ ] Hypothesis: edges fire well on cluster X, fail on cluster Y; linear combiner pancakes. **This is the empirical motivation for the Phase 1 meta-learner.**

### Phase 0 gate
Documented numbers showing honest Sharpe under realistic costs, alpha-Sharpe (factor-decomposed), per-cluster Sharpe heatmap, and a per-edge "true alpha vs factor beta" classification. **Without these numbers, no Phase 1 measurement is interpretable.**

---

## Phase 1 — Combination architecture (next ~2 months)

The single highest-leverage piece of work in the entire project. The system has 30 edges that aggregate via `weighted_sum`. Replacing that aggregator with a meta-learner is what converts linear sum into multiplicative compound.

### 1.1 Edge taxonomy in code
- [ ] `EdgeSpec` gains `tier: {"alpha", "feature", "context"}` and `combination_role: {"standalone", "input", "gate"}`.
- [ ] Migration: classify existing edges per v2 doc:
  - **alpha**: rsi_bounce, atr_breakout, volume_anomaly, herding, gap_fill, panic, earnings_vol, pead_v1, pead_short, pead_predrift, insider_cluster, momentum_edge
  - **feature**: low_vol_factor (it's a ranking feature, not a direct alpha — currently miscategorized)
  - **context**: macro_yield_curve, macro_credit_spread, macro_real_rate, macro_dollar_regime, macro_unemployment_momentum (these are regime classifiers, not direct alphas)

### 1.2 Feature selection layer
- [ ] Boruta + Lasso + mutual-information filter between edge outputs and combiner.
- [ ] Prunes feature pool to 30-60 useful inputs.
- [ ] Adversarial features (20 random/permuted) included for control — real features must rank above their shuffled twins.

### 1.3 Meta-learner replacing `signal_processor.weighted_sum`
- [ ] XGBoost or LightGBM (start with XGBoost — better-known semantics, easier to interpret).
- [ ] Inputs: tier-A edge scores + tier-B feature scores + tier-C context indicators.
- [ ] Output: per-ticker score in [-1, 1].
- [ ] Held-out fold the meta-learner has never seen, refreshed annually.

### 1.4 Gate 6 in the gauntlet — factor-decomposition
- [ ] `engines/engine_d_discovery/discovery.py::validate_candidate` adds a sixth gate.
- [ ] Regress the candidate's return stream on FF5 + momentum + quality.
- [ ] Pass condition: intercept t-stat > 2 AND intercept > 2% annualized.
- [ ] Most important gate of all because it cuts factor-beta wearing alpha clothing.

### 1.5 Reclassify macro signals
- [ ] Edit `data/governor/edges.yml`: change `tier` from default to `context` for the 5 macro edges.
- [ ] `signal_processor` reads `tier`. Context edges don't enter the combiner directly — they modify the weights.

### Phase 1 gate
Combined model OOS Sharpe (under honest costs, factor-decomposed) must exceed best-single-benchmark over the same window with t-stat > 2. If not, the combiner is wrong or the inputs are wrong.

---

## Phase 2 — Edge factory expansion (months 2-4)

Per v2 §Phase 2. Cross-sectional ranking battery, pairs trading, calendar anomalies, event-driven expansions. **All entering as features (tier-B), not as direct alphas.** The combiner handles the rest.

## Phase 3 — Risk and deployment (months 4-6)

Per v2 §Phase 3. Vol targeting, correlation-aware sizing, tail hedge sleeve, kill switches with chaos engineering, real OMS replacing the 22-line stub, shadow-live mode. **Gate: 90 days of shadow-live performance tracking actual live decisions vs backtest expectations.**

## Phase 4 — Intraday & microstructure (months 6-9)

Alpaca minute bars, intraday edges, time-of-day execution awareness.

## Phase 5 — Statistical ML discovery (months 9-12)

Symbolic regression, self-supervised time-series embeddings, causal discovery, GNN on the universe graph.

## Phase 6 — LLM augmentation (year 2+)

Filing/transcript scoring, hypothesis generator, adversarial critic. **Only after the system already works without LLMs.**

---

## Cross-cutting workstreams

These run continuously starting now:
1. `docs/Audit/health_check.md` discipline — every finding logged, every fix dated.
2. Decision diary on every trade.
3. Edge graveyard documenting failure modes.
4. Reproducibility (DVC/content-addressed data + git SHA + seed pinning per backtest).
5. Shadow-live (from Phase 3 onward).

---

## What this plan replaces

This document supersedes the next-step ordering in `docs/Core/ROADMAP.md` from
2026-04-28 forward. The roadmap's Phase 2.10 is mostly complete; the next
phases there (sector rotation, mutual info, MAP-Elites, etc.) become **Phase 2
or later inputs to the edge factory**, not Phase 1 priorities. Until Phase 0
and Phase 1 ship, more edges into a linear sum just adds noise.

## Today's session 3 work in this frame

| Commit | Phase mapping |
|--------|--------------|
| dda474c, 8ee8289 (9 discovery bug fixes) | **Pre-Phase 0** prerequisite — discovery loop must function before anything else |
| 896b3df (`macro_credit_spread` rolling 5y) | **Phase 0.1 prep** — structural fix to one edge's input |
| 3c3b8d3 (`--reset-governor`) | **Phase 0** measurement infra — clean in-sample baseline |
| 2793860 (rsi_mean_reversion cleanup) | Hygiene — closes a 6-month-old dead-import bug |
| 4fb0832, 1fe72c9 (health_check updates) | **Cross-cutting workstream A** |

---

## Single-paragraph TL;DR

**Phase 0 + Phase 1 in the next ~12 weeks. After that the system either honestly beats SPY with the edges that already exist, or we know honestly that it doesn't and what to do about it. Skip Phase 0 and we're tuning a system whose reported numbers we can't trust.**
