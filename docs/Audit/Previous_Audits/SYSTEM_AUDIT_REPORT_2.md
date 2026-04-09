# COMPREHENSIVE SYSTEM AUDIT (PHASE 3 PREPARATION)

## 1. Data Integrity (CRITICAL)
**Severity**: 🟥 HIGH
**Fault**: `DataManager` requests `adjustment="raw"` from Alpaca.
**Impact**: Stock Splits (e.g., NVDA 10:1) appear as 90% price crashes. This triggers Stop Losses, destroys indicators (RSI goes to 0), and ruins PnL calculations.
**Fix**: Must use `adjustment="split"` or `adjustment="all"`.

## 2. AI "Brain" Poverty
**Severity**: 🟧 MEDIUM-HIGH
**Fault**: `SignalGate` uses only 3 features: `vol_20`, `trend_dist`, `mom_14`.
**Impact**: The AI is "context blind". It cannot see:
*   **Volume**: Is the move supported by accumulation?
*   **Macro**: Is VIX exploding? (Market crash mode).
*   **Sector**: Is Tech leading or lagging?
**Fix**: Expand Feature Engineering to include Volume Profile, Relative Strength vs SPY, and VIX regime.

## 3. Portfolio Scalability (MVO)
**Severity**: 🟧 MEDIUM
**Fault**: Mean-Variance Optimization requires $N > M$ (History > Tickers) to be stable.
**Impact**: As we expand to S&P 500 (500 tickers), if we use a rolling 60-day window, the Covariance Matrix will be singular/noisy. This leads to extreme allocations (e.g., -200% Short, +300% Long).
**Fix**: Implement **Ledoit-Wolf Shrinkage** for covariance estimation.

## 4. Execution Realism
**Severity**: 🟨 LOW-MEDIUM
**Fault**: Fixed 10bps slippage.
**Impact**: Underestimates costs for small caps / illiquid names.
**Fix**: Dynamic slippage model based on Spread and Volatility.

## 5. Learning Loop Bias
**Severity**: 🟧 MEDIUM
**Fault**: "Survivor Bias" in training data. We only learn from trades we *took*.
**Impact**: The model never learns "What would have happened if I bought X?". It only learns "I bought Y and lost". It becomes overly conservative.
**Fix**: **Shadow Paper Trading** — Log *every* signal's theoretical outcome, not just executed trades.

## Conclusion
The system is functionally sound but statistically fragile. The Data split issue invalidates long-term backtests. The AI is too simple to generalize well. MVO will break at scale. These must be addressed in Phase 3.
