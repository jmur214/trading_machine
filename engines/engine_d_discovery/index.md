# Engine D: Discovery & Evolution
**Purpose:** Autonomously discover new trading edges, evolve existing ones through genetic algorithms, and validate all candidates through a rigorous multi-gate pipeline before promoting them to active status.

**Architectural Role:** Engine D is an **offline engine** — it operates on historical data during the post-backtest discovery cycle and does not participate in the live trading loop. It writes candidate edge specs to `edges.yml` for Governance (F) to manage. Triggered via `python -m scripts.run_backtest --discover`.

**Key Design Decisions:**
- *Two-Stage ML:* LightGBM screens features by importance, then a shallow decision tree extracts interpretable rules. This avoids the opacity of pure ML while leveraging its feature selection power.
- *GA Evolution:* CompositeEdge genomes are evolved via tournament selection, crossover, and mutation. The GA vocabulary spans 7 gene types, allowing cross-category combinations (e.g., "RSI < 30 AND overnight gap down AND gold rising").
- *Vol-Adjusted Labels:* Target thresholds scale by rolling ATR%, preventing regime-dependent labeling (5% in TSLA vs. 5% in KO).
- *4-Gate Validation:* No candidate reaches `active` without passing backtest, PBO robustness, WFO degradation, and Monte Carlo significance tests.
- *Inter-Market Features:* Gracefully degrade when TLT/GLD are not in the backtest universe.

**Pipeline Flow (per `--discover` cycle):**
1. **REGIME** — Get regime context from Engine E (passed to feature engineering)
2. **FEATURES** — Compute 40+ features across 7 categories per ticker, then cross-sectional ranks
3. **HUNT** — LightGBM screening -> decision tree rule extraction -> RuleBasedEdge candidates
4. **EVOLVE** — Template mutations + GA cycle (select -> crossover -> mutate -> save population)
5. **VALIDATE** — 4-gate pipeline: backtest (Sharpe>0) -> PBO (50 paths) -> WFO -> significance (p<0.05)
6. **PROMOTE** — Winners to `active` in `edges.yml`; validation Sharpe stored for GA fitness

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `discovery.py`
- **Class `DiscoveryEngine`**: Engine D (Discovery): The Evolutionary Lab.
  - `def __init__()`
  - `def hunt()`: Phase 2 Core: The "Hunter". Scans for patterns using two-stage ML pipeline.
  - `def generate_candidates()`: Produce candidate specs via template mutation + GA evolution.
  - `def validate_candidate()`: Multi-gate validation pipeline (backtest -> PBO -> WFO -> significance).
  - `def get_queued_candidates()`: Retrieve candidates from registry by status.
  - `def save_candidates()`: Append/update candidates in edges.yml.

### `feature_engineering.py`
- **Class `FeatureEngineer`**: Central feature factory. Computes 40+ features across 7 categories.
  - `def compute_all_features()`: Master method. Accepts OHLCV, fundamentals, SPY/TLT/GLD, regime context.
  - `def compute_cross_sectional_features()` (static): Percentile ranks across universe per date.

### `tree_scanner.py`
- **Class `DecisionTreeScanner`**: Tier 2 Research: The Hunter.
  - `def generate_targets()`: Multi-class vol-adjusted target labeling.
  - `def scan()`: Two-stage pipeline: GBT screening -> decision tree rule extraction.

### `genetic_algorithm.py`
- **Class `GeneticAlgorithm`**: Manages persistent population of CompositeEdge genomes.
  - `def load_population()` / `def save_population()`: YAML persistence.
  - `def tournament_select()`: Pick k random, return highest fitness.
  - `def crossover()`: Single-point gene swapping.
  - `def mutate()`: Threshold perturbation, operator flip, gene add/delete, direction mutation.
  - `def evolve()`: One generation: elitism + tournament + crossover + mutation.
  - `def to_candidate_specs()`: Convert genomes to EdgeRegistry-compatible format.

### `significance.py`
- **Function `monte_carlo_permutation_test()`**: Shuffle returns to build null Sharpe distribution, compute p-value.
- **Function `minimum_track_record_length()`**: Bailey & Lopez de Prado MinTRL formula.

### `robustness.py`
- **Class `RobustnessTester`**: Probability of Backtest Overfitting (PBO) calculation.
  - `def calculate_pbo()`: Synthetic path analysis for overfitting detection.

### `wfo.py`
- **Class `WalkForwardOptimizer`**: Walk-forward optimization with in-sample/out-of-sample split.
  - `def run_optimization()`: Returns degradation ratio (OOS Sharpe / IS Sharpe).

### `discovery_logger.py`
- **Class `DiscoveryLogger`**: Append-only JSONL logger for discovery cycle events.
  - `def log_hunt()`: Record hunt results and feature importances.
  - `def log_ga_generation()`: Record GA population statistics.
  - `def log_validation()`: Record per-candidate validation gate results.
  - `def log_cycle_summary()`: Record cycle-level summary stats.

### `synthetic_market.py`
- Synthetic market data generation for testing.
