# Engine D: Research & Evolution
**Purpose:** This is the automated "Hunter" and "Governor" layer of the system that discovers, backtests, and validates edges autonomously. It acts like a Quant Researcher.
**Architectural Role:** Structurally isolated from Engines A, B, and C. It hunts for patterns using `DecisionTreeScanner` and `WalkForwardOptimizer`, modifying the JSON config weights for Engine A to read during runtime.

**Key Components:**
- `discovery.py` & `edge_generator.py`: Autonomously creates candidate edges.
- `evaluator.py`: Ranks edges using a time-decay.
- `governor.py`: Adjusts weights and applies performance kill-switches.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `discovery.py`
- **Class `DiscoveryEngine`**: Engine D (Discovery): The Evolutionary Lab.
  - `def __init__()`
  - `def hunt()`: Phase 2 Core: The "Hunter".
  - `def generate_candidates()`: Produce N candidate specs by sampling from Template hyperparameter spaces.
  - `def get_queued_candidates()`: Retrieve candidates from registry that are ready for validation.
  - `def save_candidates()`: Append candidates to the active edges.yml (or a separate staging registry).
  - `def validate_candidate()`: Run a quick backtest (fitness function) for a candidate.

### `evaluator.py`
- **Class `EvaluatorConfig`**: No docstring
- **Class `EdgeEvaluator`**: Loads historical edge results, computes a composite score with time-decay,
  - `def __init__()`
  - `def load()`
  - `def score_rows()`: Compute per-run normalized metrics and a composite score with time-decay.
  - `def summarize_edges()`: Aggregate per-edge: weighted means, stability (score std), and recent trend.
  - `def export()`
  - `def run()`

### `feature_engineering.py`
- **Class `FeatureEngineer`**: Tier 1 Research Feature Factory.
  - `def __init__()`
  - `def compute_all_features()`: Master factory method.

### `governor.py`
- **Class `GovernorConfig`**: Configuration for the Strategy Governor (Engine D).
- **Class `StrategyGovernor`**: Engine D: Governance & Meta-Allocation (non-ML MVP).
  - `def normalize_weights()`: Safeguard: Ensure internal weights sum to 1.0 (clamped in [0,1]).
  - `def __init__()`
  - `def update_from_trades()`: Update internal weights using most-recent data window.
  - `def get_edge_weights()`: Return the current smoothed weights for edges.
  - `def save_weights()`: Persist weights to JSON (data/governor/edge_weights.json by default).
  - `def merge_evaluator_recommendations()`: Optionally blend in evaluator-produced edge weights (e.g., from research runs).

### `metrics_engine.py`
- **Class `MetricsEngine`**: Tier 2 Metrics: Institutional Grade Scorecard.
  - `def calculate_all()`: Compute comprehensive metrics from an equity curve (daily or intraday).
  - `def sharpe_ratio()`
  - `def sortino_ratio()`
  - `def max_drawdown()`: Returns positive number 0.15 for 15% drawdown, or strictly negative? Convention: Negative.
  - `def cagr()`
  - `def beta()`
  - `def value_at_risk()`: Historical VaR.
  - `def sqn()`: System Quality Number (Tharp).
  - `def kelly_fraction()`: Kelly = W - (1-W)/R

### `regime_analytics.py`
- **Class `RegimePerfAnalytics`**: Analytics module to measure strategy performance CONDITIONAL on Market Regime.
  - `def analyze()`: Merge trades with the regime AT ENTRY TIME.

### `regime_detector.py`
- **Class `RegimeDetector`**: Detects the current market regime based on a benchmark (e.g., SPY).
  - `def __init__()`
  - `def detect_regime()`: Analyzes the benchmark DataFrame.

### `robustness.py`
- **Class `RobustnessTester`**: Tier 1 Research Tool: Robustness & Overfitting Check.
  - `def generate_bootstrap_paths()`: Generate N synthetic price histories using Circular Block Bootstrap.
  - `def calculate_pbo()`: Probability of Backtest Overfitting (PBO).

### `synthetic_market.py`
- **Class `SyntheticMarketGenerator`**: Generates realistic synthetic market data using Regime-Switching Geometric Brownian Motion.
  - `def __init__()`
  - `def generate_price_history()`: Generates OHLCV Data.
  - `def generate_fundamentals()`: Generates consistent P/E, P/S data for the simulated price.

### `system_governor.py`
- **Class `SourceFiles`**: No docstring
  - `def state_fingerprint()`
- **Class `SystemGovernor`**: Watches trade/snapshot files, refreshes metrics & weights, and writes a single
  - `def __init__()`
  - `def process_once()`: Process current state once. Returns True if an update was performed.
  - `def watch()`: Loop forever, refreshing as files change.
- **Function `main()`**: No docstring

### `tree_scanner.py`
- **Class `DecisionTreeScanner`**: Tier 2 Research: The Hunter.
  - `def __init__()`: :param max_depth: Max depth of the tree (limits complexity).
  - `def generate_targets()`: Generate Multi-Class Targets based on future returns.
  - `def scan()`: Run the Scanner.

### `wfo.py`
- **Class `WalkForwardOptimizer`**: Tier 1 Research Feature: Walk-Forward Optimization (WFO).
  - `def __init__()`
  - `def run_optimization()`: optimize parameters over rolling windows.
