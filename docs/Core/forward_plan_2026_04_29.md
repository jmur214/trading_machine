# Forward Plan — 2026-04-29

> **STATUS UPDATE 2026-04-29 (same day, evening):** Phase 2.10b
> dispatched and **failed all three questions** by wide margins.
> See "Result" section at the end of this doc. The downstream phases
> below (2.11 / 2.12 / 2.5) are now BLOCKED. New BLOCKING phase
> **2.10c — Falsification triage** added to ROADMAP. **The "what to
> work on next" instructions in this doc no longer apply** — read
> `docs/Core/forward_plan_2026_04_29b.md` (created when Phase 2.10c
> completes) or current ROADMAP Phase 2.10c section for live
> sequencing. The plan body below is preserved as historical context
> for what the project intended *before* the OOS gate falsified the
> in-sample headline.

Synthesis of `docs/Progress_Summaries/Other-dev-opinion/04-29-26_a-and-i.md`
(outside reviewer's take following the Phase 1 push) plus the user's
explicit goals: A) compound, B) significantly + consistently beat the
market, C) **catch some moonshots** (the architectural gap).

This plan supersedes `forward_plan_2026_04_28.md`'s next-step ordering.
The phasing structure (Phase 0/1/2/3/4) from that doc still holds — what
changes is **what gates the next move** and **what runs in parallel.**

---

## What just shipped (and what it means)

Reviewer's headline: "**Phase 0 and most of Phase 1 from the prior plan
have been substantively executed in a single sprint.**" Specifically:

- Realistic cost model wired end-to-end (commit `9546937`)
- Multi-benchmark gate, strongest-of-three default (`8e1d683`)
- Factor decomposition baseline + Gate 6 in gauntlet (`771a5d0`, `b918e08`)
- Three-layer architecture: existence / tier / allocation
  (`55d1ec6`, `b9940e7`)
- Autonomous TierClassifier — factor-decomp t-stats drive
  reclassification, AST-test prevents profile pollution
- MetaLearner integrated into SignalProcessor (default OFF until
  per-ticker training proves out)
- Multi-metric fitness profiles: retiree / balanced / growth
  (`config/fitness_profiles.yml`)

**Headline number:** in-sample Sharpe **1.063** under realistic costs vs
SPY 0.875, half the volatility (5.7% vs 16.5%), half the drawdown
(-10% vs -24.5%). That's a real jump from the prior "Sharpe 0.4 on
universe-B vs SPY 0.88" baseline.

**Reviewer's updated assessment:** infrastructure went from ~50–55% of
the institutional bar to ~70%. Real progress.

---

## What's load-bearing now (the OOS gate)

The 1.063 number is **in-sample**. Legacy in-sample → OOS shrinkage on
this codebase has historically been ~50–60%. If the new cost model
preserves the same shrinkage curve, OOS Sharpe lands at ~0.5 — still
good, but **not** the headline number.

**Until the OOS run completes, the 1.063 is a hypothesis, not a result.**
Everything below is gated on three empirical questions answering cleanly:

| # | Question | Pass criterion | If it fails |
|---|----------|----------------|-------------|
| 1 | What's the 2025 OOS Sharpe under the new cost model? | OOS Sharpe > 0.5 | Recent gains were partly in-sample artifact; priority shifts back to gauntlet rigor |
| 2 | What's Universe-B (held-out tickers) Sharpe under new costs? | Universe-B doesn't collapse below in-sample by more than ~30% | Cost-model fix only made the favorable universe look better; underlying universe-heterogeneity problem isn't actually fixed |
| 3 | Do `volume_anomaly_v1` + `herding_v1` (the factor-decomp-identified real alphas) still pass all 6 gates under realistic costs? | Both pass Gates 1-6 with intercept t > 2 | The "real alpha" claim was a factor-cost confound, not signal |

**These three results are the next session's first work item, before
anything else.** Don't add features, don't enable the meta-learner, don't
ship anything new until they're in.

---

## The user's three goals — current scorecard

The reviewer assessed the system against the user's stated goals:

