# Engine C: Portfolio Accounting & Allocation
**Purpose:** The core ledger of the trading system. It maintains the absolute accounting identity: `equity = cash + market_value`. The allocation layer determines target portfolio weights using regime-aware, vol-targeted strategies.
**Architectural Role:** It receives target portfolio states from Risk or the ModeController and explicitly executes the theoretical paper trades.

**Regime-Adaptive Allocation:**
- `PortfolioPolicy.allocate()` accepts `regime_meta` for regime-conditional behavior:
  - **Vol Targeting:** Estimates portfolio-level vol via `w @ cov @ w` and scales weights to match `target_volatility` (scalar clamped 0.3-2.0).
  - **Advisory Exposure Cap:** Enforces `suggested_exposure_cap` from Engine E advisory, scaling all weights proportionally when gross exposure exceeds the cap.
  - **Regime-Specific Config Overrides:** Loads per-regime allocation recommendations from `AllocationEvaluator` (mode, max_weight, target_vol, rebalance_threshold) and temporarily applies them during allocation.
- `AllocationEvaluator` (new) autonomously tests 384 parameter combinations and finds optimal configs per regime. Integrated into Governor's `update_from_trade_log()` feedback loop. Recommendations saved to `data/research/allocation_recommendations.json`.

**Known Issues & Quirks:**
- *The Vanity Bug Fix:* Contains workarounds to mark missing assets to `0.0` or last explicit price during data gaps.
- *The Bagholder Bug:* If an asset stops trading and no price data arrives, the engine gets stuck holding it.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `allocation_evaluator.py`
**Module Docstring:** Autonomous Portfolio Allocation Discovery.
- **Class `AllocationMetrics`**: Performance metrics for an allocation configuration.
  - `def score()`: Composite score: higher is better.
- **Class `AllocationRecommendation`**: A recommended allocation config with its score.
  - `def to_dict()`
- **Class `AllocationEvaluator`**: Evaluate allocation parameter combinations over historical trades.
  - `def __init__()`
  - `def evaluate()`: Evaluate all parameter combos over trade history.
  - `def evaluate_by_regime()`: Find optimal configs per regime label.
  - `def recommend()`: Return best config globally + per regime as dicts.
  - `def get_config_for_regime()`: Get recommended params for a specific regime, falling back to global.
  - `def save_recommendations()`
  - `def load_recommendations()`

### `allocator.py`
- **Class `AllocatorConfig`**: No docstring
- **Class `EngineCAllocator`**: Portfolio-level selection & diversification.
  - `def __init__()`
  - `def select()`: scored:  {ticker: {"score": float, "side": "long|short|none", "contrib":[...]}}

### `composer.py`
**Module Docstring:** Engine C — Portfolio Composer.
- **Class `PortfolioOptimizerSettings`**: Config for PortfolioComposer.
- **Class `PortfolioComposer`**: Applies HRP + turnover gating to per-ticker info dicts.
  - `def __init__()`
  - `def is_active()`
  - `def compose()`: Mutate ``per_ticker`` in place to add ``hrp_weight`` and

### `optimizer.py`
- **Class `PortfolioOptimizer`**: Mean-Variance Optimizer (MVO) for professional portfolio construction.
  - `def __init__()`
  - `def optimize()`: Derive optimal weights.
  - `def calculate_metrics()`

### `policy.py`
- **Class `PortfolioPolicyConfig`**: Configuration for the portfolio policy allocator.
- **Class `PortfolioPolicy`**: Determines target position weights.
  - `def __init__()`
  - `def compute_vol_estimates()`: Compute annualized volatility per asset based on the last N bars.
  - `def allocate()`: Compute target weights for each asset.
  - `def requires_rebalance()`: Determine whether the portfolio should rebalance based on deviation.

### `portfolio_engine.py`
- **Class `Position`**: No docstring
- **Class `PortfolioEngine`**: Core accounting and allocation layer.
  - `def __init__()`
  - `def apply_fill()`
  - `def snapshot()`
  - `def total_equity()`: Compute total portfolio equity = cash + Σ(qty * price).
  - `def compute_target_allocations()`: Wrapper around PortfolioPolicy.allocate() that stores and returns weights.
  - `def target_notional_values()`: Translate current target weights to target dollar notionals.
  - `def gross_notional()`
  - `def net_exposure()`
  - `def positions_map()`
  - `def get_position_info()`
  - `def get_avg_price()`
  - `def get_qty()`
- **Function `is_portfolio_debug()`**: No docstring
