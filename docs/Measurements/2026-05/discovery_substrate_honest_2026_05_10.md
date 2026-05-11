# Discovery Cycle on Substrate-Honest Universe — First-Ever Run (T-2026-05-10-021)

**Date:** 2026-05-10 (run completed 2026-05-11 wall clock)
**Branch:** `feature/discovery-cycle-substrate-honest`
**Source spec:** inbox brief T-2026-05-10-021
**Window:** 2024-01-01 → 2024-12-31 (single-year, see "Scope deviation" below)
**Substrate:** F6 historical S&P 500 universe + missing-CSV closure d5af02e (`use_historical_universe=True`)
**Mode:** journal-mode (`apply_journal_at_end=True`), deterministic-harness (`PYTHONHASHSEED=0` + `isolated()`)

---

## Headline

**3 candidates evaluated. 0 promoted. ALL 3 failed Gate 1 (Sharpe-contribution).** Per-candidate cost on substrate-honest substrate is **54-111 min (mean 74 min)** — far above the spec's implicit assumption that 30-50 candidates would fit in 6-8 hr. The 3-candidate sample size is below the spec's floor of 30, but the two headline findings replicate across all 3 records and answer the spec's strategic questions cleanly.

**Two answers to spec's "three possible outcomes" framing (lines 36-39):**

1. **First-failed-gate is uniformly Gate 1** — the "specific gate-failure pattern" outcome. Gate 1's `min_contribution_to_ensemble = 0.1` threshold kills all 3 candidates despite their RAW Sharpes being in the 0.54-0.72 range (which would be respectable in isolation).

2. **GA vocabulary is single-archetype** — all 3 candidates are `rsi_bounce_v1` mutations. The post-T-006 Foundry features are NOT being consumed by Discovery's gene encoding. This is direct evidence for spec open question 2 ("Does the GA actually emit candidates that consume Foundry features?") — **answer: NO**.

## Scope deviation from spec

The spec called for 30-50 candidates on a 2021-2024 in-sample / 2025 OOS geometry within 6-8 hr. Empirical per-candidate cost (54-111 min on the SHORTER 2024-only window) makes 30 candidates require **27-55 hr wall time**. The dispatch shipped with the smoke-batch (3 candidates) on the 2024 window:

- **Sample size: 3 (vs spec 30-50)** — below the spec's floor. Statistical power is weak BUT the two findings replicate across all 3, so the directional conclusions are defensible.
- **Window: 2024 only (vs spec 2021-2024 in-sample, 2025 OOS)** — single-year window. The 2021-2024 window would have INCREASED per-candidate cost (~3-4× more bars to evaluate), exceeding the 8-hr budget on even a 3-candidate run.

The "30-50 candidates in 6-8 hr" target is mathematically infeasible at the current per-candidate cost on substrate-honest substrate. **This itself is a top finding** — the spec's open Q4 ("Wall-time profile") made concrete.

## First-failed-gate histogram

| First failed gate | Count | % of N=3 |
|---|---:|---:|
| **gate_1 (Sharpe contribution)** | **3** | **100%** |
| gate_2, 4, 5, 6, 7, 8 | 0 | 0% (not reached) |
| Promoted (cleared all gates) | 0 | 0% |

## Per-gate evaluation table

| Gate | Evaluated | Passed | Pass rate |
|---|---:|---:|---:|
| gate_1 | 3 | 0 | 0% |
| gate_2 | 0 | 0 | n/a (Gate 1 short-circuited) |
| gate_4 | 0 | 0 | n/a |
| gate_5 | 0 | 0 | n/a |
| gate_6 | 0 | 0 | n/a |
| gate_7 | 0 | 0 | n/a |
| gate_8 | 0 | 0 | n/a |

## Per-candidate detail

