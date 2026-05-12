Here is the response with access to the codebase:

Pushed. Branch `claude/review-archondex-state-YQssU` is up. Now the actual review.



---



# External Review — ArchonDEX State (2026-05-07)



Four parallel audits run with file:line evidence. Brutal honesty as requested. The team self-falsifies; this is what's wrong, not what's good.



## 1. The single most important framing correction



**You don't have 6 surviving edges. You have 3 mechanically distinct alpha sources.**



Per `engines/engine_a_alpha/edges/_fundamentals_helpers.py:189` and the four V/Q/A edges (`value_earnings_yield_edge.py:48-99`, `value_book_to_market_edge.py:44-93`, `accruals_inv_sloan_edge.py:57-99`, `accruals_inv_asset_growth_edge.py:50-92`), all four call the same `top_quintile_long_signals` helper with identical defaults (`top_quantile=0.20, min_universe=30`) on the same SimFin-FREE-covered ~80-name subset. E/P ≈ B/P × ROE in expectation; Sloan accruals correlate with low-asset-growth via the same denominator. **This is one quintile-rank fundamental factor wrapped four ways.** Daily P&L correlation across the four is likely 0.4–0.7 pairwise; nothing in the codebase tracks inter-edge correlation (`grep cross_edge_correlation engines/` → zero hits).



The actual diversified set is: **1 cross-sectional fundamental factor + `gap_fill_v1` (overnight microstructure) + `volume_anomaly_v1` (volume z-score)**. And those four V/Q/A edges share a single point of failure: SimFin coverage. They go silent simultaneously. This is not the diversification the briefing implies.



## 2. The meta-cause of 6 falsifications in 6 weeks



**Substrate is not part of the validation contract.** The team validates against fixed cardinality (universe, governor anchor, feature horizon, n_trials) where the cardinality itself was the variable that broke the prior finding. F6 (1.296 → 0.507) was the obvious case. Two structural problems remain that will produce F7-F12:



- **No embargo / no purged k-fold / no CPCV.** Repo-wide grep for `purged|embargo|CPCV` returns zero hits. `engines/engine_d_discovery/wfo.py:98` is gapless (`test_start = full_timeline[train_end_idx]`, comment "gapless"). With features at 60-252 day horizons (`core/feature_foundry/features/realized_vol_60d.py:36`, `beta_252d.py`) and autocorrelated daily returns, the WFO leaks training-window state into the first ~60 test bars and inflates OOS Sharpe by exactly the autocorrelation-decay length of the active feature set. **Every Sharpe number from the 6-week falsification record was measured under no-embargo geometry.**

- **DSR multiple-testing correction is structurally OFF.** `engines/engine_d_discovery/discovery.py:708` defaults `n_trials_for_dsr=1`; `discovery.py:788` initializes `gate_8_passed=True` as SKIPPED. Orchestration never passes the actual GA candidate count. So Discovery cycles generate ~10-50 candidates and DSR sees `n=1` — the gate that's supposed to catch hunting in the haystack trivially passes.



If you fix nothing else this round, **fix these two**. Until they are *in the gate*, F7-F12 will be found by the next audit instead of by the harness.



## 3. Substrate-independent additions, ranked



Highest leverage first. Each is buildable today on existing code paths.



| # | Addition | Plug-in | Why first |

|---|---|---|---|

| 1 | Embargo in WFO + dynamic `n_trials_for_dsr` | `wfo.py:98` (insert ≥max-feature-horizon gap), `discovery.py:708` (read GA pop count) | Meta-fix for §2 above |

| 2 | Wire Feature Foundry into Discovery | `engine_d_discovery/feature_engineering.py:30-73` (replace hardcoded panel with `for feat in get_feature_registry()...`); add `"foundry"` gene type at `discovery.py:_create_random_gene` | `grep feature_foundry engines/ orchestration/` → zero hits today. Foundry is wired to dashboard + meta-learner only. Without this, all 24 features are invisible to the GA, and Engine D can't construct a V/Q/A-style genome (no fundamentals percentile operator in `discovery.py:402-416`) |

