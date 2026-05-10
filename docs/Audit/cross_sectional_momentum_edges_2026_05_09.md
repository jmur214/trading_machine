# Cross-Sectional Momentum Edges — Audit (T-2026-05-09-016)

**Date:** 2026-05-09
**Branch:** `feature/cross-sectional-momentum-edges`
**Scope:** Engine A autonomy lane. Three new edges in `engines/engine_a_alpha/edges/`. No engine surgery, no Engine B / live_trader / `core/metrics_engine.py` touch. No `data/governor/edges.yml` mutation — auto-register only at status='paused' tier='feature'.

## What ships

| edge_id | category | direction | window | universe gate |
|---|---|---|---|---|
| `momentum_12_1_v1` | cross_sectional_momentum | long top quintile | 252-day return, skip 21d | min 50 names |
| `momentum_6_1_v1` | cross_sectional_momentum | long top quintile | 126-day return, skip 21d | min 50 names |
| `short_term_reversal_v1` | cross_sectional_reversal | long bottom decile + short top decile | 21-day return, no skip | min 50 names |

Each edge:
- Cross-sectionally ranks tickers in `data_map` at `now`. No dependency on pre-computed `XS_*_Pctile` columns (those don't exist for 12-1 / 6-1 in `engines/engine_d_discovery/feature_engineering.py` — see "Column-name verification" below).
- Returns `Dict[str, float]` per `EdgeBase.compute_signals` interface (matches the 6 actives + the calendar_anomaly + cot_positioning paused edges).
- Auto-registers at `status='paused' tier='feature'` via the standard `EdgeRegistry.ensure(EdgeSpec(...))` import-time pattern.

## Column-name verification

The brief assumed `XS_Mom_12_1_Pctile`, `XS_Mom_6_1_Pctile`, `XS_Mom_20_Pctile` columns existed in the data_map (per T-006 cross-sectional features). Verification:

`engines/engine_d_discovery/feature_engineering.py:404-409` only computes:
- `XS_Mom_20_Pctile` (20-day return rank — close to but NOT identical to a 1-month reversal)
- `XS_Mom_60_Pctile` (60-day return rank)

There is **no** `XS_Mom_12_1_Pctile` and no `XS_Mom_6_1_Pctile` in the cross-sectional feature engineering. The `mom_12_1` / `mom_6_1` Foundry features (per T-006) are scalar feature-registry entries — not columns automatically added to per-ticker DataFrames in `data_map`.

**Implication:** edges cannot consume `XS_Mom_12_1_Pctile` directly. Two paths:
1. Wire `XS_Mom_12_1_Pctile` and `XS_Mom_6_1_Pctile` into Engine D feature engineering (touches engine code — out of scope for this dispatch).
2. Compute the rank in-edge by iterating over `data_map` at `now`. Picked this path — matches `xsec_momentum.py` precedent and keeps the dispatch within the Engine A autonomy lane.

`short_term_reversal_v1` could have used the existing `XS_Mom_20_Pctile` but uses in-edge ranking for consistency with the other 2 edges in this batch and to avoid coupling to Engine D's feature-engineering schema.

## Auto-registration verification

```
$ python3 -c "
from engines.engine_a_alpha.edges.momentum_12_1_v1 import Momentum12_1Edge
from engines.engine_a_alpha.edges.momentum_6_1_v1 import Momentum6_1Edge
from engines.engine_a_alpha.edges.short_term_reversal_v1 import ShortTermReversalEdge
from engines.engine_a_alpha.edge_registry import EdgeRegistry
reg = EdgeRegistry()
for eid in ['momentum_12_1_v1', 'momentum_6_1_v1', 'short_term_reversal_v1']:
    spec = next((s for s in reg.get_all_specs() if s.edge_id == eid), None)
    print(f'{eid}: status={spec.status}, tier={spec.tier}')"

momentum_12_1_v1: status=paused, tier=feature
momentum_6_1_v1: status=paused, tier=feature
short_term_reversal_v1: status=paused, tier=feature
```

## Determinism guard — paused edges enter ensemble at 0.25×

**Per spec, this is expected behavior, not a bug.** The soft-pause infrastructure (`PAUSED_WEIGHT_MULTIPLIER = 0.25` in `orchestration/mode_controller.py` lines 890-898, capped at `PAUSED_MAX_WEIGHT = 0.5`) routes paused edges into the ensemble at reduced weight. The mechanism is **status-driven**, not metric-history-driven — any edge with `status="paused"` in the registry contributes, regardless of whether it has a prior `edge_metrics.json` entry.

Reference: `project_soft_pause_win_2026_04_24.md` — soft-pause is load-bearing infrastructure ensuring paused edges produce continuous post-pause data for the lifecycle revival gate.

**Empirical canon md5 verification:**

| Run | canon md5 | Sharpe |
|---|---|---|
| Baseline (T-010 reference, main) | `182af6a1240da35055f716ef9dfcd333` | 0.127 |
| This branch (3 paused/feature edges added) | **`e30aaa03d066a5db44bf40586c70fe4e`** | **0.235** |

**canon md5 SHIFTED, as expected.** The 3 new edges entered the ensemble via soft-pause at 0.25× weight, perturbing position sizing across the q1 backtest. The shift is the soft-pause mechanism working correctly — `PAUSED_WEIGHT_MULTIPLIER = 0.25` is status-driven, not history-driven, so newly-registered paused edges contribute immediately.

**Sharpe LIFTED from 0.127 to 0.235 (+0.108).** This is a positive perturbation, not a regression. Two interpretations are consistent with the data:

1. **In-sample signal hypothesis**: 2025-Q1 had momentum-favorable conditions (cross-sectional momentum is a documented Carhart factor; Q1 2025 had clear sector dispersion per existing regime classifications). The new 12-1 / 6-1 momentum edges added top-quintile-long signal at 0.25× weight, the reversal edge added counter-balance shorts, and the net impact was Sharpe-positive.
2. **Position-sizing-cap hypothesis**: the new paused edges may have triggered exposure-cap rebalancing on existing edges, indirectly improving sizing on the 6 actives. Less likely given the magnitude.

Either way, the result is consistent with "these edges have plausible signal that should be evaluated by the lifecycle gauntlet." The lift does NOT mean they should be deployed at status='active' — that's the gauntlet's call on next Discovery cycle (Gates 1-8 incl. factor-decomp at t > 2 on substrate-honest).

**Director note:** other in-flight measurement work that pins to the 182af6a1 reference will need re-baselining if this dispatch lands first. Recommend coordinating merge order with any open T-010+ measurement campaigns.

## Spec open questions — resolutions

### 1. Soft-pause vs proposed-tier

Investigated. `EdgeSpec.status` set: `active | candidate | retired | paused | archived | failed` (per existing usage). **There is no `proposed` status** — the brief's worst-case fallback is unavailable. Registered at `paused`. Soft-pause weighting (0.25×) applies; canon md5 will shift.

If the director wants new edges to be EXCLUDED from the ensemble entirely until lifecycle clears them, three options exist:
1. Add a `proposed` status to the registry vocabulary (engine-completion-track work; not in this dispatch).
2. Use `status='candidate'` if it exists in the soft-pause exclusion path (verify by running this guard).
3. Gate via a flag: `status='paused'` AND mark something like `metric_history_required=True` so soft-pause skips edges with no metrics — but this would need a code change in `mode_controller.py` (engine surgery — not in this dispatch).

Documented as a follow-up item.

### 2. Top-quintile threshold

Used **0.80 quantile (top quintile, 20% of universe)** per the most-cited Jegadeesh-Titman parameterization. Top decile (10%) was considered but rejected for a 109-name universe — top decile = 10-11 names → too concentrated as a starting parameterization. Top quintile lands at ~22 names, comparable to other paused edges' position counts and within the asymmetric vol-clamp / exposure-cap envelope.

For `short_term_reversal_v1`, top decile (0.90) is used because it's a short signal — concentrating short conviction in fewer extreme winners is the literature-preferred parameterization. Bottom decile (0.10) for the long-loser side mirrors.

### 3. 1-month reversal direction

The Lehmann (1990) original is cleaner on the long-loser direction (no borrow-cost concern). `short_term_reversal_v1` returns +1.0 on bottom-decile losers and -1.0 on top-decile winners. Both directions are emitted; downstream meta-learner / signal_processor decides which to weight at production deploy time. The short side at deploy may need an additional shortable-name filter — a known limitation, documented in the edge's docstring.

### 4. Universe minimum for cross-sectional ranking

Each edge has `min_universe_size=50` parameter. If the data_map has fewer than 50 ranked tickers (after filtering for sufficient lookback history), the edge returns universal abstain. This avoids 5-10 name concentration bets that would dominate ensemble sizing on small universes.

50 names is approximately half the current 109-ticker S&P 500 universe → enforces ~20% concentration at the long side. For Discovery's universe-shrinkage stress tests, this gate is the kill-switch.

## Tests

`tests/test_cross_sectional_momentum_edges.py` — 14 tests, all pass:

| Test | Asserts |
|---|---|
| `test_all_three_edges_register_at_paused_feature` | All 3 in registry, status='paused', tier='feature' |
| `test_momentum_12_1_long_top_quintile_signal_shape` | 50-ticker universe, top 10 names by 12-1 return get score 1.0; bottom 40 get 0.0 |
| `test_momentum_12_1_handles_small_universe` | 20 tickers → universal abstain (below `min_universe_size=50`) |
| `test_momentum_12_1_handles_insufficient_history` | 100 bars vs 274 needed → universal abstain |
| `test_momentum_6_1_long_top_quintile_signal_shape` | Same shape as 12-1 but works on 200-bar series |
| `test_momentum_6_1_uses_shorter_horizon_than_12_1` | 6-1 fires, 12-1 universally abstains on 200 bars |
| `test_short_term_reversal_long_losers_short_winners` | Bottom 5/50 → +1.0, top 5/50 → -1.0, middle 40 → 0.0 |
| `test_edges_handle_missing_close_column_gracefully` (×3) | Ticker without Close column → excluded from rank, score 0.0 in output |
| `test_edges_handle_empty_data_map` (×3) | Empty input → empty output, no crash |
| `test_soft_pause_pattern_documented` | `PAUSED_WEIGHT_MULTIPLIER = 0.25` constant exists in `mode_controller.py` (tripwire if it moves) |

Existing `tests/test_signal_processor_*.py` (4 files), `tests/test_edge_outputs_extended.py`, and other Engine A tests: 34/34 still pass on this branch.

**One pre-existing failure (NOT caused by this branch):** `tests/test_alpha_pipeline.py::test_alphaengine_pipeline` fails with `ValueError: Length of values (200) does not match length of index (199)` in the test fixture's `create_mock_data` helper. Verified by removing the 3 new edges + retesting — same failure on clean checkout. This is a pre-existing test bug separate from this dispatch; flagged for the director.

## What this dispatch does NOT do

- No promotion to `status='active'` in `data/governor/edges.yml`.
- No Engine B / live_trader / metrics-engine modification.
- No `XS_Mom_12_1_Pctile` / `XS_Mom_6_1_Pctile` column wired into Engine D feature engineering. The brief's assumption was incorrect on column existence; dispatch worked around by computing in-edge.
- No new dependencies. Pandas + numpy + the existing edge registry only.
- No industry-relative momentum, QMJ, profitability composite, etc. (deliberately out of scope per brief).
- No `lifecycle_history.csv` mutation. Edges are paused on first registration; lifecycle on next Discovery cycle decides.

## Forward-looking note: lifecycle gauntlet validation

For any of these 3 edges to deploy at `status='active'`, they must clear:
- Gate 1 (PSR ≥ 0.50 with CI-aware reading per T-010)
- Gates 2-6 (cost-completeness, factor decomp at t > 2, etc.)
- Gate 7 (substrate-transfer)
- Gate 8 (DSR vs Discovery batch size)

Given T-004's finding that 0/6 active edges have positive factor-adjusted alpha at t > 2 on substrate-honest, the bar is **high**. These edges likely clear or fail at Gate 6 / factor-decomp specifically — they're DESIGNED to be factor-correlated (momentum is a Carhart factor; reversal is its inverse). The factor-adjusted alpha they need is the residual after Mom-factor exposure is regressed out. Whether that residual is t > 2 on substrate-honest is the empirical question — answered by running them through the gauntlet on next Discovery cycle.

## Files changed

- `engines/engine_a_alpha/edges/momentum_12_1_v1.py` — new (Momentum12_1Edge)
- `engines/engine_a_alpha/edges/momentum_6_1_v1.py` — new (Momentum6_1Edge)
- `engines/engine_a_alpha/edges/short_term_reversal_v1.py` — new (ShortTermReversalEdge)
- `tests/test_cross_sectional_momentum_edges.py` — new (14 tests)
- `docs/Audit/cross_sectional_momentum_edges_2026_05_09.md` — this audit doc

Total ~600 LOC added, 0 removed. No `__init__.py` modification needed — the standard EdgeRegistry import-time discovery in `mode_controller._load_edges_via_registry` enumerates the edges directory.
