# Engine B: Risk Management
**Purpose:** This engine acts as the gatekeeper. It takes the rough raw signals from Engine A and applies sizing, sector constraints, correlation penalties, and volatility standardization (ATR).
**Architectural Role:** Sits between Alpha and Portfolio. Translates raw `-1.0 to 1.0` signals into concrete position sizing targets.

**Known Issues & Quirks:**
- *State Mutation Violation:* For trailing stops, the `RiskEngine` explicitly reaches into `PortfolioEngine`'s internal state to mutate the stop positions because the simulator struggles with "update" orders via standard messaging. This must be refactored eventually.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `factor_analysis.py`
- **Class `FactorRiskModel`**: Computes factor exposures for a universe of assets.
  - `def __init__()`
  - `def compute_exposures()`: Returns a DataFrame of factor loadings (Tickers x Factors).

### `risk_engine.py`
- **Class `RiskConfig`**: Risk and constraint configuration (config-driven).
- **Class `RiskEngine`**: Engine B — Risk / Sizing / Constraints.
  - `def __init__()`
  - `def prepare_order()`
  - `def manage_positions()`: Check all open positions and generate 'update' orders (e.g. moving stops).
  - `def prepare_order()`: Build an order dict or return None if constraints block it.

### `risk_engine_bak.py`
- **Class `RiskConfig`**: Risk and constraint configuration (config-driven).
- **Class `RiskEngine`**: Engine B — Risk / Sizing / Constraints.
  - `def __init__()`
  - `def prepare_order()`
  - `def manage_positions()`: Check all open positions and generate 'update' orders (e.g. moving stops).
  - `def prepare_order()`: Build an order dict or return None if constraints block it.
