# Autonomous Edge Lifecycle Plan (2026-04-24)

> **One-liner**: The system has Engines D and F described as "edge hunter" and "performance reviewer," but **neither actually does its job**. Discovery plumbing is broken; deprecation doesn't exist in code. This is the root cause of underperforming SPY.

## Why This Plan Exists

After ~2 weeks of multi-session auditing + walk-forward validation of the existing advisory/governance stack, the honest state of the system is:

| What was claimed | What the code actually does |
|---|---|
| "Governance autonomously manages edge lifecycle (candidate → active → paused → retired)" | Only `candidate → active | failed` transitions exist. No active edge can be paused or retired by any code path, regardless of performance. |
| "Discovery runs post-backtest: hunt → validate → promote winners" | [evolution_controller.py:101](engines/engine_f_governance/evolution_controller.py#L101) subprocess-calls `scripts/walk_forward_validation.py` — **that script does not exist**. Every Discovery candidate fails silently. 132 failed / 1 candidate / 13 active in `edges.yml`. |
| "Active edges have proven their worth" | All 13 `active` edges are the original hand-entered edges from project start. None went through autonomous validation. `atr_breakout_v1` is active with global Sharpe −0.04 and lost $5,365 in the last baseline run. |
| "The system learns which edges work in which regimes" | Per-edge per-regime kill-switch has been built and falsified under walk-forward (3 splits: -0.50 / +0.18 / -0.21 Sharpe). Currently disabled. |
| "Weights auto-adjust based on rolling performance" | Partially true: `update_from_trade_log` runs EMA on weights. But it never changes edge `status`. Weight can decay toward zero; the edge keeps running and getting data written to the tracker. |

**Bottom line**: The "autonomous" part of the autonomous trading system is not implemented. What exists is a hand-tuned rules engine with 14 human-weighted edges and a large graveyard of never-activated Discovery candidates. Whether the system beats SPY is currently a matter of whether **momentum_edge_v1 minus atr_breakout_v1** happens to yield positive alpha — which measured shows: ~+$9,400 realized P&L vs SPY buy-and-hold's ~+$50K on same capital. SPY wins.

---

## Evidence

### Finding 1: `scripts/walk_forward_validation.py` is missing
```bash
$ ls scripts/walk_forward_validation.py
MISSING
```
Every candidate goes through `EvolutionController.run_wfo_for_candidate(...)`, which:
1. Calls `subprocess.run([python, str(self.wfo_script), ...])`
2. Captures stderr, continues even on failure
3. Tries to read `data/research/wfo_summary.json` (stale from months ago)
4. Returns `(False, 0.0, None)` → candidate marked `failed`

This has been silently killing every candidate since the script was referenced but never created.

### Finding 2: No demotion code path exists
```bash
$ grep -rn "retire\|deprecate\|paused" engines/engine_f_governance/*.py
# Only result: a comment about datetime deprecation, unrelated
```
`StrategyGovernor.update_from_trades()` computes per-edge Sharpe, Sortino, MDD, correlation — and writes weights. It **never writes `status` changes** back to `edges.yml`. The tracker accumulates data on dead edges forever.

### Finding 3: The 7 "base" active edges are immutable
From [data/governor/edges.yml](data/governor/edges.yml):
```yaml
- edge_id: atr_breakout_v1       # status: active  ← NEVER VALIDATED by the 4-gate pipeline
- edge_id: rsi_bounce_v1         # status: active  ← same
- edge_id: bollinger_reversion_v1 # status: active  ← same (but weight 0.0 in config = silently dead)
- edge_id: momentum_edge_v1      # status: active  ← the only real winner
```
These 7 entries are hand-typed. They predate Discovery. They've never been through the validation pipeline that new candidates are (theoretically) subjected to. They persist through every Discovery cycle because nothing touches `active` status.

### Finding 4: Validation thresholds are too weak
`discovery.py`'s Gate 1 is `sharpe > 0` (trivially passed by any market-correlated exposure). `run_evolution_cycle.py`'s Gate 1 is `sharpe >= 0.5` — still under SPY's buy-and-hold Sharpe on most recent windows.

A useful edge should beat the "do nothing except hold SPY" benchmark. Passing at Sharpe 0.5 when SPY has been at ~1.0 just crowns edges that happen to correlate with SPY — providing no marginal alpha.

---

## The Plan — 6 Phases

Ordered by leverage-per-effort. Each phase ships independently.

### Phase α: Active-Edge Retirement (2-3 days, HIGHEST LEVERAGE)
**Goal**: give the system a lifecycle enforcement layer so underperforming active edges get paused/retired without human action.

**Deliverables**:
1. New method `StrategyGovernor._evaluate_lifecycle_transitions(trades_df)` called at end of `update_from_trade_log`. For each edge with `status: active`:
   - Compute rolling-window metrics: Sharpe (last N trades, last N days), MDD, WR, trade frequency
   - Apply gates (see below)
   - Write `status` transitions back to `edges.yml` with audit trail
2. New file `data/governor/lifecycle_history.csv` — append-only log of every transition with timestamp, edge_id, old_status, new_status, triggering metric, evidence window
3. Config additions in [engines/engine_f_governance/governor.py](engines/engine_f_governance/governor.py) `GovernorConfig`:
   - `lifecycle_enabled: bool = False` (start defense-first)
   - `retirement_min_trades: int = 100`
   - `retirement_min_days: int = 90`
   - `retirement_sharpe_vs_benchmark: float = -0.2` (retire if edge Sharpe < benchmark Sharpe - 0.2)
   - `pause_mdd_threshold: float = -0.30` (pause if edge realized MDD exceeds 30%)
   - `max_retirements_per_cycle: int = 1` (avoid mass de-risking cascade)

**Gates (all must fire to trigger retirement)**:
| Gate | Rule | Purpose |
|---|---|---|
| Minimum evidence | >=100 trades AND >=90 days since activation | Protect against early-stage noise |
| Benchmark-relative | Edge Sharpe (N-trade rolling) < benchmark Sharpe - 0.2 over same dates | Retire losers, not just zero-alpha edges |
| Recent decay | Last 30-trade Sharpe < all-time Sharpe - 1.0 std.dev | Distinguish "always bad" (old alpha dead) from "having a bad month" |
| Not revived | Edge has NOT been in recovery (30-trade Sharpe > 0.3) in the last 15 trades | Don't retire edges that are turning around |

**Pause gates** (triggers sooner than retire; reversible):
| Gate | Rule |
|---|---|
| MDD spike | Rolling 90-day MDD < -30% |
| WR collapse | Rolling 30-trade WR < rolling 90-trade WR - 15pp |

**Revival gate** (for `status: paused`):
| Gate | Rule |
|---|---|
| Sustained recovery | Last 20 trades (since pause): Sharpe > 0.5 AND WR > 45% |

**A/B test this**: deploy with `lifecycle_enabled: true`, measure 3-split walk-forward. Acceptance: OOS Sharpe ≥ baseline on ≥2/3 splits. Specifically: when applied to the current 14-edge roster, `atr_breakout_v1` should retire in Split A's training window (91+ days in 2021-2022 clearly losing money).

**Files to modify**: `engines/engine_f_governance/governor.py`, `config/governor_settings.json`, new file `engines/engine_f_governance/lifecycle_manager.py` (or inline), tests in `tests/test_lifecycle.py`.

---

### Phase β: Benchmark-Relative Gates Everywhere (1-2 days)
**Goal**: stop using absolute Sharpe thresholds that are trivially passed by beta exposure.

**Deliverables**:
1. Add `core/benchmark.py` — computes rolling SPY Sharpe/MDD/CAGR for any window, cached
2. Replace absolute thresholds in 3 places:
   - [discovery.py](engines/engine_d_discovery/discovery.py) Gate 1: `sharpe > 0` → `sharpe > benchmark_sharpe - 0.2`
   - [run_evolution_cycle.py:87](scripts/run_evolution_cycle.py#L87) Gate 1: `sharpe < 0.5` → `sharpe < benchmark_sharpe - 0.3`
   - Phase α's retirement gate (already uses benchmark — this just wires the same computation)
3. Add BenchmarkContext to `regime_meta["advisory"]` so all downstream gates can reference it consistently

**Why**: an edge that trades stocks during a bull market is *by default* going to show positive Sharpe. The question isn't "does the edge make money" — it's "does the edge beat buying SPY?" This single change will probably cull most currently-active edges and correctly filter Discovery candidates going forward.

**Files**: `core/benchmark.py` (new), `engines/engine_d_discovery/discovery.py`, `scripts/run_evolution_cycle.py`.

---

### Phase γ: Fix Discovery Plumbing (2-3 days)
**Goal**: make Engine D actually validate candidates so they can get promoted or failed on their merits.

**Deliverables**:
1. **Delete or rewrite** `engines/engine_f_governance/evolution_controller.py`'s `run_wfo_for_candidate` — it calls a missing script. Replace with direct invocation of `engines.engine_d_discovery.wfo.WalkForwardOptimizer` (already exists) matching the pattern in `run_evolution_cycle.py`.
2. Wire `scripts/run_autonomous_cycle.py` to run once per week as a scheduled job: Discovery hunt → validate → promote. Log to `data/discovery/run_history.jsonl`.
3. Add a `--validate-existing-actives` flag that re-runs all current active edges through the 4-gate validation pipeline (one-time cleanup; see Phase ε).

**Acceptance**: run one full cycle end-to-end. At least one new discovered candidate gets promoted OR cleanly failed with logged reason. No silent failures on missing scripts.

**Files**: `engines/engine_f_governance/evolution_controller.py`, `scripts/run_autonomous_cycle.py`.

---

### Phase δ: GA Fitness Function Upgrade (1 week)
**Goal**: the GA currently selects genomes by in-sample Sharpe. That's why 132 candidates failed — in-sample winners didn't generalize.

**Deliverables**:
1. In [genetic_algorithm.py](engines/engine_d_discovery/genetic_algorithm.py), change fitness calculation:
   ```
   fitness = 0.5 * oos_sharpe_vs_benchmark  +
             0.3 * (1 - pbo_overfitting_prob) +
             0.2 * oos_is_degradation_ratio
   ```
   All three components must be positive for the genome to be considered viable.
2. Record FAILURE reasons in `ga_population.yml` — which gate each failed candidate hit. Use as credit signal: if 80% of "fundamental" gene candidates fail Gate 2 (robustness), reduce that gene type's spawn probability.
3. Seed GA population not from random but from MUTATIONS of currently-validated-profitable edges (the successful ones after Phase ε).

**Files**: `engines/engine_d_discovery/genetic_algorithm.py`, `engines/engine_d_discovery/discovery.py` (fitness calc site).

---

### Phase ε: Demote Hand-Entered Base Edges to `candidate` (1 day)
**Goal**: put the system on equal footing — all edges, new and old, go through the same validation.

**Deliverables**:
1. Script `scripts/reset_base_edges.py`: iterate the 7 hand-entered active edges in `edges.yml`, change status to `candidate`.
2. Run Phase γ's validation cycle against them. Each either passes (→ `active`, evidence-based) or fails (→ `failed`).
3. Expected outcome based on the audit data:
   - `momentum_edge_v1`: probably passes (rolling Sharpe +1.65, real alpha)
   - `atr_breakout_v1`: probably fails (rolling Sharpe -0.04, trade volume exceeds benchmark)
   - `rsi_bounce_v1`, `bollinger_reversion_v1`: currently silenced (weight 0.0); validation confirms whether to fully retire
   - Others: inconclusive, let the data decide

**This is the MOST IMPORTANT step** because it subjects the currently-untouched base edges to the autonomous discipline. Without it, the deprecation machinery from Phase α can retire NEW edges but not the old ones that are actually losing money.

**Files**: new `scripts/reset_base_edges.py`; data `edges.yml` modified by script run.

---

### Phase ζ: New Alpha Source Templates (2-3 weeks, LOW IMMEDIATE PRIORITY)
**Goal**: once the lifecycle machinery works, feed it higher-quality edge candidates than random technical-indicator mutations.

Candidate templates (from academic literature and `docs/Core/Ideas_Pipeline/ideas_backlog.md`):
1. **Post-Earnings Announcement Drift (PEAD)** — buy/sell on earnings surprise, hold 2-3 months. Well-documented 2-4% monthly excess return.
2. **Cross-sectional momentum with factor neutralization** — long top-decile by 6-month momentum, short bottom-decile, sector-neutralize. Requires `fundamental_data_pipeline` beefing up.
3. **Low-volatility factor** — buy bottom-quartile realized-vol stocks, rebalance monthly. Empirically adds ~1 Sharpe unit in bear markets, flat in bulls.
4. **Insider buying** — requires new data source (13F-like or Form 4 feed). `#DATA-2` in ideas backlog.
5. **Event-driven (guidance changes, SEC filings)** — requires NLP pipeline on 8-K filings.

**Why last**: no point adding new alpha templates until the system can (a) validate them honestly (Phase β + γ), (b) retire them when they stop working (Phase α), (c) stop wasting capital on worse alternatives (Phase ε).

---

## Execution Order and Dependencies

```
Phase β (benchmark)  ──┐
                       ├──► Phase α (retirement)  ──► [first autonomous retirement happens]
Phase γ (plumbing)   ──┼──► Phase ε (demote bases) ──► [SPY outperformance possible]
                       │
                       └──► Phase δ (GA fitness)   ──► Phase ζ (new templates)
```

**Week 1**: Phase β + Phase γ (both small, unblock the rest)
**Week 2**: Phase α (lifecycle manager + walk-forward verify)
**Week 3**: Phase ε (demote bases, re-validate)
**Week 4+**: Phase δ, then Phase ζ

## Acceptance Criterion for "Drastically Improved"

After Phase α + ε:

**In-sample**: One or more currently-active edges gets auto-retired (expected: `atr_breakout_v1`, maybe `rsi_bounce_v1`). Remaining edges' combined Sharpe exceeds 1.2 (vs current 0.98).

**Walk-forward (3 splits)**: OOS Sharpe beats SPY OOS Sharpe on at least 2 of 3 splits. Current state: loses SPY on 3 of 4 measurements.

**Autonomy proof**: Discovery cycle runs weekly unattended; retires at least one edge per quarter based on live performance; promotes at least one new candidate per quarter.

## Scope Limits (What This Plan Does NOT Cover)

- Engine C sleeves (Phase 5 in ROADMAP) — independent work, not blocking.
- Live broker integration — irrelevant until backtests beat SPY.
- UI/dashboard changes — the lifecycle_history.csv above gives enough explainability for now.
- Re-enabling the per-edge per-regime kill-switch — already falsified, redesign needed before re-attempting.
- The "Grey edges" and alternative data — deferred to Phase ζ and beyond.

## Files Summary

**New files**:
- `engines/engine_f_governance/lifecycle_manager.py` — Phase α
- `core/benchmark.py` — Phase β
- `scripts/reset_base_edges.py` — Phase ε
- `docs/Core/Ideas_Pipeline/autonomous_lifecycle_plan.md` — this file
- `data/governor/lifecycle_history.csv` — created at first lifecycle event
- `data/discovery/run_history.jsonl` — created at first Discovery run

**Modified files**:
- `engines/engine_f_governance/governor.py` — Phase α (lifecycle hook), Phase β (benchmark integration)
- `engines/engine_f_governance/evolution_controller.py` — Phase γ (fix subprocess call)
- `engines/engine_d_discovery/discovery.py` — Phase β (Gate 1 benchmark-relative), Phase δ (fitness)
- `engines/engine_d_discovery/genetic_algorithm.py` — Phase δ
- `scripts/run_autonomous_cycle.py` — Phase γ (proper cycle orchestration)
- `scripts/run_evolution_cycle.py` — Phase β (Gate 1 benchmark-relative)
- `config/governor_settings.json` — Phase α config additions
- `data/governor/edges.yml` — Phase ε (demote bases, then re-validate)
- `docs/Core/ROADMAP.md` — link this plan as a new Phase 4.6 or Phase 5 work stream
