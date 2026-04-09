# Engine A: Alpha Generation
**Purpose:** This engine is responsible for computing trading signals (-1.0 to 1.0) using technical, fundamental, and alternative edges. 
**Architectural Role:** It acts as the signal factory. The monolith class `AlphaEngine` handles config loading, instantiates edge instances, dynamically normalizes data, and scores the asset universe.

**Known Issues & Quirks:**
- *The God Class Problem:* `AlphaEngine` is an 800+ line monolith doing too much.
- *Strict Separation Violations:* It currently imports `RegimeDetector` from Engine D (Research).
- *Math Crashes:* The input arrays supplied by `DataManager` currently cause pandas-related TypeErrors deep inside Edge math when testing the live execution pipeline.

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `alpha_engine.py`
**Module Docstring:** AlphaEngine (Engine A)
- **Class `AlphaConfig`**: Configuration container for AlphaEngine.
- **Class `AlphaEngine`**: Main class orchestrating Edge collection -> processing -> aggregation -> signals.
  - `def __init__()`
  - `def generate_signals()`: Main entry point (used by BacktestController / PaperTradeController / LiveTradeController).
- **Function `is_info_enabled()`**: No docstring

### `edge_base.py`
- **Class `EdgeBase`**: Minimal contract all edges must follow.
  - `def __init__()`
  - `def set_params()`
  - `def compute_signals()`

### `edge_registry.py`
- **Class `EdgeSpec`**: No docstring
- **Class `EdgeRegistry`**: Lightweight file-backed registry for edges.
  - `def __init__()`
  - `def register()`
  - `def set_status()`
  - `def list()`
  - `def list_modules()`: Returns module names for edges with the specified status.
  - `def list_active_modules()`: Returns module names for edges whose status == 'active'.
  - `def get()`
  - `def ensure()`

### `edge_template.py`
- **Class `EdgeTemplate`**: Interface for edges that support autonomous parameter generation.
  - `def get_hyperparameter_space()`: Returns a dictionary defining the parameter space.
  - `def sample_params()`: Generates a valid random parameter set based on the space.

### `ml_predictor.py`
- **Class `MLPredictor`**: Tier 1 Feature: Machine Learning based signal generation.
  - `def __init__()`
  - `def train()`: Train the model on historical data.
  - `def predict()`: Predict probability of Up move for the latest bar.

### `signal_collector.py`
- **Class `SignalCollector`**: No docstring
  - `def __init__()`
  - `def collect()`: Returns:

### `signal_diagnostics.py`
*No public classes or functions found.*

### `signal_formatter.py`
**Module Docstring:** SignalFormatter
- **Class `SignalFormatter`**: No docstring
  - `def __init__()`
  - `def to_side_and_strength()`

### `signal_processor.py`
**Module Docstring:** SignalProcessor
- **Class `RegimeSettings`**: No docstring
- **Class `HygieneSettings`**: No docstring
- **Class `EnsembleSettings`**: No docstring
- **Class `SignalProcessor`**: No docstring
  - `def __init__()`
  - `def process()`: Returns a dict per ticker with normalized & aggregated score and details.
