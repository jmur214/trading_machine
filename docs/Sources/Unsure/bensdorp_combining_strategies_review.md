# Laurens Bensdorp — Combining “Unrelated” Strategies into a Robust System (A/B/C/D)

This document summarizes **what I can verify from Laurens Bensdorp’s published material (books/interviews/articles)** about **combining non-correlated strategies**, including the idea that **two “ugly” or even losing sleeves can improve (or even flip) the combined outcome** via interaction, hedging, and compounding.

It is written to be **general and portable** (not tied to any specific platform or codebase), while still being faithful to the themes he emphasizes publicly.

---

## 1) Core idea: non-correlated, multi-system portfolios

### A) What it does
Instead of searching for *one* best strategy, Bensdorp’s framework emphasizes running **multiple strategies that behave differently across regimes** (bull / bear / sideways), aiming for a **smoother combined equity curve** and better risk-adjusted performance.

Across his books and interviews, this is repeatedly described as:
- **Many systems**, not one
- Systems designed to do well in **different market environments**
- Preferably **weakly correlated** (or “non-correlated”) so their failure modes don’t line up

### B) The mathematics used
The “non-correlated systems” idea is naturally expressed with a **correlation/covariance view**.

Let each strategy be a return series \(r^{(k)}_t\), \(k=1..K\).  
Define the correlation matrix:
\[
ho_{ij} = \frac{\text{Cov}(r^{(i)}, r^{(j)})}{\sigma_i\sigma_j}
\]
and covariance matrix:
\[
\Sigma_{ij} = \text{Cov}(r^{(i)}, r^{(j)})
\]

For a portfolio of strategies with weights \(w\) (summing to 1), the portfolio variance is:
\[
\sigma_p^2 = w^T \Sigma w
\]

A simple “distance” for clustering “unrelated” strategies:
\[
d_{ij} = 1 - \rho_{ij}
\]
(High distance = low correlation.)

**Key practical consequence:** even if two strategies have mediocre stand-alone Sharpe, lowering \(\sigma_p\) by reducing cross-strategy correlation can materially improve portfolio Sharpe and drawdowns.

### C) When it’s best used / shouldn’t be used
**Best used when**
- You can identify strategies with **structurally different payoffs** (trend vs mean reversion, long vs short, fast vs slow timeframes).
- Your goal is **robustness** across market conditions, not maximizing one backtest curve.

**Shouldn’t be used (or needs care) when**
- “Non-correlation” is only cosmetic (strategies are secretly the same bet).
- Correlations jump in crises (many risk assets correlate in stress).
- Costs and turnover dominate the expected benefit.

### D) General implementation notes
- Treat each strategy as a **module** with a clear return stream; build portfolio logic above it.
- Keep “non-correlation” measured in **rolling windows** and **stress windows**, not only full-sample averages.
- Prefer **simple**, different mechanisms rather than one complicated mechanism.

---

## 2) Combining different styles: trend + mean reversion, long + short

### A) What it does
A recurring theme in Bensdorp commentary is to **combine styles** that tend to win in different conditions, commonly framed as:
- **Trend following** (captures persistent moves)
- **Mean reversion** (captures snap-backs / pullbacks)
- **Long and short components**
- **Different timeframes** (slow + fast)

The intent is that when one sleeve is in a drawdown, another sleeve is more likely to be in a neutral or favorable state.

### B) The mathematics used
This is portfolio math again, but the useful developer-facing abstraction is:

Let strategy \(A\) be trend-like and \(B\) be mean-reversion-like. The combined return is:
\[
r^p_t = w_A r^A_t + w_B r^B_t
\]

Even if \(\mathbb{E}[r^A]\) and \(\mathbb{E}[r^B]\) are modest, the combined portfolio can improve because:
\[
\sigma_p^2 = w_A^2\sigma_A^2 + w_B^2\sigma_B^2 + 2w_Aw_B\sigma_A\sigma_B\rho_{AB}
\]
If \(ho_{AB}\) is low or negative, the cross term reduces variance.

### C) When it’s best used / shouldn’t be used
**Best used when**
- Trend strategies do well in persistent directional markets.
- Mean reversion does well in choppy / range markets or in pullbacks within an overall trend.
- Short or defensive sleeves contribute during equity stress.

**Shouldn’t be used (or needs care) when**
- Both sleeves depend on the same fragile assumption (e.g., both need high liquidity + stable volatility).
- The “short” sleeve has tail risk without controls.

### D) General implementation notes
- Ensure “different style” really means **different drivers**, not just different parameters.
- If you add shorts or hedges, judge them by **portfolio contribution in drawdowns**, not by stand-alone CAGR.

---

## 3) The “two losers make a winner” (Parrondo-style interaction)

