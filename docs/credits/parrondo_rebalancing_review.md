# Parrondo-Style “Rebalancing Wins” — Review + Reproducible Spec (A/B/C/D)

This document applies the same **A/B/C/D** format to:

1) **Michael Stutzer — _The Paradox of Diversification_** (PDF)  
2) **Learning Machines — _Parrondo’s Paradox in Finance: Combine two Losing Investments into a Winner_** (blog post)

The two sources are tightly aligned: the blog post is essentially a simulation-based reproduction of the PDF’s simple binomial example.

---

## 1) Stutzer — *The Paradox of Diversification* (PDF)

### A) What the “strategy” actually does
This is not a single-asset trading strategy; it is a **portfolio mechanism**:

- Choose fixed target weights (in the paper’s toy example, **50% risky market + 50% “risk-free” T-bills**, even when T-bills have a **slightly negative real return**).
- **Rebalance** back to the target weights at a regular interval (annually in the example).
- Over long horizons, this can shift the **distribution** of terminal wealth so that the **median** outcome becomes positive, even if each constituent investment has a negative median outcome over the same horizon.

The “Parrondo” flavor comes from the fact that **alternating / combining** losing components with **capital-dependent payoffs** (returns scale with current wealth) can create a “winner” at the portfolio level through compounding.

---

### B) The mathematics used

#### (1) Binomial risky asset (market) model
Each period (year) the market gross return is:

- Up: \(1+u\) with probability \(1/2\)  
- Down: \(1-d\) with probability \(1/2\)

Parameters \(u\) and \(d\) are calibrated to match the assumed expected return and volatility (in the paper: expected real return 6%, volatility 40%), yielding \(u=0.46\) and \(d=0.34\).

After \(n\) periods, if the market has \(w\) up moves:
\[
S_n = S_0\,(1+u)^w\,(1-d)^{n-w}
\]

#### (2) Expected vs. median terminal wealth (why they differ)
- The expected value compounds the expected gross return:
\[
\mathbb{E}[S_n] = (1.06)^n S_0
\]
- The median is governed by **log-compounding**. With symmetric \(p=1/2\), the median number of up moves is \(w=n/2\), so:
\[
\text{Median}[S_n] = S_0 \exp\left(n\cdot \tfrac{1}{2}\big[\log(1+u)+\log(1-d)\big]\right)
\]

This is the key conceptual move: **arithmetic mean** outcomes can look great while **typical (median / geometric)** outcomes can be poor when volatility is high and outcomes are skewed.

#### (3) Rebalanced 50/50 portfolio with a (slightly losing) “risk-free” leg
Let the “risk-free” real gross return be constant: \(g_f = 1 - 0.001 = 0.999\).

If the portfolio is rebalanced to 50/50 at the start of each year, then:

Up-year portfolio gross return:
\[
G_{up} = \tfrac{1}{2}(1+u)+\tfrac{1}{2}g_f
\]

Down-year portfolio gross return:
\[
G_{down} = \tfrac{1}{2}(1-d)+\tfrac{1}{2}g_f
\]

With equal up/down probability, the median terminal wealth for the rebalanced portfolio is:
\[
\text{Median}[P_n] = P_0 \exp\left(n\cdot \tfrac{1}{2}\big[\log(G_{up})+\log(G_{down})\big]\right)
\]

In the paper’s numeric example, this median becomes **> 1**, i.e. positive median terminal wealth, despite the “risk-free” leg having negative real return.

#### (4) Why buy-and-hold doesn’t show the same effect (in this toy model)
With buy-and-hold, you don’t “pump” volatility via rebalancing. In the paper’s simplified setup (with deterministic negative real return for T-bills), buy-and-hold does **not** produce the paradoxical positive-median outcome.

---

### C) When it’s best used / shouldn’t be used
**Best used when**
- You have **a volatile return source** + **a stabilizer** (cash/short-duration bonds/defensive asset), and you can maintain target weights.
- There’s enough **variance + diversification** that rebalancing produces a measurable “rebalancing premium” (often called volatility harvesting/pumping).
- You care about **typical** outcomes (median / geometric growth), not only arithmetic expectations.

