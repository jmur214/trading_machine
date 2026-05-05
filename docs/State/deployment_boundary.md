# Deployment Boundary — Path 1 ship state (2026-05)

**Date:** 2026-04-30 (filed under 2026-05 because that's the deployment month)
**Phase:** 2.10d shipped + 2.11 (portfolio meta-learner) shipped within
the boundary defined here.
**Branch of record:** `path1-deployment-ship` (see also `cap-bracket-below-020`,
`metalearner-robustness`, `universe-b-diagnosis`).

This document is load-bearing. Anyone who proposes deploying this
system to non-prod-109 universes, to live capital, or to additional
edges without re-validation must read it first and explicitly justify
each boundary crossed.

---

## What's deployable today

**Configuration (CAP-ONLY path, validated):**
- `metalearner.enabled: false` — the ML stacking is **NOT validated
  on this worktree** (see `path1_ship_validation_2026_05.md` —
  cap=0.20 + ML-on produced Sharpe -0.378 in this worktree, vs Agent C's
  1.064 in their worktree; the divergence has not been diagnosed). Until
  reproducibility is established, the ML half of Path 1 stays off.
- `fill_share_cap: 0.20` — validated at Sharpe 1.102 (2025 OOS, agentA
  bracket round 2) and 1.113 (2021-2024 in-sample, multi-year robustness).
- `RealisticSlippageModel` (default in `config/backtest_settings.json`)
- All Phase 2.10d primitives active (per-bar fill-share ceiling, soft-pause
  weight clamp, regime-summary slot reduction)

**Configuration (FULL path, ML stacking — pending reproduction):**
The director's intended ship state was `metalearner.enabled: true` +
`fill_share_cap: 0.20` simultaneously. That state is provisionally
present in this branch's `config/alpha_settings.prod.json` BUT the
ship-validation run (this worktree, A3) produced Sharpe **-0.378**,
not the expected 1.1+. Merging that config blindly would deploy a
state that does not reproduce its own audit. See `path1_ship_validation_2026_05.md`
recommendations Path A / Path B / Path C for next steps.

**Universe:** **prod-109 only** — the 109-ticker list in
`config/backtest_settings.json` (mostly mega-cap S&P 100 + select mid-cap S&P 500).
The universe is enumerated at the end of this document. Any ticker
not in this list is **out of scope**.

**Window of validation:**
- 2021-01-01 → 2024-12-31 in-sample Sharpe **1.113** under cap=0.20
  (run `0e26bf97-44e3-45d0-be1d-7d4bdf23fbf6`, but with ML-OFF —
  see `cap_bracket_sweep_2026_04.md`).
- 2025-01-01 → 2025-12-31 OOS Sharpe under cap=0.20 + ML-ON
  in this worktree: **-0.378** (run
  `bf9488a6-e682-4a49-8ff2-38917d178c8a`,
  `path1_ship_validation_2026_05.md`). **This is a ship blocker** —
  the result does not reproduce Agent C's 1.064 anchor on this
  worktree's governor state. The cap-only path (cap=0.20, ML-OFF)
  still validates at Sharpe 1.102 (B3 v2 in agentA's prior round)
  / 0.920 (A3 in trading_machine-2). The ML-on path is **not yet
  validated for shipping**.

**Mode:** Backtesting only. **No paper trading. No live capital. No
broker integration.** Phase 3 deployment infra (kill switches, OMS
safety, position reconciliation, order audit) has not been built.

---

## What's NOT deployable today

1. **Any non-prod-109 universe.** Universe-B (50 held-out tickers,
   seed=42) under the same config produces Sharpe **0.273** —
   `metalearner_robustness_2026_04.md` C1 finding. The ML lift is
   ~0.05 Sharpe on Universe-B vs ~0.75 Sharpe on prod-109; the lift
   does not generalize.
2. **Live trading.** Engine B's risk paths haven't been exercised
   under real-money conditions. `live_trader/` is not part of this
   ship state. Any move to live capital requires Phase 3.
3. **Paper trading.** Paper trading exposes the system to broker
   integration, market data feeds, intraday timing — none of which
   have been validated under the current edge stack. Same Phase 3
   prerequisite.
4. **Edge additions to the active stack.** Any edge promoted to
   `status: active` must clear the realistic-cost gauntlet under
   Engine D's discovery validation pipeline before it can ride on
   this configuration. See `gauntlet_revalidation_2026_04.md` for
   the ensemble-context caveats on standalone gauntlet results.
5. **Portfolio profile change** (`balanced` → `growth` /
   `retiree` etc.). The per-edge weights and the meta-learner
   training were calibrated under `balanced`. Switching profile
   requires re-training the meta-learner and re-validating against
   this boundary.

---

## Why the boundary exists

The boundary is **mechanical, not cultural**. Three pieces of evidence
together:

### Evidence 1 — Universe-B Sharpe collapse
Same config (cap=0.20 + ML-on + all Phase 2.10d primitives), same
window, only the universe changes. prod-109 Sharpe ≈ 1.064 → Universe-B
Sharpe **0.273** (Agent C C1, `metalearner_robustness_2026_04.md`).
The lift evaporates outside the design universe.

### Evidence 2 — ADV liquidity gap
Universe-B has 6× lower median ADV ($118M/day vs prod $763M/day) and
**0% of names ≥ $1B/day** vs prod's **31.2%**
(Agent D `universe_b_diagnosis_2026_04.md`). The realistic-cost model's
Almgren-Chriss `√(qty/ADV)` impact term scales unfavorably on
lower-ADV names.

### Evidence 3 — Per-edge ADV-fragility
`atr_breakout_v1`'s per-fill loss multiplied **76×** on Universe-B
(-$0.70 → -$53 per fill) — same edge logic, same risk sizing, but
the edge had no awareness of the ADV regime it was firing into.
`volume_anomaly_v1` and `herding_v1` (the stable contributors on
prod-109) saw their fill counts collapse 89% on Universe-B because
order-flow-density signals don't reach threshold on smaller names.

**Synthesis:** the active edge stack carries implicit ADV preconditions
that aren't expressed in code. The deployment universe must match
those preconditions. Until Path 2 (Agent D's per-edge ADV floors)
ships, the only universe that meets the implicit preconditions is
prod-109.

---

## Conditions to lift the boundary

The boundary lifts when **both** of the following are true:

1. **Path 2 ships.** Per-edge ADV floors (or equivalent
   liquidity-gating mechanism) land in the active edge stack and
   pass the realistic-cost gauntlet. Tracked on Agent D's branch
   `path2-adv-floors-edges`.
2. **Universe-B re-test ≥ 0.5 Sharpe.** Re-run the standard Universe-B
   validation (`scripts/run_oos_validation.py --task q2`) under the
   ADV-floor-equipped stack. Result must be ≥ 0.5 Sharpe to count as
   "universe-portable." If 0.4 ≤ Sharpe < 0.5, partial-pass with a
   narrower allowed universe to be specified by the next reviewer.
   < 0.4 means Path 2 didn't fix the structural issue; the boundary
   stays.

A separate "live-money gate" exists *on top* of the universe gate:
even with the universe boundary lifted, no live capital deploys
until Phase 3 ships. The two gates are independent and must both
pass.

---

## Non-goals of this document

- This is **not** a trade-execution playbook. It documents what's
  validated to backtest cleanly under realistic costs. Live execution
  has separate concerns (latency, slippage variance, broker quirks)
  not covered here.
- This is **not** a long-term strategic plan. It's the snapshot of
  what shipped on 2026-04-30. The forward plan
  (`docs/Archive/forward_plans/forward_plan_2026_04_30.md`) is the right place to look
  for what comes next (Phase 3 paper trading, Path 2 universe
  portability, Phase 2.5 moonshot sleeve).

---

## Reference: prod-109 universe

Defined in `config/backtest_settings.json::tickers`. As of this
document, the universe is:

```
AAPL ABBV ABNB ABT ACN ADBE ADI ADP AMAT AMGN AMT AMZN AVGO AXP BA
BAC BDX BKNG BLK BSX C CAT CI CMCSA COIN COP COST CRM CSCO CVS CVX
DE DHR DIS DKNG ELV EOG ETN GE GILD GOOGL GS HD HON IBM INTC INTU
ISRG JNJ JPM KO LIN LLY LMT LOW LRCX MA MARA MCD MDLZ MDT META MO
MRK MS MSFT MU NEE NFLX NKE NOW NVDA ORCL PANW PEP PFE PG PGR PLD
PLTR PM QCOM QQQ REGN RIOT RTX SCHW SLB SNOW SO SPGI SPY SYK TJX
TMO TMUS TSLA TXN UBER UNH UNP UPS V VRTX VZ WFC WMT XOM ZTS
```

(109 entries; SPY/QQQ in the universe are tradable but also serve as
benchmark proxies elsewhere. Composition can drift via lifecycle —
see `data/governor/edges.yml` for what's currently active.)

---

## How to re-derive this state

```bash
# 1. Run validation backtest on current config (2025 OOS)
PYTHONHASHSEED=0 python -m scripts.run_oos_validation --task q1
# Outputs at data/research/oos_validation_q1.json + data/trade_logs/<UUID>/.

# 2. Run multi-year robustness (2021-2024 in-sample)
PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run is_optimum
# Outputs at data/research/cap_recalibration_is_optimum.json.

# 3. Re-validate Universe-B baseline (should still FAIL until Path 2)
PYTHONHASHSEED=0 python -m scripts.run_oos_validation --task q2
# Sharpe should land in the 0.27-0.5 range (current ML-on).
```
