

Trading Machine – MASTER_CONTEXT-v3 (AI-Facing)

> This document is for AI assistants only.  
> Goal: keep you grounded in how Trading Machine works, what must never drift, and how core data structures look.  
> Use this as your “single source of truth” when reasoning about or editing the system.

---

## 0. How to Use This Document (for AI)

When working on the Trading Machine repo:

1. **Load this file first** and keep it in context whenever possible.
2. **Align to these contracts and invariants** before trusting anything inferred from local code.
3. **If repo code disagrees with this doc**, treat the disagreement as a **bug or migration in progress**, not a license to invent new behavior.
4. **Do not invent new fields or columns** for core contracts unless:
   - You explicitly call out that you are proposing a change, and
   - You also update all affected schemas, tests, and logging/documentation.
5. If you are unsure, **say you are unsure** and ask the user to confirm intent. Avoid hallucinating missing pieces.

The rest of this document is structured to be compact but precise:

- §1 – Identity & Modes
- §2 – Golden Invariants
- §3 – Core Data Contracts (Python-style + tables)
- §4 – Engine & Pipeline Overview
- §5 – Edge & Governor Contracts
- §6 – Logging & File Layout
- §7 – Safe-Change vs. Dangerous-Change Rules

---

## 1. Identity & Modes

**Name:** `trading_machine`  
**Domain:** Quantitative trading research + backtesting + (future) paper/live trading.  
**Language:** Python.  
**Core loop:** Daily bar backtesting today; design anticipates multi-asset, multi-timeframe extension.

**Primary modes (all share the same core logic):**

- `backtest` – historical bars, ExecutionSimulator, full logging to CSV/DB.
- `paper` – Alpaca / broker API for execution, simulated capital, real-time data (planned/partial).
- `live` – true live trading via OMS + broker adapter (future).

All modes must use **the same Order → Fill → Position → Snapshot contracts**. Only data sources and execution adapters change.

---

## 2. Golden Invariants (Do Not Break)

These are the most important rules. If you change code that violates one of these, you must treat it as a bug.

1. **Equity Accounting**
   - At every snapshot:  
     `equity ≈ cash + Σ(position.qty * last_price)` within floating-point tolerance.
   - **Realized PnL changes only on exits / partial closes / flips**, never on mark-to-market.

2. **Run Isolation**
   - Every run has a **unique `run_id` (UUID-like string)**.
   - All trades and snapshots for that run **must carry that run_id**.
   - No run is allowed to overwrite or merge into another’s logs.

3. **One Snapshot per Bar**
   - For a given `run_id` and timestamp (bar), there must be **exactly one** portfolio snapshot.
   - No duplicate timestamps; no missing bars within the configured backtest range (for traded universe).

4. **Unified Edge API**
   - Edges emit **numeric scores per ticker** via `compute_signals(...) -> dict[str, float]`  
     or structured signals via `generate_signals(...) -> list[dict]`.
   - Alpha/SignalCollector must convert everything into a **normalized ticker→score mapping** plus optional metadata.
   - Do not introduce new ad-hoc edge signatures.

5. **Order/Fill/Position Contracts**
   - All engines must exchange orders, fills and positions using the **canonical structures in §3**, not arbitrary dicts.
   - Adapters (sim vs broker) can extend with extra metadata but **must preserve the core fields & meanings**.

6. **Stable Logging Schema**
   - `trades.csv` and `portfolio_snapshots.csv` schemas are **stable over time**.
   - New columns are allowed only if:
     - They are documented in §6, and
     - Logger, analytics, tests, and dashboards are kept in sync.

7. **Edge Attribution**
   - Every trade/fill must be attributed to an `edge_id`.
   - Snapshots must track `open_pos_by_edge` so per-edge performance can be computed.

8. **Risk & Safety**
   - RiskEngine must enforce configured limits (per-trade risk, max gross exposure, max positions, etc.).
   - Debug / experimental code **must not bypass risk controls by default**.

9. **Purity of Edges**
   - Edge code should be **pure** in backtests: no uncontrolled I/O, no global mutable state, no network calls in the hot loop.
   - Heavy research/ML work should be **precomputed** and joined in via data files.

---

## 3. Core Data Contracts (Hybrid: Python Stubs + Tables)

