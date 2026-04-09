# Engine C: Portfolio Accounting
**Purpose:** The core ledger of the trading system. It maintains the absolute accounting identity: `equity = cash + market_value`.
**Architectural Role:** It receives target portfolio states from Risk or the ModeController and explicitly executes the theoretical paper trades.

**Known Issues & Quirks:**
- *The Vanity Bug Fix:* Contains workarounds to mark missing assets to `0.0` or last explicit price during data gaps.
- *The Bagholder Bug:* If an asset stops trading and no price data arrives, the engine gets stuck holding it.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `allocator.py`
- **Class `AllocatorConfig`**: No docstring
- **Class `EngineCAllocator`**: Portfolio-level selection & diversification.
  - `def __init__()`
  - `def select()`: scored:  {ticker: {"score": float, "side": "long|short|none", "contrib":[...]}}

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
