# ArchonDEX — System State Briefing for External Review

> Briefing for a reviewer with codebase access but no prior project context. Honest current-state audit. **Live execution / OMS / deployment infrastructure is intentionally out of scope** — we know that gap and aren't focused on it right now.

---

## What this is

An autonomous algorithmic trading system aimed at retail capital ($10K-$100K AUM range), targeting risk-adjusted outperformance vs passive benchmarks (SPY / QQQ / 60-40), with a parallel mandate for asymmetric upside capture (a separate "Moonshot Sleeve"). Currently in paper-trading state — no live capital deployed, none planned in the near term.

Architecturally: a 6-engine system with formal authority boundaries between engines, a deterministic measurement harness, a multi-gate candidate validation gauntlet, and an autonomous lifecycle layer that promotes/pauses/retires edges.

The user is a 20-something with 40+ year horizon. Goals (in priority order):

- **Goal A**: compound steadily over time
- **Goal B**: significantly + consistently outperform the market
- **Goal C**: capture asymmetric upside (moonshot-style winners)

---

## Current architecture

### Six engines

| Engine | Role | Status |
|--------|------|--------|
| **A — Alpha** | Edge libraries + signal aggregation (signal_processor) | Active. Currently has 6 surviving edges + 3 falsified after recent audit. signal_processor pure-signals after F4 charter inversion was closed. |
| **B — Risk** | Position sizing, ATR stops, tax/wash-sale guards | Active. Still uses fixed-fraction sizing (`risk_per_trade_pct: 0.025`) — vol-targeting / correlation-aware sizing not yet implemented. ~955 LOC. |
| **C — Portfolio** | Portfolio composition (HRP, turnover penalty, tax-aware rebalancing) | Recently activated. HRP shipped but default OFF after slices 1-3 falsified at small edge count (HRP needs ≥20 edges to be useful; we have 6). Charter inversion closed (HRP/TurnoverPenalty moved here from Engine A). |
| **D — Discovery** | Candidate generation + 8-gate validation gauntlet | Active. Currently uses GA mutation; replacement with Bayesian opt + symbolic regression is planned. Gauntlet recently upgraded with Gate 7 (substrate-transfer) + Gate 8 (DSR). |
| **E — Regime** | Multi-resolution HMM regime classification + cross-asset confirmation | Default OFF. HMM was empirically falsified (AUC 0.49 on 20d-fwd drawdowns; coincident not predictive). 3 cross-asset features (HYG/LQD spread, DXY, VVIX-proxy) kept; the 2-of-3 confirmation gate archived (TPR=0% on -5% drawdowns over 1086 days). |
| **F — Governance** | Edge lifecycle (active/paused/retired), three-layer architecture (lifecycle / tier / allocation) | Active. Three-layer separation is AST-locked. Lifecycle write-back during runs is a known architectural smell (mutates `data/governor/edges.yml`); current mitigation is harness snapshot/restore. |

### Cross-cutting infrastructure

| Component | Status |
|-----------|--------|
| **Determinism harness** (`scripts/run_isolated.py`) | Active. Snapshots/restores 4 governor files + 6 module-level mutable globals across runs. 3-rep bitwise reproducibility verified. |
| **Realistic cost model** | Slippage (ADV-bucketed half-spread + Almgren-Chriss square-root impact) + Alpaca fees + borrow + short-term cap gains tax drag. **Tax drag alone moves Sharpe from 0.984 → -0.577**, which is the most important deployment-context finding to date. |
| **Multi-benchmark gate** | SPY + QQQ + 60/40-vol-matched. Strongest-of-three default. |
| **Factor decomposition** | Fama-French 5 + momentum + quality regression. Required Gate 6 (alpha intercept significance). |
| **Multi-metric reporting** | PSR + DSR + IR + Calmar + Sortino + skewness + kurtosis + tail ratio + Ulcer index — all wired into the multi-year measurement report. **PSR is the new headline metric**; raw Sharpe is secondary. |
| **Feature Foundry** | Generic ingestion plugin architecture; `@feature` decorator; auto-ablation runner; adversarial-twin generator (per-ticker lag-1 autocorrelation, 30% margin); 90-day archive enforcement; CI gate via pre-commit + GitHub Actions. **Currently 24 features** (16 from Engine A + 8 from external data sources). |
| **Decision diary** | JSONL append-only, auto-emit on backtest. 12 load-bearing decisions captured to date. |
| **Edge graveyard** | Structured `failure_reason` + `superseded_by` schema on EdgeSpec. 2 edges migrated. |
| **Information leakage detector** | Advisory (not enforcing). 0 false positives on 4 real Foundry features. |
| **Engine versioning** | Semver per engine; per-run snapshots in `engine_versions.json`. Every backtest result tagged with engine versions. |
| **Capital allocation diagnostic dashboard** | Built in `cockpit/dashboard_v2`. Shows per-edge fill share vs PnL contribution. Caught the 83%-of-fills-by-bottom-3-edges rivalry pattern that drove the Phase 2.10d structural fixes. |
| **Operational-pattern audit script** | F8 OOS lock + script that audits whether parameters were human-tuned vs autonomously discovered. |

