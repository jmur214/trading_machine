# Forward Plan — 2026-05-02 (post-reviewer synthesis)

> **Live plan.** Supersedes `forward_plan_2026_05_01.md` after the
> two outside-reviewer docs landed
> (`docs/Progress_Summaries/Other-dev-opinion/05-1-26_1-percent.md`
> + `05-1-26_a-and-i_full.mf`). Both converge on the same architectural
> picture and identify gaps the prior plans had underweighted.
>
> **HONEST RE-ACCOUNTING — 2026-05-02 evening:**
>
> The director (this assistant) overstated workstream completion in
> the round-5 synthesis. User correctly called out: claiming "WS A
> ~90% shipped, WS D shipped, WS B in flight as if completing in one
> round" conflated *first slice shipped* with *workstream complete*.
> The 1-percent doc lists 4-7 named deliverables per workstream; we
> haven't met all of them on any workstream. Honest re-accounting
> below; future sessions should track per-deliverable, not vibes.
>
> | WS | Honest % | What's shipped | What's missing |
> |---|---|---|---|
> | A — Foundation | ~65% | Gauntlet fix ✓, cost completeness ✓ | ADV floor sweep under new gauntlet ⏳, integrated 2025 OOS rerun ⏳, health_check finding "geometry mismatch" still listed open ⏳ |
> | B — Engine C rebuild | ~25-30% (post-Path-A) | HRP slice 1 (failed), Path A slice 2 in flight (HRP composition + turnover penalty + tax-aware rebalancing) | mean-variance with shrinkage ❌, capital efficiency layer ❌, multi-asset proper ❌ |
> | C — Engine E rebuild | ~25-30% | HMM 3-state classifier shipped, default off | multi-resolution regime detection ❌, transition warning detector ❌, cross-asset confirmation ❌, regime-conditional sleeve de-gross ❌ |
> | D — Feature Foundry | ~60% | DataSource ABC ✓, @feature decorator ✓, ablation runner function ✓, twin generator ✓, dashboard tab ✓, model card schema ✓, CFTC COT proof-of-architecture ✓ | auto-ablation cron scheduler ❌, adversarial filter as runtime/CI gate ❌, 90-day archive enforcement ❌, integration with main backtest pipeline ❌ |
> | E — Edge factory expansion | 0% | (nothing) | All ~50 features (cross-sectional, event-driven, calendar, pairs, auto-engineered) ❌ |
> | F — External data sources | ~5% | CFTC COT seed ✓ | All other ~11 sources ❌; real fundamentals data layer decision ❌ (BLOCKS Path C compounder enable) |
> | G — Statistical ML upgrades | 0% | (nothing) | Bayesian opt, symbolic regression, SSL embeddings, causal, GNN ❌ |
> | H — Moonshot Sleeve | ~5% | Path C sleeve abstraction can host it ✓ | All Moonshot edges, asymmetric sizing, sleeve config ❌ |
> | I — Deployment infrastructure | 0% | (nothing) | Real OMS, vol-targeting, tail hedge, kill switches, shadow-live, chaos engineering ❌ |
> | J — Cross-cutting | ~30% | Capital allocation dashboard ✓, determinism harness ✓, ablation runner function ✓ | Decision diary ❌, DVC versioning ❌, edge graveyard structured tagging ❌, info-leakage detector ❌, data quality monitoring (Great Expectations) ❌, CI for backtests ❌, engine versioning ❌, synthetic data harness ❌ |
>
> **Honest cumulative: ~20-25% of the doc's full plan.** The doc estimated 12-18 months for 2-3 devs. We're a few intense agent-weeks in. Roughly on pace, **NOT ahead**. Prior synthesis implied ahead; that was wrong.
>
> **Discipline correction going forward:** when reporting workstream
> status, list the doc's named deliverables and mark each ✓/⚠️/❌
> explicitly. "X% complete" should mean "X% of named deliverables
> shipped with their acceptance criteria met," not "vibes."
>
> **Kill thesis status:** nominally triggered by the post-tax -0.577
> reading (cost completeness shipped). Reinterpreted as deployment-
> context drag rather than alpha refutation. Path A engineering and
> Path B Roth deployment are both responses; combination is the plan.
> But this re-accounting also reveals: the kill thesis was tied to
> "post-Foundation" measurement, and Foundation is genuinely ~65%
> not ~90% — the integrated rerun that would actually be "post-
> Foundation" hasn't happened. So the -0.577 is post-cost-layer-only,
> not post-full-foundation. Doesn't change the directional finding
> (tax drag is real and large) but does mean the kill thesis trigger
> reading is on incomplete data.

