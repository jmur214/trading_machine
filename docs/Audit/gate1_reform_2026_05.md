# Gate 1 Reform — Ensemble-Simulation Contribution Gate (2026-05-01)

> **Phase 2.10e** — replaces standalone single-edge Gate 1 with an
> ensemble-simulation contribution gate. Standalone Sharpe is preserved
> as a *diagnostic*, not a gate.

> **2026-05-01 baseline-fix update** — the original implementation
> filtered the baseline to `status='active'` only. Production deploys
> soft-paused edges at `PAUSED_WEIGHT_MULTIPLIER` (= 0.25), so the
> "active" baseline was strictly smaller than what
> `ModeController.run_backtest` actually deploys. This re-introduced
> the same geometry-mismatch the reform was meant to close — just
> inside the gate this time. Branch `gate1-reform-baseline-fix`
> includes paused edges at the production weight, restoring the
> match. Verification table below uses the corrected baseline.

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

### Original verification (2026-05-01T01:45:58, pre-baseline-fix)

The original implementation produced this result on the 2021-01-01 →
2024-12-31 window:

| edge | baseline (2-edge) | with-candidate (3-edge) | **contribution** | threshold | verdict | standalone diag |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| `volume_anomaly_v1` | -0.114 | -0.232 | **-0.118** | 0.10 | **FAIL** | 0.176 |
| `herding_v1` | -0.028 | -0.085 | **-0.057** | 0.10 | **FAIL** | -0.242 |

Both edges failed at threshold 0.10. Raw artifact:
`docs/Audit/gate1_reform_2026_05_run.md`.

### Diagnosis — why those baselines were wrong (2026-05-01)

The original `_load_active_ensemble_specs` filtered the registry to
`status='active'` only. That set has **3 edges** (`gap_fill_v1`,
`volume_anomaly_v1`, `herding_v1`). But that's not the production
ensemble. Per memory
`project_production_ensemble_includes_softpaused_2026_05_01.md`:

> `data/governor/edges.yml` partition (2026-05-01):
> - `status=active` (3): gap_fill_v1, volume_anomaly_v1, herding_v1
> - `status=paused` (14): momentum_edge_v1, low_vol_factor_v1, panic_v1,
>   earnings_vol_v1, pead_v1, pead_short_v1, pead_predrift_v1,
>   insider_cluster_v1, macro_real_rate_v1, rsi_bounce_v1, value_trap_v1,
>   value_deep_v1, growth_sales_v1, bollinger_reversion_v1
>
> **Effective deployed ensemble:** 3 active at full weight + 14 paused
> at 0.25× weight = ~6.5 edge-equivalents in capital terms. That's
> the actual production ensemble, not "3 edges."

Phase α v2 soft-pause (2026-04-24, see memory
`project_soft_pause_win_2026_04_24.md`) introduced
`PAUSED_WEIGHT_MULTIPLIER = 0.25` so paused edges keep trading at
reduced weight — that's what makes the lifecycle bidirectional.
`orchestration/mode_controller.run_backtest` applies this multiplier
inside the production code path. The original gate filtered it out.

**The cascade of mismatches:**

- The original baseline ensemble was strictly *smaller* than what
  production deploys.
- A smaller ensemble means each firing edge takes a *larger* share of
  the per-bar capital allocation.
- Larger per-fill `qty/ADV` puts the trade right back at the
  Almgren-Chriss impact knee — **the same geometry mismatch the reform
  was meant to close, just inside the gate this time**.
- Result: the corrected gate's "baseline" ran a 3-edge ensemble
  through realistic costs and the impact tax dragged the Sharpe to
  -0.114 / -0.028 even though production runs that exact same window
  + universe at Sharpe ~0.96 under the harness.

### The fix (branch `gate1-reform-baseline-fix`)

Two changes, contained to `engines/engine_d_discovery/discovery.py`:

