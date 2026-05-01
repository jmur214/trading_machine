# Forward Plan — 2026-05-01

> **Live plan.** Supersedes `forward_plan_2026_04_30.md` after today's
> determinism-restoration work + Path 1/2 revalidations + autonomous
> lifecycle pruning + user vision clarifications. This is the honest
> state-of-the-machine as of 2026-05-01 evening, with all measurements
> taken under the determinism harness unless noted.
>
> **POST-ROUND-4 UPDATE (2026-05-01 late evening) — top-level summary:**
>
> Four parallel agents (Discovery diagnostic + gates 2-6 audit + IS
> multi-year + per-ticker re-val + capital allocation dashboard) all
> reported clean. Two convergent findings reshape the next dispatch:
>
> 1. **All 6 gauntlet gates share the same standalone-vs-ensemble
>    geometry-mismatch bug class.** Agent A confirmed empirically:
>    Gate 1 kills 30/30 candidates today, but 7 of 30 have positive
>    Sharpe (one at 0.999) — they're real candidates dying at the
>    wrong gate, not noise. Agent B's audit found gates 2/3/5/6 also
>    FAIL the same geometry mismatch + gate 4 SUSPECT. **The clean
>    fix is one architectural rework at the top of `validate_candidate`
>    that fixes all 5 gates simultaneously, not 5 separate piecemeal
>    fixes** (the prior Reform Gate 1 attempts failed because they
>    tried to reimplement the ensemble; the right answer is to invoke
>    `mode_controller.run_backtest` directly). Memory:
>    `project_gauntlet_consolidated_fix_2026_05_01.md`. Estimated
>    3-5 days agent time. THIS is the next-session top-priority dispatch.
>
> 2. **System is genuinely robust under harness across every measurement
>    cut taken.** Agent C's IS multi-year (2021-2024) reading: Sharpe
>    0.905 (3 runs identical, beats SPY 0.875). OOS (0.984) > IS (0.905)
>    means **no IS overfit.** Drifted readings (1.063 / 1.113) were
>    overstated by ~0.2 Sharpe each. **Per-ticker meta-learner formally
>    falsified at deployment level** — 0.442 Sharpe vs ML-off 0.984.
>    Both ML directions (portfolio + per-ticker) now stay disabled.
>
> Plus two independent gauntlet bugs surfaced by Agent B (WFO equity-
> stitching at `wfo.py:112`; PBO single-ticker bootstrap) — small fixes
> to bundle alongside the architectural rework.
>
> Capital allocation dashboard (Agent D) shipped to
> `cockpit/dashboard_v2/` — surfaces 2025 rivalry pattern visually.
> Useful infrastructure forever after.
>
> **Next dispatch when work resumes:** consolidated gauntlet fix
> per `project_gauntlet_consolidated_fix_2026_05_01.md`. After it
> ships, Engine D begins promoting candidates autonomously for the
> first time in months — the factory works.
>
> Body of plan below is preserved as the strategic context that
> motivated the round-4 dispatch. The "Tier 1" and "Tier 2" lists
> remain valid; the consolidated gauntlet fix subsumes most of
> Tier 1 #1 (Reform Gate 1 baseline fix).

---

## What changed today (one paragraph each)

**Determinism floor restored.** Agent A bisected the regression source to a single file: `data/governor/edges.yml`. End-of-run lifecycle + tier-reclassification writes mutate it; subsequent runs read the mutated state. The new `scripts/run_isolated.py` snapshots+restores the four governor files around each backtest. **3-run verify produces bitwise-identical canon md5 across runs.** The 04-23 floor is back. Memory: `project_determinism_floor_2026_05_01.md`.

**Path 1 ship-state revalidated under harness.** Agent A ran a 4-cell × 3-run grid for cap × ML on prod-109 2025 OOS. **Best deterministic Sharpe: 0.984 at cap=0.20 + ML off.** Adding ML at any cap value DEGRADES Sharpe by ~0.58 — the +0.749 lift Agent C measured in round 1 was governor-drift coincidence. `metalearner.enabled=false` stays on main. Memory: `project_metalearner_drift_falsified_2026_05_01.md`.

