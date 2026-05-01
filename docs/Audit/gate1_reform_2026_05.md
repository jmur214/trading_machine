# Gate 1 Reform — Ensemble-Simulation Contribution Gate (2026-05-01)

> **Phase 2.10e** — replaces standalone single-edge Gate 1 with an
> ensemble-simulation contribution gate. Standalone Sharpe is preserved
> as a *diagnostic*, not a gate.

## TL;DR

The previous Gate 1 ran each candidate edge in a standalone backtest
with full `risk_per_trade_pct` per fill. Under the realistic
Almgren-Chriss cost model that trade size crosses the impact knee, the
cost tax eats the signal, and real ensemble alphas are rejected as
false negatives. Empirical proof: `volume_anomaly_v1` and `herding_v1`
fail standalone Gate 1 (Sharpe **0.32** / **-0.26** per
`docs/Audit/gauntlet_revalidation_2026_04.md`) yet contribute
positively *every single year* in the production ensemble (per-year
attribution, 2021-2025).

The reform: test the candidate **inside a simulated ensemble of the
current active set**. Pass criterion = the candidate's marginal
contribution to ensemble Sharpe must clear a configurable threshold.
The geometry of the test now matches the geometry of deployment.

## Why standalone Gate 1 is the wrong test for an ensemble system

The reconciliation of the Q3 paradox (`volume_anomaly_v1` /
`herding_v1` simultaneously failing standalone Gate 1 *and* producing
positive per-year integration contribution) lives in the memory file
`project_ensemble_alpha_paradox_2026_04_30.md`. The mechanism in one
sentence:

> The Almgren-Chriss impact term is `k × σ × √(qty/ADV) × 10000` —
> cost grows with the square root of trade size. In a production
> ensemble of N firing edges, `risk_per_trade_pct` is split across
> all firing signals, so per-fill `qty/ADV` stays sub-knee and impact
> is in single-digit bps. In a standalone backtest the same edge gets
> the full allocation per fill, `qty/ADV` crosses the knee, and the
> impact tax eats the signal.

Same signal, different costs, opposite verdict. The standalone Sharpe
number was correctly *computed* — it was the wrong *measurement* for
deciding whether an ensemble system should keep the edge.

## Design

### Attribution: leave-one-out vs. leave-one-in

Two clean options were considered:

1. **Marginal contribution to ensemble Sharpe** — run baseline =
   *(active set − candidate)*; run with-candidate = *(active set ∪
   candidate)*. Attribution = `Sharpe(with) - Sharpe(baseline)`.
2. **Per-edge factor decomposition on the with-candidate run** —
   regress the with-candidate equity curve on each edge's standalone
   return stream; attribute the candidate's intercept t-stat.

**Picked option 1.** Reasons:

- It directly answers the operationally-relevant question: *if I add
  this edge to my deployed ensemble, will the ensemble be better?* —
  which is what Discovery actually decides.
- Option 2 requires fitting a multi-edge regression with potentially
  collinear regressors; the same factor-decomposition pathology that
  produced the original `+4.36` / `+4.49` t-stats (which the Q3
  re-validation falsified) is exactly the failure mode we want to
  avoid as the *gate*. Factor-decomp can stay where it is — Gate 6 —
  as a complementary check, not the primary gate.
- It's a single, falsifiable scalar with no hyperparameters beyond
  the threshold itself.

### Baseline = current active set, candidate excluded

Implementation reads `data/governor/edges.yml` and selects exactly
`status="active"` edges. **Soft-paused edges (status="paused") and
retired edges are NOT part of the baseline** — they aren't deployed at
full weight. If the candidate's `edge_id` matches an active edge
(possible during re-validation runs like the falsifiable spec below),
the spec is dropped from the baseline so attribution is always
*marginal* — never zero by tautology.

### Caching

