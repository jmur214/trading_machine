# Engine E: Regime Intelligence

**Purpose:** Single source of truth for market environment classification. Provides 5-axis regime detection with hysteresis stabilization, named macro regime mapping with soft probabilities, and non-binding advisory hints.

**Architectural Role:** Every other engine depends on Engine E. Alpha (A) conditions forecasts on regime, Risk (B) adjusts stops and exposure, Governance (F) attributes edge performance by regime, and Discovery (D) researches regime-conditional edges.

**Key Design Decisions:**
- No `transition` state exposed to consumers. Ambiguous conditions hold the last confirmed state via hysteresis. Consumers see `transition_risk` rise and `regime_stability` drop instead.
- Soft regime probabilities are strictly more useful than hard labels. The macro regime output includes a probability distribution across all named regimes.
- Forward-looking signals (VIX term structure) detect regime changes months before realized vol (Lai 2022).
- Advisory hints are non-binding. Downstream engines may ignore them.

## Architecture

### Detection Axes

| Axis | Detector | States | Hysteresis |
|------|----------|--------|------------|
| Trend | `TrendDetector` (SMA200/50 + dual ER) | bull, bear, range | 5 bars |
| Volatility | `VolatilityDetector` (ATR + Yang-Zhang + vol ratio) | low, normal, high, shock | 3 bars (shock bypasses) |
| Correlation | `CorrelationDetector` (PC1 + sector + SPY-TLT/GLD) | dispersed, normal, elevated, spike | 3 bars (spike bypasses) |
| Breadth | `BreadthDetector` (SMA%, slope, NH-NL) | strong, narrow, recovering, weak, deteriorating | 3 bars |
| Forward Stress | `ForwardStressDetector` (VIX term structure, 3-tier) | calm, cautious, stressed, panic | 2 bars (panic bypasses) |

### Named Macro Regimes
- **robust_expansion** — Classic risk-on: bull trend, low/normal vol, strong breadth
- **emerging_expansion** — Growth but fragile: includes "Walking on Ice" pattern
- **cautious_decline** — Intermediate: deteriorating breadth, rising vol, not full panic
- **market_turmoil** — Full crisis: vol spike, correlation spike, broad selling
- **transitional** — No regime exceeds 0.40 probability

### Flow Per Bar
1. Call 5 sub-detectors -> raw (state, confidence, details)
2. Hysteresis stabilization per axis
3. Compute transition_risk and regime_stability
4. Map to named macro regime with soft probabilities
5. Query history for duration, flip-frequency, empirical transitions
6. AdvisoryEngine -> non-binding hints + coherence warnings
7. Assemble full output dict (structured + backward-compat flat keys)
8. Append to RegimeHistoryStore

### Wiring
- `ModeController` creates `RegimeDetector` and passes it to `BacktestController`
- `BacktestController` calls `detect_regime()` once per bar before Alpha signals
- Regime meta is propagated to edges via `EdgeBase.regime_meta` attribute
- Regime history is saved to `data/trade_logs/{run_id}/regime_history.csv` at end of run

## File Reference

### `regime_detector.py`
- **Class `RegimeDetector`**: Coordinator holding 5 sub-detectors, 5 hysteresis filters, advisory engine, and history store.
  - `detect_regime(benchmark_df, data_map, now)` -> full output dict
  - `reset()` -> clears all state between backtest runs

### `regime_config.py`
- **Class `RegimeConfig`**: Dataclass loaded from `config/regime_settings.json`

### `hysteresis.py`
- **Class `HysteresisFilter`**: Generic state machine with crisis bypass

### `advisory.py`
- **Class `AdvisoryEngine`**: Dynamic weights, coherence checks, duration modulation, macro regime mapping

### `regime_history.py`
- **Class `RegimeHistoryStore`**: Duration tracking, flip frequency, empirical transition matrix

### `detectors/`
- `trend_detector.py` — TrendDetector
- `volatility_detector.py` — VolatilityDetector
- `correlation_detector.py` — CorrelationDetector
- `breadth_detector.py` — BreadthDetector
- `forward_stress_detector.py` — ForwardStressDetector

## Configuration
All tunable parameters in `config/regime_settings.json`.


<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->

## Auto-Generated Code Reference

*This section is automatically built by `scripts/sync_docs.py`. Do not edit manually.*

### `advisory.py`
**Module Docstring:** AdvisoryEngine — generates non-binding advisory hints from stabilized regime state.
- **Class `AdvisoryEngine`**: Generates non-binding advisory hints from stabilized regime state.
  - `def __init__()`
  - `def generate()`: Generate advisory hints and macro regime info.