## What the reviewer docs added that we hadn't fully internalized

### The biggest engine gaps are C and E, not D
We'd been treating Engine D (Discovery) as the load-bearing problem because the gauntlet had visible bugs. The reviewer's engine-by-engine gap analysis ranks **C > E > A > B > D > F** by expected impact of investment. **Engine C is the thinnest engine in the system.** What looks like portfolio-construction logic is mostly happening implicitly in `signal_processor.weighted_sum`. Real portfolio construction (HRP, mean-variance with shrinkage, turnover penalty, tax-aware rebalancing, capital efficiency, multi-asset) is missing. Engine E is similarly thin — threshold-based regime detection without confidence outputs, no multi-resolution, no transition prediction, and macro signals architecturally mis-classified as edges instead of regime inputs.

### Feature Foundry as critical infrastructure
The 1-percent doc's central rule: **build the infrastructure that makes adding features cheap before adding the features.** Without auto-ablation, adversarial twins, feature lineage, and a feature audit dashboard, even 3 new features create chaos by feature #15. With the infrastructure: marginal cost of feature N is constant, not N-growing.

### Goal C reframed as Track-3 parallel, not Phase-5 deferred
The reviewer explicitly: *"Don't let core's struggles delay it. A 20-something with 40-year horizon needs this sleeve more than the core's incremental refinements."* The Moonshot Sleeve is architecturally independent (different universe, different gauntlet, different objective function). It can run parallel to core foundation work, gated by its own criteria (skewness > 0.5, hit rate ≥ 5%, sleeve CAGR ≥ 15%).

### Five non-negotiable rules (codified)
1. **Deterministic measurement always.** Every Sharpe runs through harness.
2. **Adversarial validation by default.** Every feature ships with a permuted twin.
3. **One feature per PR.** Never batch.
4. **90-day archive rule.** Auto-pruning is mandatory.
5. **Geometry of measurement matches deployment.** No standalone tests for ensemble-deployed strategies.

## The 10 workstreams (1-percent doc structure)

| # | Workstream | Status | Effort (1 dev) | Blocks |
|---|---|---|---|---|
| A | Foundation completion | **THIS ROUND PRIORITY** | 4-6 weeks | All others |
| B | Engine C rebuild (HRP, turnover, tax) | THIS ROUND | 4-6 weeks | — |
| C | Engine E rebuild (HMM, multi-res, transitions) | THIS ROUND | 4-6 weeks | — |
| D | Feature Foundry infra | THIS ROUND | 6-8 weeks | E, F, G, H |
| E | Edge factory expansion (~50 features) | After D | 6+ weeks | — |
| F | External data sources (~12 free) | After D | parallel | — |
| G | Statistical ML upgrades | After D | 8-12 weeks | — |
| H | Moonshot Sleeve | After D | 8-12 weeks | — |
| I | Deployment infrastructure | Later | 8-12 weeks | — |
| J | Cross-cutting (ablation, leakage detection, etc.) | Continuous | ongoing | — |

## Phase gates (must pass to advance)