| Goal | Status | What this means |
|------|--------|-----------------|
| A. Compound over time | ✓ on track, **but not optimized for a 20-something** | 6% CAGR for 40 years → $1M from $100k. 12% CAGR → $9.3M. The current defensive profile leaves serious compounding on the table for someone with a 40-year horizon. |
| B. Significantly + consistently beat the market | ⚠ on track for *consistently*, NOT for *significantly* | Beats SPY by +0.19 Sharpe (risk-adjusted) but with **lower absolute CAGR (6% vs 14%)**. That's underperforming SPY in dollars while being smoother — most retail investors would (rightly) reject that. |
| C. Asymmetric upside (the moonshots — RKLB, NVDA, BTC type wins) | ✗ **not even attempted** | The current architecture *specifically avoids* moonshot strategies. Sharpe optimization punishes high-vol positions. 109-name diversification dilutes any single 10x to noise. The lifecycle/gauntlet is built around statistical rigor, not narrative-driven theme conviction. **A system designed to maximize Sharpe will never own enough RKLB to matter** — that's the consequence of the optimization target. |

Goal C is **a real architectural gap**, not a tuning problem. Solving it
requires a parallel sleeve with its own mandate. See Phase 2.5 below.

---

## Phase 2.10b — OOS Validation Gate (immediate, ~1 week)

**This phase blocks every later phase.** Until it completes, treat the
1.063 number as provisional.

- [ ] **Run 2025 OOS backtest under realistic-cost model.** Use the
      same edge stack and config as the in-sample 1.063 run; just
      shift the window. Output Sharpe, CAGR, MDD, vol vs SPY +
      QQQ + 60/40 over 2025.
- [ ] **Run Universe-B (held-out tickers) backtest under realistic
      costs.** `engine_d_discovery.discovery._load_universe_b()`
      already samples non-production tickers; reuse that. Same
      window as in-sample so the comparison is clean.
- [ ] **Re-validate `volume_anomaly_v1` and `herding_v1`** through all
      6 gates under realistic costs. The factor-decomp said these
      are the only true alphas (intercept t > 4.3 each). The
      gauntlet has to confirm under honest costs or the
      "two real alphas" claim was a cost-model artifact.
- [ ] **Document results** in
      `docs/Audit/oos_validation_2026_04.md` with explicit
      pass/fail flags vs the three gate criteria above.

**Phase 2.10b gate:** all three results published, pass/fail flags
stamped. Pass → unblock Phase 2.11+. Fail → revert to gauntlet-rigor
mode, no new features.

---

## Phase 2.11 — Per-ticker meta-learner (Session N+1 proper)

Conditional on Phase 2.10b passing.

The Phase 1 N+1 portfolio-level meta-learner showed +0.056 OOS
correlation — barely above coin flip. The reviewer agrees with the
project's own diagnosis: **per-ticker training is the real lift.**

- [ ] **Log per-bar per-ticker edge scores during backtest.**
      `alpha_engine.AlphaEngine.run_alpha_logic()` already computes
      these; route them into a parquet that the trainer can consume.
- [ ] **`scripts/train_metalearner.py` per-ticker mode.** Walk-forward
      rolling folds, target = profile-aware fitness, one model per
      ticker (or per ticker-cluster if data is too sparse).
- [ ] **A/B comparison.** Same backtest under each of the three
      profiles (retiree / balanced / growth) with
      `metalearner.enabled: true`. Confirm: retiree-profile model
      produces lowest-vol output, growth-profile model produces
      highest-CAGR output, all from the same edge pool.
- [ ] **Phase 1 gate crossing.** "Meta-learner-active backtest
      strictly better fitness than disabled" on OOS data. Until
      then, `metalearner.enabled: false` stays in production config.

---

## Phase 2.12 — Universe configured for growth (1 week of config + edges)

Conditional on Phase 2.10b passing. The user's goal-A-and-B framing
explicitly favors **growth profile** over retiree/balanced for a
20-something with a 40-year horizon. The architecture already supports
this — the reviewer notes "the growth knob exists in code." Most of
this is configuration moves with one small-code addition.