These are **soft schemas**: they define the *shape and meaning* of data.  
AI assistants should **treat these as canonical** and avoid inventing new fields.

### 3.1 Order / Fill / Position (in-memory OMS contract)

Use this as the conceptual model, even if code is still using dicts.

```python
from typing import Literal, TypedDict, Optional, Dict
from datetime import datetime

Side = Literal["buy", "sell", "short", "cover"]
OrderType = Literal["market"]  # future: "limit", "stop", "stop_limit"
TimeInForce = Literal["day", "gtc"]

class Order(TypedDict, total=False):
    run_id: str                  # propagated from controller
    timestamp: datetime          # decision time (bar t)
    ticker: str
    side: Side                   # semantic: direction of position change
    qty: float                   # shares/contracts; sign is NOT used for side
    order_type: OrderType        # currently "market" in v1
    time_in_force: TimeInForce   # usually "day"
    stop: float                  # stop-loss price (optional)
    take_profit: float           # take-profit price (optional)
    edge_id: str                 # source edge
    meta: dict                   # free-form metadata (debug / explanations)

class Fill(TypedDict, total=False):
    run_id: str
    timestamp: datetime          # execution time (typically next bar open)
    ticker: str
    side: Side                   # must be consistent with resulting position change
    qty: float
    fill_price: float
    commission: float
    trigger: Literal["entry", "exit", "stop", "target", "flip"]
    edge_id: str
    meta: dict

class Position(TypedDict, total=False):
    ticker: str
    qty: float                   # +long, -short; 0 means flat
    avg_price: float
    edge_id: str                 # primary source edge for this position
    stop: float
    take_profit: float
    meta: dict                   # edge-specific metadata (e.g., regimes, indicators)
```

**Key rules:**

- `qty` is always non-negative in **Order**, but in **Position** it may be signed (long/short).  
- `side` controls intent (`buy`/`sell`/`short`/`cover`); do not use sign tricks.  
- `fill_price` is the actual execution price including slippage (simulated or real).  
- `trigger` distinguishes normal exits vs stop/target vs flip.

---

### 3.2 Portfolio Snapshot (in-memory)

```python
class Snapshot(TypedDict, total=False):
    run_id: str
    timestamp: datetime
    cash: float
    market_value: float          # Σ qty * price over all open positions
    equity: float                # cash + market_value
    realized_pnl: float
    unrealized_pnl: float
    gross_exposure: float        # Σ |qty * price|
    net_exposure: float          # Σ qty * price
    positions: Dict[str, Position]      # keyed by ticker
    open_pos_by_edge: Dict[str, int]    # edge_id → count of open positions
```

**Accounting rules:**

- `equity` must equal `cash + market_value` (up to float tolerance).
- `realized_pnl` **only changes when a position is reduced/closed**.
- `unrealized_pnl` is mark-to-market at the snapshot prices.

---

### 3.3 Trade Log Row (trades.csv)

| Column         | Type      | Required | Notes                                           |
|----------------|-----------|----------|-------------------------------------------------|
| run_id         | str       | yes      | Unique per run; same as controller run_id       |
| timestamp      | datetime  | yes      | Execution time                                  |
| ticker         | str       | yes      | Symbol                                          |
| side           | str       | yes      | "buy" / "sell" / "short" / "cover"             |
| qty            | float     | yes      | Executed quantity                               |
| fill_price     | float     | yes      | Execution price incl. slippage                  |
| commission     | float     | yes      | Fee (0 allowed)                                 |
| realized_pnl   | float     | yes      | PnL realized on this fill (0 for opens)        |
| edge_id        | str       | yes      | Edge that generated the order                   |
| sleeve         | str       | no       | For sleeve-based portfolio v2 (core/tactical/exp) |
| meta           | str/json  | no       | JSON-encoded metadata (optional)                |

**AI rule:**  
Do **not** add new columns casually. If proposing a new column, also propose:

- Logger update,
- Analytics update,
- Schema update in this table.

---

### 3.4 Snapshot Log Row (portfolio_snapshots.csv)

