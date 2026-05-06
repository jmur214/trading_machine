# Independent Audit — ArchonDEX, 2026-05-06

> Independent reviewer pass. Read CLAUDE.md, `docs/State/forward_plan.md`,
> `docs/State/health_check.md` (1700+ lines), the 5 most recent measurement
> docs in `docs/Measurements/2026-05/`, and verified findings against
> `engines/`, `core/`, `orchestration/`, `backtester/`, and `config/`.
> Out-of-scope items (live_trader, OMS, deployment) skipped per request.
>
> The picture is harsher than the docs convey. The system has done a lot
> of careful engineering on a substrate that doesn't support the
> conclusions being drawn from it.

---

## Top findings (prioritized)

### 1. The "Foundation Gate PASS" is on a survivorship-biased, hand-curated universe — and the survivorship-aware loader you built is not wired into a single backtest

`engines/data_manager/universe.py:226-240` defines a working
`historical_constituents(as_of)` method that returns "tickers active on a
given date — the survivorship-bias-aware view." Wikipedia membership is
cached. Tests exist. But:

- `engines/data_manager/index.md:98` — "**Not yet wired into any engine**."
- `grep -rn "historical_constituents\|UniverseLoader" engines orchestration backtester scripts`
  returns zero production callers. (Only `index.md` and `universe.py`
  itself.)
- The actual universe every backtest consumes is `config/universe.json` —
  a static 115-name list of current S&P 500 mega-caps
  (`AAPL, MSFT, NVDA, GOOGL…`), used by `scripts/update_data.py:26` to
  fetch prices.
- `docs/Measurements/2026-05/multi_year_foundation_measurement.md:6` —
  every cell of the 5-year Foundation Gate measurement runs on this
  universe.

The team's own earlier work showed what happens when you swap to a
held-out universe: `health_check.md` line 85 — "**Universe-B held-out
50, in-sample window: Sharpe 0.225 vs in-sample 1.063 — a 79% Sharpe
collapse**". That collapse has not been re-measured since the gauntlet
rewrite, the cost layer, the V/Q/A merge, etc. Every Sharpe in the
multi-year measurement is conditional on the favorable universe.
Building and not wiring the survivorship-aware loader is worse than not
building it — it creates the appearance of solved bias.

### 2. The "5 years × 3 reps = 15 runs" multi-year measurement is one deterministic run replicated three times per year, not 15 independent samples

`docs/Measurements/2026-05/multi_year_foundation_measurement.md:10-14` —
for each year, `Sharpe (rep1, rep2, rep3) = (1.6660, 1.6660, 1.6660)`,
"Canon md5 unique 1/3, Determinism PASS (bitwise)". This is the
determinism harness (`scripts/run_isolated.py`) doing exactly what it
was designed to do: produce bit-identical output across reruns. It is
**not** statistical robustness. Mean Sharpe 1.296 is a single point
estimate; standard error is undefined; the 0.583 (2022) → 1.890 (2024)
range is the true cross-year noise envelope on N=1 measurements per
year. The "Foundation Gate: PASS" headline conflates "the harness is
reproducible" with "the system has alpha." Anyone reading the report at
face value gets the wrong message.

### 3. There is no real out-of-sample period

The system's parameters were tuned during the same window that includes
"OOS" data:

- `fill_share_cap` chosen from `scripts/sweep_cap_recalibration.py`
  sweep that explicitly optimized 2025 OOS Sharpe
  (`docs/Measurements/2026-04/cap_bracket_sweep_2026_04.md`). Final
  pick: 0.20 (`config/alpha_settings.prod.json:29`).
- Soft-pause `PAUSED_MAX_WEIGHT = 0.5` (`health_check.md` line 232-236)
  chosen by inspecting 2026-04 in-sample atr_breakout fill counts.
- ADV floors $200M / $300M chosen via
  `path2_adv_floors_under_new_gauntlet_2026_05.md`.