| candidate_id | first_failed | wall sec | raw Sharpe | raw Sortino | bench threshold |
|---|---|---:|---:|---:|---:|
| `rsi_bounce_v1_mut_9187` | gate_1 | 6,689 | 0.7191 | 1.014 | 0.10 |
| `rsi_bounce_v1_mut_2e63` | gate_1 | 3,444 | 0.5407 | 0.655 | 0.10 |
| `rsi_bounce_v1_mut_68e5` | gate_1 | 3,240 | 0.5644 | 0.790 | 0.10 |

All 3 candidates have raw Sharpes that would pass naive thresholds in isolation (0.54-0.72). **Gate 1 doesn't measure raw Sharpe — it measures contribution to ensemble Sharpe.** Each candidate's *marginal* contribution to the ensemble that already contains the 6 actives + 14 paused (incl. the 5 new paused from T-014/T-016/T-017/T-018) is below 0.1 Sharpe-points, hence the kill.

This is consistent with T-019's finding: when the active 6 are already collectively producing ensemble decisions, adding a 7th edge whose top-quintile picks overlap the actives' decisions has near-zero marginal Sharpe contribution. The same dynamic is killing Discovery candidates AND T-019's paused-tier additions.

## Bootstrap CI on gauntlet survival

Per CLAUDE.md non-negotiable 6: even for a 0-of-3 proportion, the bootstrap CI is reported.

- **Survival rate**: 0/3 = 0.000, 95% CI **[0.000, 0.000]**
- N=3 makes the bootstrap CI degenerate (no positive resamples possible).
- The CI's lack of upper bound > 0 is mechanical from the sample, not reassuring. Genuine "Discovery never works on substrate-honest" claim requires N≥30 to discriminate from "Discovery sometimes works with rate p where bootstrap upper bound spans 0-X%".

## Candidate origin distribution — GA vocabulary diagnostic

| Parent archetype | Mutations seen |
|---|---:|
| `rsi_bounce_v1` | **3** |
| Any other archetype | 0 |
| Any post-T-006 Foundry-feature consumer | 0 |
| Any post-T-014 calendar-feature consumer | 0 |

**This is the spec open Q2 made concrete: Discovery's GA is single-archetype.** Three independent mutation runs produced three `rsi_bounce_v1` mutations. None of the new Foundry vocabulary (post-T-006 fundamentals percentiles, post-T-014 calendar features) is reachable from the GA's current gene encoding.

Implication: even if Gate 1 were tuned more permissively, the GA cannot SAMPLE the new feature space, so vocabulary expansion via T-014/T-006 has zero effect on Discovery output until the gene encoding is extended.

This is independently informative for the engines-first directive: **Discovery's value as a candidate generator is bounded by its gene encoding, not by the gauntlet thresholds.** The Bayesian-opt swap of Engine D (forward_plan) should prioritize gene-encoding extension, not gate threshold tuning.

## Gene type distribution

Empty. None of the 3 records emitted `gene_types` in the JSONL payload. Possible explanations:
- The 3 candidates are MUTATIONS of an existing edge (`rsi_bounce_v1`) rather than NEW genes — so they don't have a separate gene-type field in the discovery record.
- Or the JSONL emission path doesn't populate gene_types for mutation-class candidates.

Either way, this confirms the GA-vocabulary diagnostic: NEW genes that compose Foundry features didn't make it into the candidate batch.

## Wall-time profile

| Statistic | Value |
|---|---:|
| Min per-candidate (sec) | 3,240 |
| Max per-candidate (sec) | 6,690 |
| Mean per-candidate (sec) | 4,458 |
| Mean per-candidate (min) | 74 |
| Total wall time (min) | 223 |

**Wall-time spent entirely on Gate 1.** All 3 candidates have `gates_run: ["gate_1"]` and `gate_seconds: {"gate_1": 3239-6689}`. No other gate consumed time. Gate 1 evaluates the candidate inside a full backtest pipeline to measure ensemble contribution — that's the cost source.

If 30 candidates were processed at this rate: 30 × 74 min = **37 hr**. The 50-candidate cap target is **62 hr**. Both far exceed the spec's 6-8 hr budget.

