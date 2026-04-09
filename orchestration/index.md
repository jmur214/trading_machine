# Orchestration Layer
**Purpose:** The central nervous system of the execution environment.
**Architectural Role:** Binds the disconnected core engines into a unified execution pipeline. The `ModeController` provides a single abstraction interface to run the system in Backtest, Paper, or Live modes.

**Known Issues & Quirks:**
- *Hidden Feedback Loop:* `ModeController` attempts to run back-end performance reweighting silently after Paper/Live ticks.
- *Brittle Feed:* `CachedCSVLiveFeed` acts as a fragile polling loop to simulate a websocket, causing synchronization bugs.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `mode_controller.py`
**Module Docstring:** ModeController
- **Class `Mode`**: No docstring
- **Class `ExecutionAdapter`**: Base interface for live execution. Implement for Alpaca, IBKR, etc.
  - `def __init__()`
  - `def place_order()`: Place a live order. Return a fill dict compatible with PortfolioEngine.apply_fill:
- **Class `DryRunExecutionAdapter`**: Default "live" adapter that does NOT send to a broker.
  - `def __init__()`
  - `def place_order()`: For dry-run, we simulate an immediate fill at provided 'price' (post-slippage).
- **Class `AlpacaExecutionAdapter`**: Adapter that routes live/paper trades through AlpacaBroker.
  - `def __init__()`
  - `def place_order()`
- **Class `PaperParams`**: Parameters for paper trading realism.
- **Class `PaperTradeController`**: Streaming-like controller that *simulates* a live feed from historical data.
  - `def __init__()`
  - `def run()`
- **Class `LiveParams`**: Parameters for live trading.
- **Class `LiveTradeController`**: Live controller skeleton.
  - `def __init__()`
  - `def step_once()`: Process a single "latest bar" snapshot per ticker.
  - `def run_loop()`: Run a simple polling loop using a provided feed (must expose .latest_map()).
- **Class `ModeController`**: High-level orchestrator that prepares data, wires engines, and runs the chosen mode.
  - `def __init__()`
  - `def run_backtest()`
  - `def run_paper()`: Simulated streaming using historical data, with configurable fill delay.
  - `def run_live()`: Live loop using an external feed (e.g. cached CSV, Alpaca, or data stream).
- **Class `CachedCSVLiveFeed`**: Minimal live-like feed that reads cached CSVs produced by DataManager.ensure_data().
  - `def __init__()`
  - `def latest_map()`
