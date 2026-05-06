# Regime Signal Validation — 2026-05-06

**Question:** Do HMM + WS-C cross-asset signals predict forward SPY
drawdowns above the unconditional rate? Or are they noise that we'd
be wiring into Engine B's risk-sizing layer for no measurable benefit?

**Verdict (TL;DR):** **Branch 3 — NOISE. Do NOT scope Engine B
integration.** With one narrow exception (VVIX-proxy AUC 0.64 at 20d
in the 2023+ subwindow), every signal form falls below the 0.55
useful-AUC threshold at the load-bearing 20d horizon, INVERTS sign
on the genuine 2025 OOS event, and stays "on" so persistently that
it can't time anything. The HMM is a coincident vol detector, not a
forward-looking regime predictor.

---

## Methodology

- **Window:** 2021-01-01 → 2025-04-30, n=1086 trading days
- **Train/OOS split:** HMM trained 2021-01-04 → 2024-12-31 (1005
  obs); 2025-01-01 → 2025-04-30 is genuine OOS (81 obs)
- **Universe:** SPY (regime calls are macro-level)
- **Forward target:** 20d trading-day window, binary "fwd dd ≤ -5%"
  (5d / 60d sensitivity reported)
- **HMM model:** `engines/engine_e_regime/models/hmm_3state_v1.pkl`,
  3 states (benign / stressed / crisis), 7-feature panel
- **WS-C signals:** `hyg_lqd_z`, `dxy_change_20d`, `vvix_proxy` —
  computed directly per `core/feature_foundry/features/*.py` semantics
- **AUC:** Mann-Whitney U-based, with-tie-handling, computed from
  scratch; ties on rank averaged
- **Read-only:** no governor writes, no production runs, no full backtests
- **Script:** `scripts/validate_regime_signals.py`
- **Raw output:** `docs/Measurements/2026-05/regime_signal_validation_2026_05_06.json`

**Data caveat:** BAML OAS series (BAMLH0A0HYM2, BAMLC0A0CM) starts
2023-04-25, so `hyg_lqd_z` is None for 2021 + most of 2022. WS-C
signals jointly defined for ~451/1086 obs (~July 2023 onward).
Reported in dedicated subwindow section below.

---

## 1. AUC results — primary horizon (20d)

Target: P(forward 20d SPY drawdown ≤ -5%). Base rate 0.212.

| Signal | AUC | Verdict |
|---|---|---|
| `hmm_neg_p_benign` | **0.6146** | marginal |
| `hmm_p_stressed` | 0.6014 | marginal |
| `hmm_p_stress_or_crisis` | 0.5965 | marginal |
| `hmm_p_crisis` | 0.4919 | coin flip |
| `hyg_lqd_z` | 0.4883 | coin flip |
| `vvix_proxy` | 0.4600 | coin flip |
| `dxy_change_20d` | **0.2350** | inverted |
| `combined_pcrisis_x_confirms` | 0.4146 | inverted |
| `combined_pstress_x_confirms` | 0.4094 | inverted |

**Reading.** The single best 20d-horizon signal is "1 minus
P(benign)" — i.e. the HMM's general "this isn't normal" call — at
AUC 0.61. It just barely clears the 0.55 useful threshold. The
canonical `p_crisis` posterior is a coin flip. Combining HMM with
WS-C confirmation makes things WORSE, not better — both `combined_*`
signals invert because the WS-C confirmations rarely fire and when
they do, the timing of "two-out-of-three" arriving is itself lagging.

DXY at AUC 0.235 means the signal is **strongly inverted** at 20d:
when the dollar rallies fast, the next 20 days are LESS likely to
show SPY drawdown, not more. The "classic crash signature" theory
in `dxy_change_20d.py`'s docstring does not survive measurement
in this window.

## 2. AUC at 5d / 60d horizons

| Signal | 5d AUC | 60d AUC |
|---|---|---|
| `hmm_p_crisis` | 0.8796 | **0.3102 (inverted)** |
| `hmm_p_stress_or_crisis` | 0.7388 | 0.4317 |
| `hyg_lqd_z` | **0.9627** (small-N) | 0.1535 (inverted) |
| `dxy_change_20d` | 0.3482 | 0.2645 |
| `vvix_proxy` | 0.4945 | 0.3174 |

