# Cheap-Input Regime Signal Validation — 2026-05-06

**Date:** 2026-05-06
**Branch:** `regime-cheap-validation`
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-2/.claude/worktrees/agent-a824c9a6180a8b84c`
**Prior baseline:** `regime_signal_validation_2026_05_06.{md,json}` (HMM falsification)
**Prior slice 1:** `hmm_panel_rebuild_slice1_2026_05_06.md` (VIX-term as HMM input)
**Verdict:** **Branch 3 — neither cheap source is leading. Schwab IV skew (or a paid alternative) becomes the priority for any next regime-panel work.**

---

## Question

Per the outside-dev review (`docs/Sessions/Other-dev-opinion/5-5-26_schwab-plan-reflection.md`):
can the regime-panel rebuild ship using FREE cheap inputs — VIX term structure
from yfinance and CBOE total put-call ratio — without writing any Schwab adapter?

Methodology mirrors the 2026-05-06 baseline: AUC vs forward 20d SPY
drawdown ≤ −5%, plus the coincident-vs-leading Pearson-correlation
test. A genuine leading feature must satisfy BOTH:
- AUC > 0.55 at the 20d horizon (after sign-correction for inverted features)
- |Pearson(fwd 20d ret)| > |Pearson(trail 20d ret)|

---

## What was tested

**VIX term-structure log-slopes (4 features, all from yfinance, 1086 days):**

| Feature | Construction | Crisis sign |
|---|---|---|
| `vix_term_slope_9_30` | `log(VIX9D / VIX)` | positive (backwardation) |
| `vix_term_slope_30_3m` | `log(VIX / VIX3M)` | positive |
| `vix_term_slope_3m_6m` | `log(VIX3M / VIX6M)` | positive |
| `vix_term_slope_9_6m` | `log(VIX9D / VIX6M)` | positive (full term) |

These are LOG ratios (sign-symmetric, unitless) covering the full 9-day
through 6-month curve. Slice-1 used spread/ratio variants of the
9d/30d and 30d/3m pairs in the HMM input panel; the new contribution
here is feature-level standalone validation across the **full 4-tenor
curve including VIX6M** (the missing piece in slice 1).

**CBOE total put-call ratio (NOT TESTED — see "Data gap" below).**

---

## Headline AUC table (target: forward 20d SPY dd ≤ −5%, base rate 0.212)

For each feature I report both the raw AUC and the inverted (1−AUC) form,
because the 20d AUCs come in below 0.5 — the features have negative-AUC
content at the 20d horizon, not positive. The "effective" AUC is
max(AUC, 1−AUC).

| Feature | 5d AUC | 20d AUC | 60d AUC | 20d_3% AUC | 20d effective |
|---|---:|---:|---:|---:|---:|
| `vix_term_slope_9_30`  | 0.7230 | 0.3988 | 0.2672 | 0.3188 | **0.6012** (inverted) |
| `vix_term_slope_30_3m` | 0.7824 | 0.3439 | 0.1895 | 0.2413 | **0.6561** (inverted) |
| `vix_term_slope_3m_6m` | 0.7981 | 0.4066 | 0.1984 | 0.2988 | 0.5934 (inverted) |
| `vix_term_slope_9_6m`  | 0.7694 | 0.3688 | 0.1941 | 0.2638 | **0.6312** (inverted) |

Reading: at the 20d horizon, **higher backwardation predicts SMALLER
forward drawdowns**, not larger. AUC > 0.55 on the inverted side.
At 5d horizon AUC looks great (0.72-0.80), at 60d the inversion deepens
to 0.73-0.81. This is the canonical mean-reversion / coincident-detector
signature. Same shape baseline 2026-05-06 documented at lines 87-94.

**The AUC > 0.55 criterion is technically satisfied** (when inverted),
but the criterion was meant to surface forward-predictive content. An
inverted-AUC pass means "the feature lights up after the drawdown is
already happening, then the next 20-60 days are net-positive on average."
That is the textbook lagging-coincident signature, not leading.

---

## Coincident-vs-leading test (the verdict criterion)

Pearson correlation of each feature against trailing 20d return AND
forward 20d return. A leading feature has |fwd_corr| > |trail_corr|.

| Feature | Corr(trail 20d ret) | Corr(fwd 20d ret) | \|fwd\|/\|trail\| | Leading? |
|---|---:|---:|---:|---:|
| `vix_term_slope_9_30`  | −0.4205 | +0.1068 | 0.254 | **NO** |
| `vix_term_slope_30_3m` | −0.5937 | +0.1262 | 0.213 | **NO** |
| `vix_term_slope_3m_6m` | −0.6235 | +0.0542 | 0.087 | **NO** |
| `vix_term_slope_9_6m`  | −0.5837 | +0.1164 | 0.199 | **NO** |

**Trailing correlations are 4× to 12× larger in absolute value than
forward correlations.** The forward correlations are also POSITIVE while
trailing are NEGATIVE — i.e. when the feature is high (backwardation),
trailing returns were negative (we just dropped) and forward returns
are slightly positive (mean reversion ahead). Pure coincident-detector
behavior. None of the four passes the leading-criterion.

---

## Conditional drawdown when feature fires (top decile = backwardation)

If the feature genuinely warns of stress, top-decile days should have
WORSE forward drawdowns than baseline.

Unconditional baseline: mean fwd dd −3.34%, base rate dd ≤ −5% = 21.2%, p10 = −6.13%.

| Feature | N (top 10%) | Mean fwd dd | p10 fwd dd | dd ≤ −5% rate | Lift vs base |
|---|---:|---:|---:|---:|---:|
| `vix_term_slope_9_30`  | 107 | **−2.37%** | −6.16% | 19.6% | −1.6pp |
| `vix_term_slope_30_3m` | 107 | **−1.33%** | −3.29% | 1.9% | **−19.3pp** |
| `vix_term_slope_3m_6m` | 107 | **−1.39%** | −3.18% | 0.9% | **−20.3pp** |
| `vix_term_slope_9_6m`  | 107 | **−1.66%** | −4.93% | 10.3% | −10.9pp |

When the feature is in the stress decile, forward drawdowns are
consistently SHALLOWER than baseline, not deeper. Lift over baseline
on the dd ≤ −5% rate is −1.6 to −20.3 percentage points — i.e. the
feature is **anti-predictive at the canonical threshold**.

The mechanism: backwardation in the term structure happens AFTER the
spike has already been printed. By the time the slope flips positive,
SPY has already done most of its work. The 20-day forward window from
that anchor catches mostly the recovery, not the next leg down.

---

## In-sample vs OOS AUC (2025 Jan-Apr is the −18.76% drawdown OOS)

| Feature | IS 20d 5% AUC | IS 20d 3% AUC | OOS 20d 3% AUC |
|---|---:|---:|---:|
| `vix_term_slope_9_30`  | 0.404 | 0.312 | 0.512 |
| `vix_term_slope_30_3m` | 0.355 | 0.247 | 0.215 |
| `vix_term_slope_3m_6m` | 0.427 | 0.308 | 0.234 |
| `vix_term_slope_9_6m`  | 0.379 | 0.263 | 0.355 |

OOS AUCs are at-or-below 0.5 across all four features. The 9d/30d
slope barely clears coin-flip OOS (0.512). All others are inverted.
The pattern is consistent: even on the genuine 2025 stress event, the
log-slopes weren't telling us anything ahead of time.

---

## OOS narrative — anchor dates around the −18.76% drawdown

SPY peak 2025-02-19 @ $604.17, trough 2025-04-08 @ $490.85.

| Date | VIX9D | VIX | VIX3M | VIX6M | slope_9_30 | slope_30_3m | slope_3m_6m | slope_9_6m |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2024-12-02 (HMM stressed flip)  | 11.86 | 13.34 | 16.34 | 18.05 | −0.118 | −0.203 | −0.099 | −0.420 |
| 2025-01-15                      | 13.94 | 16.12 | 18.23 | 19.79 | −0.145 | −0.123 | −0.082 | −0.350 |
| 2025-02-19 (PEAK)               | 13.06 | 15.27 | 17.93 | 19.41 | −0.156 | −0.161 | −0.079 | −0.396 |
| 2025-03-14                      | ≈    | ≈    | ≈    | ≈    |  0.000 | −0.018 | −0.009 | −0.027 |
| 2025-04-08 (TROUGH)             | 67.63 | 52.33 | 41.50 | 35.77 | **+0.257** | **+0.232** | **+0.149** | **+0.637** |

**At the peak, all four slopes were strongly negative (calm/contango).
At the trough, all four flipped to large positive (extreme backwardation).
The slopes provided zero warning during the 78-day decline; they fired
at the bottom.**

Slice 1 found the same pattern at the trough date — confirming this
isn't a tenor-specific artifact. Adding VIX6M to the curve does not
change the conclusion. All four pairs are coincident.

---

## Data gap — CBOE put-call ratio

The dispatch's plan B was to validate CBOE total P/C ratio in the same
harness. **CBOE no longer exposes free historical P/C ratio CSVs**. I
probed:

| Endpoint | Status |
|---|---|
| `https://cdn.cboe.com/api/global/us_indices/daily_prices/total_pc.json` | 403 Forbidden |
| `https://cdn.cboe.com/api/global/delayed_quotes/historical/totalpc.csv` | 403 Forbidden |
| `https://cdn.cboe.com/resources/options/PutCallRatio_2025.xls` | 403 Forbidden |
| `https://www.cboe.com/us/options/market_statistics/historical_data/...` | Next.js HTML page; no underlying public CSV API found |
| Stooq `cpc.us`, `cpce.us`, etc. | API now requires captcha-gated apikey |
| `data.nasdaq.com /datasets/CBOE/TOTAL_PC.csv` | 403 Forbidden (paid tier) |
| yfinance `^CPC`, `^CPCE`, `^VPCALL` | "possibly delisted; no timezone found" — symbols not exposed |
| FRED | No CBOE put-call series indexed in FRED |