| 3 | Equity-drawdown kill switch | New `peak_equity` / `current_drawdown_pct` on `engine_c_portfolio/portfolio_engine.py::PortfolioEngine.snapshot()`; consumed at `engine_b_risk/risk_engine.py:760-775` to scale `advisory_risk_scalar` | `grep "kill_switch\|emergency\|halt" engines/` → zero hits. April-2025 incident (`health_check.md:83`) lost 122% of full-year P&L in one month with no circuit breaker. The system has no idea what its own drawdown is |

| 4 | Feature flight recorder + regression alarm | Extend `core/feature_foundry/model_card.py:74,169-178` from append-only ablation history to a watcher that fires on rolling-Sharpe regression past threshold; render in `cockpit/dashboard_v2/tabs/feature_foundry_tab.py` | The 6 falsifications were retrospective audits. None were triggered by an in-system alarm. Same pattern as the universe-loader (built 2026-04-24, never wired for 6 weeks) |

| 5 | Turn on Gates 7 + 8 in production cycles | `orchestration/mode_controller.py:1185-1191` — pass `data_map_substrate_b` and real `n_trials_for_dsr` | Discovery's substrate-transfer and DSR gates are dead code today. The two gates designed to catch substrate-bias false positives are off |



## 4. Defensive layer — concrete primitives



Ranked by expected-value-given-cost. The bear/chop Sharpe gap (2022 -0.508, 2025 -0.107) is more likely a sizing/leverage-asymmetry problem than a missing-alpha-source problem.



1. **Drawdown-gated kill switch.** Input is the system's own equity curve, structurally forward of any market signal. Rule: `if dd > 0.10: scaler *= 0.5; if dd > 0.15: scaler = 0`.

2. **Wire HYG-IG OAS spread (`BAMLH0A0HYM2 - BAMLC0A0CM`) into the HMM feature panel.** Already cached at `engines/data_manager/macro_data.py:102,105`. Currently unused. The strongest single leading indicator for equity drawdowns in the 2008/2020 record. Plug into `engine_e_regime/macro_features.py:40` `FEATURE_COLUMNS`. The archived `Archive/engine_e_regime/cross_asset_confirm.py:120` had the right primitive — it was thrown out with a bad gate.

3. **Asymmetric vol-target clamp.** `engines/engine_c_portfolio/policy.py:321` clamps to `[0.3, 2.0]` — i.e., **levers up when realized vol is low**. This is exactly the wrong asymmetry around regime transitions (Minsky). Replace with `ceiling = 1.0 if regime_summary in {stressed, crisis} else 2.0`.

4. **Regime-conditional `risk_per_trade_pct` scaler at `risk_engine.py:780`.** Inverse-vol scale: `risk_pct *= min(1.0, target_vol / realized_vol_60d)`. This is the missing inverse-vol-targeting at the trade level that Engine C does for weights but Engine B ignores on its ATR path.

5. **Marginal-correlation-to-book sizing tax in Engine B.** Plug at `risk_engine.py:780` before `risk_budget` calc: `risk_scaler *= (1 - max(0, rho_to_book))`. Replays April-2025 incident with the tax should drop the simultaneous correlated fills ≥40%.

6. **Concrete `TailHedgeSleeve` against `engines/engine_c_portfolio/sleeves/sleeve_base.py:80`** (which is explicitly an abstract design artifact). Sized off VIX9D/VIX3M backwardation. Fires before realized drawdown. Multi-sleeve aggregator goes at `policy.py:198`.



**My honest call:** items 1, 3, 4 likely recover most of the 2022/2025 Sharpe gap *without adding any new edge*. The bear/chop problem is being treated as an alpha problem when it is an oversize-during-elevated-vol problem.



## 5. Uncorrelated alpha — categories with zero exposure



Each below has either data already in the repo or features already computed but no consuming edge. Ranked by IR / build-cost ratio.



| Category | Evidence of orphaned data | New edge file |

|---|---|---|

| Calendar anomalies (turn-of-month, FOMC drift) | `engine_d_discovery/feature_engineering.py:197-256` already computes `DOW_Sin`, `Month_Sin`, `QEnd_Proximity`, `OpEx_Proximity` — no edge consumes | `engines/engine_a_alpha/edges/calendar_anomaly_edge.py` |

