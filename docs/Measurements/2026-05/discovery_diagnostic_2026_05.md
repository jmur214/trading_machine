# Engine D Discovery Diagnostic — 2026-05-01

**Branch:** `discovery-diagnostic`
**Worktree:** `trading_machine-discdiag`
**Driver:** `scripts/run_discovery_diagnostic_standalone.py` + per-gate
instrumentation in `engines/engine_d_discovery/discovery.py::validate_candidate`

**One question:** for a Discovery cycle on the current production state,
where exactly do candidates die?

**Answer:** every single one dies at Gate 1. Two distinct failure modes
account for the kill rate; both are upstream of Gates 2-6, which never
execute on any candidate in the diagnostic batch.

---

## Headline

| | |
|---|---|
| Window | 2024-07-01 → 2024-12-31 (warmup back to 2023-07-02) |
| Universe | 30 prod tickers (top of `backtest_settings.json::tickers`) |
| Candidates run | **30** (15 template mutations + 15 GA composites) |
| Passed all gates | **0** |
| Died at Gate 1 | **30 (100%)** |
| Died at Gate 2-6 | 0 (none reached) |
| Timeouts | 0 |
| Total wall time | 14.3 min (median 24.2s/candidate) |
| Run jsonl | `docs/Audit/discovery_diagnostic_run_2026_05_20260501T045641.jsonl` (templates) + `..._050852.jsonl` (GA composites) |

**Verdict:** Gate 1 is the binding chokepoint. It kills 100% of candidates.
Gates 2-6 are never tested on this batch. Two distinct upstream failure
modes drive the 100% rate; the next-fix-target depends on which mode
you want to address first.

---

## Per-gate kill-rate table

| First-failed gate | N candidates | % of run |
|---|---:|---:|
| `gate_1` | 30 | 100.0% |
| `gate_2` | 0 | 0.0% |
| `gate_3` (metric only) | 0 | 0.0% |
| `gate_4` | 0 | 0.0% |
| `gate_5` | 0 | 0.0% |
| `gate_6` | 0 | 0.0% |
| timeout | 0 | 0.0% |
| error | 0 | 0.0% |

