# Engine B: Risk Management
**Purpose:** This engine acts as the gatekeeper. It takes the rough raw signals from Engine A and applies sizing, sector constraints, correlation penalties, and volatility standardization (ATR).
**Architectural Role:** Sits between Alpha and Portfolio. Translates raw `-1.0 to 1.0` signals into concrete position sizing targets.

**Regime-Adaptive Constraints (via Engine E Advisory):**
- `prepare_order()` accepts `regime_meta` and extracts advisory constraints:
  - `suggested_max_positions` — dynamic cap (can only tighten, never loosen beyond config)
  - `suggested_exposure_cap` — dynamic gross exposure limit
  - `risk_scalar` — multiplied into ATR position sizing budget
  - `correlation_regime` — drives dynamic sector limits: dispersed → 40%, elevated/spike → 20%
- All advisory-driven limits default to config values when `regime_meta` is absent (backward compatible).

**Known Issues & Quirks:**
- *State Mutation Violation:* For trailing stops, the `RiskEngine` explicitly reaches into `PortfolioEngine`'s internal state to mutate the stop positions because the simulator struggles with "update" orders via standard messaging. This must be refactored eventually.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `factor_analysis.py`
- **Class `FactorRiskModel`**: Computes factor exposures for a universe of assets.
  - `def __init__()`
  - `def compute_exposures()`: Returns a DataFrame of factor loadings (Tickers x Factors).

### `lt_hold_preference.py`
**Module Docstring:** Long-term hold preference — defer signal-driven exits past 365 days
- **Class `LTHoldPreferenceConfig`**: No docstring
- **Class `LTHoldPreference`**: Defer signal-driven exits when long-term tax saving > alpha-lift.
  - `def __init__()`
  - `def reset()`
  - `def stats()`
  - `def record_fill()`: Update the entry-date ledger from a fill.
  - `def get_entry_dt()`
  - `def should_defer_exit()`: Decide whether to defer a signal-driven exit.

### `risk_engine.py`
- **Class `RiskConfig`**: Risk and constraint configuration (config-driven).
- **Class `RiskEngine`**: Engine B — Risk / Sizing / Constraints.
  - `def __init__()`
  - `def record_fill()`
  - `def prepare_order()`
  - `def manage_positions()`: Check all open positions and generate 'update' orders (e.g. moving stops).
  - `def prepare_order()`: Build an order dict or return None if constraints block it.

### `wash_sale_avoidance.py`
**Module Docstring:** Wash-sale avoidance — refuse buys within 30 days of a loss-realizing exit.
- **Class `WashSaleAvoidanceConfig`**: No docstring
- **Class `WashSaleAvoidance`**: Per-ticker recent-loss ledger consulted at order-entry time.
  - `def __init__()`
  - `def reset()`
  - `def stats()`
  - `def record_fill()`: Push a fill into the ledger. Only loss-realizing closes register.
  - `def should_block_buy()`: True iff `ticker` had a loss-realizing close within window_days of `now`.
