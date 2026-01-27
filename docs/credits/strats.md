# Stocks Chapter — 20 Strategies (3.1–3.20) from *151 Trading Strategies* (Kakushadze & Serur, 2018)

This file explains each stock strategy in a consistent, reproducible format:

- **A)** What the strategy actually does  
- **B)** The mathematics used (core definitions and equations)  
- **C)** When it’s best used / shouldn’t be used  
- **D)** General implementation notes (kept broadly applicable)

> Notation (used throughout):  
> - Prices are assumed **fully adjusted** (splits/dividends) where applicable.  
> - Returns are typically computed from adjusted prices.  
> - “Long winners / short losers” implies a **cross-sectional** ranking at each rebalance date.

---

## 3.1 — Price-momentum

### A) What it does
Ranks stocks by past price performance over a **formation window** (commonly ~12 months) often with a **skip** (commonly 1 month), then buys winners (and optionally shorts losers).

### B) Math
Let time be measured in months with most recent month indexed as \(t=0\). Let \(P_i(t)\) be adjusted price.

Monthly return:
\[
R_i(t) = \frac{P_i(t)}{P_i(t+1)} - 1
\]

Formation length \(T\), skip \(S\). Cumulative return:
\[
R^{cum}_i = \frac{P_i(S)}{P_i(S+T)} - 1
\]

Mean return:
\[
R^{mean}_i = \frac{1}{T}\sum_{t=S}^{S+T-1} R_i(t)
\]

Volatility (sample):
\[
\sigma_i^2 = \frac{1}{T-1}\sum_{t=S}^{S+T-1}(R_i(t)-R^{mean}_i)^2
\]

Risk-adjusted score (one common choice):
\[
R^{risk.adj}_i = \frac{R^{mean}_i}{\sigma_i}
\]

Portfolio can be long-only (\(\sum w_i=1,\, w_i\ge0\)) or dollar-neutral (\(\sum |w_i|=1,\, \sum w_i=0\)).

### C) Best / worst conditions
**Best:** persistent cross-sectional trends; adequate liquidity; manageable turnover.  
**Avoid / modify:** sharp regime reversals; illiquid universes; high costs dominating signal.

### D) General implementation notes
- Decide: formation \(T\), skip \(S\), holding \(H\), score type (cum/mean/risk-adjusted), selection rule (top/bottom quantile), weighting rule (equal, volatility-scaled).
- Ensure “as-of” correctness (no lookahead) and use adjusted prices.

---

## 3.2 — Earnings-momentum

### A) What it does
Same “winners vs losers” concept as price momentum, but ranks by **earnings-based momentum** instead of past returns.

