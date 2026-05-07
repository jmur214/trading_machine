# Engine Charter Drift Inventory — 2026-05-09 evening

> **2026-05-09 NIGHT — POST-C-ENGINES-1 CORRECTION.** This inventory's
> Engine C.2 finding ("CRITICAL drift — defined but never called") was
> **empirically wrong**. The C-engines-1 dispatch agent (commit `cae2002`)
> verified that `backtester/backtest_controller.py:508` was already calling
> `self.portfolio.compute_target_allocations(...)` and threading the
> result into `risk.prepare_order(target_weights=...)`. Engine C.2's
> Allocation Layer was active all along.
>
> What was ACTUALLY misplaced (and is now closed): the HRP and
> TurnoverPenalty machinery inside `signal_processor.py:228-242`
> (charter inversion F4). C-engines-1 moved them into a new
> `engines/engine_c_portfolio/composer.py`; signal_processor LOC dropped
> 715 → 522; charter check (`grep -rn "HRPOptimizer\|TurnoverPenalty"
> engines/engine_a_alpha/`) returns zero hits.
>
> **What this changes:** the substrate-honest 0.5074 (9-edge) and
> 0.9154 (6-edge surviving) results from B1 + C-collapses-1 were
> measured on a system with Engine C.2 active. They are **not**
> "system without portfolio management" results — they are honest
> Engine-C-active substrate-honest baselines. Engine completion's
> expected lift is more measured than the original framing implied.
>
> The lesson (now captured in `lessons_learned.md`): verify drift
> claims empirically (read every entry point) before building project
> narratives on them. The original drift inventory traced
> `mode_controller.run_backtest` but missed the
> `BacktestController._prepare_orders` path that's invoked when the
> backtest controller is active. Both paths exist; only one was
> audited; the wrong one became the headline finding.
>
> The remaining 4-of-6 engine drift findings (A's EDGE_CATEGORY_MAP
> import; B's per-trade-only vol-targeting; D's 0 promoted edges; E's
> coincident HMM; F's F11 write-back concern) all stand. The
> engine-completion path is unchanged in shape; only the
> magnitude-of-expected-lift framing was wrong.
>
> ---


**Status:** read-only audit comparing each engine's charter (`docs/Core/engine_charters.md`) against current code. Built as input for the engine-completion structural review (`forward_plan.md` 2026-05-09 evening trigger). Identifies what each engine is supposed to do vs what it does.

This complements the running C-collapses-1 audit's per-edge analysis: where the audit answers "do edges have signal," this doc answers "do engines do their jobs."

## Summary table

| Engine | Charter mission | Status | Drift severity | Closed by |
|---|---|---|---|---|
| A | Calibrated forecasts only; no portfolio/risk responsibilities | Charter inversions present | **HIGH** | C-engines-1 (HRP/Turnover out) + C-engines-5 (taxonomy + calibrated strength) |
| B | Mechanical risk constructor; portfolio-aware sizing | Per-trade only; no portfolio vol-target; no correlation-aware | **HIGH** | C-engines-2 (propose-first) |
| C.1 | Ledger Layer (accounting) | Operating per charter | LOW | — |
| C.2 | Allocation Layer (portfolio composition) | **DEFINED but UNCALLED** | **CRITICAL** | C-engines-1 |
| D | Hunt + validate edges; output candidates | Machinery exists; produced 0 promoted edges in project history | **HIGH** | C-engines-4 (Bayesian opt) + ongoing substrate-aware gauntlet |
| E | Regime intelligence | Empirically coincident, not leading | **HIGH** | C-engines-3 (minimal-HMM on leading FRED features) |
| F | Lifecycle governance | Mostly operating per charter | MEDIUM | F11 architectural review (propose-first; audit recommendation) |

> **CORRECTION 2026-05-09 NIGHT:** the row above said C.2 was CRITICAL drift and the bottom-line said "C.2 is the most severe gap — defined but never invoked in production." Both empirically wrong (see top-of-file correction). C.2 was active via `BacktestController._prepare_orders:508`. Engine C's actual drift was the misplaced HRP/TurnoverPenalty machinery (F4 charter inversion in signal_processor), which C-engines-1 closed. Engine C row should now read: drift CLOSED 2026-05-09 (post-C-engines-1).

**Corrected bottom line:** Of 6 engines, **Engine C is now operating close to charter** (Ledger + Allocation both active; HRP/Turnover correctly placed). Engines A, B, D, E have remaining drift addressed by C-engines-5 / 2 / 4 / 3 respectively. Engine F has the F11 architectural concern. The substrate-honest 0.5074 / 0.9154 results were measured on a system with Engine C active — not on a system "without portfolio management" as originally framed.

## Per-engine details

### Engine A — Forecast Engine — HIGH drift

**Charter:** "Produce calibrated directional forecasts with conviction strength" — output schema includes `strength: float [0.0, 1.0]`, `decomposition` for explainability. Forbidden inputs include "current cash balance," "portfolio state," "execution state."

**Charter inversions present in code:**
- `engines/engine_a_alpha/signal_processor.py:228-242` instantiates `HRPOptimizer` and `TurnoverPenalty` from Engine C. Charter direction is A → C, not A operating C's tools. (Audit finding F4.)
- `engines/engine_a_alpha/signal_processor.py:27` imports `EDGE_CATEGORY_MAP` from `engines/engine_f_governance/regime_tracker`. Engine A taxonomy living in F is documented charter inversion (open MEDIUM in `health_check.md`).

**Output-schema gap:**
- Charter specifies `strength: float` ∈ [0,1] as conviction. Most edges output binary/ternary `signal: int` (-1/0/1) and don't populate calibrated strength. Sustained-score logic added 2026-05-07 fakes a continuous emission for held positions but isn't a real probability.

**LOC:** signal_processor.py = 715 LOC; charter says "loose, opinionated about direction, not protective about risk" — current size implies more responsibilities than charter allows.

**Drift closure:**
- C-engines-1 moves HRP+Turnover OUT (closes F4)
- C-engines-5 moves EDGE_CATEGORY_MAP to `engines/engine_a_alpha/edge_taxonomy.py` (closes the F-import inversion) + adds calibrated `signal_strength` field + adds `holding_period_bars` metadata

### Engine B — Trade Construction — HIGH drift

**Charter:** "B is mechanical and boring — fixed risk budget, volatility scaling, hard caps." Allowed inputs include "Portfolio state from Engine C's Ledger Layer (current positions, equity, exposure, available capital)." Forbidden: edge performance metrics, weight multipliers.

**Drift:**
- **Per-trade vol-targeting, not portfolio-level.** `risk_engine.py` sizes each trade individually to a vol budget. Charter says "volatility scaling" generically; current implementation makes the unit per-trade rather than per-portfolio. With correlated positions (mega-cap tech longs typically 0.6-0.8 correlated), realized portfolio vol can be wildly above the sum of per-trade budgets.
- **No correlation-aware sizing.** Sector map is loaded but used only for hard exposure caps, not for cross-position vol decomposition.
- **Vol-target multiplier hits 2.0x cap routinely** (memory `project_vol_target_in_sample_measured_2026_04_24`). Effective policy is "max 2x leverage when calm" rather than regime-aware sizing.
- **955 LOC** — plus `factor_analysis.py`, `lt_hold_preference.py`, `wash_sale_avoidance.py` siblings. Charter says "mechanical and boring"; current implementation has accreted features.

**Drift closure:**
- C-engines-2 (PROPOSE-FIRST per CLAUDE.md). Five open design questions documented in `phase_c_dispatch_branches.md`.

### Engine C.1 — Ledger Layer — LOW drift

**Charter:** "Maintain irrefutable, deterministic source of truth for all accounting state." Owns: cash balance, position quantities, cost basis, realized/unrealized PnL, fill processing, equity computation, snapshot history. Invariant: `Equity = Cash + Σ(qty × price)` always holds.

**Reality:**
- `portfolio_engine.py::PortfolioEngine` implements all the listed responsibilities cleanly.
- `apply_fill`, `snapshot`, `total_equity`, `gross_notional`, `net_exposure`, `positions_map` — all called in production backtest loop.
- Tests in `tests/test_portfolio_engine.py` verify the equity invariant.

**No meaningful drift.** Engine C.1 is operating per charter.

### Engine C.2 — Allocation Layer — CRITICAL drift

**Charter:** "Determine the theoretical target allocation across assets using declared portfolio policy." Owns: target weight computation, **portfolio-level vol targeting**, **diversification and correlation-aware weighting**, regime config overrides, drift measurement, rebalance trigger decisions.

**Reality:**
- `compute_target_allocations` is DEFINED at `portfolio_engine.py:310-323` but **NEVER CALLED** in `orchestration/mode_controller.py`'s backtest loop.
- `PortfolioPolicy.allocate()` is DEFINED at `policy.py:108` but only invoked in `scripts/system_validity_check.py` (a unit test).
- `engines/engine_c_portfolio/optimizer.py::PortfolioOptimizer` exists.
- `engines/engine_c_portfolio/optimizers/hrp.py` HRP implementation exists.
- HRP+TurnoverPenalty live IN ENGINE A (`signal_processor.py:228-242`), not Engine C.
- HRP slices 1 + 3 were both falsified on small ensembles (memories `project_engine_c_hrp_slice1_falsified_2026_05_02`, `project_hrp_slice_3_paused_small_ensemble_2026_05_02`).

**The allocation layer's machinery is built; it's just not wired into production. The portfolio-management engine of the system is effectively absent.**

**Drift closure:**
- C-engines-1 wires `compute_target_allocations` into the backtest loop, moves HRP+Turnover from A to C, restores A → C charter direction.

### Engine D — Discovery & Evolution — HIGH drift

**Charter:** "Hunt for new trading edges, validate candidates through rigorous walk-forward testing... output validated candidates for Governance to evaluate and activate."

**Reality:**
- The machinery exists: GA in `genetic_algorithm.py`, WFO in `wfo.py`, 6-gate gauntlet in `discovery.py::validate_candidate`, robustness checks in `robustness.py`.
- **Zero edges have been promoted via Discovery in project history.** Every active edge in `data/governor/edges.yml` was hand-curated (volume_anomaly, herding, V/Q/A, etc.).
- Per `health_check.md`: GA gene vocabulary searches a "strip-mined space" (open MEDIUM since 2026-04-24).
- The gauntlet's geometry-mismatch bug was fixed 2026-05-02 but the underlying problem — that GA can't find new alpha in the current vocabulary — remains.

**The engine HAS the machinery to do its job; the machinery has produced nothing useful. Both interpretations are true.**

**Drift closure:**
- C-engines-4 replaces GA with Bayesian optimization via BoTorch. Substrate-independent infrastructure. Doesn't promote candidates — they go through the existing gauntlet. The gauntlet's substrate-aware version (post-C-collapses-1) provides the right downstream gate.

### Engine E — Regime Intelligence — HIGH drift

**Charter:** "Detect, score, and publish the current multi-axis market environment as an official, system-wide context object."

**Reality:**
- HMM produces structured output per the charter (regime label, confidence, advisory hints).
- BUT: empirically coincident, not leading. Memory `project_regime_signal_falsified_2026_05_06`: HMM crisis AUC 0.49 on 20d-fwd drawdowns (coin flip); 2-of-3 cross-asset gate had 0% TPR on -5% drawdowns over 1086 days.
- The 2026-05-06 cheap-validation Branch 3 found that 4 specific FRED features carry forward signal (yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d, spy_vol_20d) but are drowned by coincident features in the larger panel.
- `cross_asset_confirm.py` archived 2026-05-07 (TPR=0% on drawdowns).
- Engine B reads E's `risk_score` but the value is structurally non-predictive — the wire is in place; the signal isn't.

**Engine E satisfies the charter's literal output contract but fails its mission ("Regime Intelligence" implies forward-looking; current implementation is backward-looking).**

**Drift closure:**
- C-engines-3 trains minimal-HMM on the 4 leading FRED features only, validates against forward drawdowns, produces wire-readiness assessment. Engine B integration explicitly OUT OF SCOPE (propose-first).

### Engine F — Governance — MEDIUM drift

**Charter:** "F never changes live state without a versioned audit trail." Owns: edge weight management, lifecycle transitions, regime-conditional weights, autonomy without human-in-the-loop.

**Reality:**
- `LifecycleManager` exists and works. First autonomous pause shipped 2026-04-24 (atr_breakout_v1 paused on evidence — memory `project_first_autonomous_pause_2026_04_24`). Soft-pause at 0.25x is Pareto improvement.
- Decision diary scaffold in `core/observability/decision_diary.py`. Backfilled with 12 + 5 events.
- Edge graveyard tagging shipped (failure_reason + superseded_by fields).
- F11 from audit: write-back-to-edges-yml pattern mutates the upstream measurement substrate. The 2026-04-25 registry-stomp bug (now fixed) was a manifestation. Architectural concern still open.

**Lower drift than A/B/C.2/D/E. Engine F is closer to operating per charter than any other engine besides C.1.**

**Drift closure:**
- F11 architectural redesign is propose-first per CLAUDE.md. Surface to user when ready; not in the C-engines-N queue.

## Cross-engine observations

**Charter inversion pattern.** Two engines have HIGH drift via charter inversion (A holds C+F responsibilities; HRP/Turnover and EDGE_CATEGORY_MAP). One engine has CRITICAL drift via under-implementation (C.2's allocation layer is defined but uninvoked). One engine fails its mission despite satisfying its output contract (E produces regime signals that aren't predictive). One engine satisfies the contract but has 0 production output (D's Discovery cycle).

**The system has been operating as Engine A + Engine B + Engine C.1 + Engine F**, with Engines C.2, D, and E nominally present but functionally absent.

This is what the user surfaced 2026-05-09 evening. The substrate-honest Sharpe 0.507 isn't "the strategy doesn't work" — it's "the strategy operating with 3 of 6 engines effectively missing doesn't survive substrate honesty."

**Engine completion = restoring 4-of-6 to charter operation.** The engine-incomplete substrate-honest measurement is not a fair test of the architecture.

## What this changes for the structural review

The kill-thesis structural review (declared TRIGGERED 2026-05-09 evening) needs to engine-complete BEFORE re-measuring. The C-engines-N dispatches in `phase_c_dispatch_branches.md` are the structural review's main vehicle. The C-remeasure result (post-completion substrate-honest multi-year) is the new pre-commit baseline.

**Sequencing:**
1. C-engines-1 (Engine C.2 activation) — closes the most severe drift; lowest effort
2. C-engines-5 (Engine A pure-signals) — sequenced after C-engines-1; both touch signal_processor.py
3. C-engines-3 (Engine E minimal-HMM) — substrate-independent; can run in parallel with above
4. C-engines-4 (Engine D Bayesian opt) — substrate-independent; can run in parallel
5. C-engines-2 (Engine B portfolio vol-target) — PROPOSE-FIRST; needs user design decisions before firing

After all 5 land + close their respective drift, C-remeasure runs the multi-year on substrate-honest universe. THAT result defines the next pre-commit gate.

## What this doesn't address

- **The strategy may have no per-name signal even with completed engines.** This is the load-bearing question that C-collapses-1.5 (concentration-equivalent capital test) is designed to answer. Engine completion doesn't manufacture alpha; it gives the strategy a fair test.
- **Goal C / Moonshot Sleeve** stays parked until C-remeasure verdict (per the user's framing: "if we can't get the bones working properly we shouldn't be working on the golden apple yet").
- **The pre-2026-05-07 V/Q/A baseline non-reproducibility** the running audit just surfaced — this is a separate finding that touches every measurement memory but doesn't change the charter-drift inventory above.

## Honest caveats

- This inventory is read-only — comparing charter text against grep output and code structure. It does not assert any code is buggy or that the engines must operate as the charter specifies. The charter is the design intent; deviations might be deliberate.
- "Charter drift" is not synonymous with "broken." Engine C.2 being uncalled is a deliberate choice (someone wrote it without wiring it). Whether wiring it improves outcomes is what C-engines-1 will test.
- Engine F's F11 concern is architectural (write-back-to-edges-yml during measurement), not "Engine F is broken." It's a propose-first decision the user can take their time on.