The CBOE data exists but every public-facing free endpoint is now
locked behind authentication, captchas, or a paid Nasdaq Data Link
subscription. **The dispatch's "free CBOE historical" assumption was
correct circa 2018-2022, no longer true in 2026.**

I deliberately did NOT synthesize a put-call proxy from VIX-family
data — that would be circular reasoning since the VIX panel already
encodes much of the same information, and a synthetic proxy that
"looks" leading would mislead the verdict. **A real put-call signal
requires either a paid feed or Schwab's options-chain endpoint.**

---

## Verdict — **Branch 3**

**Neither cheap source is leading.** VIX term structure, across all
four tenor pairs through the full 9d-to-6M curve, is a coincident /
mean-reverting detector with the same waveform as the level-VIX itself.
CBOE P/C ratio is unobtainable for free at historical resolution.

### Why Branch 3 specifically

- **Not Branch 1**: AUC > 0.55 was technically achieved on the inverted
  side, but the coincident-vs-leading Pearson test failed decisively
  for all four features (|fwd|/|trail| ratio of 0.087-0.254). The
  inverted-AUC pass is a mean-reversion artifact, not forward
  predictive content.
- **Not Branch 2**: The 4-feature failure is not borderline. Conditional
  drawdown rates in stress regime are 1-19 percentage points BELOW
  baseline; OOS AUCs are at-or-below 0.5. There is no ambiguity to
  resolve with one more cheap probe.