1. **`_load_active_ensemble_specs` now reads `active` AND `paused`
   edges**, mirroring `EdgeRegistry.list_tradeable()`. Each spec carries
   a `weight` field computed exactly as `mode_controller.run_backtest`
   does it:
   ```
   weight = config_edge_weights.get(edge_id, 1.0)
            × (PAUSED_WEIGHT_MULTIPLIER if paused else 1.0)
            capped at PAUSED_MAX_WEIGHT for paused edges
   ```
   Constants `PAUSED_WEIGHT_MULTIPLIER = 0.25` and
   `PAUSED_MAX_WEIGHT = 0.5` mirror mode_controller exactly. The gate
   also resolves short module names (e.g. `rsi_bounce` →
   `engines.engine_a_alpha.edges.rsi_bounce`) the same way
   mode_controller does.

2. **`_run_ensemble_backtest` now wires the production config bundle**
   that mode_controller wires into `BacktestController`:
   - `AlphaEngine(config=alpha_settings.prod.json)` — regime gates,
     ensemble shrinkage, fill_share_cap, hygiene, flip_cooldown.
   - `RiskEngine(risk_settings.prod.json)` — vol-target, advisory regime
     floor, exposure cap, per-trade sizing.
   - `BacktestController(portfolio_cfg=PortfolioPolicyConfig(...),
     regime_detector=RegimeDetector())` — fill-share cap, regime
     classification used by AlphaEngine's regime gates.
   - `edge_weights` dict (with paused×0.25) → AlphaEngine.

   Without this bundle, AlphaEngine ran with permissive defaults, no
   regime gating, no fill-share cap, no advisory regime floor — and
   the ensemble's dynamics diverged from production.

The fix is `~150 lines net` in one file, plus updated unit tests
(`tests/test_discovery_gate1_reform.py`, 23 tests covering the new
weight propagation + production-config wiring + composition rules).
No changes to other engines, signal_processor, lifecycle, alpha_engine,
or any non-Discovery code.

### Corrected verification

Run config:

- Driver: `scripts/gate1_reform_falsifiable_spec.py`
- Window: **2025-01-01 → 2025-12-31** (matches `run_isolated.py
  --task q1`, the canonical harness reference for production-equivalent
  Sharpe)
- Universe: 109 of 109 production tickers
- Slippage: realistic Almgren-Chriss + ADV-bucketed half-spread
- Threshold: 0.10 (default)
- Baseline composition (read from `data/governor/edges.yml` at run time):
  16 tradeable edges (2 active + 14 paused at production weights), one
  excluded per candidate.

> **Verification table from run `gate1_reform_2026_05_run_v3.md`** —
> filled in below after the production-config-wired + warmup re-run
> completes.

```
[See docs/Audit/gate1_reform_2026_05_run_v3.md]
```

### Sanity-check journey (four runs to find the configuration mismatches)

The director's brief required the corrected baseline to land near
`run_isolated.py --task q1`'s reference Sharpe (~0.96 on 2025 OOS
prod-109) before the verification could be considered honest. Each
run revealed an additional missing piece:

| Run | Fix applied | Vol-anomaly contrib | Herding contrib | Baseline (16 edge) | with_cand (17 edge) |
| --- | --- | ---: | ---: | ---: | ---: |
| v1 | paused edges loaded at 0.25× weight (the load-bearing fix from director's brief) | +0.614 PASS | +0.572 PASS | -0.453 / -0.407 | 0.161 / 0.165 |
| v2 | + alpha/risk/portfolio config + regime detector wired through | -0.429 FAIL | (killed) | 0.454 | 0.025 |
| v3 | + 365-day warmup window on data_map (mirrors `fetch_start = sim_start − 365 days` from mode_controller) | -0.040 FAIL | -0.059 FAIL | 0.627 / 0.646 | 0.586 / 0.587 |
| v4 | + governor wiring with reset_weights() | -0.040 FAIL | -0.059 FAIL | 0.627 / 0.646 | 0.586 / 0.587 |

**v4 is bitwise-identical to v3** — `governor.reset_weights()` clears
both `_weights` and `_regime_weights`, so AlphaEngine's governor
adjustment loop multiplies signal strength by 1.0 (no-op). Governor
wiring confirmed *not* load-bearing for the residual gap.

### Final verification — v4 (full production wiring, threshold 0.10)

| edge | baseline (16-edge tradeable, candidate excluded) | with-candidate (17-edge full) | **contribution** | threshold | verdict | standalone diag |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| `volume_anomaly_v1` | 0.627 | 0.586 | **-0.040** | 0.10 | **FAIL** | 1.920 |
| `herding_v1` | 0.646 | 0.587 | **-0.059** | 0.10 | **FAIL** | 1.449 |

Per-edge baselines (read from `data/governor/edges.yml` at run time,
2 active + 14 paused at 0.25× weight, candidate excluded):

- `volume_anomaly_v1` baseline = 16 edges (gap_fill, herding active;
  bollinger_reversion, earnings_vol, growth_sales, insider_cluster,
  low_vol_factor, macro_real_rate, momentum_edge, panic, pead,
  pead_predrift, pead_short, rsi_bounce, value_deep, value_trap paused)
- `herding_v1` baseline = 16 edges (same composition with herding↔volume_anomaly)

Raw JSON + per-edge timing: `docs/Audit/gate1_reform_2026_05_run_v4.md`.
Wall time 12.4 min on 109-ticker × 1-year (2025) window.

### What the v4 result actually says

**Both contributions are essentially zero** (-0.040 and -0.059, around
the threshold but on the wrong side). Mechanically: FAIL.
Interpretation requires acknowledging two facts simultaneously:

1. **Residual ~0.3 Sharpe gap to harness.** The full 17-edge ensemble
   (with_cand for either run) produces 0.586 / 0.587 here, vs
   `run_isolated.py --task q1`'s ~0.96 on the same window/universe/
   exec_params/governor-state-reset. The four progressive fixes (paused
   edges, production config, warmup, governor wiring) closed the gap
   from 0.96 → -0.45 (original) → 0.46 (v2) → 0.59 (v3/v4). A
   ~0.3 Sharpe residual remains. Plausible sources: AlphaEngine's
   metalearner block, signal_gate state, edge-construction order, or
   small init-time differences not yet identified. **The remaining gap
   is small enough that the gate's qualitative signal (~zero
   contribution from these two edges) is plausible, but large enough
   that the absolute contribution numbers should be treated with
   suspicion.**

2. **Both edges contribute essentially nothing to the 16-edge
   baseline.** Adding either to the 16-edge ensemble *reduces* Sharpe
   by ~0.04-0.06 — well within the noise band of a 1-year window.
   This is consistent with the 04-30 paradox memory's capital-rivalry
   finding: in a saturated ensemble, adding a redundant signal
   doesn't help (and may slightly hurt via fill-share competition).
   The signal is "these two edges are *replaceable*" — not
   "these two edges are alpha-destroying," which would require
   contributions like the v2 result (-0.4).

### Decision rule (mechanical)

| Outcome | Action |
| --- | --- |
| Both edges PASS with contribution > 0.15 | Promote to default Gate 1 (director's "reasonable margin"). |
| Both edges PASS at 0.10 ≤ contribution < 0.15 | Promote with threshold re-calibration flagged. |
| **Either edge FAILS (← actual outcome)** | **Per director spec: gate is mis-designed — re-tune. Do NOT promote yet.** |

### Verdict and recommendation

**Verdict: do NOT promote** — the falsifiable spec failed per the
pre-committed criterion. Two work items before re-attempting:

1. **Close the residual ~0.3 Sharpe gap.** The fixes shipped
   (`paused-weight + production-config + warmup`) move the baseline
   from -0.45 to 0.59 — most of the way to the harness reference 0.96
   but not all the way. A separate diagnostic effort needs to compare
   the gate's `_run_ensemble_backtest` to `mode_controller.run_backtest`
   line-by-line to find what's still different. Likely candidates:
   AlphaEngine's metalearner block, signal_gate persistent state,
   per_ticker_score_logger interactions, or initialization order.
   None of these were touched by the original gate-1-reform brief
   (the brief was scoped to paused-edge inclusion).

2. **Once baseline matches harness, re-run the falsifiable spec.**
   Only then is the gate's contribution number a trustworthy signal
   about edge-level value. With baseline at ~0.59, contribution
   numbers near zero are ambiguous: they could mean the edges add
   ~zero value (interpretation B from session 1's audit), or they
   could be a measurement artifact of the residual config gap
   (interpretation A). The two cannot be cleanly separated from this
   data alone.

This branch ships the structural fix (paused-edge inclusion +
production-config wiring + warmup + governor wiring + 23 unit tests).
The promote/no-promote decision and the residual-gap investigation
both remain on main per user discretion.

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