- **Foundation Gate:** 2025 OOS Sharpe ≥ 0.5 deterministic, all 5 gauntlet gates measure correctly, 3-run reproducibility verified
- **Architecture Gate:** Combined Sharpe ≥ Foundation + 0.2; Engine C real optimizer in production; macro signals reclassified as regime inputs
- **Factory Gate:** ≥50 active features, auto-pruning < 5/month, combined Sharpe ≥ 0.7
- **Discovery Gate:** ≥1 symbolic-regression edge in production; ≥1 SSL-derived edge in production; GA replacement complete
- **Deployment Gate:** All chaos tests pass; 90 days shadow-live with Sharpe gap < 0.2 vs backtest; sustained Sharpe ≥ 1.0 over 90 days
- **Moonshot Gate:** Backtest 2010-2024 ≥ 1 5x+ winner/year average; hit rate ≥ 5%; sleeve CAGR ≥ 15%

## Pre-committed kill thesis (no goalpost moving)

If post-Foundation 2025 OOS Sharpe < 0.4 net of all costs (incl. taxes + borrow), **stop and run structural review**. Don't proceed to other workstreams.

## This round's dispatch — 5 parallel agents

The four MUST-HAVE workstreams (A foundation, B Engine C, C Engine E, D Feature Foundry) plus one NICE-TO-HAVE (cost completeness within A) all have independent code surfaces. They can run in parallel under worktree isolation without conflict.

| Agent | Workstream | Code surface | Effort |
|---|---|---|---|
| 1 | A — consolidated gauntlet fix + ADV floor verify | `engines/engine_d_discovery/`, `orchestration/`, `wfo.py` | ~3-5 days |
| 2 | D — Feature Foundry skeleton + 1 DataSource | `core/feature_foundry/` (new), `cockpit/dashboard_v2/` | ~2-3 days |
| 3 | B — Engine C HRP slice | `engines/engine_c_portfolio/`, `engines/engine_a_alpha/signal_processor.py` (config-only) | ~2-3 days |
| 4 | C — Engine E HMM slice + macro reclass | `engines/engine_e_regime/`, `data/governor/edges.yml` (4 edges) | ~2-3 days |
| 5 | A — cost completeness layer | `backtester/`, `core/` | ~1-2 days |

After this round: re-run 2025 OOS under harness to test Foundation Gate. If pass → unlock Tracks 2/3/4/5. If fail → kill thesis kicks in, structural review.

## What's queued for the round AFTER this one

Conditional on Foundation Gate passing:

- **Track E batch 1:** ~10-15 cross-sectional ranking primitives (12-1 momentum, value composite, quality composite, etc.)
- **Track F batch 1:** ~3-5 free data sources via Foundry (CFTC COT, USPTO patents, Polymarket via warproxxx/poly_data, FDA approvals/PDUFA, USAspending)
- **Track H setup:** Moonshot Sleeve universe + objective function + sleeve-level allocation primitive
- **Track G setup:** Bayesian optimization replacing GA for hyperparameter search
- **Track I start:** Real OMS scaffolding + shadow-live mode

## Repo audit findings (from reviewer's review)

Three external repos worth real time investigation:
- `noterminusgit/statarb` — 20+ alpha strategies + portfolio optimization. Saturday-afternoon audit.
- `ScottfreeLLC/AlphaPy` — Python AutoML for trading; relevant to Foundry. May accelerate Track G.
- `warproxxx/poly_data` — Polymarket integration. Drop-in for Track F.

These are **investigation tasks, not dispatched tasks** for this round. The user can audit them at their own pace.

## Single-paragraph TL;DR

**5 agents in parallel this round: gauntlet architectural fix, Feature Foundry skeleton, Engine C HRP slice, Engine E HMM slice, cost completeness. After this round, re-run 2025 OOS under harness to test the Foundation Gate. If pass → unlock the rest of the 10-workstream plan in tiered parallel waves. If fail → pre-committed kill thesis kicks in, structural review. The reviewer's most emphatic point — "build infrastructure first, then features" — is captured by putting Foundry in this round; the engine-gap finding (C and E are biggest) is captured by putting both engines' first slices in this round. After Foundation, the path is parallel-track aggressive but discipline-gated. Real-money deployment no earlier than ~12 months out, probably mid-late Year 2.**