- **Branch 3 confirmed**: Adding more VIX-derivative tenors does not
  produce a leading signal. The information that the term structure
  carries is already discounted into the level. The signal we need
  must come from somewhere outside the VIX-implied-vol surface — IV
  skew (cross-strike, not cross-tenor), put-call flow, or
  fundamentals-driven stress proxies.

### What this means for sequencing

1. **Stop trying to make VIX features lead.** Slice 1 added them to
   the HMM input panel and found the lift came from yield-curve / credit
   features rotating the state space; the VIX features themselves were
   coincident. This dispatch confirms at the feature level (no HMM in
   the way) that they are coincident across all tenor pairs. Three
   independent measurements now agree.

2. **The HMM panel's leading content lives in `yield_curve_spread` +
   `credit_spread_baa_aaa` + `dollar_ret_63d`** — features already in
   the baseline panel. The slice-1 78-day OOS lead came from those.
   See slice-1 doc §"OOS narrative" for the exact attribution. **A
   targeted minimal-HMM experiment on those 3-4 features alone is the
   highest-ROI next regime-detection step**, not Schwab.

3. **Schwab IV skew becomes the priority for the *next* novel-input
   regime work**, with the historical-data caveat intact:
   - 30-min Schwab API verification step required (does
     `/marketdata/v1/chains` accept a date param?). If no, IV skew is
     a forward-collection problem, not an integration problem.
   - If Schwab has historical chains: the cross-strike skew (25Δ put /
     25Δ call IV) is the orthogonal information to VIX term structure.
     It captures asymmetric tail-risk pricing that level-and-tenor
     features can't see.
   - If Schwab does NOT have historical chains: paid provider
     (IVolatility, OptionsDX, CBOE DataShop) becomes the gate, and
     regime-panel rebuild gets blocked on real money.