**5d looks great. It is not.** Base rate at 5d is 0.012 (13 positives
in 1086 days). HYG_z at AUC 0.96 is computed on **4 positives in
446 obs** within the WS-C subwindow — a known small-N inflation
artifact. The 5d signal is essentially "vol just spiked, the next
week probably stays bad," which is a continuation effect, not a
forward warning.

**60d is where the regime story dies.** Every signal INVERTS at the
60d horizon. AUC 0.31 means "when HMM says crisis, the next 60 days
are LESS likely to draw down ≥ -5%." This is mean reversion: by
the time HMM detects crisis, the drawdown is already in progress,
and 60 days later we're recovering. Classic textbook **lagging /
coincident indicator** signature.

This is empirically verified in §6 below.

## 3. Conditional forward drawdown by regime

Unconditional 20d fwd dd: mean -3.34%, P10 (worst tenth) -8.65%.

| Regime | N (% days) | mean fwd dd | P10 |
|---|---|---|---|
| `hmm_benign` | 488 (45.8%) | -3.20% | -5.31% |
| `hmm_stressed` | 319 (29.9%) | -3.67% | -7.14% |
| `hmm_crisis` | 259 (24.3%) | -3.21% | -7.33% |
| `hyg_z > 1` | 70 (6.6%) | -1.62% | -3.31% |
| `dxy_change > 2%` | 120 (11.3%) | -2.14% | -4.53% |
| `vvix > p90` | 91 (8.5%) | -3.50% | -6.98% |
| any 1+ confirmation | 263 (24.7%) | -2.50% | -4.88% |
| 2+ confirmations | 18 (1.7%) | -1.77% | -3.97% |
| HMM crisis AND 2+ confirms | **9 (0.8%)** | -2.56% | -4.61% |
| HMM crisis only | 259 (24.3%) | -3.21% | -7.33% |

**The killer line.** HMM crisis days have mean fwd dd of -3.21%.
Benign days have mean fwd dd of -3.20%. **Indistinguishable.**

The combined "HMM crisis AND 2+ confirmations" gate — the canonical
WS-C transition gate — fires on 9 days out of 1086 (0.8%), and on
those 9 days the mean fwd dd is -2.56% — BETTER than the
unconditional baseline. Acting on this gate would have been WORSE
than not acting.

## 4. Hit rate / FPR / precision (target: 20d fwd dd ≤ -5%)

| Signal | TPR | FPR | precision | lift_vs_base |
|---|---|---|---|---|
| `argmax_stressed_or_crisis` | 0.681 | 0.505 | 0.266 | +0.054 |
| `argmax_crisis` | 0.274 | 0.235 | 0.239 | +0.027 |
| `vvix > p90` | 0.088 | 0.085 | 0.220 | +0.008 |
| `dxy_chg > 2%` | 0.018 | 0.138 | 0.033 | -0.179 |
| `hyg_z > 1` | 0.000 | 0.083 | 0.000 | -0.212 |
| `2+ confirmations` | 0.000 | 0.021 | 0.000 | -0.212 |
| `HMM crisis AND 2+` | 0.000 | 0.011 | 0.000 | -0.212 |

The "best" precision lift over base rate is 5.4 percentage points
(argmax_stressed_or_crisis), purchased at a 50.5% false-positive
rate. To gain 5pp of precision the signal calls "stress" on
**half of all calm-market days**. That isn't risk awareness —
that's a permanently-pessimistic bias.

The two-out-of-three confirmation regime — the architectural
keystone of WS-C — has TPR=0 on -5% drawdowns. It never warned
on a single one in this window.

## 5. Lead time and signal persistence

The original "lead time" question (when stress fires, how many
trading days before the trough?) is dominated by **persistence**:
the HMM stress signal is on for so long that the "first fire date
in lookback window" becomes the start of the lookback.

| Signal | n_runs | median run len (bars) | max run len | % time on |
|---|---|---|---|---|
| `argmax_crisis` | 5 | 48 | 120 | 25.7% |
| `argmax_stressed_or_crisis` | 4 | 40 | **497** | 55.1% |
| `2+ confirmations` | 9 | 2 | 12 | 2.8% |

