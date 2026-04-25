# Trading Machine: Project Context & Philosophy

## What is the Trading Machine?
The Trading Machine is a professional-grade, autonomous algorithmic trading system. Its ultimate goal is to discover market edges, actively learn, compound returns, manage risk, and significantly outperform the market. It merges research, backtesting, and live execution into a single, cohesive, self-evolving pipeline.

The Trading Machine is a modular Python trading research and execution framework. It is intended to be a full-spectrum, self-updating trading lab that merges algorithmic precision with human-level transparency. 

It is designed to eventually function like a "Schwab Intelligent Portfolio" (SIP) crossed with an adaptive Quant Fund. It does not just hold passive ETFs; it actively generates "signals" across different sleeves of capital (Technical, Fundamental, True Edge) and dynamically rebalances its trust in those strategies based on how well they perform in current market regimes.

## The 6-Engine Architecture
The system is built on six core engines:

1. **Engine A: Alpha Generation (The Brain)** — `engines/engine_a_alpha/`
   - Responsible for identifying opportunities (Signals).
   - Utilizes pluggable "Edges" (strategies based on mean reversion, momentum, sentiment, or news).
   - Reads edge weights from Governance (F) and regime state from Regime (E) to produce ranked signals.
   - Houses `SignalGate` (ML confidence gating) in `engine_a_alpha/learning/`.
   - Applies True Edge combination rules (discovered by D) during ensemble aggregation.

2. **Engine B: Risk & Order Placement (The Safety Net & Executor)** — `engines/engine_b_risk/`
   - Converts theoretical signals into actionable orders and executes them with the broker.
   - Enforces position sizing (e.g., ATR-based, volatility-adjusted, Kelly criterion).
   - Manages strict stop-loss, take-profit rules, and portfolio exposure limits.
   - Reads regime state from E to adjust exposure limits in volatile regimes.

3. **Engine C: Portfolio Management (The Accountant)** — `engines/engine_c_portfolio/`
   - *Planned:* Will manage portfolio "Sleeves", breaking the single custodial account into virtual sub-accounts (e.g., specialized equity, fixed-income, or core/satellite sleeves) that can be tracked and managed independently.
   - Keeps track of global account balance, equity, realized/unrealized P&L, and position states.
   - Does *not* generate signals or place orders; strictly manages the holistic portfolio picture.

4. **Engine D: Discovery & Evolution (The Lab)** — `engines/engine_d_discovery/`
   - Autonomously hunts for new edges via a two-stage ML pipeline: LightGBM feature importance screening followed by shallow Decision Tree rule extraction.
   - Evolves composite edge genomes through a full genetic algorithm (tournament selection, single-point crossover, Gaussian mutation, elitism) with persistent population across cycles.
   - Feature engineering produces 40+ features across 7 categories: technical, fundamental, calendar/seasonality, microstructure, inter-market, regime context, and cross-sectional.
   - Validates candidates through a 4-gate pipeline: quick backtest (Sharpe > 0) -> PBO robustness (50 paths, survival > 0.7) -> WFO degradation (OOS >= 60% IS) -> Monte Carlo significance (p < 0.05).
   - Outputs validated candidate edge specs to `edges.yml` for Governance (F) to activate.
   - Does NOT manage live edge weights or lifecycle — that's Governance.

5. **Engine E: Regime Intelligence (The Weather Station)** — `engines/engine_e_regime/`
   - Single source of truth for market environment classification.
   - Detects market regime (trend direction, volatility level) via SMA/ATR/Efficiency Ratio on SPY.
   - Outputs structured regime object + non-binding advisory policy hints.
   - Called once per bar by ModeController; regime state is passed to A, B, and F as a parameter.

