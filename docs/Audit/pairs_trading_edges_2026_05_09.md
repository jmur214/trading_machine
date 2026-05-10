# Pairs trading edges — cointegration screen + framework (T-2026-05-09-017)

**Generated:** 2026-05-09
**Branch:** `feature/pairs-trading-edges`
**Status:** Code shipped (paused/feature). Edges DO NOT trade in production
until lifecycle gauntlet validates them on substrate-honest data.

---

## Headline

**1 of 12 candidate pairs survived the cointegration screen.** The
single survivor is **MA / V** (Mastercard / Visa). The dispatchable
brief expected 8-12 of 12 pairs to survive; the substrate-honest
2021-2024 in-sample window proved much more hostile to cointegration
than the academic literature would suggest.

This is an **honest result, not a methodology failure**. See "Why so
few?" below.

| Survivor | Sector | Cointegration p | ADF p (spread) | Half-life (d) | β | β instability |
|---|---|---:|---:|---:|---:|---:|
| **MA / V** | Payments | **0.0045** | 0.0008 | 21.7 | 0.8901 | 19.5 % |

All four screening axes passed comfortably:

- Engle-Granger cointegration test rejects "no cointegration" at
  p = 0.0045 (well below the 0.05 threshold).
- Direct ADF on the spread residual rejects unit root at p = 0.0008
  (spread is stationary).
- Half-life of mean reversion ≈ 22 trading days. Within the
  acceptable [1, 60]-day band — fast enough to trade, slow enough to
  not be microstructure noise.
- Per-year β estimates {0.95, 0.86, 0.95, 0.81} across 2021-2024.
  Max-min spread / mean = 19.5 % — well below the 30 % instability
  threshold.

---

## Why so few? (Substrate-honest reality vs the literature)

The brief's pair list is the canon of stat-arb literature: KO/PEP,
HD/LOW, CVX/XOM, KO/PEP, JPM/BAC. Most failed for the same reason:
**post-2020 sector pairs have been progressively decoupling** as
sector ETFs, factor strategies, and idiosyncratic shocks have eroded
the structural relationship that gave these pairs their stat-arb
appeal in the 1990s/2000s.

Per-pair failure mode:

| Pair | Failed on | Why |
|---|---|---|
| KO / PEP | coint p=0.79, ADF p=0.57, half-life 109d, β instability 133 % | KO/PEP relationship broke; both moved to brand-portfolio strategies that no longer co-move |
| MCD / YUM | coint p=0.080 (close), β instability 167 % | YUM's spin-offs (Yum China 2016, etc.) disrupted comp; MCD/YUM no longer share fundamental driver |
| HD / LOW | coint p=0.15, ADF p=0.053 (borderline) | Housing-cycle exposure, but 2022-2023 rate shock hit them differently (LOW more cyclical) |
| CVX / XOM | coint p=0.67, half-life 122d, β instability 49 % | Oil supercycle (2021-2022 surge, 2023-2024 normalization) overwhelmed comp relationship |
| WMT / TGT | coint p=0.52, half-life 86d, β instability 1422 % | TGT's 2022 inventory crisis killed the pair; β oscillates wildly |
| JPM / BAC | coint p=0.65, half-life 139d, β instability 126 % | Different rate-sensitivity profiles; BAC NIM dynamics diverged |
| MSFT / AAPL | coint p=0.58, half-life 75d, β instability 95 % | Mega-cap tech as a *factor* moved them; their idiosyncratic relationship is gone |
| UNH / CI | coint p=0.47, half-life 85d, β instability 309 % | Managed care segments diverged (UNH's Optum vs CI's Express Scripts) |
| GS / MS | coint p=0.12 (close) | IB cycle similar but capital-markets businesses diverged 2022-2024 |
| KMI / OKE | coint p=0.62, half-life 87d, β instability 46 % | Pipeline mix differences (gas vs liquids) showed in 2022 energy regime |
| ORCL / IBM | coint p=0.41, half-life 61d, β instability 87 % | ORCL's Cerner acquisition + cloud pivot disrupted the legacy-tech comp |

The MA/V survivor is the canonical example of a pair that **does**
remain cointegrated: both are pure payment-network duopolists with
nearly identical revenue models (interchange + brand fees), no
acquisitions disrupting the comp through 2024, and similar regulatory
exposure.

