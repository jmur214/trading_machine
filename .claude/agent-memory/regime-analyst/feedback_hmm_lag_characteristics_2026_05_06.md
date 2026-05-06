---
name: HMM detection methods — lag characteristics summary (2026-05-06)
description: Cross-method lag survey from the slice-1 panel rebuild. Documents what lead-time each HMM variant gives on the canonical 2025 -18.76% drawdown, so future regime work has a quantitative baseline for "how leading is leading enough?"
type: feedback
---
Use this table as the lag-characteristics baseline when proposing new regime detectors. Lead-time measured against SPY peak (2025-02-19) of the canonical -18.76% peak-to-trough event.

**Core rule: lead-time alone is insufficient.** The slice-1 HMM has 78-day lead-time but the lead came from features unrelated to the slice (yield curve / credit). Verify the *mechanism* of the lead-time, not just the lead-time itself.

**Why:** Mistaking state-space rotation for "the new feature added a leading signal" produces a 1-of-1 OOS lookback that cherry-picks 2025. The 2024-12-02 stressed-flip would not have generalized to 2022 (which the slice-1 HMM also catches via `crisis` from 2022-02-11) on the same mechanism.

**How to apply:**
1. Whenever a new feature is added to the HMM panel and AUC moves, immediately check whether the new feature's *standalone* AUC and standalone coincident-vs-leading ratio support the change. If not, the lift is state-space rotation, not new leading information.
2. When proposing new regime detectors, attach an expected lead-time AND a mechanism. "VIX backwardation should lead by X days because Y" is the testable form. "AUC went up" is not.
3. Before any Engine B integration, confirm the lead-time is reproducible across multiple drawdown events, not just 2025.

## Lag survey table (lead time on 2025-02-19 peak)

| Method | First non-benign state | Lead time | Mechanism |
|---|---|---:|---|
| Baseline 7-feature HMM | never (benign through peak) | 0 days | n/a — lagging |
| Slice-1 10-feature HMM (with VIX-term) | stressed @ 2024-12-02 | 78 days | yield-curve / credit features rotated into stressed state |
| Standalone `vix_term_spread` (any threshold) | only @ trough | negative (lags) | coincident vol detector |
| Standalone `vix9d_over_vix_ratio_minus1` | only @ trough | negative (lags) | coincident vol detector |
| Standalone `vix_zscore_60d` | only @ trough | negative (lags) | coincident vol detector |
| 5-axis ForwardStressDetector tier 1 (term spread + level + z) | unknown — not validated against this event | TBD | candidate, needs independent test |

## Lag survey on prior drawdowns (slice-1 HMM, all argmax transitions)

| Event date (transition) | Argmax | Subsequent SPY behavior |
|---|---|---|
| 2020-07-10 → stressed | stressed | early-COVID-recovery; 2 days later → crisis |
| 2020-07-13 → crisis | crisis | held through 2020-08; transient |
| 2022-02-11 → crisis | crisis | 1 month before 2022-Q1 -25% bear started — clean lead |
| 2023-10-06 → crisis | crisis | mid-correction (Oct 2023 dip) — coincident |
| 2024-08-02 → crisis | crisis | August 2024 mini-crash — coincident |
| 2024-10-25 → stressed | stressed | flag for late-2024-low-vol-yield-curve-uninversion regime |
| 2024-12-02 → stressed | stressed | persists |
| 2025-02-21 → crisis | crisis | 2 days after peak — coincident on the top, leading on the bottom |

Pattern: HMM `crisis` is reliably coincident-with-events; `stressed` is sometimes leading (2024-Q4) but driven by yield-curve / credit, not vol features.

## Method classes by lag characteristic (project-wide)

- **Lagging by construction:** rolling realized vol (spy_vol_20d), past returns (spy_ret_5d), drawdown depth, ATR-based axis. Use as state-confirmation, never as state-trigger.
- **Coincident:** VIX level, VIX term spread, VIX z-score, VVIX-proxy, all option-implied vol features tested so far in this codebase. They fire AT events, not before. Useful for confirming a regime change is real; useless for de-grossing in advance.
- **Sometimes-leading:** yield-curve un-inversion (T10Y2Y change-of-sign), credit spread tightening into late cycle (BAA-AAA), DXY trend persistence. Mechanism is fundamental late-cycle dynamics, not market-implied. Validated lead on 2025 drawdown via state-space rotation in slice-1 HMM. Need to confirm on more events.
- **Untested:** IV skew (25Δ put / 25Δ call), put/call ratio, earnings revision dispersion, insider net-buy. These are the candidates for slice 2.

## Kill-switch / threshold lessons from this round

- 0.5 threshold on `p_crisis` and `p_stress_or_crisis` produced **TPR 0.504 / 0.739** at FPR **0.276 / 0.640** in slice-1 — i.e., the stress-or-crisis gate fires on 64% of non-event days. Threshold tuning won't fix this; it's an artifact of the state being on 67% of the time.
- Persistence > 100 bars median run-length means the signal is operationally useless for de-grossing decisions even when AUC is OK.
- Hard rule before any kill-switch deployment: median run-length must be ≤ 20 trading days OR the signal must be a transition trigger, not a state label.
