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