- `sustained_score = 0.3` (V/Q/A) hand-picked to bring 2021 Sharpe
  within "noise band" of the 1.666 baseline
  (`engines/engine_a_alpha/edges/_fundamentals_helpers.py:199`;
  `forward_plan.md:267` admits "current 0.3 is a starting heuristic,
  not validated").

Net: **2025's Sharpe = 0.954 is pseudo-OOS**, and that number tracks
SPY 2025 = 0.955. Zero risk-adjusted alpha vs benchmark on the
favorable universe with parameters tuned to the period. CAGR 4.39% vs
SPY ~13% (`post_foundation_preflight_2026_05.md:55`). The team needs a
frozen-code, frozen-config window with no peeking before any
"Foundation passes" claim is honest.

### 4. Engine C "rebuild" produced HRP that regressed Sharpe by 0.63 — and is disabled in production. Portfolio construction is still implicit linear aggregation in Engine A

- `engines/engine_a_alpha/signal_processor.py:78` — explicit comment:
  `method = "hrp" → HRP-as-replacement (slice 1 — FALSIFIED). Sharpe regression -0.63 vs weighted_sum`.
- `config/portfolio_settings.json:13` —
  `"portfolio_optimizer": {"method": "weighted_sum"}`. Production runs
  the no-op.
- `engines/engine_c_portfolio/portfolio_engine.py` is 366 LOC of
  position accounting + policy gating; no optimizer is invoked from
  there in production.
- `signal_processor.py:228-242` instantiates HRP/Turnover from inside
  Engine A (charter inversion A→C).

The reviewer doc the team relies on
(`docs/Sessions/Other-dev-opinion/05-1-26_1-percent.md`) was emphatic:
Engine C is the thinnest engine. **It still is.** Workstream B status
of "~25-30%" in `forward_plan.md:68` is generous — the shipped slice
was falsified. Calling it "shipped" misleads forward planning.

### 5. ~1500 LOC of regime code is shipped as the "regime engine" while the team's own validation says the signals don't work

`docs/Measurements/2026-05/regime_signal_validation_2026_05_06.md`:

- 20d AUC of HMM `p_crisis` = **0.49** (coin flip).
- Mean fwd 20d drawdown: HMM-crisis days **-3.21%**, benign days
  **-3.20%** (indistinguishable, line 116).
- 2-of-3 cross-asset confirmation gate: **TPR=0** on -5% drawdowns over
  1086 days (line 144).
- OOS 2025 AUC = 0.36 (worse than coin flip on the actual event,
  line 226).
- HMM inputs `spy_ret_5d`, `spy_vol_20d` are coincident by construction
  (`engines/engine_e_regime/macro_features.py:206-207`,
  `hmm_classifier.py:56`).

Code surface still present: `hmm_classifier.py` (464 LOC),
`regime_detector.py` (624 LOC), `multires_hmm.py`,
`transition_warning.py` (302 LOC), `cross_asset_confirm.py`,
`advisory.py` (479 LOC). The verdict in the validation doc — "WS-C
three-way 'two-out-of-three' architecture should be archived" — has
not happened. Engine E currently presents itself as a regime-detection
engine while empirically being a coincident-vol logger. That gap should
not survive in active engines for weeks while features land downstream
of it.

### 6. The discovery gauntlet still passes silently on failures, after 2 weeks of being told

`engines/engine_d_discovery/discovery.py`:

- Line 1084-1086 —
  `gate_5_passed = bool(math.isnan(universe_b_sharpe) or universe_b_sharpe > 0)`.
  **NaN passes.** Bare `except Exception` (line 1078) sets NaN on any
  failure.
- Line 1117 — Gate 6 default `factor_alpha_passed = True`; bare
  exception (line 1114-1118) preserves True on failure.
- Line 1129-1131 — `if significance_threshold is None: sig_passed = True`
  regardless of p-value (Gate 4 bypass for the common code path).
- Line 1078, 975-976, 1026-1027, 1114 — Gates 2/4/5/6 still wrap broad
  `except Exception`. Gate 3 (line 1006-1008) is the only one with the
  `isinstance(e, (TypeError, AttributeError)): raise` pattern from the
  prior fix.

The 2026-05-06 code-health scan flagged this exact pattern
(`health_check.md` lines 525-555) and recommended replicating Gate 3's
narrowed-catch to gates 2/4/5/6. It hasn't shipped. The "consolidated
architectural fix" of 2026-05-02 fixed measurement geometry but left
silent-pass behavior intact. Combined with
`gate1_contribution_threshold=0.10` Sharpe (low bar) and
`universe_b_passed = > 0` (almost-anything bar), the gauntlet's net
selectivity is "candidate did not crash."

### 7. V/Q/A edges added net-zero signal and were merged anyway

`docs/Measurements/2026-05/vqa_edges_sustained_scores_2026_05_07.md` and
`forward_plan.md:252-269`: 6 new SimFin factor edges (~600+ LOC +
helpers + tests) were sequentially debugged across three sessions.
Final state: 2021 Sharpe **1.607 vs baseline 1.666 = -0.06 drag**,
framed as "within noise band". Verified ON 2021 ONLY. The 2022
bear-regime smoke that the doc itself names as the diagnostic test
("required before promoting default-on", line 265) hasn't been run.
The hand-tuned `sustained_score=0.3` parameter has had no grid search.
The integration surfaced 3 HIGH bugs (silent-zero ROIC for distressed
firms, bare-except in shared helper, status-stomp risk in 6
auto-register blocks) that were fixed in the same window. This is
being scored as "shipped" and entering the production weight table at
0.5 each (`config/alpha_settings.prod.json:38-44`). Best honest read:
6 edges shipped, 0 demonstrated alpha, 1 single-year smoke that is at
parity with baseline.

### 8. The Governor's learning loop produces non-determinism the team patches at the harness level instead of the architecture level

`scripts/run_isolated.py` snapshots and restores 4 files
(`data/governor/edges.yml`, `edge_weights.json`,
`regime_edge_performance.json`, `lifecycle_history.csv`) around every
backtest because `evaluate_lifecycle` and `evaluate_tiers` mutate
`edges.yml` at end-of-run, which the next run reads at start
(`health_check.md:40-50`). The "fix" papers over a structural design
bug: an autonomous lifecycle that writes back into upstream measurement
substrate is mathematically incompatible with reproducible measurement.
The harness is a measurement workaround; the architecture still mutates
state any production-equivalent run will inherit. The day the harness
is forgotten in some new entry-point, the ±1.4 Sharpe variance era
returns.

The deeper symptom: health_check now contains finding after finding
where the "fix" is "remember to call `--reset-governor`" or "wrap in
`lifecycle_readonly: true`" or "snapshot+restore." The autonomous
learning loop is being domesticated by manual ceremonies rather than
redesigned.

### 9. Production "ensemble" weights are hand-tuned numbers in a JSON file; the only learning component (MetaLearner) is a -0.4 to -0.6 Sharpe drag

- `config/alpha_settings.prod.json:32-58` — every edge weight is a
  hardcoded float (atr_breakout_v1: 2.5, momentum_edge_v1: 1.5, V/Q/A:
  0.5, etc.).
- `path1_revalidation_under_harness_2026_05.md:42-58` — under the
  harness, ML-on (`metalearner.enabled: true`) costs **-0.578 Sharpe**
  at cap=0.20, **-0.436 Sharpe** at cap=0.25. The +0.749 Sharpe lift
  previously cited from ML stacking was governor-drift coincidence.
- Result: every "ensemble combination" claim is a human tuning a JSON
  file. The narrative of "autonomous improvement" in CLAUDE.md is, in
  production, a no-op. The system has neither working learned weights
  nor working learned signal combinations.

### 10. Substantial dead/superseded code is checked into active engine packages, accumulating drift

Confirmed via `git ls-files`:

- `engines/engine_b_risk/risk_engine_bak.py` (752 LOC) — backup
  committed inside Engine B.
- `engines/engine_f_governance/system_governor.py` (653 LOC) — flagged
  in `health_check.md:207-213` as zero production importers; still
  tracked.
- `engines/engine_f_governance/evolution_controller.py` (387 LOC) —
  flagged in `health_check.md:157-163` as charter-violating + dead;
  still tracked.
- `engines/engine_e_regime/cross_asset_confirm.py` — empirical TPR=0;
  `health_check.md:465-493` recommends archive; still tracked.
- `engines/engine_a_alpha/not-yet_edges/` — directory of half-done work
  in an active engine.

Total ≥ 2400 LOC of dead-or-disabled code in *active* engine
namespaces, all of which the next code-health subagent will keep
flagging on every scan. CLAUDE.md says "Archive, never delete" — it
does not say "never archive either."

---

## Single biggest gap the team is not seeing

**You are doing extensive engineering rigor on the wrong substrate.**

The 109-ticker survivorship-biased modern-mega-cap universe + a
2021-2025 window that is partly used for tuning + a hand-curated weight
file + a celebrated "Foundation Gate PASS" of 1.296 mean Sharpe that is
one deterministic measurement (not 15 samples) — this is a system whose
entire performance signal is dominated by universe selection and
parameter tuning, not by any of the engineering work being done
downstream of it.

Concrete evidence the team has produced themselves but isn't acting on:

- Universe-B held-out at the same window: Sharpe collapsed
  1.063 → 0.225 (`health_check.md:85`).
- 2025 (the only quasi-OOS year): Sharpe 0.954 = SPY 0.955; CAGR 4.39%
  vs SPY ~13%.
- HMM regime layer empirically a coincident-vol detector with OOS AUC
  0.36.
- HRP, MetaLearner, and the autonomous discovery cycle all individually
  neutral or negative when measured under the harness.

Every workstream in `forward_plan.md` (Engine C HRP, Engine E HMM,
Feature Foundry, V/Q/A, Foundation completion) is being graded against
fluctuations inside this bias envelope. The next 6 months of work —
adding 50 features via Foundry, lifting ML modules from
`noterminusgit/statarb`, building Path C compounder — will all live or
die on the same biased substrate.

**The single highest-leverage move is to wire
`UniverseLoader.historical_constituents()` into the backtest path,
generate a price panel for the survivorship-aware S&P 500 across
2010-2025, freeze code, and rerun the multi-year measurement.** If the
1.296 Sharpe survives, you have a real foundation to build on. If it
doesn't, you've discovered before another 6 months of work that
everything downstream of the universe was measuring noise. Today, you
cannot tell which is the case — and nothing else on the roadmap can
change that.

---

## Things I could not verify

- Actual `data/governor/edges.yml` contents and current active-edge set
  — `data/` is gitignored and not in this checkout.
- Current `data/processed/` price panel content / freshness.
- Whether SimFin panel for V/Q/A edges has any unintentional
  point-in-time leakage (helper has a `publish_date <= asof_ts` filter
  at `_fundamentals_helpers.py:130, 161`, but I did not exercise the
  SimFin adapter itself).
- Whether the `2025 OOS` runs labeled in audits actually used
  end-of-2024 governor state vs. current governor state (the harness
  should isolate this, but the attestation is internal to the harness).
- Independence of trade fills across "reps" in the multi-year
  measurement beyond what the canon-md5 reproduction tells us.

If the team disagrees on any specific finding, the fastest
falsification is `grep` the cited line numbers — every claim has a
path/line attached.