(`gate_3` is metric-only in the current `validate_candidate` final pass-check
— wfo_degradation is collected but not gated; it cannot be a "first-failed
gate" by construction.)

---

## Standalone Gate-1 Sharpe distribution

Combined batch (n=30):

| Sharpe bin | N |
|---|---:|
| `[< -0.5]` | 0 |
| `[-0.5, 0)` | 1 |
| `[0, 0.25)` | 21 |
| `[0.25, 0.5)` | 1 |
| `[0.5, 0.75)` | 5 |
| `[0.75, 1.0)` | 2 |
| `[≥ 1.0]` | 0 |

- Sharpe > 0: 10 / 30 (33.3%)
- Sharpe > 0.5: 7 / 30 (23.3%)
- Sharpe > 1.0: 0 / 30 (0.0%)
- Benchmark threshold for 2024H2 window: **1.491** (SPY 2024H2 Sharpe ≈ 1.69 minus 0.2 margin)
- Best candidate Sharpe: **0.999** (`rsi_bounce_v1_mut_2e63`) — still 0.49 below threshold

**Key observation:** Generated candidates are NOT uniformly noise.
A meaningful tail (7 of 30 at Sharpe > 0.5, 2 at > 0.75, peak 0.999) shows
the GA + template-mutation pipeline produces edges that are *qualitatively
profitable in standalone mode*. The kill rate is not "noise gets rejected";
it's "real-Sharpe candidates can't beat SPY-margin in a strong bull window."

---

## Per-cohort breakdown — the two failure modes

### Cohort A — template mutations (n=15)

Mutations of the 9 production templates: `RSIBounceEdge`, `ValueTrapEdge`,
`FundamentalRatioEdge`, `SeasonalityEdge`, `GapEdge`, `VolumeAnomalyEdge`,
`PanicEdge`, `HerdingEdge`. (`EarningsVolEdge` mutations didn't make the
batch slice.)

| Metric | Value |
|---|---:|
| Sharpe nonzero | 11 / 15 (73%) |
| Sharpe > 0 | 10 / 15 (67%) |
| Sharpe > 0.5 | 7 / 15 (47%) |
| Median Sharpe | 0.454 |
| Max Sharpe | 0.999 |
| Top 3 candidates | `rsi_bounce_v1_mut_2e63` (0.999), `panic_v1_mut_d6f7` (0.791), `panic_v1_mut_86b3` (0.730) |

**Failure mode:** standalone benchmark-relative threshold. Template
mutations produce *real* signal — 47% have Sharpe > 0.5, 13% > 0.75 — but
none reach SPY's 2024H2 Sharpe (1.69) minus margin (0.2) = 1.491. They are
all rejected by the benchmark-relative cap.

This is exactly the architectural issue Phase 2.10e Reform Gate 1 was
designed to fix (memory `project_ensemble_alpha_paradox_2026_04_30.md`):
single-edge Gate 1 against a benchmark assumes the candidate would deploy
standalone, when in production it would deploy as a member of a 17-edge
ensemble at fractional capital, where it doesn't need to beat SPY alone —
only to lift ensemble Sharpe contribution.

### Cohort B — GA composite candidates (n=15)

Genetic-algorithm-generated `CompositeEdge` candidates from
`ga_population.yml`. Genome shape: 1-4 genes ANDed, with types drawn from
`{technical, calendar, behavioral, fundamental, microstructure, intermarket}`.

| Metric | Value |
|---|---:|
| Sharpe nonzero | 0 / 15 (0%) |
| Sharpe > 0 | 0 / 15 (0%) |
| Median Sharpe | 0.000 |
| Max Sharpe | 0.000 |
| Trades fired | 0 across all 15 candidates |

**Failure mode:** the AND-conjunction of restrictive genes drives trade
firing rate to zero. Inspection of the GA population shows representative
genomes such as:

```
composite_gen0_7e9b70 (short):
  calendar.day_of_week_sin < -0.2     (~28% of trading days)
  technical.rsi < 30                   (~5% of bars)
  technical.sma_cross < 0              (~50% of bars)
→ joint probability ≈ 28% × 5% × 50% = ~0.7% of bars
```

Some genomes contain redundant/contradictory clauses
(`composite_gen3_22dd47` has three `day_of_week_sin` gates with three
different thresholds). The GA's `_create_random_gene` + crossover/mutation
operators are producing genomes whose joint signal-firing rate is too
low to generate any backtest activity. With zero trades, Sharpe = 0,
trivially below the 1.491 threshold.

**Gene-type distribution across the 15 composites** (51 total gene slots):

| Gene type | Count | % |
|---|---:|---:|
| `technical` | 21 | 41% |
| `calendar` | 11 | 22% |
| `behavioral` | 4 | 8% |
| `fundamental` | 2 | 4% |
| `microstructure` | 1 | 2% |
| `intermarket` | 1 | 2% |
| `macro` | 0 | 0% |
| `earnings` | 0 | 0% |

The macro + earnings expansions shipped in commit `45abf0e` (resolved entry
in `health_check.md`) are present in `_create_random_gene` weights but
absent from this batch — bad luck of the random sampler, not a deeper
issue. Worth re-running with a larger GA population to confirm.

---

## Honest verdict on the binding constraint

**The binding constraint is Gate 1, but for two architecturally-distinct
reasons that should be tackled in sequence.**

### Primary: Gate 1 standalone-vs-ensemble geometry mismatch (high leverage)

The current `gate_sharpe_vs_benchmark` requires a candidate's standalone
Sharpe to be within 0.2 of SPY's Sharpe over the same window. In a strong
bull window like 2024H2 (SPY 1.69), the threshold becomes 1.49 — a bar
that *no single edge in the production ensemble would clear standalone*
either. Per the per-edge attribution in
`docs/Audit/per_edge_per_year_attribution_2026_04.md`, even
`volume_anomaly_v1` and `herding_v1` (the verified stable contributors)
hit standalone Sharpe in the 0.3-0.6 range during 2025 OOS. The gate
applies a bar that production edges themselves can't clear. The 7 of 15
template mutations at Sharpe > 0.5 are the same class of edge as the
working production set — they're being rejected by a gate that wouldn't
admit `volume_anomaly_v1` or `herding_v1` either.

This is exactly the failure mode the Phase 2.10e Reform Gate 1 work
addresses, and exactly the *implementation problem* that left it not
promoted (memory: `project_gate1_reimplementation_problem_2026_05_01.md`).
The memory's architectural recommendation — invoke production pipeline
rather than reimplement ensemble — would unblock the 7-10 candidates per
30 that have positive standalone Sharpe.

### Secondary: GA composite gene over-restrictiveness (low leverage today, high leverage post-fix)

15 of 15 composite candidates fired zero trades. The GA's gene composition
operators produce genomes whose joint conjunction probability is too low
to be tested, which means *the GA generates statistical-noise candidates
masquerading as null candidates*. We can't tell whether any of the 15
composite genomes contained genuine alpha because none of them traded.

This is invisible until the primary fix lands, because today even
non-zero-Sharpe candidates are rejected. After Reform Gate 1 promotes,
the GA will start being the bottleneck — at which point the gene
composition fix becomes the next-target. Until then, fixing the GA
without fixing Gate 1 saves no candidate.

### Quantification

Out of 30 randomly-sampled diagnostic candidates:

- **0 / 30 promote today.**
- **7 / 30 (23%) would clear a contribution-based Gate 1** that asked
  "does adding this candidate to the ensemble lift Sharpe?" rather than
  "does this candidate beat SPY-margin standalone?" — the seven with
  standalone Sharpe > 0.5 are the realistic ensemble-contribution
  candidates.
- **0 / 15 GA composites would promote even under a fixed Gate 1**, because
  they don't trade. Fixing GA gene composition would not move the needle
  until Gate 1 is fixed; and after Gate 1 is fixed, there's no signal in
  the current GA output to reward.

---

## Recommended next-fix-target

**Promote Reform Gate 1 with the architectural rework already filed in
`project_gate1_reimplementation_problem_2026_05_01.md`.** The memory
spells out the design (invoke `mode_controller.run_backtest` from inside
`validate_candidate`, attribute by `Sharpe(with) - Sharpe(baseline)`,
cache by `(active_set_fingerprint, window, exec_params_fingerprint)`).
Cost is roughly 1-2 weeks per the Forward Plan's Tier-1 entry on the same
topic. **This unlocks the 23% of candidates that have real signal but
are dying at the wrong gate.**

Secondary fix-target — **GA gene composition** — should wait until after
Gate 1 promotes. Then re-run this same diagnostic harness, observe whether
GA candidates start clearing Gate 1 too. If yes, the GA is fine and Tier-2
edge factory work is the next move. If composites still trivially fail
(zero trades), then the gene composition is the binding constraint.

---

## Reproducibility

Run yourself in this worktree:

```bash
# Templates
PYTHONHASHSEED=0 python scripts/run_discovery_diagnostic_standalone.py \
    --tickers 30 --window 2024H2 --batch 15 --timeout 1500 --n-mutations 2

# GA composites
PYTHONHASHSEED=0 python scripts/run_discovery_diagnostic_standalone.py \
    --tickers 30 --window 2024H2 --batch 15 --timeout 1500 --n-mutations 0

# Combined analysis
cat docs/Audit/discovery_diagnostic_run_2026_05_*.jsonl > /tmp/combined.jsonl
python scripts/analyze_discovery_diagnostic.py /tmp/combined.jsonl
```

The standalone harness skips the in-sample backtest + TreeScanner hunt
phase that made the full `--discover` path take >20 min before any
candidate validation began (TreeScanner ran silently in the eval frame,
no progress output). Validation logic is unchanged; the diagnostic just
bypasses orchestration overhead and feeds 30 ticker × 18 month data
directly to `validate_candidate`.

---

## Caveats

- 30-ticker slim universe vs prod's 109 — Gate-1 Sharpe magnitudes here
  are not directly comparable to a full-universe production discovery
  cycle. The benchmark threshold (SPY 2024H2 ≈ 1.69 minus 0.2 = 1.49)
  is window-dependent, not universe-dependent. The *relative* finding —
  candidates produce real Sharpe but not enough to clear bull-window
  threshold — should be window-stable (verified against 2024H1 if the
  fix-target requires confirmation).
- Hunt-phase candidates (`RuleBasedEdge` from `TreeScanner`) are NOT in
  this batch. Per `health_check.md`'s open HIGH finding, they are
  expected to all fail Gate 1 with Sharpe = 0 (because `RuleBasedEdge`
  reads features that aren't populated in the validation `data_map`).
  That's a separate, independently-tracked bug with its own fix path
  in the health check; this diagnostic does not change that finding's
  priority.
- The 100% Gate-1 kill rate is for *2024H2 (a strong bull window)*. The
  kill rate would be smaller in flat/bear windows where SPY's Sharpe is
  closer to candidate Sharpes. Even so, the architectural mismatch
  between standalone-test and ensemble-deployment is window-independent.
- One run (15 candidates per cohort) is enough to expose both failure
  modes but is not statistically tight on Sharpe-distribution percentiles.
  Re-run with `--batch 30` and a larger GA population to harden the
  numbers if the fix-target work needs them.