6. **Engine F: Governance (The Judge)** — `engines/engine_f_governance/`
   - Fully autonomous edge lifecycle manager.
   - Tracks per-edge performance metrics (Sharpe, Sortino, MDD, win rate) via rolling windows.
   - Dynamically reweighs edge capital allocation via EMA-smoothed scoring.
   - Manages edge lifecycle: candidate → active → paused → retired.
   - Global kill-switch: disables edges exceeding MDD threshold (-25%) or with rolling Sharpe ≤ 0. Active in the normal governor weight-update path.
   - **Per-edge-per-regime kill-switch: architecture in place but runtime-disabled (2026-04-23)** — three walk-forward splits, net-negative on 2 of 3 (Split A eval 2023-2024 -0.50 Sharpe, Split B eval 2024-2025 +0.18, Split C eval 2025 -0.21). The positive outlier doesn't cleanly correspond to a regime-type trigger. Mechanism is not reliably additive. `regime_conditional_enabled: false` in `config/governor_settings.json`. Do not re-enable; consider redesigning the regime signal source (coarser grouping, continuous features, or portfolio-level exposure overlay). See `docs/Progress_Summaries/lessons_learned.md` 2026-04-23 and memory `project_regime_conditional_activation_blocked_2026_04_23.md`.
   - **Autonomous lifecycle: VALIDATED end-to-end (2026-04-25)** — `engines/engine_f_governance/lifecycle_manager.py` implements active ↔ paused → retired transitions with evidence gates (≥100 trades, ≥90 days, benchmark-relative Sharpe margin), cycle caps, and audit trail (`data/governor/lifecycle_history.csv`). Soft-pause via 0.25x weight multiplier so paused edges keep trading and the revival gate has data. Has correctly paused 2 of 14 active edges (`atr_breakout_v1`, `momentum_edge_v1`) on the 109-ticker universe based on real evidence, with measurable risk-adjusted improvement (-13.27% MDD → -9.03%). 21 regression tests in `tests/test_edge_registry.py` + `tests/test_lifecycle_manager.py` enforce the `edges.yml` Write Contract. See `memory/project_lifecycle_vindicated_universe_expansion_2026_04_25.md`.
   - Outputs `edge_weights.json` consumed by Alpha (A) at runtime.

## Supporting Infrastructure & Ecosystem
While the 6 Engines govern trading logic, the broader system heavily relies on:
- **Data Ingestion & Management:** Standardizes external market/alternative data into clean, highly optimized formats (e.g., Parquet).
- **The Backtester:** A rigorous, high-fidelity historical simulator that replays data to validate edge hypotheses, built with strict cross-validation guardrails to prevent overfitting.
- **Shared Utilities:** `core/metrics_engine.py` provides centralized metrics computation (Sharpe, Sortino, Calmar, VaR, Kelly) used by both Discovery and Governance.

## Orchestration Layer
The `ModeController` (`orchestration/mode_controller.py`) binds the engines together. It calls Engine E once per bar and passes the regime state to downstream engines. It allows the exact same logic pipeline to run in:
- **Backtest Mode:** Slices data bar-by-bar locally.
- **Paper Mode:** Streams data via websockets and simulates execution.
- **Live Mode:** Plumbs the final Portfolio engine diffs straight to Broker REST APIs.

## Shared State: `edges.yml` Write Contract
Both Discovery (D) and Governance (F) write to `data/governor/edges.yml`:
- **D writes:** New entries (candidate specs, params, metadata, source info)
- **F writes:** `status` field changes (candidate → active → paused → retired), weight assignments
- Neither engine deletes the other's fields.

## Current State

| Component | Status | Notes |
|-----------|--------|-------|
| Engine A (Alpha) | ✅ Functional | Signal filtering may need to be loosened |
| Engine B (Risk) | ✅ Functional | ATR sizing, exposure caps, trailing stops |
| Engine C (Portfolio) | ✅ Functional | Ledger/Allocation wall not yet enforced |
| Engine D (Discovery) | ✅ Functional | Two-stage ML (LightGBM + DTree), GA evolution, 4-gate validation, 40+ features |
| Engine E (Regime) | ✅ Functional | RegimeDetector standalone; advisory hints planned |
| Engine F (Governance) | ✅ Functional | Autonomous edge lifecycle + weight management |
| Data Manager | ✅ Functional | Alpaca + cache + normalization |
| Backtester | ✅ Functional | Walk-forward capable |
| Dashboard (V2) | ✅ Functional | V1 deprecated |
| Live Trading | ⚠️ Scaffolded | Broker interface exists, not fully tested |

