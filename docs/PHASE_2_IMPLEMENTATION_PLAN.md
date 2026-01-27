# Phase 2 Implementation Plan: The Quant Factory

> **Status**: DRAFT FOR REVIEW
> **Objective**: Implement a "Hunter-Gatherer" architecture where the machine ingests massive datasets (Fundamental + Technical), discovers "Explosion" patterns using Decision Trees, and validates them in a Shadow Live Environment.

---

## 1. The "Megadata" Layer (Milestone 1)
**Goal**: Build a unified "Feature Matrix" that aligns Fundamentals, Technicals, and Price perfectly in time.

### 1.1 Fundamental Data Loader
- **Module**: `engines/data_manager/fundamental_loader.py`
- **Logic**:
  - Ingest CSVs/APIs containing [Ticker, Date, Feature, Value].
  - **CRITICAL**: Implement "Point-in-Time" Forward Filling.
    - *Scenario*: Earnings released May 1st.
    - *Action*: Value is `NaN` before May 1st. Value is constant (or interpolated) from May 1st until next report.
    - *Prevention*: Strict "Lookahead Bias" prevention.
- **Output**: `data/processed/fundamentals.parquet`

### 1.2 The Feature Engineer
- **Module**: `engines/engine_d_research/feature_engineering.py`
- **Function**: `compute_features(ohlc_df, fund_df) -> feature_matrix`
- **Feature Set**:
  - **Growth**: `Rev_Growth`, `EPS_Accel`, `Earnings_Surprise`.
  - **Value**: `PE_Ratio`, `PS_Ratio`, `Peg_Ratio`.
  - **Vol/Momentum**: `RSI`, `ADX` (Trend Strength), `Bollinger_Width` (Squeeze), `Volume_ZScore`.
  - **Relative**: `Rel_Strength_SPY`, `Rel_Strength_Sector`.

---

## 2. The "Hunter" (Milestone 2)
**Goal**: Automate the discovery of "Explosion" rules (e.g. "Buy when PE < 15 and RSI Breakout").

### 2.1 Target Definition ("The Explosion")
- **Definition**: A "Positive Event" is defined as:
  - `Return_N_Days > X%` (e.g. +5% in 3 days)
  - `Drawdown_N_Days < Y%` (e.g. Max Drop < 2%)
- **Labeling**: The engine will pre-scan history and tag every day as `1` (Buy Opportunity) or `0` (Noise).

### 2.2 Decision Tree Scanner
- **Module**: `engines/engine_d_research/tree_scanner.py`
- **Algorithm**:
  - Use `sklearn.DecisionTreeClassifier` or `RandomForest`.
  - **Input**: The Feature Matrix (Milestone 1).
  - **Target**: The Explosion Labels (2.1).
- **Extraction**:
  - Extract the "Leaf Nodes" as human-readable rules.
  - *Example*: "Node 42: RSI > 60 & Vol_ZScore > 2.0 & PE < 20 => Win Rate 65%".

### 2.3 The "Settings" Auditor
- **Logic**: Take the discovered rule (e.g. RSI > 60) and "fuzz" it.
  - Test RSI > 55, 60, 65.
  - Test Vol_ZScore > 1.5, 2.0, 2.5.
  - Return the *Robust* sweet spot, not just the overfit peak.

---

## 3. The "Shadow Realm" (Milestone 3)
**Goal**: A safe "Live-Fire" zone where strategies must prove themselves before touching logic.

### 3.1 Shadow Broker
- **Module**: `engines/engine_c_portfolio/shadow_broker.py`
- **Behavior**:
  - Accepts "Shadow Orders".
  - Fills them at real-time market bid/ask (simulated execution).
  - Tracks "Ghost Equity" separately for each strategy.

### 3.2 Shadow Loop
- **Script**: `scripts/run_shadow_paper.py`
- **Process**:
  1.  Run daily alongside `run_live.py`.
  2.  Execute *only* the "Candidate Strategies" (from Milestone 2).
  3.  Log every trade to `data/shadow_trades.csv`.

### 3.3 The Promotion Gate
- **Logic**:
  - **Condition 1**: Live Shadow Performance > Threshold (e.g. Profit > 0).
  - **Condition 2**: Correlation to Real Portfolio < 0.8 (Don't just add more of the same).
  - **Action**: Move strategy ID from `shadow_config.json` to `active_config.json`.

---

## 4. Metrics & Standards (Milestone 4)
**Goal**: Institutional-grade scorecard.

### 4.1 New Metrics
- **Calmar Ratio**: Annual Return / Max Drawdown.
- **Kelly Fraction**: Optimal bet size.
- **Beta**: Market correlation.

---

## 5. Execution Order
1.  **Fundamental Loader**: (Because we can't hunt without data).
2.  **Feature Engineer**: (Transform data into "Huntable" signals).
3.  **Discovery Tree**: (The Hunter logic).
4.  **Shadow Loop**: (The Validation gate).