| Column            | Type      | Required | Notes                                              |
|-------------------|-----------|----------|----------------------------------------------------|
| run_id            | str       | yes      | Run identifier                                     |
| timestamp         | datetime  | yes      | Snapshot bar time                                  |
| cash              | float     | yes      | Cash balance                                       |
| market_value      | float     | yes      | Σ qty * price                                      |
| equity            | float     | yes      | cash + market_value                                |
| realized_pnl      | float     | yes      | Cumulative realized PnL                            |
| unrealized_pnl    | float     | yes      | Cumulative unrealized PnL                          |
| gross_exposure    | float     | yes      | Σ |qty * price|                                    |
| net_exposure      | float     | yes      | Σ qty * price                                      |
| positions         | str/json  | yes      | JSON-encoded positions dict                        |
| open_pos_by_edge  | str/json  | yes      | JSON: edge_id→open positions count                 |
| positions_count   | int       | no       | Derived; number of open positions                  |

**AI rule:**  
There must be **exactly one row per (run_id, timestamp)**.

---

## 4. Engine & Pipeline Overview (Minimal but Precise)

This is the **logical flow**; details live in repo modules but this is the authoritative shape.

1. **DataManager**
   - Input: list of tickers, date range, timeframe, env/config.
   - Output: `dict[str, pd.DataFrame]` of OHLCV+features, clean datetime index.
   - Responsibilities:
     - Fetch from Alpaca / other sources or local cache.
     - Normalize columns; compute ATR and any basic indicators needed system-wide.
     - Handle caching and incremental updates.

2. **AlphaEngine (Engine A)**
   - Input: `slice_map` (ticker→DataFrame up to `now`), `now`, governor weights, config.
   - Output: list of **signals** (per-ticker desired side/strength + meta).
   - Pipeline:
     - `SignalCollector` → collects edge scores / signals.
     - `SignalProcessor` → normalizes, filters, regime-gates, ensembles.
     - `SignalFormatter` → converts scores into discrete signals.

3. **RiskEngine (Engine B)**
   - Input: signals, portfolio state (equity, positions), recent prices, risk config.
   - Output: list of **Order** objects (or dicts matching Order contract).
   - Responsibilities:
     - Check warmup, cooldown, max positions, exposure limits.
     - Compute size via risk-per-trade and ATR/volatility.
     - Attach stop and take-profit levels.
     - Enforce portfolio-level constraints.

4. **ExecutionSimulator**
   - Input: orders, price bars (t+1), previous close, slippage config.
   - Output: list of **Fill** objects.
   - Responsibilities:
     - Execute at next-bar open (fallback close), apply slippage and commission.
     - Evaluate stops/targets intrabar with conservative ordering.
     - Tag fills with triggers (`entry`, `exit`, `stop`, `target`, `flip`).

5. **PortfolioEngine (Engine C)**
   - Input: fills, current positions, price map for snapshot.
   - Output: updated positions + **Snapshot**.
   - Responsibilities:
     - Apply fills, update cash, positions, realized PnL.
     - Enforce equity accounting invariants.
     - Maintain `open_pos_by_edge`.

6. **CockpitLogger**
   - Input: fills and snapshots.
   - Output: `trades.csv`, `portfolio_snapshots.csv` under `data/trade_logs/<run_id>/`.
   - Responsibilities:
     - Ensure schema, no NaNs in critical fields.
     - Maintain per-run directories + optional promoted flat files.
     - Flush to disk safely.

7. **Analytics & EdgeFeedback**
   - Input: latest trades & snapshots for a given run.
   - Output: per-edge metrics (`edge_metrics.json`), updated weights (`edge_weights.json`).
   - Responsibilities:
     - Compute portfolio & per-edge performance metrics.
     - Feed metrics into governor logic.
     - Persist history for transparency.

8. **StrategyGovernor (Engine D)**
   - Input: per-edge performance metrics, current configuration.
   - Output: normalized weights for each `edge_id`.
   - Responsibilities:
     - Map Sharpe / drawdown / other metrics → weights.
     - Optionally apply decorrelation penalties and sleeve budgets.
     - Smooth updates over time (EMA).

9. **BacktestController**
   - Orchestrates all of the above per bar.
   - Ensures:
     - Correct bar loop,
     - `run_id` propagation everywhere,
     - Initial and final snapshots exist,
     - One snapshot per bar.

---

## 5. Edge & Governor Contracts (AI-Safe Version)

### 5.1 Edge Interface (conceptual)