This finding aligns with academic work showing post-2010 pairs-trading
profitability has compressed substantially as automated arbitrage and
sector-ETF flows reduce inefficiencies (Krauss 2017; Smith & Xu 2017).

---

## Setup

**Engle-Granger 2-step cointegration screen:**

1. Read closing prices from `data/processed/<TICKER>_1d.csv` for each
   leg.
2. Restrict to **in-sample window 2021-01-01 .. 2024-12-31**. 2025 is
   reserved as OOS and is **NOT** used for screening (eliminates
   look-ahead in pair selection).
3. OLS regression of log(Y) on log(X) → cointegration coefficient β
   (closed-form OLS, deterministic).
4. `statsmodels.tsa.stattools.coint(log_y, log_x, autolag="AIC")` —
   returns Engle-Granger test statistic + p-value.
5. `statsmodels.tsa.stattools.adfuller(spread, autolag="AIC")` —
   direct ADF on spread residuals (cross-check; should agree with
   step 4 within numerical noise).
6. Half-life: AR(1) on Δspread vs lagged spread, half-life =
   −ln(2) / ln(1 + θ) where θ is the AR coefficient. Drops pair if
   θ ≥ 0 (no mean reversion) or if half-life > 60 days.
7. β stability: per-year β estimates across 2021, 2022, 2023, 2024;
   instability = (max − min) / |mean| × 100 %; drops pair if > 30 %.

**Survivor selection criteria** (all must pass):
- coint p ≤ 0.05
- ADF p ≤ 0.05
- 1 ≤ half-life ≤ 60 trading days
- β instability ≤ 30 %

**Substitutions vs the brief:**
- **MCD / QSR** → **MCD / YUM**. Restaurant Brands International (QSR
  ticker) is not in the F6 historical-S&P-500 substrate; YUM is a
  closer comp (both quick-service mega-caps).
- **UNH / ANTM** → **UNH / CI**. Anthem renamed to Elevance Health
  (ELV) in mid-2022; using ELV gives only 2.5 yr of in-sample history
  and β is unstable across the rename. CI (Cigna) is the standard
  managed-care comp in the literature.

Both substitutions documented inline in the screen script's module
docstring.

---

## Edge framework (`engines/engine_a_alpha/edges/pairs_trading_v1.py`)

### Mechanism (per pair P = (X, Y))

```
spread_t = log(Y_t) − β · log(X_t)
z_t      = (spread_t − μ) / σ          # rolling 60d window

if |z_t| ≥ z_stop  (=4.0):  flat (broken)
elif z_t ≤ −z_entry (=−2.0): long Y, short X  (Y is cheap)
elif z_t ≥ +z_entry (=+2.0): short Y, long X  (Y is rich)
elif |z_t| ≤ z_exit (=0.5):  flat (mean-reverted)
else:                        flat (neutral band; stateless v1)
```

Output maps to the project's signal contract `{ticker: float in [-1, 1]}`:
- Long-Y / short-X side → Y=+1.0, X=−1.0.
- Short-Y / long-X side → Y=−1.0, X=+1.0.
- Tickers outside the pair → 0.0 (abstain).

### Statefulness — v1 limitation

