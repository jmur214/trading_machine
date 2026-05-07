# Engine F — Governance & Lifecycle

## Mission

Per `docs/Core/engine_charters.md` § Engine F:

> Apply continuous statistical scrutiny to the active edge population, manage edge weights based on observed evidence, and govern lifecycle transitions (candidate → active → paused → retired). Operate fully autonomously over a long horizon — no human-in-the-loop required for weight or lifecycle decisions.

## Public API surface

- `governor.StrategyGovernor` — master orchestrator (canonical). EMA-smoothed scoring, regime-conditional weights, allocation evaluation orchestration.
- `regime_tracker.RegimePerformanceTracker` — per-edge per-regime Welford online stats.
- `evaluator.EdgeEvaluator` — research-result ranking with time-decay scoring.
- `lifecycle_manager.LifecycleManager` — candidate → active → paused → retired transitions with versioned audit trail.
- `regime_analytics.RegimePerfAnalytics` — conditional edge performance by regime.
- `evolution_controller.EvolutionController` — coordinates evolution cycles with lifecycle management. Critical-path autonomy code (Phase γ rewire 2026-04-24).
- `promote.py` / `promote_best_params.py` — lifecycle promotion helpers.

## Charter invariants

1. F **never** changes live state without a versioned audit trail
2. Weight updates require minimum evidence thresholds (≥50 trades, ≥30 days)
3. Maximum weight change per cycle is capped (±15%)
4. Edge demotions require statistically significant underperformance, not bad streaks
5. F can be completely disabled without breaking A, B, C, D, or E
6. F distinguishes "edge is broken" from "edge is out of regime phase" using E's history
7. F is fully autonomous — no human-in-the-loop required

## Status notes

- **Soft-pause at 0.25× weight is shipped** (memory `project_soft_pause_win_2026_04_24`). Lifecycle is genuinely bidirectional.
- **First autonomous pause** shipped 2026-04-24 (atr_breakout_v1 paused on evidence; memory `project_first_autonomous_pause_2026_04_24`).
- **Registry status-stomp bug FIXED** 2026-04-25 (memory `project_registry_status_stomp_bug_2026_04_25`); `EdgeRegistry.ensure()` now write-protects the `status` field.
- **F11 architectural concern (open):** the write-back-to-edges-yml pattern mutates the upstream measurement substrate. Audit-flagged 2026-05-06; awaiting propose-first redesign decision.
- **Decision diary scaffold** at `core/observability/decision_diary.py` (12 backfilled + 5 high-value events as of 2026-05-09).
- **Edge graveyard structured tagging** (`failure_reason`, `superseded_by`) shipped via WS-J 2026-05-05.

## edges.yml Write Contract (D + F shared file)

- **D writes:** new candidate entries, params, metadata, source info, validation results.
- **F writes:** `status` field changes (candidate → active → paused → retired), weight assignments.
- Neither engine deletes the other's fields.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `evaluator.py`
- **Class `EvaluatorConfig`**: No docstring
- **Class `EdgeEvaluator`**: Loads historical edge results, computes a composite score with time-decay,
  - `def __init__()`
  - `def load()`
  - `def score_rows()`: Compute per-run normalized metrics and a composite score with time-decay.
  - `def summarize_edges()`: Aggregate per-edge: weighted means, stability (score std), and recent trend.
  - `def export()`
  - `def run()`

### `evolution_controller.py`
- **Class `EvolutionController`**: Autonomous Evolution Controller
  - `def __init__()`
  - `def run_cycle()`
  - `def load_edges()`
  - `def save_edges()`
  - `def run_wfo_for_candidate()`: Run WFO for a candidate using WalkForwardOptimizer directly.
  - `def update_production_config()`: Updates alpha_settings.prod.json to include the new 'active' edge parameters.

### `governor.py`
- **Class `GovernorConfig`**: Configuration for the Strategy Governor (Engine D).
- **Class `StrategyGovernor`**: Engine D: Governance & Meta-Allocation (non-ML MVP).
  - `def normalize_weights()`: Safeguard: Ensure internal weights sum to 1.0 (clamped in [0,1]).
  - `def __init__()`
  - `def update_from_trades()`: Update internal weights using most-recent data window.
  - `def get_edge_weights()`: Return edge weights, optionally regime-conditional.
  - `def set_edge_weights()`: Directly set edge weights (e.g. after recency decay scaling).
  - `def update_from_trade_log()`: End-to-end edge feedback loop: load trade/snapshot CSVs, update weights,
  - `def evaluate_lifecycle()`: Run lifecycle gates on active/paused edges using the provided trade
  - `def evaluate_tiers()`: Phase 2.10d Trigger 3: post-backtest tier reclassification hook.
  - `def reset_weights()`: Reset in-memory weights to neutral (1.0 for all edges).
  - `def save_weights()`: Persist weights to JSON (data/governor/edge_weights.json by default).
  - `def merge_evaluator_recommendations()`: Optionally blend in evaluator-produced edge weights (e.g., from research runs).

### `lifecycle_manager.py`
**Module Docstring:** engines/engine_f_governance/lifecycle_manager.py
- **Class `LifecycleConfig`**: Gates and thresholds for edge lifecycle transitions.
- **Class `LifecycleEvent`**: One transition event for the audit trail.
- **Class `LifecycleManager`**: Evaluates lifecycle transitions for all edges in edges.yml.
  - `def __init__()`
  - `def evaluate()`: Evaluate lifecycle transitions using the current trade log and benchmark.

### `promote.py`
- **Function `is_info_enabled()`**: No docstring
- **Function `promote_best_params()`**: Promotes the best-performing parameter combo for a given edge

### `promote_best_params.py`
- **Function `promote_best_params()`**: No docstring

### `regime_analytics.py`
- **Class `RegimePerfAnalytics`**: Analytics module to measure strategy performance CONDITIONAL on Market Regime.
  - `def analyze()`: Merge trades with the regime AT ENTRY TIME.

### `regime_tracker.py`
**Module Docstring:** Per-edge, per-regime performance tracking using Welford's online algorithm.
- **Class `RegimeEdgeStats`**: Rolling per-edge, per-regime statistics via Welford's online algorithm.
  - `def update()`: Record a single trade PnL.
  - `def mean_pnl()`
  - `def std_pnl()`
  - `def sharpe()`: Annualized Sharpe approximation (assuming ~252 trades/year baseline).
  - `def win_rate()`
  - `def to_dict()`
  - `def from_dict()`
- **Class `RegimePerformanceTracker`**: Track per-edge performance across different market regimes.
  - `def __init__()`
  - `def record_trade()`: Record a trade and update stats for both regime-specific and global buckets.
  - `def get_trigger_stats()`: Return per-trigger stats, or None if insufficient samples.
  - `def get_regime_sharpe()`: Get Sharpe for an edge in a specific regime. Returns None if insufficient data.
  - `def get_regime_weight()`: Compute weight for an edge in a regime using same logic as Governor.
  - `def get_learned_affinity()`: Compute per-edge-category average weights for a regime.
  - `def trade_count_for_regime()`: Total trades recorded under a regime label.
  - `def save()`: Persist to JSON.
  - `def load()`: Load from JSON. Silently no-ops if file doesn't exist.
