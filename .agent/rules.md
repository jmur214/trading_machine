---
description: Golden Invariants and Rules for the Trading Machine Codebase
---

# Trading Machine Rules

These rules must be followed by all agents working on this codebase. They are derived from `MASTER_CONTEXT-v3.md`.

## 1. Golden Invariants (DO NOT BREAK)

1.  **Equity Accounting**:
    *   `equity` must always equal `cash + market_value` (within float tolerance).
    *   `realized_pnl` changes ONLY on exits/partial closes/flips.

2.  **Run Isolation**:
    *   Every run must have a unique `run_id`.
    *   Never overwrite logs from a different run.

3.  **One Snapshot per Bar**:
    *   Exactly one portfolio snapshot per `run_id` and timestamp.

4.  **Unified Edge API**:
    *   Edges must emit numeric scores or structured signals.
    *   Do not introduce ad-hoc edge signatures.

5.  **Data Contracts**:
    *   Use `Order`, `Fill`, `Position` structures as defined in `MASTER_CONTEXT-v3.md`.
    *   Do not invent new fields without explicit user approval and schema updates.

6.  **Stable Logging**:
    *   Do not add columns to `trades.csv` or `portfolio_snapshots.csv` without updating the logger, analytics, and schema documentation.

7.  **Risk & Safety**:
    *   Never bypass `RiskEngine` controls in production or backtest code.
    *   Edge code must be pure (no side effects, no network calls in hot loops).

## 2. Change Discipline

*   **Safe Changes**: Refactoring internal logic, adding helper functions, optimizing performance (without changing outputs).
*   **Dangerous Changes**: Adding fields to core contracts, changing `run_id` logic, changing PnL math. **REQUIRE EXPLICIT USER APPROVAL.**
*   **Forbidden**: Removing `run_id`, multiple snapshots per bar, silent JSON format changes.

## 3. File Paths

*   Data is stored in `data/`.
*   Logs are in `data/trade_logs/<run_id>/`.