| COT positioning extremes | `core/feature_foundry/sources/cftc_cot.py:39-52` ingests for 12 ETFs; `core/feature_foundry/features/cot_commercial_net_long.py:64-73` derived. Zero edges consume | `engines/engine_a_alpha/edges/cot_positioning_edge.py` |

| Idiosyncratic-vol effect (Ang/Hodrick/Xing 2006) | None ingested but Foundry can produce it from existing OHLCV | `engines/engine_a_alpha/edges/idio_vol_edge.py` (long-only-neuter version) |

| Earnings-day vol crush | `earnings_proximity_5d.py` Foundry feature exists | `engines/engine_a_alpha/edges/earnings_overnight_edge.py` |

| 52-week-high momentum (George-Hwang 2004) | `dist_52w_high.py` Foundry feature exists | Goes into the moonshot sleeve, not the core book |

| VIX term structure | `engine_e_regime/macro_features.py:67-73` has it behind `include_vix_term=False` **default off** | Flip the default. Free signal, currently dark |

| Pairs / stat-arb | None — but the universe is in place | `engines/engine_a_alpha/edges/pair_zscore_edge.py` |



**Two pushbacks on framing:**



- "Engine D will autonomously discover the next edge with Bayesian opt." **No it won't.** The gene vocabulary at `discovery.py:402-416` lacks a fundamentals-percentile operator; threshold sets are coarsely discrete (e.g., `random.choice([-0.03, -0.01, 0.0, 0.01, 0.03])` at line 344); seed templates at `discovery.py:44-54` don't include the V/Q/A edges. The GA *cannot* construct a Fama-French-style genome from this gene set, regardless of optimizer. Bayesian opt over the same narrow space won't help. **Fix the vocabulary first** — wire the Foundry (item 3.2 above), add `top_percentile`/`bottom_percentile` operators on fundamentals.

- "Moonshot sleeve is parked until bones work." This is a deadlock if "bones working" depends on a defensive layer the surviving-6 lack. Goal C is architecturally independent. Start it in parallel — different universe (Russell 2000 / IPO), different gauntlet (Sortino + skewness + upside-capture, not Sharpe), different sizing (many small bets, trailing 50%-from-peak). It can't damage the core because it doesn't share capital allocation logic.



## 6. Top-1% patterns the codebase is missing



Cross-cutting things that would have caught the 6 falsifications earlier:



- **Purged k-fold CV / embargo / CPCV** (López de Prado 101) — see §2. Single biggest item in this entire review.

- **MLflow / W&B experiment tracker.** Cross-run state lives in (a) `--save-anchor` files, (b) `data/trade_logs/<run_id>/`, (c) memory files like `project_universe_aware_collapses_2026_05_09.md`. There is no queryable surface where every `(config_hash, universe_substrate, governor_anchor_md5, n_trials, Sharpe, PSR, DSR)` tuple lives. When 6 findings die in 6 weeks, the only way to compare them is hand-grep memory files. Add `core/observability/run_registry.py` with SQLite.

- **Ledoit-Wolf shrinkage covariance fed into position sizing.** Today LW is used for HRP weight construction at `engine_c_portfolio/optimizers/hrp.py:97-101` only. Engine B never reads a covariance matrix. Top-1% shops use it everywhere sizing happens.

- **CVaR / ES budgeting.** Zero hits for `cvar`, `expected_shortfall`, `var_quantile` in `engines/`.

- **Per-cluster risk budgets** — cluster-of-correlated names treated as one risk slot. Today `max_pos_value_pct=0.30` permits one name at 30% with no view on whether 3 other 20% positions are 0.9-correlated to it.

- **Stress-test sizing against historical scenarios at allocation time** (1987, 2008-Oct, 2020-Mar, 2022).

- **Liquidity-on-exit modeling.** ADV-on-entry is bucketed (Almgren-Chriss); exit ADV is not modeled. A position you sized at 1% of ADV might be 4% of ADV in stress.

- **Backtest leak-detection at the harness level.** `core/observability/leakage_detector.py:1-31,177` is static-AST-advisory on `@feature` functions only. It does not check the runtime backtest for index-misalignment, fwd-shifted columns in joins, or cache-warmth leakage across folds.