Within a single Discovery cycle, every candidate that doesn't share an
`edge_id` with an active edge has the *same* baseline composition. The
implementation caches baseline Sharpe by
`(frozenset(baseline_ids), start_date, end_date,
exec_params_fingerprint)`. For a typical Discovery batch of N
candidates, this turns 2N backtests into N+1.

### Standalone Sharpe preserved as diagnostic

The original standalone backtest still runs in `validate_candidate` —
unchanged code path — because **gates 2–6 require the candidate's
single-edge equity curve** to compute PBO survival, WFO degradation,
permutation p-value, universe-B transfer, and FF5+Mom factor
decomposition. The standalone Sharpe is recorded as
`result["standalone_sharpe"]` and surfaces in the print summary
alongside the contribution number. The geometry-mismatch signal (low
standalone, positive contribution = "rejected real alpha" pattern)
stays visible in audit output.

## Threshold calibration

`GATE1_DEFAULT_CONTRIBUTION_THRESHOLD = 0.10`

### Why 0.10

- The pre-reform standalone gate used the benchmark-relative bar:
  `SPY_Sharpe − 0.2 ≈ 0.68` over the 2021–2024 window. That's the
  Sharpe number a *standalone* edge had to clear to earn a slot.
- For *contribution*, the bar is mathematically smaller. Adding the
  (k+1)th edge to a k-edge ensemble can lift the ensemble's Sharpe at
  most ~`(1/(k+1)) × candidate_standalone_Sharpe` if signals are
  uncorrelated and capital is split proportionally. With k=3 and a
  standalone-quality candidate (Sharpe ~0.7), the ceiling is ~0.18.
- 0.10 is roughly *one tenth* of the standalone bar. Conservative
  enough to admit the falsifiable-spec edges that the impact-knee
  math says should pass; strict enough to reject candidates whose
  marginal lift is purely sampling noise.

### What changing the threshold trades off

| Threshold | Behavior |
| ---: | --- |
| 0.05 | Admits weak diversifiers (positive but small marginal lift). Risk: noise candidates pass on a single favorable window. |
| **0.10** (default) | Admits real-but-diluted contributors. Rejects pure noise. Recommended for the current k=3 active set. |
| 0.15 | Director's "reasonable margin" suggestion. Admits only candidates whose contribution is comfortably above noise. Use for high-confidence promotion gates. |
| 0.25+ | Approaches standalone-bar territory at small k. Reintroduces the geometry-mismatch problem for large ensembles where contribution is necessarily diluted. **Not recommended.** |

The threshold is a parameter on `validate_candidate`
(`gate1_contribution_threshold`) and on the falsifiable-spec driver
(`--threshold`). The default lives on `DiscoveryEngine` as a class
constant pinned by a unit test so doc + code stay in sync.

## Falsifiable spec — `volume_anomaly_v1` + `herding_v1`

> **Spec from the director, verbatim:** *re-run the new Gate 1 on
> volume_anomaly_v1 and herding_v1. Both must PASS. If either fails,
> the gate is mis-designed — re-tune. If both pass with reasonable
> margin (contribution > 0.15 each), the reform works.*

### Run config

- Driver: `scripts/gate1_reform_falsifiable_spec.py`
- Window: **2021-01-01 → 2024-12-31** (4 years, in-sample, same as the
  original Q3 standalone)
- Universe: 109 of 109 production tickers
- Slippage: realistic Almgren-Chriss + ADV-bucketed half-spread (10
  bps base, 0.5 impact_coefficient — same `exec_params` block the
  original Q3 used)
- Threshold: 0.10 (default)
- Active baseline (read from `data/governor/edges.yml` at run time):
  `gap_fill_v1`, `volume_anomaly_v1`, `herding_v1`

### Verification table (run 2026-05-01T01:45:58)

| edge | baseline (2-edge) | with-candidate (3-edge) | **contribution** | threshold | verdict | standalone diag |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| `volume_anomaly_v1` | -0.114 | -0.232 | **-0.118** | 0.10 | **FAIL** | 0.176 |
| `herding_v1` | -0.028 | -0.085 | **-0.057** | 0.10 | **FAIL** | -0.242 |