### B) Math
A common selection criterion is **standardized unexpected earnings (SUE)**:
\[
SUE_i = \frac{E_i - E'_i}{\sigma_i}
\]
- \(E_i\): most recently announced quarterly EPS  
- \(E'_i\): EPS from 4 quarters ago  
- \(\sigma_i\): standard deviation of \((E_i - E'_i)\) over the last 8 quarters

Trade construction is typically analogous to price momentum (e.g., long top decile by \(SUE\), short bottom decile).

### C) Best / worst conditions
**Best:** strong earnings-drift environments; reliable, timely fundamental data; liquid names.  
**Avoid / modify:** noisy/restated EPS; sparse coverage; inability to timestamp earnings availability.

### D) General implementation notes
- Treat earnings as arriving at a specific time (announcement timestamp).
- Handle missing history (need enough quarters to compute the 8-quarter std dev).

---

## 3.3 — Value (Book-to-Price)

### A) What it does
Ranks stocks by a **value metric** (commonly Book-to-Price, B/P) and buys “cheap” stocks (and optionally shorts “expensive” ones).

### B) Math
Book-to-Price:
\[
\text{B/P}_i = \frac{\text{Book Value}_i}{\text{Market Value}_i}
\]
Typical: long top decile by B/P, short bottom decile (zero-cost).

### C) Best / worst conditions
**Best:** environments where valuation spreads matter; longer horizons; broad universes.  
**Avoid / modify:** strong “growth-dominant” regimes; structural shifts causing persistent value underperformance; obvious value traps.

### D) General implementation notes
- Be explicit about the accounting definition of “book” and how stale/updated it can be.
- Consider sector-neutral ranking if you want to reduce structural tilts.

---

## 3.4 — Low-volatility anomaly

### A) What it does
Prefers stocks with **lower historical return volatility**, based on the empirical observation that they can outperform high-volatility stocks on a risk-adjusted basis.

### B) Math
Use historical volatility (e.g., the \(\sigma_i\) defined from returns over a window). Rank stocks by \(\sigma_i\):
- Long low-vol bucket, short high-vol bucket (or long-only low-vol).

### C) Best / worst conditions
**Best:** risk-off or stable markets; when leverage constraints and behavioral effects can persist.  
**Avoid / modify:** sudden high-vol rallies; momentum-driven melt-ups where high beta dominates.

### D) General implementation notes
- Decide the volatility window length and rebalancing frequency.
- Watch unintended factor/sector exposures (low-vol tends to tilt defensively).

---

## 3.5 — Implied volatility (IV changes)

### A) What it does
Uses **changes in call and/or put implied volatilities** as predictive signals for stock returns.

### B) Math
Define a 1-month change in implied volatility (example):
\[
\Delta IV^{call}_i = IV^{call}_i(t) - IV^{call}_i(t-1),\quad
\Delta IV^{put}_i = IV^{put}_i(t) - IV^{put}_i(t-1)
\]
Example constructions:
- Long top decile by \(\Delta IV^{call}\)
- Short top decile by \(\Delta IV^{put}\)
Or use a spread score \(\Delta IV^{call}-\Delta IV^{put}\).

### C) Best / worst conditions
**Best:** options are liquid and IV moves contain information (risk repricing, sentiment).  
**Avoid / modify:** names with unreliable option markets; around extreme event risk where signals become unstable.

### D) General implementation notes
- Define which option maturities/strikes you standardize on (e.g., nearest 30D ATM).
- Ensure consistent IV sourcing and corporate-action handling.

---

## 3.6 — Multifactor portfolio

### A) What it does
Combines multiple factor strategies (e.g., value + momentum + low-vol) into a single portfolio to diversify sources of return.

### B) Math
Allocate weights \(w_A\) across \(F\) factor portfolios:
\[
\sum_{A=1}^{F} w_A = 1,\quad I_A = w_A\,I
\]
Each factor portfolio is built as in its own subsection; the combined portfolio is the weighted aggregation.

### C) Best / worst conditions
**Best:** when factors are imperfectly correlated; when you want robustness across regimes.  
**Avoid / modify:** if factors are highly overlapping due to implementation choices; if constraints force concentration.

### D) General implementation notes
- Decide factor set, normalization, and combining rule (equal weights vs optimized).
- Consider how you prevent one factor from dominating due to scale differences.

---

## 3.7 — Residual momentum

### A) What it does
Runs momentum on **residual returns** after removing common factor exposures (e.g., market/size/value), aiming to capture stock-specific trend persistence.

### B) Math
Regression (example with 3 Fama–French factors):
\[
R_i(t) = \alpha_i + \beta_{1,i}MKT(t)+\beta_{2,i}SMB(t)+\beta_{3,i}HML(t)+\epsilon_i(t)
\]
Compute residuals for the formation window:
\[
\epsilon_i(t)=R_i(t)-\beta_{1,i}MKT(t)-\beta_{2,i}SMB(t)-\beta_{3,i}HML(t)
\]
Residual risk-adjusted score:
\[
\tilde R^{risk.adj}_i = \frac{\epsilon^{mean}_i}{\tilde\sigma_i},
\quad
\tilde\sigma_i^2=\frac{1}{T-1}\sum (\epsilon_i(t)-\epsilon^{mean}_i)^2
\]

### C) Best / worst conditions
**Best:** when raw momentum is dominated by factor moves (sector/market) and you want idiosyncratic signal.  
**Avoid / modify:** unstable factor model; short histories; regimes where factor structure shifts rapidly.

### D) General implementation notes
- Choose factor model, regression window, and formation window consistently.
- Use consistent “excess return” definitions if your factor model assumes them.

---

## 3.8 — Pairs trading

### A) What it does
Identifies two historically correlated stocks and trades **spread mean-reversion**: short the “rich” one and buy the “cheap” one when they diverge.

### B) Math
Returns between \(t_1\) and \(t_2\):
\[
R_A=\frac{P_A(t_2)}{P_A(t_1)}-1,\quad
R_B=\frac{P_B(t_2)}{P_B(t_1)}-1
\]
(Also presented in log-return form.) Demean:
\[
R=\frac{1}{2}(R_A+R_B),\quad \tilde R_A=R_A-R,\quad \tilde R_B=R_B-R
\]
Dollar-neutral position sizing at entry time \(t^*\):
\[
P_A|Q_A|+P_B|Q_B|=I,\quad P_AQ_A+P_BQ_B=0
\]

### C) Best / worst conditions
**Best:** stable relationships (same industry, common drivers); range-bound relative behavior.  
**Avoid / modify:** structural breaks (mergers, business model changes); high borrow costs; extreme macro shifts.

### D) General implementation notes
- Define pair selection rule and divergence metric.
- Include clear exit/stop logic for relationship breaks.

---

## 3.9 — Mean-reversion (single cluster)

### A) What it does
Generalizes pairs trading to \(N>2\) highly related stocks (“a cluster”). It shorts recent relative outperformers and buys underperformers within the cluster.

### B) Math
Log returns:
\[
R_i=\ln\frac{P_i(t_2)}{P_i(t_1)}
\]
Cluster mean and demeaned returns:
\[
R=\frac{1}{N}\sum_{i=1}^N R_i,\quad \tilde R_i=R_i-R
\]
Dollar constraints:
\[
\sum_{i=1}^N P_i|Q_i|=I,\quad \sum_{i=1}^N P_iQ_i=0
\]
Example sizing rule using dollar positions \(D_i=P_iQ_i\):
\[
D_i=-\gamma\tilde R_i,\quad \gamma=\frac{I}{\sum_{i=1}^N |\tilde R_i|}
\]

### C) Best / worst conditions
**Best:** tight peer groups with stable common drivers.  
**Avoid / modify:** strong trending regimes within the cluster; clusters that are not truly comparable.

### D) General implementation notes
- Decide cluster definition (industry/sector/other).
- Ensure cluster sizes are large enough to be statistically meaningful.

---

## 3.9.1 — Mean-reversion (multiple clusters)

### A) What it does
Runs the cluster mean-reversion logic across multiple clusters, diversifying across many groups.

### B) Math
Define a cluster-membership matrix \(\Lambda_{iA}\in\{0,1\}\) for clusters \(A=1..K\). Regression without intercept:
\[
R_i=\sum_{A=1}^K \Lambda_{iA}f_A+\epsilon_i
\]
Matrix form:
\[
f=Q^{-1}\Lambda^TR,\quad Q=\Lambda^T\Lambda
\]
Residuals:
\[
\epsilon = R-\Lambda Q^{-1}\Lambda^TR
\]
For binary membership, residuals correspond to returns demeaned within each cluster, yielding cluster neutrality.

### C) Best / worst conditions
**Best:** when many clusters provide diversification and reduce single-cluster risk.  
**Avoid / modify:** unstable or ill-defined clusters; tiny clusters with noisy residuals.

### D) General implementation notes
- Keep cluster definitions stable and well-documented.
- Consider allocation rules across clusters (equal vs scaled by volatility/liquidity).

---

## 3.10 — Mean-reversion (weighted regression)

### A) What it does
Generalizes “demeaning” by using a broader factor/loading matrix (not necessarily binary) and enforces neutrality via regression residuals, optionally with weights.

### B) Math
Let \(\Omega_{iA}\) be a general loadings matrix (industry + other factors). With regression weights \(z_i\) (diagonal matrix \(Z\)):
\[
\tilde R = Z\epsilon
\]
\[
\epsilon = R-\Omega Q^{-1}\Omega^T ZR
\]
\[
Q=\Omega^T Z\Omega,\quad Z=\text{diag}(z_i)
\]
A common choice: \(z_i=1/\sigma_i^2\).

### C) Best / worst conditions
**Best:** when you want systematic neutrality (industry/style) while harvesting residual mean reversion.  
**Avoid / modify:** poor factor specification; unstable covariances/vol estimates; too few observations.

### D) General implementation notes
- Decide the factor set and weighting rule.
- Confirm neutrality constraints match the exposures you intend to neutralize.

---

## 3.11 — Single moving average

### A) What it does
Trades based on the relationship between price and a moving average: above MA = bullish, below MA = bearish.

### B) Math
Simple moving average (SMA):
\[
SMA(T)=\frac{1}{T}\sum_{t=1}^T P(t)
\]
Exponential moving average (EMA):
\[
EMA(T,\lambda)=\frac{1}{1-\lambda^T}\sum_{t=1}^T \lambda^{t-1}P(t)
\]
Signal:
\[
P>MA(T)\Rightarrow \text{long (or cover short)},\quad P<MA(T)\Rightarrow \text{short (or exit long)}
\]

### C) Best / worst conditions
**Best:** trending markets; longer horizons; reduced noise if MA is long enough.  
**Avoid / modify:** sideways/choppy markets (whipsaws).

### D) General implementation notes
- Choose MA type (SMA/EMA) and length \(T\).
- Decide whether the strategy is long-only, short-only, or long/short.

---

## 3.12 — Two moving averages

### A) What it does
Uses a fast and a slow moving average to define trend via crossover/ordering.

### B) Math
With \(T'<T\):
\[
MA(T')>MA(T)\Rightarrow \text{long},\quad MA(T')<MA(T)\Rightarrow \text{short}
\]

### C) Best / worst conditions
**Best:** sustained trends; smoother than single-threshold rules in some markets.  
**Avoid / modify:** range-bound regimes; frequent crossovers create churn.

### D) General implementation notes
- Choose \(T'\) and \(T\) and any confirmation/filters (optional).

---

## 3.13 — Three moving averages

### A) What it does
Extends MA logic with three horizons to reduce false signals and encode “trend alignment.”

### B) Math
Example rule with \(T_1<T_2<T_3\):
\[
MA(T_1)>MA(T_2)>MA(T_3)\Rightarrow \text{enter/hold long}
\]
\[
MA(T_1)<MA(T_2)<MA(T_3)\Rightarrow \text{enter/hold short}
\]
With separate liquidation conditions based on loss of alignment.

### C) Best / worst conditions
**Best:** strong, persistent trends; when you prefer fewer trades.  
**Avoid / modify:** faster markets where lag costs too much; choppy periods.

### D) General implementation notes
- Choose three lengths \(T_1,T_2,T_3\) appropriate to your holding horizon.

---

## 3.14 — Support and resistance (pivot points)

### A) What it does
Computes pivot-based support/resistance levels from the prior day’s OHLC, then trades based on price relative to these levels.

### B) Math
Pivot (“center”):
\[
C=\frac{P_H+P_L+P_C}{3}
\]
Resistance and support:
\[
R=2C-P_L,\quad S=2C-P_H
\]
Example signal (with current price \(P\)):
- Long if \(P>C\), liquidate long if \(P\ge R\)
- Short if \(P<C\), liquidate short if \(P\le S\)

### C) Best / worst conditions
**Best:** range-bound or mean-reverting intraday behavior; liquid stocks.  
**Avoid / modify:** strong breakouts/trends that ignore pivot levels; illiquid names.

### D) General implementation notes
- Define the bar interval (daily in this pivot-point version).
- Decide execution details for equality/threshold cases (touch vs cross).

---

## 3.15 — Channel (Donchian)

### A) What it does
Trades when price hits the floor/ceiling of a channel; can be used for mean-reversion (“bounce”) or breakout (“trend”) logic.

### B) Math
Donchian channel over last \(T\) bars (most recent indexed as 1 in the definition used):
\[
B_{up}=\max(P(1),\ldots,P(T)),\quad B_{down}=\min(P(1),\ldots,P(T))
\]
Example signal:
- Long if \(P=B_{down}\)
- Short if \(P=B_{up}\)

### C) Best / worst conditions
**Best:** well-defined ranges (bounce logic) or clean breakouts (trend logic with modifications).  
**Avoid / modify:** noisy microstructure; frequent false touches without confirmation.

### D) General implementation notes
- Choose \(T\) and whether you trade touches or require confirmation (e.g., close beyond band).

---

## 3.16 — Event-driven (M&A)

### A) What it does
Trades around merger & acquisition events (often “merger arbitrage”): attempts to capture the spread between a target’s trading price and the implied deal value, subject to deal completion risk.

### B) Math
Common “spread” concept (conceptual):
\[
\text{Spread} \approx \frac{\text{Deal Value} - \text{Target Price}}{\text{Target Price}}
\]
Positioning often includes hedges depending on deal type (cash vs stock), but the strategy is primarily event- and probability-driven.

### C) Best / worst conditions
**Best:** clear deal terms; assessable regulatory/financing risk; liquid deal names.  
**Avoid / modify:** highly uncertain deals; extreme market stress; deals with complex contingencies.

### D) General implementation notes
- You need a clean event feed (announcement time, terms) and a way to track deal status changes.

---

## 3.17 — Machine learning (single-stock KNN)

### A) What it does
Predicts a stock’s future return using **k-nearest neighbors** on feature vectors constructed from that stock’s own history (price/volume), then trades based on the prediction.

### B) Math
Target variable: cumulative return over next \(T\) trading days:
\[
Y(t)=\frac{P(t-T)}{P(t)}-1
\]
Features \(X_a(t)\) can be technical/volume transforms; features are normalized to \([0,1]\):
\[
\tilde X_a(t)=\frac{X_a(t)-X^-_a}{X^+_a-X^-_a}
\]
Distance (Euclidean):
\[
D(t,t')^2=\sum_{a=1}^m\big(\tilde X_a(t)-\tilde X_a(t')\big)^2
\]
Prediction as average of neighbor outcomes:
\[
\hat Y(t)=\frac{1}{k}\sum_{\alpha=1}^k Y(t'_{\alpha}(t))
\]
Alternative linear model over neighbors:
\[
\hat Y(t)=\sum_{\alpha=1}^k Y(t'_{\alpha}(t))w_{\alpha}+v
\]

### C) Best / worst conditions
**Best:** stable feature-to-return relationships; careful out-of-sample validation; adequate data history.  
**Avoid / modify:** nonstationary regimes; feature leakage; insufficient training history.

### D) General implementation notes
- Separate train/validation/test by time.
- Define feature set, normalization window, and neighbor selection rules clearly.

---

## 3.18 — Statistical arbitrage (optimization)

### A) What it does
Builds a (often market-neutral) long/short portfolio by **optimizing** holdings using expected returns and a covariance matrix to maximize risk-adjusted performance.

### B) Math
Let \(C_{ij}\) be covariance of returns; dollar holdings \(D_i\); expected returns \(E_i\). Portfolio P&L, variance, Sharpe:
\[
P=\sum_i E_i D_i,\quad V^2=\sum_{i,j} C_{ij}D_iD_j,\quad S=\frac{P}{V}
\]
Use dimensionless weights \(w_i=D_i/I\) with:
\[
\sum_i |w_i|=1
\]
Then:
\[
\tilde P=\sum_i E_i w_i,\quad \tilde V^2=\sum_{i,j} C_{ij} w_i w_j,\quad S=\frac{\tilde P}{\tilde V}
\]
Unconstrained (no costs/bounds) Sharpe-max solution:
\[
w_i = \gamma\sum_j C^{-1}_{ij}E_j
\]
where \(\gamma\) normalizes to satisfy \(\sum |w_i|=1\).

### C) Best / worst conditions
**Best:** diversified universe; decent alpha estimates; robust covariance estimation; manageable turnover.  
**Avoid / modify:** unstable covariance/alpha estimates; extreme crowding; high trading costs.

### D) General implementation notes
- Clarify how you estimate \(E\) and \(C\) and how often they update.
- Decide constraints (bounds, sector neutrality, etc.) based on your overall system design.

---

## 3.18.1 — Dollar-neutrality (constraint)

### A) What it does
Adds the constraint that the portfolio is **dollar-neutral** (long dollars ≈ short dollars), reducing market-direction sensitivity.

### B) Math
Recast Sharpe maximization as minimizing a quadratic objective:
\[
g(w,\lambda)=\frac{\lambda}{2}\sum_{i,j}C_{ij}w_iw_j-\sum_iE_iw_i
\]
Dollar-neutral version introduces a Lagrange multiplier \(\mu\) for:
\[
\sum_i w_i=0
\]
Leading to conditions like:
\[
\lambda\sum_j C_{ij}w_j = E_i + \mu,\quad \sum_i w_i=0
\]

### C) Best / worst conditions
**Best:** when you want reduced market beta; cross-sectional alpha focus.  
**Avoid / modify:** when borrow constraints or long-only requirements apply.

### D) General implementation notes
- Decide whether “dollar-neutral” also implies additional neutrality (beta/sector) in your system.

---

## 3.19 — Market-making (conceptual)

### A) What it does
Attempts to capture the **bid–ask spread** by buying at the bid and selling at the ask, while managing adverse selection (“toxic flow”) and inventory risk.

### B) Math
Toy rule (as written):
\[
\text{Buy at bid; Sell at ask}
\]
In practice, profitability depends on fill probabilities, adverse selection, and inventory/risk controls (microstructure-dependent).

### C) Best / worst conditions
**Best:** when you can manage queue priority and adverse selection; liquid markets; short horizons.  
**Avoid / modify:** when informed flow dominates; slow execution; high latency environments.

### D) General implementation notes
- Requires reliable bid/ask data and careful handling of fills, cancellations, and inventory exposure.

---

## 3.20 — Alpha combos

### A) What it does
Combines many “alphas” (expected-return signals or target-holding instructions) into a single portfolio, typically with normalization and neutralization steps.

### B) Math
One example expected return estimate is a \(d\)-day moving average of returns:
\[
E_i = \frac{1}{d}\sum_{s=1}^{d} R_{is}
\]
A common approach then normalizes by volatility \(\sigma_i\), optionally neutralizes via regression, and sets weights proportional to residual signal (then normalizes so \(\sum |w_i|=1\)).

### C) Best / worst conditions
**Best:** when individual alphas are weak but diversifiable; robust combination reduces noise.  
**Avoid / modify:** when alphas are highly correlated; when alpha decay is extremely fast; when combination increases turnover without net benefit.

### D) General implementation notes
- Define how alphas are standardized onto comparable scales.
- Decide combination rule (equal, weighted, regression/optimizer-based) and normalization constraints.

---

### End of stock strategies (3.1–3.20)
If you want, I can append a short “parameter index” (formation windows, signals, required data types) as a final section in the same file.