### Configuration moves (no new code)

- [ ] **Switch active fitness profile to `growth`.** Single change in
      `config/fitness_profiles.yml`'s active flag. Allocation
      re-weights toward CAGR-dominant edges immediately.
- [ ] **Concentrated universe.** Cap to top 30–50 names by momentum +
      liquidity rather than the full 109. **Concentration is itself
      growth-profile alpha** — breadth is hurting on the broad
      universe per the active HIGH finding in `health_check.md`.
- [ ] **Loosen position sizing in `engines/engine_b_risk/risk_engine.py`.**
      `risk_per_trade_pct` 0.025 → 0.05; sector cap 20% → 30%;
      single-name cap 5% → 8%. **Touches Engine B — propose to user
      first per CLAUDE.md.**
- [ ] **Allow modest gross leverage (1.1–1.3x)** when meta-learner
      confidence is high. Alpaca supports 2x Reg-T overnight, 4x
      intraday. Not all of it, but not leaving 30%+ on the table.
      **Touches Engine B — propose first.**

### Small-code edge additions (Phase 2 picks specifically for growth)

These are net-new edges through the existing gauntlet — no
architectural change needed, just more edges that lean growth.

- [ ] **Cross-sectional 12-1 momentum** (Asness/Moskowitz). Long top
      decile by 12-1 month return on the 109-ticker universe.
      ~0.5–0.7 Sharpe in academic literature, growth-flavored,
      complements PEAD. **Note**: `momentum_factor_v1` was tried
      vanilla and falsified on OOS (memory:
      `project_factor_edge_first_alpha_2026_04_24.md`); the v2
      should add **sector neutralization** to address the
      concentrated-mega-cap issue.
- [ ] **Earnings revision momentum.** Long stocks with rising EPS
      estimate consensus over 3 months. Strongest in growth
      regimes.