**Path 2 universe-fragility revalidated under harness.** 9-run grid on Universe-B 2021-2024: anchor 0.610 → floors 0.762 → floors+ML 0.849. The original "0.225 collapse" was massively governor-drifted (3× understated). ADV floors deliver a real +0.152 lift. ML helps on UB (+0.087 over floors) but hurts on prod-109 — universe/window-conditional, not universally good or bad. The "0.916 beats SPY" claim from Path 2 was drifted; deterministic 0.849 is just under SPY 0.875 on the same window.

**Autonomous lifecycle pruned the active edge set to 3.** The triggers Agent B shipped (zero-fill timeout, sustained-noise, revival_veto) plus benchmark-relative pause logic combined to autonomously: retire 6 edges (atr_breakout, all four macro_*, seasonality), pause 14 (momentum_edge, low_vol_factor, all PEAD variants, etc.), leave 3 status=active (gap_fill, volume_anomaly, herding). **The system did this without human input** — exactly the autonomy the user has been pushing for.

**Production ensemble is NOT a 3-edge stack.** Soft-paused edges trade at `PAUSED_WEIGHT_MULTIPLIER = 0.25×`. The harness logs show panic_v1, earnings_vol_v1, momentum_edge_v1 also being loaded and contributing at reduced weight. **Effective deployed ensemble ≈ 3 full + 5+ partial = ~4.25 edge-equivalents.** This is important context — any future Discovery gate, validation, or A/B comparison must use the production-equivalent ensemble (active + soft-paused at correct weights), not "pure active."

**Gate 1 reform shipped, baseline definition needs fix.** Agent 1 (gate1reform) replaced standalone-Sharpe Gate 1 with an ensemble-simulation contribution gate (Phase 2.10e). The implementation is 90% there. Falsifiable-spec verification: both `volume_anomaly_v1` and `herding_v1` failed the new gate. Reason discovered today: Agent 1's `_load_active_ensemble_specs` filters to `status='active'` only, EXCLUDING soft-paused edges that production deploys at 0.25×. The gate's "ensemble" is smaller than production's, hits the impact knee inside the gate itself — same class of geometry-mismatch the reform was supposed to fix. **The gate is not promoted; the fix is straightforward.**

**User vision crystallized.** Three new memories captured the user's actual goal C framing: (1) retail capital math forces asymmetric upside as a CORE objective, not optional Phase 5+ work; (2) thematic-conviction picking is a missing edge category requiring LLM-as-analyst; (3) **plateau-before-AI sequencing** — keep building all non-LLM capability until plateau, THEN add LLM as amplifier. This corrected my earlier drift toward "ship Path 1 to deployment." Path 1 was a *measurement* milestone, not a deployment one. The system is nowhere near plateau.

---

## The actual state of the system, under harness

| Window | Universe | Config | Sharpe | Source |
|---|---|---|---|---|
| 2025-01-01 → 2025-12-31 | prod-109 | cap=0.20, ML off, floors on | **0.984** | Agent A path1-revalidation |
| 2025-01-01 → 2025-12-31 | prod-109 | cap=0.25, ML off | 0.407 | Agent A path1-revalidation |
| 2025-01-01 → 2025-12-31 | prod-109 | cap=0.20, ML on | 0.406 | Agent A path1-revalidation |
| 2021-01-01 → 2024-12-31 | Universe-B (50 held-out) | floors off, ML off | **0.610** | Path 2 revalidation (this director) |
| 2021-01-01 → 2024-12-31 | Universe-B | floors on, ML off | **0.762** | Path 2 revalidation |
| 2021-01-01 → 2024-12-31 | Universe-B | floors on, ML on | **0.849** | Path 2 revalidation |