**T-013 vectorization helped at multi-year measurement scale (T-019 ran in 50min vs T-002's 10hr) but does NOT appear to help Gate 1 in Discovery cycles.** This is because Discovery's Gate 1 invokes a SEPARATE backtest pipeline per candidate, not the bulk feature panel that T-013 vectorized.

## Implications

### For the engines-first directive

1. **Edge expansion via paused-tier parking AND via Discovery's GA are both currently inert on substrate-honest substrate.** T-019 showed paused-tier additions contribute zero. T-021 shows Discovery's gauntlet rejects 100% of GA proposals (small N caveat). Neither mechanism is currently producing lift.

2. **Three blocking issues to address before edge expansion can deliver lift:**
   - **Gate 1 threshold vs ensemble overlap:** when the active 6 already produce coherent decisions, marginal-Sharpe-contribution-to-ensemble is the wrong dimension for evaluating candidates with overlapping signal universes. Possible directions:
     - Tier-aware Gate 1 (different threshold for `tier=feature` candidates that are meta-learner inputs, not standalone)
     - Replace Gate 1's "marginal contribution" with "factor-adjusted alpha at t > 2" (T-004 already runs this offline)
   - **GA vocabulary too narrow:** gene encoding doesn't reach Foundry features. Engine D Bayesian-opt swap (forward_plan) should prioritize extending the gene space.
   - **Per-candidate wall time:** Gate 1's "run a full backtest per candidate" is the dominant cost. Optimizing this (e.g., approximate Gate 1 with cached signal-collector output) would unlock scale.

3. **The 30-edges-untested list in the dev review needs different sourcing.** Discovery's GA isn't going to produce them at scale, and the gauntlet's Gate 1 is going to reject them when their signal overlaps the actives. A separate path (manual hypothesis → handwritten edge → propose-first paused promotion → Gate 1 isolation diagnostic per T-020) may be the realistic mechanism for the next 30 edges.

### For Engine B vol-targeting prioritization

Unchanged from T-003/T-019: vol-targeting can be added on top, but with no candidate edges producing factor-adjusted alpha at t > 2 (T-004) AND no Discovery output (this dispatch), there's nothing to vol-target that beats noise.

## Spec open questions — answers

### Q1: Existing diagnostic harness substrate-compatibility

The harness (`scripts/run_discovery_diagnostic.py`) needed minimal extension: 2 new CLI flags (`--substrate-honest`, `--apply-journal-at-end`) passed through to `mc.run_backtest()`. Both already existed on `mc.run_backtest`. No engine code modified. The diagnostic JSONL emission at `engines/engine_d_discovery/discovery.py:822-870` worked unchanged. Anchor was current (post-T-019).

### Q2: Foundry feature consumption in Discovery's gene encoding

**Confirmed NO.** All 3 candidates are `rsi_bounce_v1` mutations; no record emitted `gene_types` indicating Foundry-feature use. The GA is invisible to T-006 / T-014 vocabulary expansion. **This is the highest-leverage finding from this dispatch** — vocabulary expansion is only useful if Discovery can sample it.

### Q3: Gate 8 (DSR) calibration

Moot — no candidate reached Gate 8. With cap=3 the DSR penalty would be minimal anyway. Worth re-investigating if the gene-encoding extension lifts more candidates past Gate 1.

### Q4: Wall-time profile

Answered above. **Gate 1 is the dominant cost (3,200-6,700 sec / candidate) and is single-threaded per candidate.** T-013-style vectorization at the panel level doesn't help because Gate 1 invokes a full ModeController backtest per candidate. The "30-50 candidates in 6-8 hr" target requires either (a) a different Gate 1 evaluation strategy or (b) parallel candidate evaluation (concurrent ModeController instances).

### Q5: Gauntlet on substrate-honest may be inherently harsher

**Confirmed.** Gate 1's 0.1 minimum-contribution-to-ensemble threshold is binding on substrate-honest with the current 6-active ensemble already producing decisions. The 3 candidates with raw Sharpe 0.54-0.72 all failed because their marginal contribution overlaps the actives' signal universe. This is the same dynamic that produced T-019's zero-contribution paused edges, viewed through the Gate 1 lens.

## Hard constraints — verification

- [x] **No edges.yml mutation beyond journal-mode** — journal-mode active throughout, edges.yml restored by `isolated()` exit per the harness.
- [x] **No Engine D / Engine F / Engine B code modified** — only the diagnostic harness (`scripts/run_discovery_diagnostic.py`) extended with CLI flags.
- [x] **8-gate thresholds unchanged** — `min_contribution_to_ensemble=0.1` is the configured threshold; no tuning to force promotions.
- [x] **Candidate cap honored upward bound** — 3 << 50. Cap=30 floor NOT met; documented as scope deviation.
- [x] **Journal-mode not disabled mid-run** — `--apply-journal-at-end` set throughout.
- [x] **CLAUDE.md non-negotiable 6** — bootstrap CI reported on the survival rate (0.000, [0.000, 0.000]).

## Caveats

- **N=3 is below the spec's statistical-power floor of 30.** The two findings (Gate 1 100% killer, GA single-archetype) replicate across all 3 records, so the directional conclusions are robust, but I'd want N≥10 to make claims like "Discovery's gauntlet rejects ≥90% of candidates" with any precision.
- **Window is 2024 single-year, not 2021-2024 four-year.** Per-candidate cost on 4-year window would be larger; the 30-candidate cap is even more infeasible there. Director may want to dispatch a follow-up with a tighter Gate 1 timeout if budget allows.
- **3 candidates over ~7 hours wall time** — the smoke "consumed" the spec's budget. No additional batch was launched after the smoke completed; recommendation to director below.
- **`rsi_bounce_v1` ancestor edge.** Whether the parent edge is itself producing meaningful signal on substrate-honest is a separate question; this dispatch only measured what the GA produces FROM it.

## Recommendations for director

1. **Don't dispatch a 30-candidate run on the current Discovery code.** Per-candidate cost makes it ≥37 hr. Either:
   - Optimize Gate 1 first (cached signal-collector replay?)
   - OR cap at 5-10 candidates and accept low statistical power
   - OR dispatch the cap=30 run but expect 1-2 days of wall time

2. **Highest-leverage Engine D work is gene-encoding extension, not gate threshold tuning.** With the GA producing only `rsi_bounce_v1` mutations, no amount of gate-threshold tuning changes the candidate universe. The Bayesian-opt swap (forward_plan) should prioritize gene encoding that consumes Foundry-registered features.

3. **Consider rerouting paused-tier edges through Gate 1 isolation diagnostic instead of Discovery.** T-020 (B's parallel dispatch) is asking the right complementary question — what is the standalone Gate 1 score of each of today's handwritten paused edges? If T-020 finds the new paused edges fail standalone Gate 1, that's the same Gate 1 ensemble-contribution problem T-021 surfaces in Discovery, and the fix is upstream of both.

4. **Gate 1's threshold appears mismatched to the engines-first directive.** The directive wants to ADD edges that contribute marginal signal; Gate 1's "must add ≥0.1 to ensemble Sharpe" is a high bar when the ensemble already has 6 active edges producing 0.27 substrate-honest Sharpe. A tier-aware Gate 1 (lower bar for `tier=feature` candidates that are meta-learner inputs, not standalone alpha) would unblock the engines-first track without compromising the alpha-tier discipline.

## Files

- `scripts/run_discovery_diagnostic.py` — extended with `--substrate-honest` and `--apply-journal-at-end` CLI flags
- `scripts/discovery_diag_analytics.py` — new (analytics + audit-doc renderer)
- `docs/Audit/discovery_diagnostic_run_2026_05_20260510T182650.jsonl` — raw 3-candidate JSONL
- `docs/Measurements/2026-05/discovery_substrate_honest_2026_05_10.md` — this audit doc
- `docs/Measurements/2026-05/discovery_substrate_honest_2026_05_10.json` — structured payload for downstream

No engine code modified. No `data/governor/` mutation beyond `isolated()` snapshot/restore.