4. **CBOE P/C as a separate workstream is now harder, not easier.**
   The cheap-historical assumption broke. Acquiring P/C history for
   2021+ requires Nasdaq Data Link subscription (~$50/month for the
   CBOE feed last I checked) or scraping CBOE's authenticated portal.
   For the marginal information P/C adds beyond what VIX + breadth +
   credit already encode, this is **not currently worth the cost**.

5. **HMM panel rebuild is not blocked on Schwab.** Per slice-1: the
   yield-curve / credit features in the EXISTING baseline panel produce
   a 78-day OOS lead through state-space rotation. The architectural
   question is whether to ship a re-trained HMM that emphasizes those
   features, NOT whether to add more inputs. The minimal-HMM experiment
   in §3 above answers that question without any new data.

### Engine-B integration status

**STILL BLOCKED**. Same logic as the 2026-05-06 baseline. We cannot
honestly tell Engine B's risk-sizing layer that any of the candidate
HMM forms is leading. The Pearson |fwd|/|trail| ratios are not just
sub-1, they're sub-0.3 across every measured feature today. If we wire
this into risk sizing, we'll be increasing exposure during the recovery
leg of every drawdown — exactly the wrong policy.

---

## Files

- `scripts/validate_regime_signals_cheap.py` — feature-level cheap-input validator
- `scripts/fetch_vix_term_structure.py` — extended to include `^VIX6M`
- `data/macro/VIX6M.parquet` — newly cached 6-month VIX term, 2020-01-02 → 2025-04-30
- `docs/Measurements/2026-05/regime_signal_validation_cheap_2026_05_06.json` — full numeric output

## Methodology notes

- 1086 trading days, 2021-01-01 → 2025-04-30
- Features `ffill`-aligned to SPY trading days (yfinance VIX series have rare gaps that the macro pipeline already handles via reindex/ffill)
- Forward target: SPY's worst forward drawdown over (t, t+20]; binary at −5% threshold
- AUC: Mann-Whitney U with tie-handling, computed locally (no sklearn)
- Pearson correlation on overlapping non-NaN rows
- Top-decile thresholds computed on the full 1086-day window (in-sample bias acknowledged; the IS/OOS split tests robustness)
- Read-only — no governor mutations, no production runs, no full backtests; ran inside worktree `agent-a824c9a6180a8b84c` on branch `regime-cheap-validation` (worktree branch named `worktree-agent-a824c9a6180a8b84c` in this isolation pattern)
