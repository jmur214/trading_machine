# OOS Validation Gate — Phase 2.10b (Q1 + Q2)

**Date:** 2026-04-29
**Branch:** `oos-validation`
**Driver:** `scripts/run_oos_validation.py`
**Anchor in-sample run:** `abf68c8e-1384-4db4-822c-d65894af70a1`
(Sharpe 1.063 in-sample, documented in
`docs/Audit/realistic_cost_backtest_result.md`)

This document covers Q1 (2025 OOS, prod universe) and Q2 (held-out
universe-B, in-sample window). Q3 (volume_anomaly_v1 / herding_v1
through all 6 gates under realistic costs) is being run separately on
the `gauntlet-revalidation` branch and is documented in
`docs/Audit/gauntlet_revalidation_2026_04.md`.

## Setup (both runs)

- Cost model: `RealisticSlippageModel` (mode default in
  `config/backtest_settings.json`) — ADV-bucketed half-spread + Almgren-
  Chriss square-root market impact, k=0.5
- Initial capital: $100,000
- Edges: same prod stack as the 1.063 anchor (no edge changes)
- Governor: `--reset-governor` (clean baseline, both runs)
- `PYTHONHASHSEED=0` (deterministic Python hashing)
- Universe-B sampling: `np.random.RandomState(seed=42)`, n=50, mirrors
  `engines/engine_d_discovery/discovery.py::_load_universe_b()`

## Results — single table

| Run     | Window               | Universe                | Sharpe | CAGR%   | MDD%    | Vol%   | WR%   | Trades / Run UUID |
|---------|----------------------|-------------------------|--------|---------|---------|--------|-------|-------------------|
| Anchor (in-sample reference) | 2021-01-01 → 2024-12-31 | prod 109   | **1.063** | 6.06   | -10.07  | 5.70   | 49.06 | `abf68c8e-1384-4db4-822c-d65894af70a1` |
| **Q1 — 2025 OOS**            | 2025-01-01 → 2025-12-31 | prod 109   | **-0.049** | -0.43  | -6.48   | 5.65   | 40.39 | `72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34` |
| **Q2 — Universe-B**          | 2021-01-01 → 2024-12-31 | held-out 50 (seed=42) | **0.225** | 1.76   | -18.17  | 9.95   | 47.51 | `ee21c681-f8de-4cdb-9adb-a102b4063ca1` |

### Pass / fail vs criteria

| # | Criterion                                                             | Threshold     | Actual  | Result    |
|---|-----------------------------------------------------------------------|---------------|---------|-----------|
| Q1 | 2025 OOS Sharpe under realistic costs > 0.5                          | > 0.5         | -0.049  | **FAIL**  |
| Q2 | Universe-B Sharpe doesn't collapse > 30% below in-sample (= > 0.74)  | > 0.744       | 0.225   | **FAIL**  |

### Benchmark context (over each run's window)

| Window                  | SPY Sharpe | QQQ Sharpe | 60/40 Sharpe | System Sharpe | System − strongest |
|-------------------------|------------|------------|--------------|---------------|--------------------|
| 2025 OOS (Q1)           | 0.955      | 0.933      | 0.997        | -0.049        | **-1.046**         |
| 2021-2024 IS (anchor)   | 0.875      | 0.702      | 0.361        | 1.063         | +0.188             |
| 2021-2024 Universe-B (Q2) | 0.875    | 0.702      | 0.361        | 0.225         | -0.650             |

In 2025 the system finished essentially flat (-0.43% CAGR) while SPY
returned 18.18% and even the diversified 60/40 returned 12.93%. The
system trailed every benchmark by more than 1.0 Sharpe. On the
held-out universe over the *same* window where the prod universe
delivered +1.063, universe-B delivered +0.225 — a **79% Sharpe
collapse**. Vol roughly doubled (5.7% → 9.95%) and MDD nearly doubled
(-10.07% → -18.17%).

## Honest commentary

Both gates fail by wide margins. There is no soft reading of these
numbers.