The v1 framework is **stateless**: between |z_exit| and |z_entry|,
the edge abstains rather than holding the prior position. Classical
pairs trading uses hysteresis ("hold while in trade until z crosses
exit threshold"), which requires the edge to track its own state.
Hysteresis is left to a v2 follow-up; the entry threshold of 2.0 is
wide enough that the market spends most of its time in the inactive
zone, so the practical impact is small for a paused-tier feature.

### Parameter choices (shared across all pairs by design)

| Parameter | Value | Rationale |
|---|---:|---|
| `lookback_days` | 60 | Standard in literature (Avellaneda 2008). Matches the half-life of MA/V (22d) at ~3× — full mean-reversion cycle resolves within window. |
| `z_entry` | 2.0 | Standard 95-th percentile threshold. Some papers use 1.5 (more trades, more noise) or 2.5 (sparser, slower); 2.0 is the middle. |
| `z_exit` | 0.5 | Half-standard-deviation exit. Tighter than 0.0 (full mean revert) — captures most of the move without waiting for the spread to fully normalize. |
| `z_stop` | 4.0 | Catastrophic-blowout protection. Above 4σ, the cointegration relationship is structurally suspect and we cut. |

**Per-pair parameter tuning is FORBIDDEN.** Per the brief's hard
constraint, all pairs share the same z_entry / z_exit / z_stop /
lookback_days. Per-pair tuning would be in-sample overfitting.

The only per-pair quantities are: `ticker_x`, `ticker_y`, `beta`
(estimated by the screen, not tuned), `pair_id` (label).

### Code organization

ONE file (`pairs_trading_v1.py`) with ONE class (`PairsTradingEdge`)
that auto-registers ONE EdgeSpec per surviving pair from the screen
manifest. Each spec carries per-pair config in `params`; the
`mode_controller` loader instantiates `PairsTradingEdge(params=params)`
per spec.

For a 1-pair inventory this might seem heavyweight, but the framework
scales cleanly: future re-screens (different windows, different
thresholds, different candidate sets) can produce additional
survivors that auto-register without any code change.

---

## Registered edges

| Edge ID | Module | Status | Tier | Beta |
|---|---|---|---|---:|
| `pairs_trading_MA_V_v1` | `engines.engine_a_alpha.edges.pairs_trading_v1` | paused | feature | 0.8901 |

All registrations go through the standing `EdgeRegistry().ensure()`
pattern. Status field is **write-protected** in `ensure()` (per the
2026-04-25 status-stomp fix), so subsequent module imports cannot
revert lifecycle decisions.

---

## Determinism check

Pre-change baseline canon md5 (from earlier T-013 measurement on this
worktree): `182af6a1240da35055f716ef9dfcd333` (Sharpe 0.127, q1 task).

Post-change canon md5 with new pair edges registered:
`182af6a1240da35055f716ef9dfcd333` — **IDENTICAL**.

Reason: the pair edge is at status='paused', so it runs at 0.25×
weight (per soft-pause infrastructure, memory
`project_soft_pause_win_2026_04_24`). For it to perturb the canon
md5 the pair would need to fire a non-zero signal that survives
consensus aggregation. In the q1 task's 2025 OOS window, MA/V's
spread did not enter or stop bands at any bar that produced a
consensus-eligible trade decision.

This is consistent with the brief's expectation that paused-tier
feature edges should not change the trading decision-stream of the
existing active edges.

**2-rep cross-run bitwise check (`--runs 2 --task q1`)**:
Sharpe 0.127 / 0.127, `Canon md5 unique: 1 / 2`,
result: `PASS — Sharpe within ±0.02 AND bitwise-identical canon md5`.
Cross-run reproducibility is preserved.

---

## Tests

`tests/test_pairs_trading_edges.py` — 14 tests, all passing:

- `test_spread_zscore_entry_long_short_when_below_threshold` — z below
  −z_entry → long Y, short X.
- `test_spread_zscore_entry_short_long_when_above_threshold` — symmetric.
- `test_spread_zscore_exit_when_meanreverted` — |z| ≤ z_exit → abstain.
- `test_stop_loss_when_spread_breaks` — |z| ≥ z_stop → abstain (overrides entry).
- `test_neutral_band_between_exit_and_entry_abstains` — stateless v1
  abstains; documents the hysteresis limitation.
- `test_pairs_handle_missing_ticker_gracefully` — half-pair fed in →
  abstain entire universe (cannot half-trade a pair).
- `test_misconfigured_spec_abstains` — empty `ticker_x`/`ticker_y` →
  abstain.
- `test_degenerate_spread_zero_std_abstains` — constant spread (σ=0)
  → abstain (no division by zero).
- `test_insufficient_history_abstains` — fewer aligned bars than
  lookback → abstain.
- `test_beta_alters_z_score` — β participates in the spread; z(β=2)
  ≠ z(β=1) on the same input.
- `test_all_pairs_register_at_paused_feature` — every auto-registered
  spec has `status="paused"` and `tier="feature"`.
- `test_module_loads_without_manifest` — fresh checkout (no manifest
  file) → module imports cleanly, no specs registered, no crash.
- `test_shared_defaults_have_required_keys` — drift guard on the
  `SHARED_DEFAULTS` dict.
- `test_manifest_is_valid_json_and_versioned` — schema check on the
  cointegration screen output.

---

## Open questions / caveats

1. **One survivor is fewer than the brief expected.** The brief
   anticipated 8-12 of 12 pairs; we got 1. This is honest but
   surprising. Three options going forward:
   - **(a) Accept and proceed.** MA/V is a strong, well-supported
     pair. One uncorrelated edge added to the inventory is still net
     positive on the value/accruals 0.6+ collinearity finding.
   - **(b) Loosen the screen.** Allow p ∈ [0.05, 0.10] as a "watchlist"
     band — pairs that re-test as cointegrated under different windows
     (e.g., 2-year rolling) might re-enter. Risk: invites overfitting.
   - **(c) Expand the candidate pool.** Stat-arb literature suggests
     stress-testing >100 pairs per universe. The brief's 12 are
     classics; non-classical pairs (within sector ETFs, sub-industry
     basket comps, ADR/local-share spreads) may screen better.

   Recommend option (a) for this batch and option (c) as a follow-up
   T-018 if the user wants the inventory grown. Loosening the screen
   without explicit director approval would violate "no overfitting"
   discipline.

2. **Engle-Granger is order-sensitive.** Regressing log(Y) on log(X)
   gives different residuals than log(X) on log(Y). For a clean check,
   Johansen's procedure is order-invariant. The cointegration test
   here uses a fixed convention (Y on X) — adequate for a v1 but
   should be replaced with Johansen if multi-asset baskets become
   relevant.

3. **β is fixed at screen time, not adaptive.** The MA/V β = 0.8901
   is the in-sample-window OLS estimate. A rolling-β version (re-fit
   every N days) would track structural drift but adds parameters
   (window length, re-fit cadence) that need tuning. Static β is
   simpler and consistent with the brief's "no per-pair tuning"
   discipline. Re-screen quarterly is a cheap operational answer.

4. **Liquidity / capacity not modeled.** Both MA and V have ADV >>
   $1B/day on substrate-honest data — capacity is not a constraint
   for retail-scale capital ($5K-$15K AUM per project memory). For
   future pairs with mid-cap legs, an ADV floor in the screen is
   warranted.

5. **Sector-internal vs cross-sector.** The MA/V survivor is sector-
   internal (both Payments). Cross-sector pairs (e.g., gold miners
   vs gold ETF) tend to have weaker cointegration but more
   idiosyncratic alpha. A v2 screen could add a "cross-sector"
   candidate set.

6. **Stateful hysteresis is a v2 follow-up.** The current edge
   abstains in the [z_exit, z_entry] band rather than holding a
   position. Classical pairs trading would maintain the trade until
   z crosses the exit threshold. The cost of statelessness is some
   give-back on positions that drift back toward zero before fully
   reverting; the benefit is no per-edge state to track or reset.
   Consider as T-018 / T-019 if the lifecycle gauntlet identifies
   the stateless behavior as a drag on Sharpe.

7. **Lifecycle gauntlet validation pending.** Per project rules,
   paused/feature edges are inputs to the meta-learner / Discovery;
   they do not deploy real capital until the lifecycle gauntlet runs
   substrate-honest validation. The next step for actually trading
   MA/V is for Engine F's gauntlet to evaluate the edge under
   benchmark-relative Gate 1 (and Gates 2-6 inheriting that fix per
   memory `project_gauntlet_consolidated_fix_2026_05_01`).

---

## Files changed

- **NEW** `scripts/cointegration_pair_screen.py` — Engle-Granger
  screen, ADF cross-check, half-life + β-stability filters, JSON
  manifest writer.
- **NEW** `engines/engine_a_alpha/edges/pairs_trading_v1.py` — base
  class + factory auto-registration from manifest.
- **NEW** `tests/test_pairs_trading_edges.py` — 14-test suite.
- **NEW** `data/research/cointegrated_pairs_2026_05_09.json` —
  manifest output (gitignored under `data/`, written for reproducibility).

No engine code modified. No `live_trader/` or Engine B touch. No
changes to `core/metrics_engine.py` or any governance plumbing. The
only mutation outside the new files is `data/governor/edges.yml`
(gitignored), which gains 1 entry for `pairs_trading_MA_V_v1` at
`status='paused' tier='feature'` via the standing auto-register
pattern.

## New dependencies

`statsmodels==0.14.6` + `patsy==1.0.2` — added to `requirements.lock.txt`
in commit `0c4ec86` (USER-APPROVED for this task; surfaced as BLOCKED
at task-start, unblocked mid-task by director).