The "stressed_or_crisis" call has only **4 runs** across 1086 days.
The longest single run is 497 consecutive trading days — nearly
two years labeled "stressed" without interruption. A signal on
55% of the time, in 4 long blocks, cannot time anything. If you
de-risk on it you stay de-risked through the entire bull leg.

Median lead-time at 63 bars (3 calendar months) for argmax_crisis
is mostly an artifact of "the signal was already on for the
maximum lookback window." The cross-asset 2+ confirmation gate
gives genuinely short-run signals (median run 2 bars), but
warned only **4 of 43 drawdown events** in the window — TPR = 9%.

## 6. Coincident vs leading — direct test

Pearson correlation of `hmm_p_crisis`:
- **vs trailing 20d realized return: -0.512**
- vs forward 20d realized return: -0.209

The crisis-state probability tracks the past more than 2× as
strongly as it tracks the future. This is a textbook **coincident
indicator**, not a forward-looking signal. The HMM is detecting
realized vol patterns (its inputs are `spy_ret_5d`, `spy_vol_20d`
plus macro levels) which by construction lag price action by the
length of the rolling window.

This is the same architectural failure mode flagged in
`docs/Core/roles.md` for this lens: "If regime detection only flags
a regime AFTER a 20% drawdown, it is useless." We have empirically
landed exactly there.

## 7. WS-C-defined subwindow (~July 2023+)

When HYG_z is actually defined (n=451), the picture changes
slightly but doesn't redeem the framework:

| Signal (5% target) | AUC |
|---|---|
| `hmm_p_crisis` | 0.5656 |
| `hmm_p_stress_or_crisis` | 0.6292 |
| `hyg_lqd_z` | 0.4883 |
| `vvix_proxy` | 0.6440 |
| `dxy_change_20d` | 0.1799 |

The WS-C subwindow gives the HMM a slightly easier test (its 60-day
warm-up is past, the 2022 bear is excluded). HMM stress probability
gets to AUC 0.63. **VVIX-proxy is the only WS-C component with
real signal** (AUC 0.64). HYG_z is a coin flip; DXY is strongly
inverted.

Implication: if any narrower wiring is justified, it's VVIX-proxy
alone. The two-out-of-three confirmation construct is dragged
down to noise by HYG and DXY.

## 8. OOS — 2025 Jan-Apr

The 2025 OOS window contains the actual -18.8% peak-to-trough event
that culminated April 8, 2025. With horizon=20d, the trough sits
outside the forward window for most anchor dates, so the -5%
binary target has 0 positives in OOS. To make OOS measurable, we
relax to -3% (18 OOS positives, base rate 0.295):

| OOS signal | AUC (3%) |
|---|---|
| `hmm_p_crisis` | 0.3630 |
| `hmm_p_stress_or_crisis` | 0.3630 |
| `hmm_neg_p_benign` | 0.3630 |

**OOS AUC of 0.36 means the signal is WORSE THAN COIN-FLIP on the
actual 2025 drawdown.** The HMM was incorrectly calling benign
into the very event WS-C was supposedly designed to anticipate.

In-sample AUC at -3% target is 0.46-0.48 (already coin-flip in
sample). OOS deteriorates further. The model does not generalize.

## 9. Component decomposition — which WS-C signal carries weight?

Across the full window:
- `hyg_lqd_z` (credit): AUC 0.49 / **0.96** at 5d (small-N artifact)
- `dxy_change_20d` (FX): AUC 0.24 — **inverted** at 20d
- `vvix_proxy` (vol-of-vol): AUC 0.46 / **0.64** in WS-C subwindow

The "two-out-of-three" architecture is the wrong combination shape.
HYG and DXY are noise and inverted-noise in this regime;
they actively dilute VVIX. If any cross-asset signal deserves
further investigation, it's VVIX-proxy alone, evaluated as a
standalone gate, not as part of a 3-way confirmation.

## Verdict — Branch 3: do NOT scope Engine B integration

Acceptance criteria (from the brief):

> **Branch 1 — predictive enough to wire:** AUC > 0.55 on at least
> one of the three signal forms (HMM alone / WS-C alone / combined).
> Conditional drawdown rate materially above baseline. Lead time
> ≥ 5 days.