---

## What's actually working (substrate-honest)

After recent substrate-bias verdict (universe was selection-biased toward modern mega-caps; original Foundation Gate of 1.296 mean Sharpe was 61% bias):

### Surviving-6 multi-year measurement (universe-aware, S&P 500 historical union)

| Year | Sharpe | CAGR | MDD | Regime |
|------|--------|------|-----|--------|
| 2021 | 2.811 | 13.34% | -2.35% | bull |
| 2022 | -0.508 | -4.29% | -9.11% | bear |
| 2023 | 1.799 | — | — | bull / Mag-7 |
| 2024 | 0.582 | — | — | Mag-7 dominance |
| 2025 | -0.107 | — | — | chop |
| **Mean** | **0.915** | — | — | **PARTIAL** |

**Real alpha at PARTIAL level. Strongly regime-conditional: bulls + Mag-7 work, bear/chop fail.**

### The 6 surviving edges

- `gap_fill_v1` (technical / mean-reversion)
- `volume_anomaly_v1` (statistical, factor-decomp t = +4.36)
- `value_earnings_yield_v1` (V/Q/A factor)
- `value_book_to_market_v1` (V/Q/A factor)
- `accruals_inv_sloan_v1` (V/Q/A factor)
- `accruals_inv_asset_growth_v1` (V/Q/A factor)

### What was falsified in the audit

- `quality_roic_v1` — falsified on substrate-honest measurement
- `quality_gross_profitability_v1` — falsified
- One contrarian edge — degraded (not falsified outright)

**Key insight from the audit:** the falsified quality edges were apparently providing a defensive hedge that the surviving set lacks. The strategy makes money in concentration regimes and loses in broad-rotation/bear regimes. **Defensive layer rebuild is the load-bearing next workstream.**

---

## Recent major findings (last 14 days)

1. **Foundation Gate verdict (F6): COLLAPSES.** Universe-aware Sharpe 1.296 → 0.507 = 61% bias. Mean technically clears 0.5 but per-year volatility (range 1.61) and missing 36 delisted CSVs (upper bound issue) push deeper into COLLAPSES band.
2. **Kill thesis TRIGGERED.** Pre-commit was 0.4. 0.507 with caveats was at-or-below threshold. Team called it triggered without goalpost-moving.
3. **Per-edge audit on universe-aware substrate** found 3 of 9 edges were the problem. Removing them lifts mean Sharpe to 0.915 (PARTIAL band).
4. **Six "exciting findings" have been falsified by the team's own validation harness over the past 6 weeks**: original 1.063 in-sample, MetaLearner 1.064 lift, wash-sale gate +0.670 lift, HRP slices 1/2/3, Foundation Gate 1.296. **Each was caught in paper, not P&L.**
5. **Tax drag is brutal.** Full ST cap gains (30%) takes Sharpe 0.984 → -0.577. Means deployment in taxable accounts requires either tax-aware operation mode or restriction to tax-advantaged accounts.

---

## What's currently planned (in `docs/State/forward_plan.md` and the team's queue)

### Highest priority (load-bearing for the surviving-6 weakness)

- **Defensive layer rebuild** — replacement for the falsified quality edges. Candidates: real tail hedge sleeve (long 30-delta SPY puts rolled monthly), regime-conditional reduce, low-vol overlay, or some combination. **The single most important addition to fix the bear/chop regime gap.**
- **3-rep determinism verification** of the 0.915 surviving-6 result (currently 1 rep)
- **PSR + DSR computation** on surviving-6 (statistical-significance-with-sample-size correction; currently raw Sharpe only)
- **Add 36 missing delisted CSVs** (tightens upper bound on 0.915)
- **2010-2020 backtest extension** (regime hypothesis test across more history)

### Medium-term workstreams

- **Calendar anomaly battery** — FOMC drift, turn-of-month, pre-holiday, day-of-week, sell-in-May (single ~200-line file)
- **Pairs trading / statistical arbitrage** — 10-15 cointegrated pairs (KO/PEP, MA/V, MCD/QSR, etc.)
- **CFTC COT-derived flow features** — data already integrated; need feature derivation for CTA positioning, commercial net long, etc.
- **Vol-targeting + correlation-aware sizing** — replaces fixed-fraction in Engine B
- **Auto-feature engineering via tsfresh** — could 10x feature count automatically; adversarial filter prunes
- **Bayesian optimization replacing GA** in Engine D
- **Symbolic regression layer** (PySR)
- **Causal discovery** (PC algorithm or NOTEARS)
- **Self-supervised time-series representations** (TS2Vec)
- **Schwab API integration** — free OPRA options data + IV term + put-call ratio + scanners (user has individual developer access; substrate-independent integration; unblocks tail hedge sleeve and several regime-rebuild paths)