### `hmm_classifier.py`
**Module Docstring:** HMMRegimeClassifier — Engine E confidence-aware regime detection.
- **Class `HMMTrainingArtifact`**: Persisted HMM model + metadata. Pickled for production inference.
- **Class `HMMRegimeClassifier`**: 3-state Gaussian HMM regime classifier.
  - `def __init__()`
  - `def fit()`: Fit Gaussian HMM on a feature DataFrame.
  - `def predict_proba_at()`: Posterior P(state | features at row) — temporally smoothed.
  - `def predict_proba_sequence()`: Posterior P(state | x_{1..T}) for a full feature sequence.
  - `def score()`: Log-likelihood of X_df under the fitted model.
  - `def confidence_from_proba()`: Map a posterior dict to a [0, 1] confidence scalar.
  - `def save()`: Pickle full state to disk.
  - `def load()`: Load pickled model from disk.

### `hysteresis.py`
**Module Docstring:** HysteresisFilter — prevents single-bar regime flips.
- **Class `HysteresisFilter`**: State machine that stabilizes raw detector outputs.
  - `def update()`: Process a new raw observation and return the stabilized state.
  - `def is_transitioning()`: True if there is an unconfirmed pending state.
  - `def transition_progress()`: Fraction of confirmation bars accumulated (0.0 – 1.0).
  - `def reset()`: Clear all state. Called between backtest runs.

### `macro_features.py`
**Module Docstring:** macro_features — regime-input features for HMMRegimeClassifier.
- **Function `build_feature_panel()`**: Build the daily feature panel for HMM regime detection.
- **Function `latest_feature_row()`**: Return the feature row at or before `as_of` (no look-ahead).
- **Function `resample_feature_panel()`**: Aggregate a daily feature panel to a slower cadence.
- **Function `build_multires_panels()`**: Build daily, weekly, and monthly feature panels.

### `multires_hmm.py`
**Module Docstring:** MultiResolutionHMM — runs daily / weekly / monthly HMM regime classifiers
- **Class `CadenceResult`**: Per-cadence regime read at a single point in time.
  - `def to_dict()`
- **Class `MultiResHMMArtifacts`**: Paths to the three persisted HMM models for this multi-res ensemble.
  - `def default()`
- **Class `MultiResolutionHMM`**: Orchestrator for daily / weekly / monthly HMM classifiers.
  - `def __init__()`
  - `def classify_at()`: Classify the regime at `timestamp` across all three resolutions.
  - `def to_advisory_dict()`: Serialize classify_at output to the advisory output schema.
  - `def loaded_cadences()`: Tuple of cadence names whose classifiers loaded successfully.
  - `def panel()`: Expose a panel for testing / backtest scripts.
  - `def classifier()`: Expose the underlying classifier for the given cadence.

### `regime_config.py`
**Module Docstring:** RegimeConfig — typed configuration for Engine E.
- **Class `TrendConfig`**: No docstring
- **Class `VolatilityConfig`**: No docstring
- **Class `CorrelationConfig`**: No docstring
- **Class `BreadthConfig`**: No docstring
- **Class `ForwardStressConfig`**: No docstring
- **Class `AdvisoryConfig`**: No docstring
- **Class `HMMConfig`**: Confidence-aware HMM regime classifier (additive to 5-axis detector).
- **Class `MultiResHMMConfig`**: Multi-resolution HMM (Workstream C slice 2 — 2026-05).
- **Class `TransitionWarningConfig`**: Transition-warning detector (Workstream C slice 2 — 2026-05).
- **Class `RegimeConfig`**: No docstring
  - `def from_json()`: Load config from JSON file. Falls back to defaults if file missing.

### `regime_detector.py`
**Module Docstring:** RegimeDetector — Engine E coordinator.
- **Class `RegimeDetector`**: 5-axis market regime detector with hysteresis, advisory hints,
  - `def __init__()`
  - `def detect_regime()`: Run full 5-axis regime detection for the current bar.
  - `def history()`: Access the regime history store.
  - `def reset()`: Clear all internal state. Must be called between backtest runs.

### `regime_history.py`
**Module Docstring:** RegimeHistoryStore — tracks regime state over time for duration,
- **Class `RegimeHistoryStore`**: In-memory store that grows one row per bar.
  - `def __init__()`
  - `def append()`: Append a single bar's regime snapshot.
  - `def axis_durations()`: Consecutive bars in current state per axis.
  - `def flip_counts()`: Count state transitions per axis in the last `lookback` bars.
  - `def get_transition_matrix()`: Compute empirical transition probabilities between macro regimes.
  - `def to_dataframe()`: Export history as a DataFrame for analysis or persistence.
  - `def save_csv()`: Save history to CSV.
  - `def reset()`: Clear all state. Called between backtest runs.

### `transition_warning.py`
**Module Docstring:** TransitionWarningDetector — fires when an HMM regime is *transitioning*,
- **Class `TransitionWarningConfig`**: Hyperparameters for the transition-warning detector.
- **Class `TransitionWarningRead`**: Per-bar transition-warning diagnostic + binary fire.
  - `def to_dict()`
- **Class `TransitionWarningDetector`**: Streaming + batch transition warning detector.
  - `def __init__()`
  - `def detect_at()`: Detect transition warning at a single bar.
  - `def detect_sequence()`: Stream the detector through a full posterior sequence.