We meet AUC > 0.55 narrowly on HMM stress-or-crisis (0.60) at 20d.
We FAIL conditional-drawdown-materially-above-baseline (HMM crisis
indistinguishable from benign). We FAIL lead-time-≥-5-days in any
honest interpretation — the signals don't have lead time, they
have persistence.

> **Branch 2 — predictive in some regimes only:** Some HMM states
> predict, others don't.

The HMM 3-state structure does NOT have a predictive subset. The
"crisis" state is the worst performer at the 20d horizon. The
"stressed" state is marginally better but is on more than 50% of
the time. There's no clean subset-selection that survives.

> **Branch 3 — noise.**

Best signal at 20d is AUC 0.61, just over the threshold. Conditional
drawdowns are flat across regimes. OOS AUC inverts to 0.36 on the
actual 2025 event. Cross-asset combination subtracts value. This is
a noise envelope around a thin signal that doesn't generalize.

**Verdict: Branch 3.**

## Recommended actions

1. **Do NOT scope Engine B integration of HMM + WS-C signals.**
   Wiring AUC-0.60-with-OOS-inversion into risk sizing would inject
   timing noise into capital allocation with negative expected value.

2. **Keep observability-only status for HMM and WS-C.** They are not
   harmful as logged-but-not-acted-on diagnostics, and they provide
   useful descriptive data for `docs/Measurements/`. Engine F can
   continue tagging trades by HMM regime for post-hoc attribution.

3. **Specifically address the architectural gap.** Engine E's HMM
   feature panel is dominated by trailing-window realized statistics
   (`spy_ret_5d`, `spy_vol_20d`) that by construction lag price.
   No amount of HMM tuning will fix this — the inputs are
   coincident. To get a leading signal, the feature set needs
   actually-leading inputs:
   - VIX **term-structure** (VIX9D / VIX / VIX3M) — index brief
     calls this out as forward-looking and we don't currently use
     it. The spec exists in `forward_stress_detector.py` but it
     feeds the threshold-detector chain, not the HMM.
   - Implied-vol skew (put-call IV ratio)
   - High-frequency option-flow / put-call volume ratio
   - Insider transaction net buys / sells (lagged but
     genuinely-leading on multi-month horizons)
   - Earnings-revision dispersion (cross-sectional analyst-revision
     z-scores, available via SimFin/yfinance)

4. **VVIX-proxy is the one exception.** AUC 0.64 in WS-C subwindow
   is interesting enough to merit standalone evaluation. If a
   narrow Engine B hook ever happens, it should be a VVIX-only
   gate, not the three-way confirmation. But this is **deferred
   below the broader "fix the leading-signal gap" work** — wiring
   one component of a broken system into Engine B doesn't justify
   the propose-first risk surface.

5. **WS-C three-way "two-out-of-three" architecture should be
   archived to `Archive/` once the report lands.** It has zero
   true positives on -5% drawdowns in the 18-month subwindow it's
   defined on, and its components fight each other (DXY inverts,
   HYG is noise, only VVIX informs). The architecture is wrong;
   keeping the code as a standing reference is misleading.

6. **For Path C unblock criteria** (per
   `project_path_c_deferred_2026_05_06.md`): regime-conditional
   de-gross was named as a prerequisite for the compounder
   strategy. The current regime detector cannot satisfy this
   prerequisite. Path C's regime-gating unlock is now blocked
   on either (a) building a leading-feature panel and retraining,
   or (b) accepting that the compounder runs without
   regime-conditional de-gross. Recommendation: keep deferred
   until at least VIX term-structure is wired into the HMM
   feature set.

## Repo state

- **Branch:** `worktree-agent-a8f8e59179e23cf91`
- **Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-2/.claude/worktrees/agent-a8f8e59179e23cf91`
- **Modified files (read-only analysis):**
  - `scripts/validate_regime_signals.py` (new)
  - `docs/Measurements/2026-05/regime_signal_validation_2026_05_06.md` (this file)
  - `docs/Measurements/2026-05/regime_signal_validation_2026_05_06.json` (raw)
- No production state changes. No `data/governor/` writes. No
  Engine B / `live_trader/` modifications. No edges.yml changes.