**Shouldn’t be used (or must be adapted) when**
- Costs/taxes/market impact make frequent rebalancing uneconomic.
- Correlations spike (diversification collapses) and the rebalancing leg becomes a persistent drag.
- You are forced into constraints that block rebalancing (illiquidity, position limits, execution constraints).

---

### D) General implementation notes (broadly applicable)
- Model it as a **rebalancing overlay**: inputs are (weights, rebalance rule, eligible assets), output is target weights each rebalance.
- Evaluate with both:
  - **Arithmetic** metrics (mean return) and
  - **Geometric/log-growth** metrics (median/typical path behavior).
- The core knobs are:
  1) target weight vector \(w\)  
  2) rebalance cadence or trigger  
  3) universe/asset definitions  
  4) frictions model (even if coarse)

---

## 2) Learning Machines blog — *Parrondo’s Paradox in Finance…* (link)

### A) What it actually does
The blog post demonstrates the same phenomenon by **simulation**, reproducing the PDF’s binomial example:

1. Simulate 30-year paths of the market’s binomial gross returns with \(u=0.46\), \(d=0.34\), \(p=0.5\).  
2. Show the **median** terminal value is about **0.57**, i.e. a typical loss.  
3. Create a rebalanced 50/50 portfolio between the risky asset and “risk-free” \(g_f=0.999\).  
4. Show the **median** terminal value is about **1.343**, i.e. a typical gain.

This is a computational “proof by example.”

---

### B) The mathematics used

#### (1) Binomial path simulation equals multiplying sampled gross returns
A simulated terminal wealth path is:
\[
W_n = \prod_{k=1}^{n} G_k
\]
where each \(G_k\) is either \(1+u\) or \(1-d\), sampled with replacement.

The blog uses the **median of many simulated paths** as the key statistic (instead of the arithmetic mean), aligning with the PDF’s focus on typical outcomes.

#### (2) How the blog “adapts u and d” for the rebalanced portfolio
In the 50/50 rebalanced case, the “effective” up/down gross returns are the portfolio gross returns:
\[
G_{up} = \tfrac{1}{2}(1+u)+\tfrac{1}{2}g_f,\quad
G_{down} = \tfrac{1}{2}(1-d)+\tfrac{1}{2}g_f
\]

If you want to represent those as:
- \(G_{up} = 1 + u'\)
- \(G_{down} = 1 - d'\)

then:
\[
u' = \tfrac{1}{2}(u + (g_f-1)),\quad
d' = \tfrac{1}{2}(d - (g_f-1))
\]
Since \(g_f-1=-0.001\), this matches the blog’s substitutions:
\[
u' = \frac{0.46-0.001}{2},\quad
d' = \frac{0.34+0.001}{2}
\]

#### (3) Optional: closed-form median (no simulation needed)
As in the PDF, for \(p=1/2\):
\[
\text{Median}[W_n] = \exp\left(n\cdot \tfrac{1}{2}(\log G_{up}+\log G_{down})\right)
\]
Simulation is a convenient verification and a bridge to more realistic return models.

---

### C) When it’s best used / shouldn’t be used
**Best used when**
- You want to explain or validate “rebalancing premium” behavior quickly.
- You want a reproducible Monte Carlo demo (and later can swap the binomial generator for empirical returns).

**Shouldn’t be used (or needs caution) when**
- You interpret the binomial parameters as “known ex-ante” in real markets.
- You ignore realistic frictions, drawdowns, and changing regimes.

---

### D) General implementation notes (broadly applicable)
- Treat the blog’s “binomial tree” as a **plug-in return generator** for a broader simulation harness.
- Separate concerns:
  1) return-path generator (binomial / empirical bootstrap / fitted model)  
  2) portfolio rule (rebalance weights)  
  3) evaluation (median/log-growth, drawdown, tail risk, etc.)
- If you move beyond the toy model, the most important change is using **realistic return distributions** and a **basic friction model** (even if approximate).

---

## Quick reproduction checklist (both sources)
- Define \(u, d, n, p\) for the risky leg and \(g_f\) for the defensive leg.
- Compute / simulate terminal wealth for:
  - risky-only
  - defensive-only
  - fixed-weight rebalanced portfolio
- Compare **median** terminal wealth (and/or average log-growth).

