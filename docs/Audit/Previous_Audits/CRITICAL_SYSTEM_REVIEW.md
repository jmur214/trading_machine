# CRITICAL SYSTEM REVIEW

## Executive Summary
This document critiques the current state of the Trading Machine (v2.0), specifically in the context of a **Small Account (<$5,000)**. While the architecture (Hunt -> Backtest -> Learn -> Exec) is sound, the implementation is currently ill-suited for small capital due to frictional costs, sizing constraints, and data limitations.

## 1. Small Account Viability (CRITICAL FAULT)
**Issue**: The current Risk Engine (`min_notional=$50`, `risk_per_trade=1%`) and Portfolio Optimizer (`MVO`) are fundamentally misaligned with a $5,000 account.
*   **Math**: With $5,000 equity, 1% risk is $50. If using a 2% stop-loss, position size is $2,500.
*   **Result**: You can max hold **2 positions** ($2,500 * 2 = $5,000).
*   **Conflict**: MVO (Mean-Variance) optimizes for diversified buckets (e.g., 20 positions @ 5% each). The Risk Engine will simply **reject** 18 of those 20 trades because $250 (5% of $5k) is below `min_notional` or fails stop-loss sizing logic.
*   **Impact**: Performance will be random (based on which 2 signals trigger first) rather than optimal.

**Proposal**: "Small Account Mode".
*   Increase Risk per Trade to 2-3% (Concentrated Bets).
*   Switch Portfolio Mode to "Top-N" (Buy top 3 strongest signals) instead of MVO.
*   Or use Fractional Shares (if broker allows) and lower `min_notional`.

## 2. Learning "Survivorship Bias"
**Issue**: `harvest_data.py` only scrapes `trades.csv`.
*   **Fault**: Use Logic: "If I didn't trade it, I don't learn from it."
*   **Reality**: The machine fails to learn from **Missed Opportunities**. If AAPL signalled 0.0 but went up 10%, the machine ignores it. It only learns from trades it *took*.
*   **Impact**: The `SignalGate` AI is trained on a biased subset of reality.

**Proposal**: Implement "Shadow Harvesting".
*   In backtesting, record *every* candidate signal's outcome, even if rejected by Risk Engine.

## 3. The "Hunter" is Myopic
**Issue**: `tree_scanner.py` only looks at internal price action (RSI, MA).
*   **Fault**: Markets are driven by Macro (Rates, VIX) and Correlations.
*   **Impact**: The Hunter is blind to "Regime changes". It keeps trying to buy dips even if the VIX is 40.

**Proposal**: Add "Macro Genes" to the Discovery Engine (e.g., `if VIX > 30: Short`).

## 4. Execution Naivety
**Issue**: We assume `fill_at_next_open`.
*   **Fault**: In smallcaps or panic selling, slippage > 10bps.
*   **Impact**: Simulated returns are inflated.

**Proposal**: Variable Slippage Model based on Volatility + Spread.

## 5. Alpha Stagnation
**Issue**: Using a fixed Universe (30-40 tickers).
*   **Fault**: Alpha decays. If we only hunt in the Dow 30, we compete with HFTs.
*   **Impact**: Low Sharpe Ratio (as seen in initial runs).

**Proposal**: Expand to Russell 1000 to find inefficient pricing.

## Conclusion
The system is a "Ferrari Engine in a Bicycle". It has advanced AI (SignalGate) and Optimization (MVO) but is constrained by the "Bicycle" chassis (Small Account, Limited Data). We must either **upgrade the chassis** (Add Capital, Data) or **tune the engine down** (Small Account Mode).