## 7. What I would cut



The codebase carries ~40 engine modules + 24 Foundry features + multiple sleeve abstractions for an alpha surface of 3 mechanically-distinct sources on equity-only. The ratio is wrong. Specific cuts:



- `engines/engine_d_discovery/synthetic_market.py` — synthetic regime generator. Bootstrap stream-resampler at `robustness.py:218` covers the same need with real returns.

- `engines/engine_e_regime/multires_hmm.py` separate from `hmm_classifier.py` — two HMM implementations + `transition_warning.py` + `advisory.py` is over-engineered for an output `forward_plan.md:98` records as "empirically coincident, not leading."

- `engines/engine_f_governance/evolution_controller.py` — health-check kept it active 2026-05-07 because it has 10 tests. But `discovery.py::validate_candidate` is the canonical WFO orchestrator. A test scaffold around an unused module is a god-class warning sign in waiting.

- The `learning/` directories inside both Engine A and Engine D — ML scaffolding ahead of demand. Prune to one trainer.



## 8. Boundary issues still open



- **`alpha_engine.py:61-63` imports `PortfolioComposer` from `engine_c_portfolio.composer`.** F4 fix moved HRP code into Engine C's package, but the *call site* at `alpha_engine.py:506,724,861` still lives in A. Charter says C.2 owns target-weight computation; A consumes signals only. Half-resolved.

- **`engines/engine_a_alpha/tier_classifier.py:83`** — sole production caller is `engine_f_governance/governor.py:627` which writes `tier`/`combination_role` to `edges.yml`. A lifecycle decision dressed as a forecast helper, in the wrong package.

- **F11 write-back smell is deeper than labeled.** Two distinct write paths into `data/governor/edges.yml` during a backtest: `governor.py:592` and `lifecycle_manager.py:289`. `run_isolated.py` had to grow a 4-file snapshot harness to bound this. Real fix is structural — write to a journal + apply at next-cycle boundary, not snapshot/restore around the smell.



## 9. Concrete pushbacks on the project's own narrative



1. **"Bear/chop edges fail" → likely a sizing problem, not an alpha problem.** §4 items 1, 3, 4 first. Adding new edges to recover bear regime before fixing inverse-vol-target asymmetry is solving the wrong layer.

2. **"Tax drag takes Sharpe to -0.577" → wash-sale gate measurement (`docs/Measurements/2026-05/wash_sale_multi_year_verification_2026_05.md:19-25`) shows 2021 Δ = -0.966 (gate ON HURT by ~1 Sharpe), 2025 Δ = +0.670.** The fix is regime-conditional gating, not deferral. Don't deploy in taxable on this stack until the gate is regime-aware. The current `wash_sale_avoidance.py:105-121` is myopic by the doc's own admission.

3. **"Six engines is the architecture."** The architecture as built is `Engine A produces edge votes → RiskEngine sizes per-ticker → PortfolioEngine books fills`. Engine C activation 2026-05-09 was a partial fix; Engine E is empirically dead; Engine D promoted zero edges. You have 3 active engines + 3 scaffolds. Before adding to the scaffolds, finish the active three.

4. **Engine D's 0 promoted edges is not a Bayesian-opt problem.** It's a vocabulary problem. The Foundry is orphaned (zero hits in `engines/`); gene operators don't include cross-sectional fundamentals percentiles; thresholds are discrete. A different optimizer over the same narrow space produces the same zero promotions.



## 10. The single highest-leverage move



**Wire embargo into `wfo.py:98` and dynamic `n_trials_for_dsr` at `discovery.py:708`. Then re-run the surviving-6 multi-year measurement under those gates.**



If 4 of 6 fail under 252-day embargo + DSR with real n_trials, the alpha surface is even smaller than thought — and you've just saved months of Sharpe-chasing on edges that aren't real. If they survive, the team finally has a Sharpe number that won't get falsified next month. Either outcome compounds. Every other recommendation in this review is downstream of having a measurement geometry that doesn't optimistically inflate by feature-autocorrelation length.



Notes appended to `docs/State/health_check.md` (4 findings, committed `7291cae`, pushed). Branch on `claude/review-archondex-state-YQssU`.