## What is an Edge?
At its core, an **Edge** is simply *a pattern that produces profitable trades*. It is not restricted to complex mathematical equations; it is a vast net of independent, real-world anomalies that can be cataloged and exploited. It is a repeatable factor that lets you consistently make money over many trades, and produces a positive expected value (EV).

There are **6 Core Edges** the system must track:
1. **Price / Technical:** Patterns (e.g., RSI bounces, Bollinger Band breakouts, mean reversion, and trend following) that are statistically more likely to work than random chance. *Implemented: RSI Bounce, ATR Breakout, Bollinger Reversion, Momentum, SMA Cross.*
2. **Fundamental:** Value discrepancies, balance sheet strength, growth metrics, or DCF models that identify mispriced assets relative to their intrinsic worth. *Implemented: FundamentalRatio, ValueTrap.*
3. **News-Based / Event-Driven:** Real-world event triggers (e.g., political tweets, macroeconomic shifts, specific corporate lawsuits). *Partial: VADER sentiment exists; EarningsVolEdge handles pre/post-earnings drift.*
4. **Stat/Quant:** Pure historical probability vectors (e.g., seasonal patterns, overnight gap fills, option flow anomalies). *Implemented: SeasonalityEdge (day-of-week / month-of-year), GapEdge (overnight gap fill), VolumeAnomalyEdge (spike reversal / dry-up breakout).*
5. **Behavioral/Psychological:** Exploiting human panic, herding, or pre/post-earnings options volatility vs. market sentiment. *Implemented: PanicEdge (multi-condition extreme reversion), HerdingEdge (cross-sectional contrarian), EarningsVolEdge (vol compression / PEAD).*
6. **"Grey":** Information that is almost like insider trading without being illegal, just less common/priced-in information (e.g., tracking politician stock purchases, or non-public corporate hacks). *Not yet implemented — abstract data source stubs planned.*
- **Evolutionary / Synthetic:** CompositeEdge genomes combine genes from any category above. The GA discovers cross-category combinations (e.g., "buy when RSI < 30 AND overnight gap down AND gold rising"). RuleBasedEdge captures patterns from decision tree scanning.
- **Execution:** While another form of an edge, outside of proper coding, we will not be able to compete with HFTs and large firms on this so it will not be a focus. However, it can be seen as gaining fractions of a percent through smarter routing or lower slippage.

**The "True Edge"**:
The ultimate goal of the system is to combine these individual edges. The holy grail of the system, a "True Edge", does not rely on a single edge; but instead activates when multiple independent categories (e.g., a strong technical setup aligns perfectly with positive news sentiment and favorable macro conditions) align simultaneously to create a high-conviction, massive-win-rate signal.


## The Long-Term Vision
- **The "Real Fund Manager" Mentality:** The system must act as a true institutional fund manager—prioritizing deep architectural planning over rushed coding, and brutal realism regarding system capabilities.
- **Live Operations:** Seamlessly transition from Backtesting (local CSVs) -> Paper Trading (Alpaca) -> Live Execution with real capital.
- **Self-Evolution:** Use machine learning to detect market regimes (high vol, low vol, trend, chop) and autonomously discover or prioritize edges.
- **NOT overfit:** The system must be designed to avoid overfitting to historical data using techniques such as cross-validation and walk-forward analysis.
- **Explainability:** Provide clear UI attribution (Cockpit Dashboard) detailing exactly *why* a trade fired, and *which* edge was responsible.
- **Resilience:** Operate with institutional-grade safety guardrails preventing catastrophic drawdowns.