### A) What it does
Bensdorp-linked discussions often use Parrondo’s paradox as the intuition: **two individually unattractive processes** can combine into a **better compounding process** because of how their wins/losses interleave and because portfolio decisions are **path-dependent**.

In trading terms, the “loser” sleeve may be a **hedge** (long-vol, defensive, short-bias, etc.) that looks bad in isolation but improves the combined trajectory.

### B) The mathematics used
A helpful way to formalize “two losers can help” is via **log-growth / typical-path thinking**.

For wealth \(W_t\) with gross returns \(G_t = 1+r_t\):
\[
\log W_n = \sum_{t=1}^{n} \log(G_t)
\]
A strategy can have an unimpressive arithmetic mean but still improve the combined system if it:
- reduces volatility in bad periods (improving average log-growth), or
- reduces tail losses (improving survivability / time-to-recovery).

### C) When it’s best used / shouldn’t be used
**Best used when**
- One sleeve is explicitly designed as “insurance” or crisis performance.
- The combined system is rebalanced or allocated in a consistent way.

**Shouldn’t be used when**
- The “hedge” bleeds heavily and never pays off in the regime you trade.
- The hedge introduces new tail risks (e.g., short-vol disguised as a hedge).

### D) General implementation notes
- Evaluate hedges by “mission metrics”: worst-day contribution, crisis convexity, peak-to-trough and time-to-recovery—more than by stand-alone Sharpe.

---

## 4) Practical combining recipes attributed to his books’ themes

### A) What it does
From reviews and descriptions of *The 30-Minute Stock Trader* and later books, Bensdorp’s approach is often presented as:
- Create a small set of distinct strategies (e.g., rotation + mean reversion long + mean reversion short)
- Then **combine** them for a smoother curve and lower beta

### B) The mathematics used
Two lightweight, platform-agnostic combination methods:

**(1) Equal capital weights**
\[
w_k = \frac{1}{K}
\]

**(2) Equal risk weights (simple)**
Let \(\sigma_k\) be realized vol of strategy \(k\). Use:
\[
w_k \propto \frac{1}{\sigma_k}
\quad \Rightarrow \quad
w_k = \frac{\sigma_k^{-1}}{\sum_j \sigma_j^{-1}}
\]

Both are simple and “portable.” They won’t be perfect, but they often beat “optimize everything” approaches out-of-sample.

### C) When it’s best used / shouldn’t be used
**Best used when**
- You want robust combination rules with minimal sensitivity.
- Your strategy set is already meaningfully diverse.

**Avoid / modify when**
- One sleeve has rare, extreme tail behavior: you’ll want explicit tail constraints or caps.

### D) General implementation notes
- Keep weights stable; avoid constantly chasing the most recent best performer (recency bias).
- Recompute correlations/volatilities on rolling windows and include stress periods.

---

## 5) Hedging and “bear market” sleeves

### A) What it does
Bensdorp’s later material (e.g., retirement-account framing) explicitly discusses systems aimed at:
- participating in bull/sideways markets, **and**
- preserving wealth in bear markets / guarding against inflation

The general pattern is: add sleeves whose job is specifically to **help during drawdowns**, even if they lag in calm periods.

### B) The mathematics used
A clean way to define “hedge success” is to use conditional metrics.

Let \(r^p_t\) be portfolio return and define “bad market days” as the worst \(q\%\) of a benchmark’s daily returns. Then the hedge’s value can be measured by:
- average contribution during those days:
\[
\mathbb{E}[r^{hedge}_t \mid t \in \text{worst } q\%]
\]
- reduction in portfolio drawdown / time-to-recovery (path metrics)

### C) When it’s best used / shouldn’t be used
**Best used when**
- Your primary objective includes capital preservation and smoother equity growth.
- You accept that a hedge may look “bad” alone.

**Avoid / modify when**
- The hedge’s cost is too large relative to its crisis benefit.
- The hedge behaves like a hidden risk-on bet.

### D) General implementation notes
- Pre-define the hedge’s purpose and how you’ll judge it (portfolio stress windows).
- Keep the hedge logic simple and distinct from the core strategies.

---

## References (public, high-level)
- Bensdorp’s books and summaries emphasize **noncorrelated / multi-system** approaches across regimes (bull/bear/sideways).  
- Reviews of *The 30-Minute Stock Trader* discuss combining strategies (weekly rotation + mean reversion variants) to improve risk-adjusted performance and reduce beta.  
- Interviews/discussions associated with Bensdorp frequently emphasize “build simple, different strategies and combine them thoughtfully,” including Parrondo-style intuition and purpose-driven evaluation of hedges.

(See the sources cited in the chat message that accompanied this file for the exact URLs and publication details.)
