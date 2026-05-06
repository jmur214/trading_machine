---
name: Macro signal leading/coincident/lagging classification — empirical map (2026-05-06)
description: Living empirical classification of which macro signals in this codebase have proven leading vs coincident vs lagging on SPY drawdowns, based on the 2026-05-06 baseline validation + slice-1 panel rebuild. Update as new features are validated.
type: project
---
**Why this exists:** the 2026-05-06 baseline finding established that the HMM is a coincident vol detector. The slice-1 rebuild then showed that coincident vs leading is a *property of each feature*, not just of the HMM aggregating them. Future panel-rebuild slices need a single place to track which features are which empirical class.

**How to apply:**
- Before adding a feature to the HMM panel, check this list. If the feature class is "coincident," it should be added to confirm regime changes, not to anticipate them — and the AUC test should weight forward correlation, not standalone AUC.
- When AUC moves on a panel rebuild, attribute the lift to a specific feature (or to state-space rotation among features already classified as leading). Do not call the rebuild successful purely on AUC.

## LEADING (forward correlation > trailing in absolute value, OR demonstrated ≥30-day lead on multiple drawdowns)

| Feature | Source | Evidence |
|---|---|---|
| (none with confirmed isolation) | | yield_curve_spread + credit_spread mass produced 78-day OOS lead in slice-1 HMM, but mechanism is state-space rotation not pure standalone leading-correlation. Mark "candidate-leading via interaction." |

## CANDIDATE-LEADING (interaction effect; validated on 1 OOS event; needs more drawdowns)

| Feature | Source | Evidence |
|---|---|---|
| `yield_curve_spread` (T10Y2Y) | FRED | Slice-1 stressed-state z-mean +1.24. Drove 78-day lead on 2025-02-19 peak. Need to test on 2022-Q1 drawdown, 2020-Q1 COVID drawdown, October 2018. |
| `credit_spread_baa_aaa` | FRED (BAA10Y - AAA10Y) | Slice-1 stressed-state z-mean -0.97. Late-cycle credit-tightening pattern. Same scope of further testing needed. |
| `dollar_ret_63d` (DTWEXBGS 3m return) | FRED | Slice-1 stressed-state z-mean +0.05; benign-state z-mean -0.50. Weakly distinctive. |

## COINCIDENT (forward correlation ~0; trailing correlation strongly negative)

| Feature | Source | Evidence |
|---|---|---|
| `spy_vol_20d` | computed | Lagging by construction; 20d backward window. |
| `spy_ret_5d` | computed | Lagging by construction; 5d backward window. |
| `vix_level` (VIXCLS) | FRED | Tracks realized vol; coincident with events. |
| `vix_term_spread` (vix3m - vix) | yfinance | Slice-1 standalone: trailing +0.498, forward -0.167. Fires AT trough. |
| `vix9d_over_vix_ratio_minus1` | yfinance | Slice-1 standalone: trailing -0.423, forward +0.107. Fires AT trough. |
| `vix_zscore_60d` | computed from yfinance VIX | Slice-1 standalone: trailing -0.617, forward +0.140. Fires AT trough. |
| `hyg_lqd_z` (HY-IG spread 60d z) | FRED via WS-C | Baseline: AUC 0.488 (coin flip on 20d-fwd). Coverage starts 2023-07. |
| `dxy_change_20d` (20d % change in DTWEXBGS) | FRED | Baseline: AUC 0.235 (strongly INVERTED; "rally → stress" theory empirically wrong). |
| `vvix_proxy` (30d log-return std of VIX) | computed | Baseline: AUC 0.46 short-window, 0.64 in WS-C-defined sub-window. Coincident but standalone OK on near-term horizons. |

## LAGGING (signal arrives only after the event is realized)

| Feature | Source | Evidence |
|---|---|---|
| 5-axis correlation/breadth detectors (existing Engine E threshold detectors) | various | Built on 20-50d rolling stats. Documented as lagging in `engines/engine_e_regime/index.md` purpose section. |

## UNTESTED (next slice candidates)

| Feature | Source candidate | Hypothesis |
|---|---|---|
| IV skew (25Δ put / 25Δ call) | CBOE; possibly via OPR option chain | Skew steepens BEFORE realized vol expands. Standard literature claim. |
| Put/call ratio (CBOE total) | CBOE direct or yfinance via ^CPC | Spikes precede drawdowns. |
| Earnings revision dispersion | I/B/E/S consensus or yfinance per-ticker | Dispersion widens at fundamental turning points. |
| Insider net-buy | EDGAR (Form 4) | Smart-money signal; lead time TBD. |

## Methodological lessons captured

1. **Standalone AUC alone misleads.** A 20d-fwd-dd AUC of 0.68 looks great until you check the sign — `vix_term_spread` AUC=0.68 means "high contango spread predicts drawdowns," which is mean-reversion, not leading. Always check signs against economic intuition AND check coincident-vs-leading correlation separately.
2. **State-space rotation can mimic a leading signal.** Adding any new feature to an HMM redistributes state probabilities; the redistribution may produce earlier transitions even when the new feature is coincident. Validate by checking that the new feature's standalone behavior matches the claimed mechanism.
3. **One OOS event is anecdote, not evidence.** The 2025 -18.76% drawdown is tempting to over-fit narratives to. Lead-time confirmations should require ≥3 independent drawdown events.
4. **Persistence kills timing.** A signal that's on 65%+ of trading days is a near-permanent label, not a regime trigger. Median run-length ≤ 20 bars is the operational floor.
