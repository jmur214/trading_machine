# Forward Plan — live (last substantive update 2026-05-09 evening)

> **2026-05-09 EVENING — KILL THESIS TRIGGERED. Structural review = engine completion.**
>
> Pre-committed kill thesis (this file, line ~228 below):
>
> > "If post-Foundation 2025 OOS Sharpe < 0.4 net of all costs (incl. taxes
> > + borrow), stop and run structural review."
>
> The data:
>
> | Measure | Value | Status vs 0.4 |
> |---|---:|---|
> | 2025 universe-aware Sharpe (pre-tax) | 0.436 | passes by 0.036 (cosmetic) |
> | After-tax adjustment (per `project_tax_drag_kills_after_tax_2026_05_02.md`) | est. negative | **fails** |
> | Plus 36-name missing-CSV upper-bound | pushes lower | **fails** |
>
> Strict reading of "net of all costs incl. taxes + borrow": **TRIGGERED.**
>
> **Trigger decision (2026-05-09):** treat as triggered. Don't move goalposts. The discipline framework only works if pre-commits are respected even when inconvenient.
>
> **What "triggered" means concretely:**
>
> - The project is NOT shut down. Pre-commit said "stop and run structural review" — not "abandon."
> - Forward feature work that claims Sharpe pauses for the duration of structural review.
> - Substrate-independent infrastructure work continues (engine completion is the structural review's main vehicle).
>
> **The structural review = engine completion.**
>
> The user surfaced the deeper finding the same evening: **the engines are not operating as engines.** Empirical confirmation:
>
> - Engine C's `compute_target_allocations` is defined but **never called** in the backtest loop (`orchestration/mode_controller.py`)
> - HRPOptimizer + TurnoverPenalty live at `engines/engine_a_alpha/signal_processor.py:228-242` (charter inversion F4)
> - No portfolio-level diversification, correlation-aware sizing, factor exposure caps, sector budgets — what actually runs is "Engine A produces edge votes → RiskEngine sizes per-ticker → PortfolioEngine books fills"
> - Engine D's discovery cycle has produced 0 promoted edges
> - Engine E's HMM is empirically coincident, not leading
>
> **The 0.507 substrate-honest Sharpe isn't "the strategy doesn't work" — it's "the strategy operating without portfolio management doesn't survive substrate honesty."**
>
> **The structural review's deliverable:** complete the engines per their charters, then re-measure on substrate-honest universe. The result becomes the new pre-commit baseline.
>
> ---
>
> **2026-05-09 AFTERNOON — F6 verdict COLLAPSES.** Multi-year mean Sharpe
> 1.296 → **0.5074** on substrate-honest universe (476-503 historical S&P
> 500 union). −0.789 Sharpe / −61%. Audit doc:
> `docs/Measurements/2026-05/universe_aware_verdict_2026_05_09.md`. Memory:
> `project_universe_aware_collapses_2026_05_09.md`.
>
> **Per-year breakdown:**
>
> | Year | Static (109) | Universe-aware (476-503) | Δ | Within ±0.15? |
> |---:|---:|---:|---:|---|
> | 2021 | 1.666 | 0.862 | −0.804 | NO |
> | 2022 | 0.583 | −0.321 | −0.904 | NO |
> | 2023 | 1.387 | 1.292 | −0.095 | **YES (only year)** |
> | 2024 | 1.890 | 0.268 | −1.622 | NO |
> | 2025 | 0.954 | 0.436 | −0.518 | NO |
>
> **0.507 is an upper bound.** 26-54 names per year were silently dropped
> for missing CSV files (FRC, DISCA, ATVI confirmed). Those are mostly
> delisted names — survivorship-bias signal pushing the real Sharpe lower.
> To pin down: run `scripts/fetch_universe.py` then re-measure.
>
> **What this means:**
>
> - **Path 1 ship: NOT VIABLE in current form.** 6 weeks of headline
>   Sharpe wins (1.296 Foundation Gate, 1.666 baseline, 1.890 in 2024,
>   V/Q/A 1.607 sustained-scores) were measured against a substrate
>   that implicitly selected for the same names the system was trading.
>   The math was correct; the test was easy.
> - **Pre-commit kill thesis nominally TRIGGERED** (Foundation Gate
>   measured at 0.507 vs. 0.5 gate; the gate is a clean fail when the
>   missing-CSV upper bound resolves). Honest restatement of the kill
>   criteria on substrate-honest universe is owed before the next
>   commitment cycle.
> - **The discipline framework is working.** This is what 8 months of
>   gauntlet / harness / decision-diary / external-review investment
>   was FOR. Today is the highest-value moment of that investment.
>   No live capital was risked on the biased measurement.
> - **2023 is the only year that held** (−0.095 within noise band on a
>   4.5× expanded universe). The 2026-05-09 evening trade-log
>   decomposition (`docs/Measurements/2026-05/multi_year_dilution_decomposition_2026_05_09.md`)
>   showed the substrate gap is NOT a single mechanism but three regime-
>   dependent ones:
>   - 2024 (largest collapse): 91.8% pure dilution on shared mega-caps —
>     same names, position size 4.4× smaller, signals drown
>   - 2022 (bear): defensive-concentration dominant — the 109-name list
>     dodged 331 expanded names that lost in the bear regime
>   - 2023 (the only year that held): broad participation; the 359 added
>     historical-S&P names contributed +$3,733; substrate didn't matter
>   - 2025: mixed; small magnitudes
>
>   The 6-non-S&P names hypothesis (COIN/MARA/RIOT/DKNG/PLTR/SNOW) is
>   refuted by data: those 6 contributed only 1.7% of static-109's
>   2024 PnL. **The actual mechanism is capital concentration on
>   shared mega-caps, not stock selection.**
>
> **What survives:**
>
> All infrastructure (Foundry, harness, gauntlet, decision diary,
> code-health, doc lifecycle, lifecycle automation, edge graveyard,
> V/Q/A integration, falsification framework, and the 2026-05-09
> metric-framework upgrade adding PSR + DSR + IR + tail/skew/kurt/ulcer).
> Edge code is intact; what's invalidated is the headline narrative
> around it.
>
> **C-collapses-1 result (2026-05-09 night).** Per-edge attribution lands. **Substrate-honest mean lifts from 0.5074 (9-edge) to 0.9154 (6-edge surviving) on the same window** — the 9-edge collapse is a 2-edge story (`quality_roic_v1`, `quality_gross_profitability_v1` both FALSIFIED with Δ Sharpe +1.358 / +0.503; `herding_v1` DEGRADED at +0.411). 4 of 9 edges (`gap_fill_v1`, `volume_anomaly_v1`, `value_earnings_yield_v1`, `value_book_to_market_v1`) are STRONGER on the wider universe. 2 (`accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1`) within ±0.2 noise.
>
> But — the surviving 6-edge set is **regime-conditional**: 2021/2023/2024 (bull / Mag-7) all materially better than the 9-edge ensemble; 2022 bear (−0.508) and 2025 chop (−0.107) are *worse*. The 2 falsified quality edges were apparently providing a defensive hedge the surviving set lacks.
>
> **Does this undo the kill-thesis trigger?** No. The trigger criterion was 2025 OOS Sharpe < 0.4 net of all costs (incl. taxes + borrow). Surviving-set 2025 = −0.107 (pre-tax), even worse than the 9-edge 0.436 that triggered. Engine completion remains the structural review's deliverable; the per-edge audit narrows down which edges are worth carrying THROUGH the engine-completion work, not whether to do it.
>
> Independently, the 6-names hypothesis was inverted by my isolation test (removing the 6 names from static-109 *improves* Sharpe by +1.30) — consistent with the evening trade-log decomposition's finding that the 6 names contributed only 1.7% of static-109's 2024 PnL.
>
> `data/governor/edges.yml` updated: `herding_v1` → `paused`, `quality_roic_v1` + `quality_gross_profitability_v1` → `failed`, all with `failure_reason='universe_too_small'`. Active count 9 → 6.
>
> Docs: `docs/Measurements/2026-05/six_names_isolation_2026_05_09.md`, `substrate_collapse_edge_audit_2026_05_09.md`, `surviving_edges_multi_year_2026_05_09.md`. Memory: `project_substrate_audit_2_edge_overfit_2026_05_09.md`.
>
> **What's queued (engine-completion structural review):**
>
> | Step | Dispatch | What it produces |
> |---|---|---|
> | ~~C-collapses-1 (running)~~ → **DONE 2026-05-09 night** | Per-edge audit on substrate-honest universe | 6 surviving / 1 paused / 2 failed; substrate-honest mean 0.9154 PARTIAL but bull-conditional. See result block above. |
> | C-collapses-1.25 | Factor decomp on volume_anomaly + herding under substrate-honest | Whether the two t > 4 alphas survive at t > 2 (4-bucket verdict). Note: herding_v1 is now paused per audit; rescope as needed. |
> | C-collapses-1.5 | Concentration-equivalent capital test | Does any per-name signal exist independent of concentration? |
> | **C-engines-1** | **Engine C activation** — wire `compute_target_allocations` into backtest loop; move HRP+Turnover OUT of signal_processor (closes F4); make Engine C a real portfolio composition layer | Engine C operating per charter |
> | **C-engines-2** | **Engine B portfolio vol-targeting + correlation-aware sizing** | Engine B operating per charter |
> | **C-engines-3** | **Engine E minimal-HMM on leading FRED features** + wire into Engine B de-grossing | Engine E operating per charter (also addresses the bull-conditionality of the surviving 6-edge set — see C-collapses-1 result) |
> | **C-engines-4** | **Engine D Bayesian opt scaffolding** (replaces GA noise factory) | Engine D producing real candidates |
> | **C-engines-5** | **Engine A pure-signals refactor** — charter restored | Engine A operating per charter |
> | C-remeasure | Re-run multi-year on substrate-honest universe with completed engines AND the 6-edge surviving set | The honest baseline. The next pre-commit gate gets defined here. |
>
> Goal C / Moonshot Sleeve stays parked until C-remeasure verdict. As
> the user framed it: "if we can't get the bones working properly we
> shouldn't be working on the golden apple yet."
>
> **All measurements citing 1.296 / 1.666 / 1.890 / 1.607 baselines below
> this section are now KNOWN substrate-conditional AND engine-incomplete.**
> Read with two caveats: (a) substrate was biased, magnitudes are upper
> bounds; (b) engines weren't operating per charter, so the result is
> "what an incomplete system did on representative substrate" — not a
> fair test of the architecture.
>
> ---

## Pre-2026-05-09 plan (substrate-conditional — kept for reference)

> **Live plan.** Supersedes `forward_plan_2026_05_01.md` after the
> two outside-reviewer docs landed
> (`docs/Sessions/Other-dev-opinion/05-1-26_1-percent.md`
> + `05-1-26_a-and-i_full.mf`). Both converge on the same architectural
> picture and identify gaps the prior plans had underweighted.
>
> **PATH C DEFERRED — 2026-05-06:** 3-day Path C arc + regime-signal
> validation complete. Cells E/F/G/H all falsified. Cell F closest
> miss at -16.09% MDD / 4.74% CAGR; do NOT iterate further on 4-event
> sample.
>
> **Original unblock criteria from earlier today are now KNOWN-BROKEN
> per `project_regime_signal_falsified_2026_05_06.md`:** HMM is
> empirically a coincident vol detector, not forward-looking.
> AUC 0.49 on 20d-fwd drawdowns (coin flip). 2-of-3 cross-asset gate
> had **0% TPR** on -5% drawdowns over 1086 days. DXY change AUC 0.24
> (inverted from docstring's "rally = stress" theory). HMM input
> features (`spy_ret_5d`, `spy_vol_20d`) are coincident by
> construction; the architecture cannot lead.
>
> **REVISED unblock criteria** (much higher bar — multi-month, not
> weeks):
> 1. **HMM input panel rebuild** with leading features. ~~First
>    candidates: VIX term structure~~ — VIX term structure FALSIFIED
>    on 2026-05-06 (3 independent measurements agree it's coincident
>    across the entire 9d-to-6M curve; anti-predictive at canonical
>    -5% threshold). CBOE P/C historical UNOBTAINABLE in 2026 (every
>    free endpoint blocked). Remaining candidates:
>    (a) **Minimal-HMM on existing FRED features only**
>        (yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d,
>        spy_vol_20d — those carry slice-1's 78-day OOS lead).
>        Highest-ROI next step, no new data integration needed.
>    (b) IV skew (25Δ put / 25Δ call) via Schwab API — GATED on
>        historical-options-chain verification per the dev review
>        (`docs/Sessions/Other-dev-opinion/5-5-26_schwab-plan-reflection.md`).
>        If Schwab doesn't expose historical chains, IV skew is
>        forward-collection-deferred 6-12 months OR a paid-provider
>        decision.
>    (c) Earnings-revision dispersion via existing fundamentals data.
> 2. **THEN scope Engine B integration** after the input panel is
>    empirically predictive — propose-first per CLAUDE.md.
> 3. **THEN Path C overlay** at `scripts/path_c_overlays.py` becomes
>    load-bearing via regime-conditional trigger.
>
> VVIX-proxy is the lone salvageable signal from the existing
> WS-C work (AUC 0.64 in its valid window). The 2-of-3 confirmation
> architecture (`engines/engine_e_regime/cross_asset_confirm.py`) is
> a misleading standing reference, archive-pending.
>
> DO NOT reset -15% MDD target — load-bearing per design, not arbitrary.
> DO NOT scope Engine B integration until input-panel rebuild ships.
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
> context drag rather than alpha refutation. But this re-accounting
> also reveals: the kill thesis was tied to "post-Foundation"
> measurement, and Foundation is genuinely ~65% not ~90% — the
> integrated rerun that would actually be "post-Foundation" hasn't
> happened. So the -0.577 is post-cost-layer-only, not post-full-
> foundation. Doesn't change the directional finding (tax drag is
> real and large) but does mean the kill thesis trigger reading is
> on incomplete data.
>
> **Deployment-context update — 2026-05-02 evening:** Alpaca (the
> deployment vehicle) may not offer Roth IRAs. Live-money deployment
> is therefore TAXABLE individual unless the user opens a separate
> Roth-supporting brokerage (non-engineering decision, deferred).
> Paper trading is tax-free but doesn't model the real-money case.
> **Tax-drag engineering (regime-conditional wash-sale gate,
> longer-hold optimizer, tax-loss harvesting / lot selection) is
> DEFERRED but HIGH PRIORITY.** Next-round dispatch prioritizes
> context-agnostic improvements (features, regime detection, data
> sources, sleeve abstractions) that help in BOTH contexts. The
> wash-sale gate multi-year falsification (2021 Δ=-0.966) confirmed
> that naive tax-drag fixes can hurt in taxable too — the
> regime-conditional design is the right answer when we get to it,
> not next round.

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

## Round-N+1 dispatch (5 context-agnostic agents) — 2026-05-04 update

The first round shipped (5 agents, May 1-2). The next-round dispatch
focuses on **context-agnostic improvements** that help in both Roth and
taxable, with tax-drag engineering deferred per the deployment-context
update above. **All 5 agents are GATE-CONDITIONAL — fire only after the
multi-year Foundation Gate measurement (driver: `scripts/run_multi_year.py`,
artifact: `docs/Audit/multi_year_foundation_measurement.md`) reports
`Gate status: PASS` (mean Sharpe across 2021-2025 ≥ 0.5).** If
status is AMBIGUOUS or FAIL, the dispatch table below is suppressed
and the kill-thesis review path takes over instead.

| Agent | Workstream | Read/write surface | Backtest? | Time budget | Branch |
|---|---|---|---|---|---|
| 1 | F — Fundamentals data scoping (Compustat / SimFin / EDGAR / `noterminusgit/statarb`) | `docs/Core/Ideas_Pipeline/`, `docs/Audit/` (research notes only) | No | 1-2 hrs research + report | `ws-f-fundamentals-data-scoping` |
| 2 | E — Foundry batch 3 (5 more features toward 50-feature target) | `core/feature_foundry/features/`, tests | No | 2-3 hrs | `ws-e-third-batch` |
| 3 | C — Cross-asset confirmation layer + HMM smoke | `engines/engine_e_regime/`, `core/feature_foundry/features/` (HYG/LQD spread, DXY, vol-of-vol) | Yes (1 smoke) | 2-3 hrs | `ws-c-cross-asset-confirm` |
| 4 | D — Foundry close-out (auto-ablation cron + adversarial filter as CI gate + 90-day archive) | `core/feature_foundry/`, `.github/workflows/` (or pre-commit), CI scripts | Yes (ablation) | 3-4 hrs | `ws-d-closeout` |
| 5 | J — Cross-cutting trio (decision diary + edge graveyard structured tagging + info-leakage detector skeleton) | `core/observability/` (new), `data/governor/` schema only, `cockpit/dashboard_v2/` | No | 2-3 hrs | `ws-j-cross-cutting-batch` |

### Per-agent acceptance criteria

**Agent 1 — WS F fundamentals data scoping** (research only, no merged code expected this round):
- Comparison matrix of Compustat / SimFin / EDGAR (license cost, point-in-time history available, update lag, schema completeness for value + quality + accruals factors)
- Audit of `noterminusgit/statarb` repo (alpha strategies that depend on fundamentals + portfolio optimizer specifics + which can drop into our Foundry without rewrite)
- Recommendation memo: which data source for what factor family, which `statarb` modules to lift, what's the prerequisite to enable Path C compounder (currently blocked per `project_compounder_synthetic_failed_2026_05_02`)
- Deliverable: `docs/Audit/ws_f_fundamentals_data_scoping.md` plus optional `docs/Core/Ideas_Pipeline/path_c_unblock_plan.md`. No code merged.

**Agent 2 — WS E batch 3 (5 features)**:
- 5 new features in `core/feature_foundry/features/` covering calendar / event-driven / pairs primitives (e.g. `days_to_quarter_end`, `earnings_proximity_5d`, `pair_zscore_60d` for sector pairs, `month_of_year_dummy`, `vix_term_structure_slope`)
- Each ≤ 50 LOC, with adversarial twin generated, ablation-runner output captured
- Tests pass; full Foundry test regression passes
- Cumulative target: 14/10 features (50% past the 10-feature pre-batch goal — substrate validates)
- Deliverable: 5 commits or one bundled commit on `ws-e-third-batch`, model card per feature

**Agent 3 — WS C cross-asset confirmation + HMM smoke**:
- HYG/LQD credit spread, DXY (USD index), VVIX (vol-of-vol) added as Foundry features
- Cross-asset confirmation gate function in `engines/engine_e_regime/` that takes HMM transition signal + cross-asset evidence and returns confirm/veto
- Default OFF (no behavior change on main without flag flip)
- Smoke run with `hmm_enabled: true` AND cross-asset confirmation ON, single year (2024) under harness, captured in audit doc
- Acceptance: smoke run completes deterministically (3 reps bitwise-identical canon md5), report shows Sharpe-impact estimate
- Pre-req for the regime-conditional wash-sale gate when tax-drag work unfreezes
- Deliverable: code + `docs/Audit/ws_c_cross_asset_confirmation.md`

**Agent 4 — WS D close-out**:
- Auto-ablation runner triggered on every PR that touches `core/feature_foundry/features/*.py` (CI workflow OR pre-commit hook)
- Adversarial-twin filter integrated as a hard CI gate: feature must outperform its permuted twin by ≥X% margin (X to be specified by agent; conservative default suggested 30%)
- 90-day archive enforcement: features whose last-90d performance trends negative get auto-tagged for review (not auto-deleted — flag and queue for human triage)
- Deliverable: code + workflow files + `docs/Audit/ws_d_foundry_closeout.md` listing what is now AUTO vs. what still requires human in the loop
- Closes WS D from ~60% to "complete per the doc's named deliverables"

**Agent 5 — WS J cross-cutting trio**:
- Decision diary scaffold: structured log entries for each significant config flip / merge to main with rationale + expected impact + actual impact (post-hoc fillable)
- Edge graveyard structured tagging: edges with `status: failed` get a structured `failure_reason` + `superseded_by` field in `data/governor/edges.yml` (schema change only; backward-compatible)
- Info-leakage detector skeleton: function that, given a feature definition, can identify whether it uses lookahead (close vs. next-bar-close, future-window stats) and emits a diagnostic. Wired in as ADVISORY (not enforcing) to start
- Deliverable: code + tests + `docs/Audit/ws_j_cross_cutting_trio.md`
- Each of the three is high-leverage, compounds on every future agent's reporting

## Repo audit findings (from reviewer's review)

Three external repos worth real time investigation:
- `noterminusgit/statarb` — 20+ alpha strategies + portfolio optimization. Saturday-afternoon audit.
- `ScottfreeLLC/AlphaPy` — Python AutoML for trading; relevant to Foundry. May accelerate Track G.
- `warproxxx/poly_data` — Polymarket integration. Drop-in for Track F.

These are **investigation tasks, not dispatched tasks** for this round. The user can audit them at their own pace.

## Single-paragraph TL;DR

**5 agents in parallel this round: gauntlet architectural fix, Feature Foundry skeleton, Engine C HRP slice, Engine E HMM slice, cost completeness. After this round, re-run 2025 OOS under harness to test the Foundation Gate. If pass → unlock the rest of the 10-workstream plan in tiered parallel waves. If fail → pre-committed kill thesis kicks in, structural review. The reviewer's most emphatic point — "build infrastructure first, then features" — is captured by putting Foundry in this round; the engine-gap finding (C and E are biggest) is captured by putting both engines' first slices in this round. After Foundation, the path is parallel-track aggressive but discipline-gated. Real-money deployment no earlier than ~12 months out, probably mid-late Year 2.**

## V/Q/A FUNDAMENTALS EDGES STATUS — 2026-05-07 (substrate-conditional, see top-of-file caveat)

> **2026-05-09 update:** F6 verdict COLLAPSES means the 1.666 baseline
> and 1.607 sustained-scores result below were measured on a biased
> substrate. The "-0.06 drag (within noise band)" framing assumed both
> baseline and treatment were measured against the same biased universe;
> on substrate-honest universe, both magnitudes are unknown. The
> integration-mismatch fix is still architecturally correct (held
> positions need a defending vote vs. silence) — that's a software
> finding, not a measurement claim. Whether V/Q/A net-helps on
> substrate-honest universe is open: gated on C-collapses-1's per-edge
> audit. Treat the 2022 bear smoke + grid search as DEFERRED until
> per-edge audit completes.

The 6 V/Q/A edges (`value_earnings_yield_v1`, `value_book_to_market_v1`, `quality_roic_v1`, `quality_gross_profitability_v1`, `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1`) shipped 2026-05-06. Three sequential fixes:

1. **2026-05-06 morning** — V/Q/A merged with default config. 2021 single-rep Sharpe 1.155 vs baseline 1.666 = **-0.51 drag**. Code-health agent surfaced 3 HIGH bugs (ROIC distressed-firm inflation, helper bare-except, auto-register exception swallowing).

2. **2026-05-06 PM** — bug fixes shipped + state-transition pattern (no daily over-trading). Trades 7057 → 538 (-92%). But Sharpe dropped to **0.592** = -1.07 drag. The over-trading was masking integration mismatch.

3. **2026-05-07** — sustained-score fix shipped. Edges emit `sustained_score=0.3` on held positions instead of 0.0, keeping their position-defending vote alive. **2021 Sharpe 1.607 vs baseline 1.666 = -0.06 drag** (within noise band). Integration-mismatch hypothesis confirmed.

**Current status:** active in `data/governor/edges.yml` with sustained-score logic. Smoke verified on 2021 only.

**Required before promoting default-on for production / multi-year measurement:**
- 2022 bear-regime smoke as the diagnostic test (single-year fail/pass)
- If 2022 passes: full 2021-2025 multi-year × 3 reps
- Grid-search on `sustained_score` parameter (0.0 / 0.2 / 0.3 / 0.5) — current 0.3 is a starting heuristic, not validated

**Honest note:** 16 names per top quintile is above the 8-name disaster threshold (see `project_factor_edge_first_alpha_2026_04_24`) but below the ≥200 academic convention. Per-edge OOS walk-forward required before promotion past `feature` tier.