**Q1 — the 2025 OOS result is the more decisive of the two.** Going
from in-sample Sharpe +1.063 to OOS Sharpe -0.049 is a near-total
collapse, not the ~50–60% legacy-shrinkage curve the forward plan was
prepared for. The system did not lose money catastrophically — MDD
-6.48% is calm, vol 5.65% is low — but it produced no return at all in
a year where SPY made 18%. The realistic-cost lift seen in-sample (the
"+0.7 Sharpe vs legacy 10 bps flat") did not generalize. **The 1.063
headline was largely an in-sample artifact.**

**Q2 — the universe-B result rules out "the OOS year was just bad."**
On the same 2021-2024 window where the prod universe scored 1.063, a
random held-out 50-ticker sample of cached non-prod names scored
0.225. Same edges, same cost model, same governor reset, same window.
The only difference is which universe is traded. That collapse — from
+1.063 to +0.225 — is the universe-fit signature, not a time-period
signature. The prod universe (109 mostly-mega-cap tickers) is curated
in a way that flatters the existing edge stack; it is not
representative of the broader investable universe.

**Combined diagnosis.** This matches what the prior memory record
already warned (`project_lifecycle_vindicated_universe_expansion_
2026_04_25`): *"system's true Sharpe on a wider universe is 0.4, vs
SPY 0.88. The 39-ticker 0.98 baseline was a curated-mega-cap-tech
artifact."* The new realistic-cost model didn't fix that finding. It
made the in-sample number on the favorable universe look better, but
neither the OOS year nor the held-out universe carries that lift
through. Universe-B (0.225) and the older 0.4 baseline are in the
same ZIP code. The cost-model upgrade is real; the alpha is not.

**What this kills, immediately.**

- Phase 2.11 (per-ticker meta-learner) — **blocked.** The forward plan
  conditions it on Phase 2.10b passing. It does not pass.
- Phase 2.12 (growth-profile config) — **blocked** for the same
  reason. There is no compounding base to lever into a growth profile.
- The `1.063 vs SPY 0.875` headline result in
  `realistic_cost_backtest_result.md` should be re-flagged as
  in-sample-only with prominent OOS shrinkage. The result is not
  retracted (the in-sample number under realistic costs is a real
  measurement) but it cannot continue to be cited as the system's
  performance.

**What the next session should do, per the forward plan's "If it fails"
clauses:**

1. *Q1 fail:* "Recent gains were partly in-sample artifact; priority
   shifts back to gauntlet rigor." Concretely — re-validate the 6-gate
   discovery pipeline. The two factor-decomp-identified "real alphas"
   (`volume_anomaly_v1`, `herding_v1`) need to clear all six gates
   under realistic costs **on universe-B as well as the prod
   universe**, not just the prod universe.
2. *Q2 fail:* "Cost-model fix only made the favorable universe look
   better; underlying universe-heterogeneity problem isn't actually
   fixed." Concretely — the gauntlet must be run on a universe-B-style
   held-out sample as a standard Gate 5 step before any edge is
   promoted. The current discovery pipeline already wires this (Gate
   5) but the lifecycle-active edges predate it.

**Caveats.** Universe-B contains 50 names sampled from cached CSVs not
in the prod set. A few of the sampled tickers are delisted or
historical (e.g. `SGP`, `TIE`, `GENZ`, `CA`, `FOSL`, `NFX` have not
traded in years; `FB` is the pre-rename Meta ticker; `SNDK` /
`PSKY` are odd remnants). Survivorship-aware sampling would likely
produce a different mix; the current 0.225 number is approximately
right but not bias-free. The directional finding (universe collapse)
is robust regardless.

## Reproduction

```bash
PYTHONHASHSEED=0 python -m scripts.run_oos_validation --task q1
PYTHONHASHSEED=0 python -m scripts.run_oos_validation --task q2
```

Outputs land at `data/research/oos_validation_q1.json` and
`data/research/oos_validation_q2.json`. Trade logs at
`data/trade_logs/<run_uuid>/`.