- [ ] **52-week breakout with volume confirmation** (CAN SLIM /
      O'Neil). Most 10-baggers break out from multi-year bases.
- [ ] **Quality + Momentum composite (QMJ).** AQR's research-confirmed
      composite — long top decile of (momentum × quality), short
      bottom. Stronger Sharpe than either factor alone.
- [ ] **Sector momentum rotation.** Long top 3 sectors by 6-month
      return. Rebalance monthly. Captures regime concentration
      cheaply. Different signal frequency from the rest of the
      stack — monthly rebalancing, ~3 positions, but more aligned
      with how SPY actually generates returns.

### The honest tradeoff

Switching to growth profile + adding these edges will likely:
- **Push Sharpe lower** (1.063 → 0.7–0.9)
- **Push MDD higher** (-10% → -20% to -30%)
- **Push CAGR higher** (6% → 12–18%)

That's the trade. Higher growth is *not* higher Sharpe. They can move
opposite. **The honest benchmark for high-growth is leveraged passive
(70/30 QQQ/TQQQ rebalanced quarterly), not SPY.** Don't deploy active
capital until the system clears that bar over 12+ months.

---

## Phase 2.5 — Moonshot Sleeve (NEW, parallel to Phase 2.11/2.12)

This is the architectural gap for goal C. **Solving "catch the next
RKLB" is not a parameter tweak — it's a different engine with a
different mandate.** The current core sleeve cannot do this and should
not be forced to.

The strategy is the **venture-capital model applied to public equities**:
- Hold a portfolio of moonshot candidates (30–50 names)
- Each sized to lose at most 1–2% of the sleeve if it goes to zero
- Stop-loss anchored at -50%, upside uncapped, trailing stops not fixed
- Hit rate ~10–30% — most go nowhere; 1–2 of 50 turning into RKLB pays
  for the rest
- Asymmetric math at portfolio level only

### Allocation (suggested for a 20-something high-risk-tolerance)

```
Core compounding sleeve:    70-75% of capital  (current system, growth profile)
Moonshot sleeve:            15-20% of capital  (new — to be built)
Cash / opportunistic:        5-10% of capital  (discretionary, BTC-at-$500 situations)
```

### Different universe

- **Russell 2000 + recent IPOs (last 5 years) + theme-tagged equities**
  (AI, space, biotech, crypto-equity, EV, semis)
- 200–400 names, refreshed quarterly
- **Explicitly NOT the S&P 100/500 names the core trades**
- Requires expanding the universe data layer; Engine D's gauntlet
  already accepts arbitrary universes.

### Different signals (the actual moonshot edges — 5–7 to ship)

1. **Long-term momentum (12-month + 24-month) on small/mid-caps.**
   Asness's research: stronger in small-caps than large.
2. **52-week breakout with volume confirmation** on small-caps.
   William O'Neil CAN SLIM — most 10-baggers break out from multi-year
   bases.
3. **Earnings beat + raised guidance.** Beats AND raises = persistent
   6–12 month signal. ~0.7 Sharpe in academic literature.
4. **Insider cluster buying in small-caps.** `insider_cluster_v1`
   already exists for large-caps; same edge in small-caps is
   dramatically stronger.
5. **Sentiment velocity.** *Rate of change* of mentions on
   Reddit/StockTwits, not absolute level. Captures attention before
   it's priced in.
6. **High short interest + improving fundamentals.** Squeeze setups.
   RKLB had 15%+ SI in 2023 before its 2024 run.
7. **Theme detection.** Cluster small-caps by 10-K language; identify
   which themes are gaining (and pivot the universe quarterly).
   *(This is the LLM-as-analyst foothold — see Phase 6 below.)*

### Different sizing engine

The core sleeve's `risk_engine.py` does Kelly-fraction-style sizing
calibrated for Sharpe optimization. Moonshot sizing is **asymmetric**:

- Each bet sized to lose at most 1–2% of the sleeve at stop-out
- 30–50 simultaneous positions (many small bets, not concentration)
- Trailing stops, not fixed exits — let winners run for years
- **The math works only at portfolio level**: hit rate × avg win >
  miss rate × avg loss

### Different gauntlet criteria

The standard 6-gate validation is built around Sharpe + factor t-stat.
Moonshot edges optimize for different metrics:

- **Skewness** > 0.5 (positive-skew strategy)
- **Upside capture > 1.2× downside capture** (asymmetric exposure)
- **Hit rate ≤ 30% acceptable** (most bets miss, that's the strategy)
- **Sortino + skewness** as primary fitness target, NOT Sharpe

The existing fitness-profile architecture supports this — adding a
fourth profile (`moonshot`) to `config/fitness_profiles.yml` with
different metric weights. Lifecycle (Layer 1) gates remain objective:
even moonshot edges retire if their factor t-stat goes negative on
their own benchmark.

### What the sleeve CAN and CANNOT do (reviewer's brutal-honesty list)

**Can do:**
- Statistically catch *some* moonshots through systematic signals
- Hold a portfolio diverse enough that 1–2 of 30 names being a 10x
  carries the sleeve
- Outperform the core in bull regimes (small/mid caps lead in
  expansions)
- Capture themes 6–12 months after they become visible to retail
  attention

**Cannot do:**
- **Replicate the user's specific calls (RKLB, NVDA, BTC-at-$500).**
  Those required *thematic conviction* the user brought to the trade.
  The system can have you in 50 small-cap growth names where 2
  happen to be RKLB-class — that's the model.
- **Catch BTC at $500.** Required identifying a category before it
  was public-equity tradable. The system can only trade what's
  listed.
- **Pick "the one."** You'll own 30 names; one will be a winner; the
  others will mostly be losers. The strategy is positive-EV at
  portfolio level only.
- **Beat survivorship bias.** For every NVDA there are 100 SHLDs.

### Hit-rate reality

True 10x moves: ~1–3% of small-cap names per 5-year window. Sleeve
holds 50 names rotating quarterly → ~200 names/year exposure →
**expected 2–6 10x winners per year.** Sized at 2% each: even one 10x
adds 20% to the sleeve. Two 10x'es double it.

### Phase 2.5 deliverables

- [ ] **Universe data layer expansion** — Russell 2000 + IPO last-5y +
      theme-tagged. ~1 week.
- [ ] **`config/fitness_profiles.yml` adds `moonshot` profile** —
      Sortino + skewness + upside capture weights.
- [ ] **Asymmetric sizing engine** as a parallel module to
      `engine_b_risk/risk_engine.py` — does NOT replace the existing
      one; runs alongside on the moonshot sleeve only. **Touches
      Engine B — design + propose to user before code.**
- [ ] **5–7 moonshot edges** ship through the existing gauntlet with
      moonshot-profile criteria.
- [ ] **Trailing-stop infrastructure** at the position level (already
      exists for the core; extend to allow per-sleeve override).
- [ ] **Two-sleeve portfolio engine** — Engine C aggregates positions
      from both sleeves, applies portfolio-level risk caps, but does
      NOT cross-net them. **Touches Engine C — propose first.**

**Phase 2.5 gate:** moonshot sleeve passes its own walk-forward over
2018–2024 with skewness > 0.5, hit rate 15–30%, and sleeve-level CAGR
> Russell 2000 over the same window.

---

## Phase 3, 4, 5, 6 — unchanged in spirit, re-prioritized

Per reviewer: the planned sequence still applies, but Phase 6 (LLM)
**becomes higher priority for the moonshot sleeve specifically:**

> "For finding the next RKLB/NVDA, LLM-as-analyst isn't a Phase 6
> nice-to-have — it's a core capability. The signal is in the
> unstructured data (filings, calls, news), not in OHLCV."

Concretely: **earnings call sentiment, news firehose theme detection,
patent + contract analysis, cross-referencing AI-related job postings
with insider buying.** These are the signals that catch
narrative-driven names before their breakout.

**Sequencing still:**
1. **Phase 2.10b OOS validation** (gates everything below)
2. **Phase 2.11 per-ticker meta-learner + Phase 2.12 growth config**
   (core sleeve mature)
3. **Phase 2.5 Moonshot Sleeve** (parallel build — start design *now*,
   deploy after Phase 3 deployment infra is real)
4. **Phase 3 deployment infra** — kill switches, OMS, real
   reconciliation. Higher risk profile means *more* critical kill
   switches, not fewer. **Required before any real-money deployment
   of either sleeve.**
5. **Phase 4 intraday** — minute bars, intraday momentum, gap fade,
   MOC imbalance. The *real* short-term edge sleeve. Moonshot
   sleeve is months-to-years horizon; this is sub-daily. Both can
   coexist.
6. **Phase 6 LLM** — for the moonshot sleeve first. Earnings calls,
   theme detection, filings cross-ref. Brings goal-C asymmetry up
   significantly.

---

## Cross-cutting concerns (still active)

The reviewer surfaced four things still missing from the cost / risk
model:

1. **Borrow cost for shorts** — could shave 0.1–0.2 Sharpe if the
   system runs any meaningful short exposure. **Add to
   `RealisticSlippageModel`.**
2. **Short-term cap gains tax** — 30%+ haircut for active strategies.
   **Tax-aware backtesting** matters once after-tax returns are the
   benchmark.
3. **Alpaca fee tiers** — currently a flat assumption. Real tiers vary
   by volume.
4. **Tail-hedge thesis untested** — the in-sample window (2021–2024)
   has no 2008/2020-class crash. Stress simulation against synthetic
   tail events is a Phase 3 prerequisite.

These don't gate Phase 2.10b but should be in flight during Phase 2.11
/ 2.12.

---

## Single-paragraph TL;DR

**Phase 2.10b first, no exceptions** — OOS validation of the realistic-cost
backtest is the single most important pending data point. Then in
parallel: per-ticker meta-learner + growth-profile config for the core
sleeve, and **start designing the Moonshot Sleeve as a separate engine
with its own mandate** because the user's goal C (asymmetric
moonshots) is a real architectural gap that no amount of core-sleeve
tuning will close. **For someone in their 20s with a 40-year horizon,
running both sleeves is the right shape — the core makes you wealthy
steadily, the moonshot sleeve makes you wealthy fast if it works.
Don't pick.**

---

## Result — Phase 2.10b ran same day, all three questions FAILED

**Q1: 2025 OOS Sharpe under realistic costs.** **-0.049** vs criterion
> 0.5. SPY 2025 was 0.955; the system trailed every benchmark by
**>1.0 Sharpe** in a strong bull year. Run UUID
`72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34`.

**Q2: Universe-B Sharpe (held-out tickers, in-sample window).**
**0.225** vs criterion not below 0.74 (1.063 × 0.7) — a **79% Sharpe
collapse**. Vol nearly doubled (5.7% → 9.95%), MDD nearly doubled
(-10.07% → -18.17%). Run UUID
`ee21c681-f8de-4cdb-9adb-a102b4063ca1`.

**Q3: `volume_anomaly_v1` + `herding_v1` through 6 gates.** Both
failed at Gate 1 (the cheapest filter): Sharpe **0.32** and **-0.26**
respectively, vs benchmark threshold ~0.68. **`herding_v1` standalone
is capital-destroying** under realistic costs. The factor-decomp
t-stats (+4.36, +4.49) were a **cost-model confound** — per-edge
backtest used hardcoded 5bps; integration backtest used realistic
Almgren-Chriss. The hardcode is in
`engine_d_discovery.discovery.validate_candidate` and was patched on
the `gauntlet-revalidation` branch (`exec_params` override) — this
patch is itself a real bug fix and should land on main even though
the edge-validation result is negative.

### Diagnosis

The 1.063 in-sample headline was a **double artifact**: favorable
universe (curated 109 mega/mid caps) AND favorable window (2021-2024
edge-regime alignment). Real OOS in 2025: -0.049. Real cross-universe:
0.225. The two "real alphas" weren't standalone alphas at all.

This matches the prior project memory
(`project_lifecycle_vindicated_universe_expansion_2026_04_25`):
*"system's true Sharpe on a wider universe is 0.4, vs SPY 0.88. The
39-ticker 0.98 baseline was a curated-mega-cap-tech artifact."* The
new realistic-cost model didn't fix that finding. It made the
in-sample number on the favorable universe look better, but neither
the OOS year nor the held-out universe carries that lift through.
Universe-B (0.225) and the older 0.4 baseline are in the same ZIP
code.

### Failure clauses activated

Per the "If it fails" clauses in this plan:
- "Recent gains were partly in-sample artifact; priority shifts back
  to gauntlet rigor" — **active.**
- "Cost-model fix only made the favorable universe look better;
  underlying universe-heterogeneity problem isn't actually fixed"
  — **active.**
- Phase 2.11 / 2.12 / 2.5 — **all blocked** until the diagnostic
  triage of Phase 2.10c determines whether any real alpha exists in
  the active edge stack.

### What didn't fail (worth noting)

The infrastructure built over the prior weeks performed exactly as
designed:
- Realistic-cost slippage model produced honest in-sample numbers
- Multi-benchmark gate caught the 2025 underperformance vs SPY/QQQ/60-40
- Universe-B sampling caught the curation artifact
- 6-gate gauntlet (and specifically Gate 1 benchmark-relative + Gate 6
  factor-decomp under realistic costs) caught the standalone-alpha claim
- Lifecycle pause/soft-pause produced the in-sample baseline that we
  could measure against

**Bones-before-paper philosophy validated.** The system told us the
truth. The next phase is using that truth to make the right
structural decisions, not retreat to feature work.

### Branches with the work

- `oos-validation` — Q1 + Q2 audit, new `scripts/run_oos_validation.py`
- `gauntlet-revalidation` — Q3 audit, new `scripts/revalidate_alphas.py`,
  `exec_params` override in `discovery.validate_candidate` (patches a
  hardcoded-5bps bug)

Both branches contain genuinely useful artifacts (audit docs + new
scripts + a real bug fix in discovery.py). Both should merge to main.