```python
from typing import Dict, List, TypedDict
from pandas import DataFrame
from datetime import datetime

class EdgeSignal(TypedDict, total=False):
    ticker: str
    side: Literal["long", "short", "exit", "none"]
    strength: float         # 0–1 magnitude
    score: float            # raw score (can be same as strength * sign)
    edge_id: str
    meta: dict

def compute_signals(data_map: Dict[str, DataFrame], now: datetime) -> Dict[str, float]:
    ...

def generate_signals(data_map: Dict[str, DataFrame], now: datetime) -> List[EdgeSignal]:
    ...
```

Rules:

- **At least one** of `compute_signals` or `generate_signals` must exist.
- `compute_signals` → numeric scores, `generate_signals` → richer dict; collector must map these into a consistent internal representation.
- **Edges must not**:
  - Read/write global mutable state in the hot loop.
  - Perform blocking network calls in the hot loop.
  - Depend on external time aside from `now`.

### 5.2 Governor State Files

- `data/governor/edge_weights.json` – `edge_id → weight (float)`.
- `data/governor/edge_metrics.json` – `edge_id → metrics dict`.
- Optional history log for debugging / dashboard.

AI rule: Do not silently change the format of these JSONs. If proposing a change, keep them **backward compatible** where possible.

---

## 6. Logging & File Layout (Paths + Schemas)

### 6.1 Directory Layout (relevant to AI)

- `scripts/`
  - `run_backtest.py` – main CLI entry for backtests.
  - (future) `run_healthcheck.py` – canonical health/diagnostic script.
- `backtester/`
  - `backtest_controller.py` – main orchestrator.
- `engines/`
  - `engine_a_alpha/` – edges, signal collector/processor/formatter.
  - `engine_b_risk/` – risk engine logic.
  - `engine_c_portfolio/` – portfolio engine implementation.
  - `execution_simulator.py` or similar – backtest fills.
  - `data_manager/` – historical data management.
- `cockpit/`
  - `logger.py` – trade/snapshot logger.
  - `dashboard.py` – UI (Dash/Plotly) (may be partial).
- `analytics/`
  - `edge_feedback.py` – governor feedback & metrics.
  - `metrics.py` – performance metric computation.
- `data/`
  - `trade_logs/<run_id>/trades.csv`
  - `trade_logs/<run_id>/portfolio_snapshots.csv`
  - `governor/edge_weights.json`
  - `governor/edge_metrics.json`
  - `research/` – research outputs.
  - `processed/` – cached OHLCV data.

AI rule:  
When writing new code that depends on these paths, prefer **config-driven** paths if they already exist; otherwise, keep this layout consistent.

---

## 7. Change Discipline (What AI Can / Cannot Freely Change)

When proposing or applying changes:

### 7.1 Safe / Local Changes (generally OK)

- Refactor **internal computation** inside one engine (e.g., improvement to RiskEngine sizing) **without** changing:
  - Order/Fill/Snapshot field names or semantics,
  - Logger schemas.
- Add **new helper functions** that respect existing contracts.
- Optimize performance **without changing outputs** (modulo numerical noise).
- Improve docstrings, comments, tests.

### 7.2 Changes Requiring Extra Care (ask the user / update schemas)

- Adding fields to:
  - `Order`, `Fill`, `Position`, `Snapshot`,
  - `trades.csv`, `portfolio_snapshots.csv`,
  - governor JSON files.
- Changing how:
  - `run_id` is generated or propagated,
  - equity / PnL are computed,
  - edge IDs are assigned or logged.

If you recommend such a change:

1. Explicitly state:  
   **“This changes a core contract (X). It will require updating logger, analytics, tests, and this MASTER_CONTEXT-v3 doc.”**
2. Provide a migration plan (search points in repo, tests to update).

### 7.3 Hard NO (do not do without explicit human instruction)

- Removing `run_id` from any core structure.
- Introducing multiple snapshots per bar for the same run.
- Changing the meaning of `equity`, `realized_pnl`, or `unrealized_pnl`.
- Silently altering JSON formats in `data/governor/*` or log schemas.

---

If you (AI assistant) stay aligned with **this MASTER_CONTEXT-v3**, you will:

- Reduce hallucinations and schema drift,
- Keep backtests and analytics consistent over time,
- Make it easier for humans (and other AIs) to understand and extend the system safely.