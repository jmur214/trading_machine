# CLI Scripts Directory
**Purpose:** Command-line wrappers to invoke specific workflows or execute tests without burying the user in Python imports.
**Architectural Role:** The user-facing execution layer.

**Key Categories:**
- *One-Button Orchestrators:* `run_autonomous_cycle.py` (Full ML Loop).
- *Execution:* `run_backtest.py`, `run_paper_loop.py`.
- *Diagnostics:* `run_healthcheck.py` (true math test), `system_validity_check.py`.
- *Documentation:* `sync_docs.py` (AST markdown generator).

*Note: Over 10 legacy proof-of-concept scripts were purged to `Archive/scripts/` during the Phase 6 Code Audit. See `docs/Audit/codebase_findings.md` for historical mapping.*

<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `analyze_edges.py`
*No public classes or functions found.*

### `audit_data_gaps.py`
- **Function `audit_file()`**: No docstring
- **Function `main()`**: No docstring

### `fetch_all.py`
- **Function `main()`**: No docstring

### `fetch_data.py`
- **Function `main()`**: No docstring

### `harvest_data.py`
- **Function `harvest()`**: Run a simulation to collect (Features, Label) pairs for ML training.

### `optimize.py`
- **Function `main()`**: No docstring

### `prune_strategies.py`
- **Class `StrategyPruner`**: The 'Reaper' of the Trading Machine.
  - `def __init__()`
  - `def prune()`
  - `def clean_logs()`: Removes old backtest log folders from data/trade_logs.

### `retrain_edges.py`
*No public classes or functions found.*

### `run.py`
*No public classes or functions found.*

### `run_autonomous_cycle.py`
- **Function `is_market_open()`**: Simple check: Mon-Fri, 9:30 AM - 4:00 PM EST.
- **Function `run_cycle()`**: No docstring

### `run_backtest.py`
- **Function `run_backtest_logic()`**: Programmatic entry point for running a backtest.
- **Function `main()`**: No docstring

### `run_diagnostics.py`
- **Function `run()`**: No docstring
- **Function `check_file()`**: No docstring

### `run_evaluator.py`
- **Function `main()`**: No docstring

### `run_evolution_cycle.py`
- **Class `AutonomousEvolution`**: The Master Learning Loop.
  - `def __init__()`
  - `def run_cycle()`

### `run_healthcheck.py`
**Module Docstring:** Trading Machine - Unified Healthcheck Script
- **Function `run_cmd()`**: Run a shell command, stream output, and return success boolean.
- **Function `run_pytests()`**: Run only the high‑signal tests that verify portfolio math + controller logic.
- **Function `run_dev_backtest()`**: Run the small/fast dev backtest. User may later customize flags.
- **Function `run_invariants()`**: Perform core snapshot/trade invariants.
- **Function `main()`**: No docstring

### `run_live.py`
*No public classes or functions found.*

### `run_paper_loop.py`
- **Function `main()`**: No docstring

### `run_shadow_paper.py`
- **Function `load_candidates()`**: Load 'Candidate' edges from the registry.
- **Function `run_shadow_session()`**: No docstring

### `start_stack.py`
- **Function `run_background()`**: No docstring
- **Function `main()`**: No docstring

### `sync_docs.py`
- **Function `parse_file()`**: No docstring
- **Function `sync_directory()`**: No docstring

### `system_validity_check.py`
- **Function `run_system_check()`**: No docstring

### `train_gate.py`
- **Function `train_gate_model()`**: Train the SignalGate model using harvested data.

### `train_signal_gate.py`
- **Function `train_gate()`**: No docstring

### `update_data.py`
- **Function `update_all_data()`**: Programmatic entry point for data updating.
- **Function `main()`**: No docstring

### `validate_active_edges.py`
- **Function `main()`**: No docstring

### `validate_complementary_discovery.py`
- **Function `validate_discovery_vocabulary()`**: No docstring

### `validate_phase2_math.py`
- **Function `test_phase2_math()`**: No docstring