Benchmarks: SPY 2025 = 0.955 / SPY 2021-2024 = 0.875 / QQQ 2021-2024 = 0.702 / 60-40 2021-2024 = 0.361.

**Gaps in measurement:**
- 2021-2024 IS prod-109 under harness with production-equivalent ensemble (Agent 1's -0.232 was at pure-active ensemble, not deployment-equivalent).
- Path 2 numbers may understate vs production-equivalent baseline if the q2 task also excludes soft-paused.

## Honest deployment-state summary

**On the design universe (prod-109), 2025 OOS:** the system at cap=0.20+ML-off+floors-on produces Sharpe **0.984**, beating SPY 0.955 by +0.03. Beats QQQ. Slightly below 60-40 (0.997). **Risk-adjusted, the system beats most equity benchmarks. Absolute return is modest** (CAGR was ~4.8% in the floors-only run; SPY was 18%).

**On a broader universe (UB held-out 50), 2021-2024:** the system reaches 0.762 with floors only, 0.849 with floors+ML. Both below SPY 0.875 — the universe-fragility doctrine softens but doesn't go away. The system's performance on broader universe is **~87-97% of SPY's risk-adjusted return**, not "catastrophically fails on broader universe" as the original drifted reading suggested.

**Status:** the system is **deployable at this state with documented prod-109 boundary, but should NOT yet deploy** because (a) Phase 3 infrastructure isn't built (no real OMS, kill switches, paper-trading validation), (b) the system has substantial pre-LLM expansion runway left, and (c) absolute return on retail capital math is meaningless until the system clears 12-15% CAGR. Per the user's "plateau before AI" + "bones before paper" principles, **the right move is to keep building.**

---

## The pre-LLM expansion runway (revised)

Per the user's clarification: build all non-LLM capability to a genuine plateau, THEN add LLM-as-analyst. The runway is multi-quarter, and most of the work is currently underweight on the formal roadmap.

### Tier 1 — immediate next workstreams (high leverage, well-scoped)

1. **Reform Gate 1 baseline fix** (1-2 days). Agent 1's gate is 90% there; fixing the soft-paused inclusion in the baseline ensemble is a one-function change. After that, re-run the falsifiable spec. If `volume_anomaly_v1` + `herding_v1` PASS, promote the gate to default. Discovery becomes more productive immediately.

2. **IS multi-year verification under harness** (1 hour compute). The Path 1 ship-state has 2025 OOS verified at 0.984. The 2021-2024 IS reading is missing — Agent A flagged this; my earlier "verification" was a misclick (script overrode dates to 2025). Need a true 2021-2024 IS run with production-equivalent ensemble to know whether the active set is regime-stable or 2025-favorable. Quick to do.

3. **Path 2 re-test under production-equivalent baseline** (1 hour compute). The Path 2 q2 numbers may have used the same pure-active baseline that biased Agent 1's gate. If so, the corrected reading might be higher than 0.762/0.849. Easy to verify alongside #2.

### Tier 2 — multi-week edge factory work

4. **Statistical Moonshot Sleeve build-out** (~3-6 weeks). The user's actual goal C framing — small-cap momentum + 52-week breakouts + insider clusters + earnings beats + sentiment velocity. None are built yet. With Reform Gate 1 working, the gauntlet should accept the good ones and reject noise. **This is the highest-leverage edge-building work for retail capital math.**

5. **Engine D investigation: why does Discovery promote near-zero?** (1-2 weeks). Even with Gate 1 fixed, Discovery's gene vocabulary is mostly technical. Macro is at 10%, earnings 5%, "Grey" 0%. If we want it to autonomously discover anything novel, the gene space needs widening + maybe Discovery-gated revival path for regime-conditional edges.

6. **Universe expansion beyond prod-109** (~2-4 weeks). Current production universe is 109 mostly-mega-cap names. Goal-A retail compounding is bottlenecked by edge fit on this curated set. Need a broader investable universe (S&P 500 fully, Russell 2000 stratified, IPO last-5y for Moonshot, theme-tagged for thematic).

### Tier 3 — multi-quarter data + observability

7. **Alt-data ingestion expansion** (~1-2 months). Wider Form-4 (insider trading), USAspending (contract awards), Capitol Trades (politician trades), free news APIs, SEC EDGAR full filings parsers, quality factor. **This is the prerequisite layer for both new edge categories and eventual LLM-as-analyst.** Not on formal roadmap; should be added.

8. **Cost-model completeness** (1-2 weeks). Borrow rates for shorts, short-term cap gains tax drag, Alpaca fee tiers. Important for after-tax compounding claim (goal A).

9. **Capital allocation diagnostic dashboard** (~2-3 hr). UX-engineer-territory; the 04-30 reviewer's recommendation. Real-time observability of rivalry/concentration patterns. Cheap, useful forever.

### Tier 4 — architectural improvements (queued)

10. **Per-ticker meta-learner re-validation under harness** (~1 day). We don't yet know what per-ticker training delivers under deterministic measurement. Worth measuring once before fully writing off the per-ticker direction.

11. **Discovery-gated revival path** (~1 week). Currently regime-conditional edges that fail constant-weight deployment have no revival route. Build the proper alternative.

12. **Multi-window walk-forward harness** (~1 week). The harness only supports q1 (2025 OOS) and q2 (UB IS) tasks. Extend for arbitrary windows so multi-year IS becomes a one-liner.

### NOT on this list (deferred per user vision)

- **Phase 3 deployment infrastructure** (paper trading, OMS, real kill switches) — correctly deferred. System nowhere near plateau.
- **Phase 4 intraday** — deferred behind Phase 3.
- **Phase 5 SIP / multi-sleeve** — correctly deferred. Don't sleeve a portfolio that hasn't earned its first dollar.
- **Phase 6 LLM-as-analyst** — correctly deferred per "plateau before AI." The first work toward it (data ingestion expansion in Tier 3 #7) has dual purpose: useful for non-LLM edges first, prerequisite for LLM later.

---

## Strategic principle for the next 3-6 months

**Build, measure, repeat.** Every workstream feeds the next; the harness keeps us honest.

The system is in a much clearer position than it was 24 hours ago:
- Determinism is restored
- Real ship-state numbers are known on the design universe (deterministically)
- Universe-fragility is partially closed by ADV floors but not fully
- Lifecycle is autonomous and producing real decisions
- The meta-learner direction is partially-falsified (portfolio-level) but not fully (per-ticker still possible)
- The user's vision is clearly captured in memory

The next quarter's work is concrete: fix Gate 1, build the moonshot edges, expand data, fix Discovery's gene vocabulary, broaden the universe. Each move is well-scoped. None of them is LLM. All of them are pre-plateau bones-improvement work.

The plateau will reveal itself when these workstreams start producing diminishing returns — i.e., when each new edge added through the (fixed) gauntlet doesn't materially lift ensemble Sharpe, when wider universes don't open new alpha, when more data doesn't surface new signals. **At that point, LLM-as-analyst becomes the next layer.** Not before.

---

## Single-paragraph TL;DR

**Determinism is back. The honest numbers are: prod-109 2025 OOS Sharpe 0.984 (beats SPY), Universe-B held-out Sharpe 0.762-0.849 (slightly below SPY), production ensemble is 3 active + ~5 soft-paused. The autonomous lifecycle did its job. Path 2 ADV floors are real. Meta-learner is universe/window-conditional and stays disabled. Reform Gate 1 needs a one-function baseline fix before promoting. The next 3-6 months are about building the statistical moonshot capability, expanding the universe and data layer, fixing Discovery's gene vocabulary — all pre-LLM. Phase 3 deployment is correctly deferred. The system is in its honest best state since the project began.**
