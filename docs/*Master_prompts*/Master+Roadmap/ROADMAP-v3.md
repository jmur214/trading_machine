

# TRADING MACHINE — ROADMAP v3 (AI-OPTIMIZED)

This roadmap is a persistent, AI‑friendly guide describing **what should be built next**, **why**, and **which components are affected**.  
It is intentionally concise, modular, and strictly non‑ambiguous.

The roadmap is divided into:

1. **CORE PRIORITIES (DO FIRST)** — highest impact, unblock future work, minimal risk.  
2. **RESEARCH & FEATURE EXPANSION** — medium‑term exploration and capability upgrades.  
3. **UX & PRODUCT LAYER** — dashboard, diagnostics, user‑oriented functionality.  
4. **HARDENING & SCALE** — stability, tests, migration, performance.  
5. **EXPERIMENTAL / LONG‑TERM** — ideas that require major design work or external systems.

Each item includes:
- **Goal** — what outcome the work enables.  
- **Why it matters** — connection to system invariants or capabilities.  
- **Touchpoints** — modules/files that will be modified.  
- **Risk** — LOW / MED / HIGH code‑contract impact.

---

## 1. CORE PRIORITIES (DO FIRST)

### 1.1 Slippage + Market Impact Model  
**Goal:** Realistic fills in backtest + paper mode.  
**Why:** Execution realism affects all future strategy evaluation.  
**Touchpoints:**  
- `engines/execution/slippage.py` (new)  
- `ExecutionSimulator`  
- future: OMS adapters  
**Risk:** LOW (contract unchanged, internal logic only)

---

### 1.2 Universe Expansion (50–500 tickers)  
**Goal:** Enable multi‑asset research and realistic cross‑sectional edges.  
**Why:** Current system is single‑digit tickers; bottlenecks appear at scale.  
**Touchpoints:**  
- `DataManager` (caching, slicing, memory)  
- `BacktestController`  
- edges that assume small universes  
**Risk:** LOW/MED (performance only; no schema changes)

---

### 1.3 Configurable Risk Modes  
**Goal:** Let backtests run under conservative → aggressive risk modes.  
**Why:** Needed for regime switching, user profiles, and future live trading.  
**Touchpoints:**  
- `RiskEngine`  
- `config/*.json`  
**Risk:** LOW (parameters only)

---

### 1.4 One-Time Intraday Prep  
**Goal:** Begin migrating code to multi‑timeframe compatibility.  
**Why:** Future 5m/15m edges require early architectural decisions.  
**Touchpoints:**  
- `DataManager`  
- `BacktestController`  
**Risk:** LOW (adds optional arguments, no breaking changes)

---

## 2. RESEARCH & FEATURE EXPANSION

### 2.1 Formal Edge Registry  
**Goal:** Unified, strict interface for all edges.  
**Why:** Prevents format drift → improves predictability for AlphaEngine.  
**Touchpoints:**  
- `edge_registry.py`  
- all edge modules  
**Risk:** MED (edge contract enforcement)

---

### 2.2 New Edge Types — News, Fundamental, AI Feature  
**Goal:** Expand machine’s multi‑edge intelligence.  
**Why:** Needed for robustness, diversification, governor learning.  
**Touchpoints:**  
- `data/research/*.csv`  
- new edge modules  
**Risk:** LOW (no contract changes if registry completed first)

---

### 2.3 Cross‑Edge Research Harness  
**Goal:** Automate tests of edge combinations & decorrelation.  
**Why:** Feeds governor via evaluator recommendations.  
**Touchpoints:**  
- `research/edge_harness.py`  
- `analytics/edge_feedback.py`  
**Risk:** LOW

---

### 2.4 Per‑Edge Attribution  
**Goal:** Accurately track PnL per edge.  
**Why:** Governor accuracy depends on real returns, not heuristic MAD proxies.  
**Touchpoints:**  
- `CockpitLogger`  
- `StrategyGovernor`  
- snapshot/trade metadata  
**Risk:** MED/HIGH if schema changes (avoid unless necessary)

---

### 2.5 Tax‑Aware Analytics (post‑processing)  
**Goal:** After‑tax evaluation + suggest loss harvesting.  
**Why:** User‑level portfolio realism.  
**Touchpoints:**  
- `analytics/tax_analyzer.py` (new)  
**Risk:** LOW (analytics only)

---

## 3. UX & PRODUCT LAYER

### 3.1 Health/System Check Pipeline  
**Goal:** Single command to validate system integrity.  
**Why:** Prevents silent failures and drift.  
**Touchpoints:**  
- `scripts/run_diagnostics.py`  
- dashboard tab  
**Risk:** LOW

---

### 3.2 Recommended Trades Tab  
**Goal:** Provide “demo trades” based on current governor + signals.  
**Why:** Product value + new user onboarding.  
**Touchpoints:**  
- dashboard  
- signal formatting metadata  
**Risk:** LOW

---

### 3.3 TradingView Chart Integration  
**Goal:** Professional visualization for backtests and live mode.  
**Touchpoints:**  
- dashboard  
**Risk:** LOW

---

### 3.4 Alerts & Notifications  
**Goal:** Event‑driven updates for live/paper mode.  
**Touchpoints:**  
- new bot modules  
**Risk:** LOW

---

## 4. HARDENING & SCALE

### 4.1 Cleanup & Unified Naming  
**Goal:** Remove stale code, enforce conventions.  
**Touchpoints:** entire repo  
**Risk:** LOW (if done incrementally)

---

### 4.2 Test Suite Expansion  
**Goal:** Strong regression protection.  
**Touchpoints:**  
- `tests/`  
- golden run fixtures  
**Risk:** LOW

---

### 4.3 Config & Schema Validation  
**Goal:** Strict validation of JSON/YAML configs and trade/snapshot schemas.  
**Touchpoints:**  
- config loaders  
- CockpitLogger reading/writing  
**Risk:** HIGH (schema changes must follow MASTER_CONTEXT rules)

---

### 4.4 Versioning & Migrations  
**Goal:** Ability to evolve architecture safely.  
**Touchpoints:**  
- config version tags  
- schema migration utilities  
**Risk:** HIGH (structural changes)

---

### 4.5 Performance Optimization  
**Goal:** Large‑scale backtests (hundreds of tickers).  
**Touchpoints:**  
- DataManager  
- Backtest loop  
- ExecutionSimulator  
**Risk:** LOW (optimization only)

---

## 5. LONG‑TERM / EXPERIMENTAL

### 5.1 RL‑Based Position Sizing  
**Goal:** Reinforcement learning enhancement to risk sizing.  
**Risk:** HIGH (experimental)

### 5.2 Meta‑Learning / Ensemble Optimizers  
**Goal:** Combine edges dynamically with advanced statistical learning.  
**Risk:** MED/HIGH

### 5.3 Cross‑Asset Expansion  
**Goal:** Add crypto, FX, futures.  
**Risk:** HIGH (new contracts, exchanges, margin rules)

### 5.4 Decentralized Logging (speculative)  
**Goal:** Transparent trade logs using blockchain.  
**Risk:** HIGH

---

## UPDATE RULES

Update this roadmap only when:
- A task moves from ACTIVE → COMPLETE  
- A new bug/limitation is found  
- A new edge/feature is proposed  
- The architecture shifts (e.g., OMS v2)  

When updating:  
**keep entries short, avoid prose, tie every task to concrete modules, never modify core invariants without updating MASTER_CONTEXT-v3.md.**