### Goal C (Moonshot Sleeve) — independent parallel build

- Russell 2000 + IPO + theme-tagged universe
- Asymmetric edges: long-momentum on small/mid caps, 52-week breakout, earnings beat+raise, insider clusters in small-caps, short-squeeze setups, FDA approval drift, federal contract wins
- Asymmetric sizing (many small bets, 1-2% each, trailing stops 50% from peak)
- Different gauntlet criteria (Sortino + skewness + upside capture, NOT Sharpe)
- 15-20% allocation of total system capital
- Long-dated calls (LEAPS) as alternative asymmetric vehicles

### Tax-aware operation mode (deferred)

- Regime-conditional wash-sale gate (active in chop/elevated-vol only)
- Long-term-hold preference in optimizer
- Tax-loss harvesting integration
- **Deferred until substrate baseline is settled and Schwab integration provides options data**

---

## What's intentionally out of scope right now

- **Live execution / OMS / `live_trader`** — currently a 64-line stub; intentionally not being built. Real-money deployment is gated 12-18 months out behind paper-trading + 90-day shadow-live track record. **Don't recommend OMS work or deployment infrastructure.**
- **Real money operations** — same as above
- **Multi-asset class trading** — equity-only currently; multi-asset scaffolding would be a future option but not active

---

## What we know we're missing (categorized) — areas where reviewer input is most valuable

We've identified some categories ourselves but want fresh input. Areas where we're underconfident or want sharper thinking:

### Hedging / offsetting / defensive layer

The single biggest known gap. Surviving-6 is regime-conditional; bear/chop regimes lose money. We need defensive contribution. Candidates we've considered: tail hedge sleeve (long puts), vol-targeting, dynamic hedge asset auto-discovery, drawdown-conditional reduction. **Open question: what defensive primitives are we not considering?**

### Predictive (not coincident) regime detection

HMM was falsified because input features were coincident by construction (`spy_ret_5d`, `spy_vol_20d`). Path C unblock criteria points at: VIX term structure, IV skew, put/call ratios. Schwab integration unblocks several of these. **Open question: what other leading-indicator features are we underweighting?**

### Mechanical flow / opponent modeling

Currently zero awareness of other-participant positioning. CFTC COT data is integrated but features not yet derived. Other candidates: CTA forced unwinds, vol-target fund de-grossing, 0DTE dealer gamma, quad-witching flows. **Open question: what flow signals are most tractable for retail-scale to capture?**

### Autonomous discovery

The system has been hand-tuning more than autonomous-discovering. Engine D has produced zero promoted edges (all current edges were human-curated). Plans include Bayesian opt, symbolic regression, causal discovery, GNN. **Open question: what discovery method ordering / priority makes most sense given the regime-conditional alpha pattern?**

### Goal C / Moonshot Sleeve

Architecturally independent. Different universe, different metrics (skewness/Sortino/upside capture, not Sharpe). **Open question: are we framing the moonshot strategy correctly — long-momentum + breakouts + insider clusters? Or is there a better approach for asymmetric retail capture?**

### Cross-asset / multi-asset

System is equity-only. Could expand to bonds, commodities, FX, crypto. Engine C scaffolded for it but nothing active. **Open question: is multi-asset expansion likely to provide diversification value at retail scale, or is it complexity without commensurate alpha?**

---

## Doc pointers for the reviewer

If you want to read more before recommending:

- `CLAUDE.md` — project operating rules
- `docs/README.md` — canonical navigation index
- `docs/State/forward_plan.md` — current strategy
- `docs/State/health_check.md` — code-quality findings (open + resolved)
- `docs/State/ROADMAP.md` — phased plan
- `docs/Core/engine_charters.md` — formal engine boundaries
- `docs/Measurements/2026-05/` — most recent measurements (universe_aware_verdict, surviving_edges_multi_year, factor decomposition results)
- `docs/Sessions/Other-dev-opinion/2026-05-06_consolidated_audit_findings.md` — last external audit findings (most still open or partially addressed)

---

## Specific request from the reviewer

We want fresh input on **what to add** that would significantly improve the system. Bias toward:

1. **Substrate-independent additions** — things that don't depend on substrate verdict
2. **Defensive layer alternatives** — what hedges / offsets / regime-conditional reductions to consider
3. **Uncorrelated alpha sources** — beyond technical / factor / fundamental edges
4. **Things you've seen at top-1% retail or institutional projects** that we don't have

Don't bias toward:

- OMS / execution / deployment infrastructure (out of scope)
- Major architectural rewrites (we have 6 engines, work within that)
- New paid data subscriptions unless genuinely transformative (Schwab is already in pipeline as the main data unlock)

We want substantive recommendations with file:line evidence where applicable. Honest critique. Brutally direct. The team has shown it self-falsifies its own findings — we'd rather hear "here's what's wrong" than "here's what's good." Praise without specifics is useless; "this primitive at file:X:Y is missing because Z" is useful.