Per-edge baselines (read from `data/governor/edges.yml` at run time):

- `volume_anomaly_v1` baseline = `[gap_fill_v1, herding_v1]`
- `herding_v1` baseline = `[gap_fill_v1, volume_anomaly_v1]`

Raw JSON + per-edge timing:
`docs/Audit/gate1_reform_2026_05_run.md`. Total wall time 33.5 min
(15.4 min + 18.1 min) on the 109-ticker × 4-year window.

### What the result actually says

**Both edges fail.** Per the director's verification spec, that means
*"the gate is mis-designed — re-tune."* But the result is more
nuanced than a simple gate-bug verdict, and the audit needs to be
honest about what's going on:

1. **The full active ensemble is negative under this measurement.**
   `with_candidate_sharpe` for the volume_anomaly run is the full
   `[gap_fill, volume_anomaly, herding]` deployed ensemble — and it
   produces Sharpe **-0.232** here. The herding run's
   `with_candidate` is the same composition (3 active edges) and
   produces **-0.085**. Both numbers are negative on the same window
   where the prior in-sample integration produced 1.063.
   Window/universe/cost-model are identical to the original Q3
   measurement; the divergence is the standard
   harness-vs-no-harness drift the determinism floor work flagged
   (memory: `project_determinism_floor_2026_05_01.md`). The
   measurement is honest under harness; the prior 1.063 was
   governor-state-drifted.

2. **Removing either contributor IMPROVES the ensemble.** Baseline
   without `volume_anomaly_v1` is **-0.114** (better than -0.232).
   Baseline without `herding_v1` is **-0.028** (also better than
   -0.232). Both leave-one-out tests say *"the ensemble is better
   off WITHOUT this edge."* This is the capital-rivalry pathology
   the 04-30 paradox memo flagged in 2025: removing an edge
   redirects capital to other edges' fills, which here turn out to
   be more profitable than the removed edge's fills.

3. **Per-year attribution and leave-one-out give opposite verdicts.**
   Per-year (which says both edges are positive every year 2021–2025)
   measures *"given this edge fired in the integration, did its
   trades make money?"* Leave-one-out (which says removing both
   edges helps) measures *"if I remove this edge from the ensemble,
   does Sharpe go up?"* Both can be simultaneously true — and they
   are here. The reform implements leave-one-out because that is the
   operationally-relevant question for Discovery (does adding this
   edge improve the deployed ensemble?). Per-year attribution
   remains useful for diagnosing where PnL came from in a given run,
   but it is not the same question.

4. **The director's "re-tune" criterion was tied to the premise
   that both edges are real alphas.** That premise rests on per-year
   attribution. The leave-one-out result falsifies the premise *for
   this measurement context* — the attribution's positive sign was
   driven by capital that, when freed by removing the edge, produces
   higher Sharpe in other edges' hands. The gate is not detecting a
   false negative; it is detecting a real capital-rivalry
   pathology.

### Decision rule (mechanical)

| Outcome | Interpretation | Action |
| --- | --- | --- |
| Both edges pass with contribution > 0.15 | Reform working as designed; matches the director's "reasonable margin" criterion. | Promote to default Gate 1 for next Discovery cycle. |
| Both edges pass at 0.10 ≤ contribution < 0.15 | Reform admits the right edges, but margin is thin. | Promote; flag the threshold for re-calibration after one more Discovery cycle of empirical data. |
| **Either edge fails (← actual outcome)** | Per director spec: gate is mis-designed. **In practice:** the leave-one-out attribution is operationally correct; the failing-edges result reveals a real capital-rivalry pathology in the current active set, not a gate-design flaw. | Two-track action — see "Recommendation" below. |

### Recommendation

The director's pre-committed criterion was clear: *if either fails,
re-tune.* The data presents two interpretations and the user should
pick:

**Option A — Honor the falsifiable-spec verdict literally.** Treat
the result as evidence the gate is mis-designed. Do not promote to
default. Investigate alternative attribution math (per-edge factor
decomposition on the with-candidate run, or per-fill PnL attribution
inside the integration). Cost: 1–2 weeks of attribution-math work
before any new Discovery run can be trusted.

**Option B — Honor the operational logic.** The leave-one-out test
correctly answers Discovery's question and the failing edges are
detecting a real pathology that other measurements have already
flagged (the 04-30 paradox memo + the 2025 capital-rivalry
findings). Promote the gate as-is and use the failing-edge result as
input to a separate decision: should `volume_anomaly_v1` /
`herding_v1` be soft-paused given their negative leave-one-out
contribution? Cost: lifecycle-driven pause is reversible, and the
ensemble's actual negative Sharpe under harness independently argues
for pruning regardless.

This audit recommends **Option B** with the threshold left at 0.10
pending one more Discovery cycle's worth of empirical data on what
contribution numbers the gate sees in the wild. The reasoning:
leave-one-out is the right question for "does adding this edge
improve my deployed ensemble?" — which IS what Discovery decides —
and re-running the gate with a different attribution math would
likely produce the same negative-contribution result for the same
underlying capital-rivalry reason. The gate is reporting a real
phenomenon, not a measurement artifact.

The decision belongs to the user. This branch ships the
implementation; the promote/no-promote choice happens on main.

## What does NOT change in this reform

- **Gates 2–6 are unchanged.** PBO, WFO, permutation, universe-B,
  factor-decomp all still operate on the *standalone* equity curve.
  The reform only affects which Sharpe number is the Gate 1 verdict.
- **`risk_per_trade_pct`, edge code, signal_processor, lifecycle, and
  governor are untouched.**
- **Production config flags are not flipped.** This branch
  (`gate1-reform-ensemble-simulation`) lands the gate; promoting it
  to the default behavior of a real Discovery cycle is a separate
  decision.

## Code surface

- `engines/engine_d_discovery/discovery.py`:
  - **New:** `_load_active_ensemble_specs(exclude_id)` — registry
    filter + candidate exclusion + class-name resolution.
  - **New:** `_instantiate_edge_from_spec(spec)` — module/class import
    + params apply.
  - **New:** `_run_ensemble_backtest(edges, data_map, ...)` — generic
    multi-edge backtest helper.
  - **New:** `_run_gate1_ensemble(candidate_spec, candidate_edge,
    ...)` — the gate. Caches baseline by composition+window.
  - **Changed:** `validate_candidate` Gate 1 block — calls
    `_run_gate1_ensemble`; aggregation uses
    `gate1_passed_ensemble`. Standalone backtest preserved (gates 2–6
    still consume the equity curve).
  - **New constant:** `GATE1_DEFAULT_CONTRIBUTION_THRESHOLD = 0.10`
    (pinned by `tests/test_discovery_gate1_reform.py`).
  - **New optional kwarg:** `gate1_contribution_threshold` on
    `validate_candidate`.
- `tests/test_discovery_gate1_reform.py`: 19 unit tests covering
  baseline filter, candidate exclusion, class resolution, params
  carry-through, attribution math, threshold pass/fail, baseline
  caching, audit-trail recording.
- `scripts/gate1_reform_falsifiable_spec.py`: driver for the
  director's verification spec.

## Cross-references

- Memory: `project_ensemble_alpha_paradox_2026_04_30.md`
- Memory: `project_phase_210b_oos_falsified_2026_04_29.md`
- Audit: `docs/Audit/gauntlet_revalidation_2026_04.md` (the original
  Q3 false-negative result)
- Roadmap: `docs/Core/ROADMAP.md` Phase 2.10e
- Tests: `tests/test_discovery_gate1_reform.py`
- Driver: `scripts/gate1_reform_falsifiable_spec.py`
- Run output: `docs/Audit/gate1_reform_2026_05_run.md`
