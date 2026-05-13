# Forward Plan — live (last substantive update 2026-05-12, canonical baseline shifts 0.270 → 0.598)

> **2026-05-12 — CANONICAL SUBSTRATE-HONEST BASELINE CORRECTED: 0.270 → 0.598 (+0.328). T-002's reading was contaminated by the cockpit metrics-pipeline bug, BI-DIRECTIONALLY (winning years inflated AS WELL AS losing years zeroed).**
>
> T-2026-05-12-034 fixed the bug (`cockpit/logger.py` field-count alignment + `cockpit/metrics.py` fail-loud assert). T-2026-05-12-035 re-measured T-002 Arm 1 with the fix applied — single-arm, identical grid (6 active edges × 5 years × 3 reps × F6 historical S&P 500 union).
>
> ### What the bug was actually doing
>
> The pre-T-034 writer emitted 11 fields against a 9-column header, causing `pandas.read_csv` to mis-align column positions. The `peak_equity` series (monotone non-decreasing — only ratchets upward) landed in the `equity` slot.
>
> - **Winning years**: peak_equity has lower variance than real equity (real equity dips during intra-year drawdowns; peak doesn't). Reading peak-as-equity systematically inflated Sharpe. 2021 was 0.413 reported → **1.791 corrected** (+1.378).
> - **Losing years**: peak_equity stays glued at the starting capital while real equity falls; the metric read like flat equity → Sharpe ≈ 0. 2024 was 0.236 reported → **-0.613 corrected** (-0.849).
>
> My pre-T-035 prediction "the bug barely fires in small-MDD cells" was **WRONG**. The contamination was bi-directional and present in BOTH winning and losing cells.
>
> ### Corrected canonical baseline
>
> | Year | T-002 reported | T-035 corrected | Δ | T-035 ci_low |
> |------|----------------|-----------------|---|--------------|
> | 2021 | 0.413 | 1.791 | +1.378 | 0.014 |
> | 2022 | 0.116 | 0.294 | +0.178 | -2.220 |
> | 2023 | 0.261 | 1.221 | +0.960 | -0.788 |
> | 2024 | 0.236 | **-0.613** | -0.849 | -2.437 |
> | 2025 | 0.325 | 0.297 | -0.028 | -1.323 |
> | **mean** | **0.270** | **0.598** | **+0.328** | — |
>
> Per CLAUDE.md 6th non-negotiable: `ci_low` is the gate-relevant number, not `point_estimate`. **No single year clears `ci_low > 0`** even at the corrected level. The honest read is: mean 0.598 is BETTER than 0.270, but the strategy is **bull-conditional with material 2024-style downside** — 2024's -0.613 was previously hidden by the bug.
>
> ### What this changes vs the 2026-05-11 entry below
>
> 1. **The 0.270 comparison-point in the engines-first directive becomes 0.598.** Every "did this engine-completion deliver projected +0.55 to +1.25 lift" comparison gets re-anchored. The structural review still holds (engines C/D/E are still scaffolding); only the comparison number shifts.
> 2. **All prior bear-year Sharpe-bearing audits remain SUSPECT** until re-measured: T-002 Arm 2, T-019 paused-tier-inert, T-029 per-regime decomp, T-020 per-edge isolation, F6 multi-year, STR T-030. T-2026-05-12-036 (in flight) takes the highest-priority subset (STR + per-regime adverse cells). Remaining queued.
> 3. **The "8-falsification pattern" framing in lessons_learned needs nuancing**: at least 1 of those 8 falsifications (T-002 Arm 1 → 0.270) was partly an artifact of the cockpit bug, not pure substrate-honesty improvement. The lesson "every time measurement gets more honest, apparent alpha shrinks" still holds for substrate/universe changes; it does NOT hold cleanly for T-002 → T-035 (where the substrate didn't change; only the metric reader did).
> 4. **2024 regime fragility is now load-bearing.** The corrected -0.613 means our 6-edge active set has real failure modes in regimes resembling 2024 (rising-rates-late-bull-into-soft-Q4 — your eye for the pattern is correct). Engine E regime work + Engine B regime-conditional de-grossing remain on hold per engines-first directive, but the BUSINESS case for them just strengthened.
>
> ### What stays on hold (unchanged from 2026-05-11)
>
> - Engine B portfolio vol-targeting (still gated on factor-significant alpha)
> - Engine D gene-encoding extension and Gate 1 caching remain the next structural fixes
> - Moonshot Sleeve, AI layer — still parked per engines-first directive
>
> ### T-036 landed (post-T-035 update) — per-regime verdict gets HARSHER, not gentler
>
> T-036 Part A: STR mean Sharpe 0.281 → **0.999** (+0.718). Strong bull-conditional profile, 2022 -0.556 corrected. STR is genuinely stronger than T-030 indicated.
>
> T-036 Part B: per-regime factor decomp regenerated on 7 cockpit-fixed edges. **Verdict-bucket shifts (11-edge panel)**:
> - UNIFORMLY NEGATIVE: 5 → **7** (+2: `volume_anomaly_v1` and `gap_fill_v1` both promoted from NOISY)
> - UNIFORMLY NOISY: 3 → 1 (STR holds)
> - UNIFORMLY POSITIVE: 1 (`dividend_initiation_drift_v1` only — currently paused-inert per T-019)
> - INSUFFICIENT DATA: 1 (pairs_MA_V)
>
> **Critical: my 2026-05-12 morning "2024 attribution dive" audit (commit d1ed01f) labeled `volume_anomaly_v1` and `gap_fill_v1` as "winners" based on +$4,527 and +$3,410 of 5-year realized dollar PnL.** T-036 reveals both are UNIFORMLY NEGATIVE on factor-adjusted α — their positive dollar PnL is Mkt+Mom factor beta exposure, NOT idiosyncratic alpha. They're worse than a passive factor replication would be. The audit was updated with this caveat 2026-05-12 evening.
>
> **What this means structurally**: 0/6 active edges have positive factor-adjusted α at t > 2. **Most are SIGNIFICANTLY NEGATIVE**, not merely noisy. T-004's finding now strengthens to "the system has no idiosyncratic alpha at the active-edge level; observed Sharpe is factor-exposure." The 0.598 corrected baseline is real Sharpe-of-the-strategy, but it's beta-driven, not alpha-driven.
>
> **Forward implications**:
> 1. T-043 candidate spec (Engine F lifecycle re-evaluation) needs broader scope: re-run retirement evaluation with BOTH corrected dollar Sharpes AND T-036's factor-adjusted-α verdicts as inputs. All 6 actives fail on factor α; the question is what Engine F's retirement gate uses.
> 2. `dividend_initiation_drift_v1` is the only UNIFORMLY POSITIVE edge in the 11-edge panel. Currently inert (zero trades over 5 years per T-019). Worth gauntlet-promoting to test whether the factor-positive verdict survives at active-tier capital allocation. Could be a T-044 candidate.
> 3. T-041 (spin-offs spec) just got more important — spin-off anomaly is structurally NON-factor (driven by forced institutional selling, not Mkt/Mom/Value). The whole point of retail-only edges is to find α that doesn't load on the FF5 factor model.
> 4. Engine D Discovery (Bayesian opt scaffolding shipped T-028a; T-038 attempted Discovery cycle BLOCKED at 4.8 hr / no emission per B's outbox) becomes the highest-leverage discovery vehicle — Gate 6 explicitly filters for factor-adjusted α at t > 2, which is exactly the gap.
>
> ### What was just dispatched (waiting)
>
> - T-036 Part A + B (COMPLETE, merged 0730be3)
> - B's T-038 (Discovery cycle re-run): BLOCKED at 4.8 hr / no Discovery emission. Last log line at lifecycle phase post-backtest. B's diagnosis: first-ever `seed_from_foundry` runs expensive feature compute. B recommends Option C (profile + targeted vectorize fix, ~5 hr). Awaiting user direction.
>
> ### What got drafted today (specs, not yet dispatched)
>
> 1. **T-039** observability layer relocation (`cockpit/logger.py` + `cockpit/metrics.py` → `core/observability/`) — propose-first
> 2. **T-040** trade-log storage migration (CSV → Parquet + retention + DuckDB query layer) — propose-first
> 3. **T-041** spin-off reversion edge (Engine A; first retail-only structural edge) — Engine A autonomous-improvement scope but drafted for visibility
> 4. **T-042** Engine D input-library expansion (insider audit + short interest + GDELT regime feed) — propose-first
>
> ---

> **2026-05-11 EARLY — EDGE EXPANSION GAUNTLET HAS TWO STRUCTURAL BLOCKERS. T-020 + T-021 together define the next-step priority.**
>
> T-2026-05-10-020 (per-edge isolation diagnostic) and T-2026-05-10-021 (first-ever Discovery cycle on substrate-honest) landed in parallel and answer the strategic question definitively.
>
> ### Finding 1: 0/11 edges clear the FF5+Mom t > 2 gate on substrate-honest
>
> - **T-004 (May 9):** 0/6 active edges have positive factor-adjusted α at t > 2
> - **T-020 (May 10):** 0/5 NEW paused edges clear t > 2 either, despite 5/5 generating trades at full isolation weight (raw Sharpe 0.28-0.45). Max α t-stat: 1.76 on `short_term_reversal_v1`.
> - **Combined: 0 of 11 edges tested produce idiosyncratic alpha at t > 2.** Raw Sharpe is Mkt + Mom factor exposure.
> - Closest-miss watchlist: `short_term_reversal_v1` (t=+1.76 with a suspicious 2022 zero-Sharpe cell worth 2-3 rep re-measurement), `pairs_trading_MA_V_v1` (α point +18%, t=1.41 limited by n=167 trades; expanding pairs inventory tightens the t-stat).
>
> ### Finding 2: Discovery's gene encoding is single-archetype
>
> - T-021's 3 candidates were ALL `rsi_bounce_v1` mutations. The post-T-006 Foundry features + post-T-014 calendar features are **invisible to Discovery's gene encoding**.
> - Gate 1 (Sharpe-contribution-to-ensemble) killed 3/3 candidates: raw Sharpe 0.54-0.72 but marginal ensemble contribution < 0.1 threshold. Same dynamic as T-019.
> - Per-candidate wall-time: 3,240-6,689 sec (Gate 1 runs full ModeController backtest). Cap=30 → 37+ hr. **Cap=30 is infeasible without Gate 1 caching.**
>
> ### The reframed next-step priority
>
> The dev review's projected +0.1 to +0.3 Sharpe from "5-10 new uncorrelated edges that survive gauntlet" is at risk because:
> 1. **Hand-written edges** don't survive Gate 6 (FF5+Mom t > 2) — universal pattern across all 11 edges tested
> 2. **Discovery-generated candidates** don't even reach Gate 6 — gene encoding can't emit candidates from the expanded vocabulary; all candidates are rsi_bounce_v1 variants
> 3. **Gate 1 wall-time** makes Discovery cycles intractable at cap=30 without caching
>
> ### The directive sharpens twice
>
> #### Primary structural fix: Engine D gene-encoding extension
>
> Engine D's GA emits candidates from a narrow gene encoding (technical indicators only — RSI/MACD/ATR/Bollinger). The Foundry features T-006 added (mom_12_1, mom_6_1, vol_regime_5_60, ma_cross_50_200, dist_52w_high, drawdown_60d, hyg_lqd_spread, dxy_change_20d, calendar/regime/macro features) and the calendar features T-014 added (FOMC drift, sell-in-May, pre-holiday, January effect, Santa Claus, triple-witching, tax-loss season) are NOT REACHABLE by the GA's gene encoding. **Vocabulary expansion delivered zero benefit to Discovery's candidate-search; gene encoding is the gating constraint.**
>
> This is now the highest-leverage Engine D work. Next dispatch (T-022 or similar) should extend gene encoding to emit candidates that consume the expanded vocabulary. Without this, every additional Foundry feature is invisible to autonomous discovery.
>
> #### Secondary structural fix: Gate 1 caching (cached signal-collector replay)
>
> Each candidate runs a full ModeController backtest in Gate 1 to compute Sharpe-contribution-to-ensemble. A signal-collector cache (compute the active-ensemble signal stream ONCE per (universe, window), then for each candidate just replay the candidate's contribution layered on top) would deliver 10-50× speedup per B's estimate. Makes cap=30+ Discovery runs tractable in 6-8 hr instead of 37+ hr.
>
> #### Threshold reconsideration (lower-priority, director-side)
>
> If 0/11 edges clear FF5+Mom t > 2 on substrate-honest, the threshold may be inherently incompatible with the retail-scale substrate-honest universe. **NOT goalpost-moving** because no Sharpe-claiming decision is being made — it's a threshold-calibration question. Worth ~2-3 hr director analysis to compare against e.g. SPY's own factor-adjusted alpha on the same window, or to check whether the bar was originally calibrated against institutional substrates.
>
> ### What stays on hold
>
> - **Engine B portfolio vol-targeting** stays on hold. Multiplying selection-dominant alpha that has no factor-adjusted significance lifts nothing.
> - **More edge expansion in isolation** — adding more hand-written edges that fail the same t > 2 gate adds zero. STR re-measurement + pairs MA/V inventory expansion (~6 hr combined) are the only edge-track follow-ups worth doing in the closest-miss territory.
> - **Moonshot Sleeve, AI layer** — still parked per engines-first directive.
>
> ### Today's session ledger (continued, 2026-05-11)
>
> Merged + pushed since the 2026-05-10 entry below:
> - T-020 per-edge isolation diagnostic (5/5 keep-paused; pairs MA/V + STR flagged as closest-miss for follow-up)
> - T-021 Discovery cycle on substrate-honest (3 candidates, 100% Gate 1 kill, GA single-archetype)
>
> Surfaces for user attention:
> - B recommends `python -m scripts.run_isolated --save-anchor` after T-020 merges so the `isolated()` stale-anchor edges.yml workaround isn't needed for future measurements. Propose-first per CLAUDE.md governor rule.
> - Disk-fill incident at cell 14/25 in T-020 grid (ENOSPC) — accumulated trade_logs across worktrees. Recovery succeeded via incremental persistence. Going forward: **each agent worktree's `data/trade_logs/` needs hygienic cleanup at session end** to avoid surprise disk-exhaustion. Adding to lessons.
>
> ---

> **2026-05-10 — PAUSED-TIER PARKING IS INERT. Lifecycle promotion via Discovery's substrate-honest gauntlet is THE lift mechanism for edge expansion.**
>
> T-2026-05-10-019 ran the full two-arm substrate-honest measurement on post-edge-expansion main HEAD. **Result: Δ Sharpe = 0.0000 in BOTH arms vs T-002. Bit-identical canon md5s in 15/15 cells per arm.** The 5 new paused edges added 2026-05-09 (T-014 calendar features, T-016 momentum × 3, T-017 pairs_trading_MA_V, T-018 dividend_initiation_drift_v1) contributed **zero trades** over the full 5-year substrate-honest window — while pre-existing `news_sentiment_edge_v1` at the same 0.25× soft-pause weight produced 451 trades, confirming the infrastructure isn't the filter.
>
> **The mechanism:** paused-tier edges in inventory can be loaded into the alpha pipeline at 0.25× but they only contribute when their signals beat the active-edge ensemble's threshold. New edges with sparse signal density (dividend-initiation, lookback-constrained momentum, single-pair statistical arbitrage) lose to 6 actives producing thousands of trades. Soft-pause provides "post-pause revival evidence" capability — NOT a path to alpha contribution while still paused.
>
> **The path to lift is lifecycle PROMOTION through Discovery's substrate-honest gauntlet** (Phase 2.10 + Gates 7/8 wired 2026-05-07). Edges must clear the 8-gate evaluation to reach `status='active'` where they get full weight. Once active, they trade competitively with the existing 6.
>
> ### Bonus signal: T-013 vectorization landed real
>
> T-019 ran 30 backtests in ~50 min wall, vs T-002's ~10 hr for the same 30 backtests. **~12× speedup** from the Foundry feature loop vectorization that B shipped 2026-05-09 (commit `e141161`). This is reproducible engineering value that survives substrate-honest measurement. Multi-year measurement cycles are now materially cheaper.
>
> ## Updated next-step priority
>
> Per the engines-first directive (`docs/Sessions/Other-dev-opinion/05-09-26.md`) PLUS today's T-019 evidence, the directive sharpens:
>
> 1. **Discovery cycle on substrate-honest data** — the gauntlet's job is to validate which paused edges (T-016 momentum, T-017 MA/V pair, T-018 dividend init, T-014 features) deserve promotion to `status='active'`. Without this, today's edge inventory stays inert. **First post-consolidation dispatch.**
> 2. **Engine D Bayesian opt swap** (per dev review) — replaces GA with Bayesian opt over the now-expanded Foundry vocabulary. More likely to find candidates GA missed. Engine D autonomy lane.
> 3. **Engine completion track** — Engine B vol-targeting STAYS ON HOLD per A's T-003 evidence (selection-dominant alpha that has no factor-adjusted significance). Multiplying noise gives noise. Re-evaluate after Discovery cycle.
> 4. **More edge expansion** — DEFER unless/until Discovery cycle proves the existing inventory has gauntlet-clearing potential. Adding more paused inventory adds nothing.
>
> ## Today's session ledger (continued, 2026-05-10)
>
> Merged + pushed since the 2026-05-09 evening entry below:
> - T-018 dividend_initiation_drift_v1 (buyback scoped out — no data source)
> - T-017 pairs trading (1/12 cointegrate, MA/V only survivor)
> - T-003 concentration-equivalent test (SELECTION-DOMINANT verdict)
> - statsmodels==0.14.6 dependency add (USER-APPROVED)
> - **T-019 substrate-honest post-edge-expansion (Δ Sharpe 0.0000)**
>
> Plus the Engine B portfolio vol-targeting spec drafted but UN-DISPATCHED (committed `2e51389`, awaiting engine-completion-track re-evaluation post-Discovery).
>
> ---

> **2026-05-09 EVENING — STRUCTURAL REVIEW COMPLETE. Engines-first directive anchored.** (Still load-bearing; below remains valid context for the engines-first reframe.)
>
> Today produced two big empirical landings + a strategic correction from the dev review (`docs/Sessions/Other-dev-opinion/05-09-26.md`). The corrected framing supersedes everything below.
>
> **The empirical state, honestly stated:**
>
> | Measurement | Sharpe (point) | Sharpe ci_low | Status |
> |---|---:|---:|---|
> | Foundation Gate (Round 1, static-39) | 1.296 | n/a (pre-CI rule) | KNOWN ARTIFACT (universe bias) |
> | Universe-aware F6 (static-115, 9 actives) | 0.5074 | n/a | UPPER BOUND (missing-CSV gap) |
> | C-collapses-1 surviving-6 (static-115) | 0.9154 | n/a | **RETRACTED** — almost certainly contaminated by 2026-05-07 zero-trade regression bug |
> | **Substrate-honest two-arm Arm 1 (T-002, May 9)** | **0.270** | **−0.383** | **HONEST BASELINE** — bootstrap CI includes zero |
> | T-004 factor decomp on per-edge streams | n/a | n/a | **0/6 edges have positive factor-adjusted α at t > 2.** 4/6 actively destroy value vs factor ETFs (t between −2.6 and −5.7). |
>
> The 1.296 → 0.5074 → 0.9154 → 0.270 sequence is the project converging on its actual signal as measurement geometry got more honest. The 0.9154 was the contamination ghost from a single-bug-class. Substrate-honest 0.270 with `ci_low = −0.383` is the honest read.
>
> **The kill thesis (pre-commit: 2025 OOS Sharpe < 0.4 net) is unambiguously triggered. Don't move goalposts.** But "kill thesis triggered" doesn't mean "abandon project" — per pre-commit it means "stop forward feature work and run structural review." That structural review is now complete. Its conclusion:
>
> ## The structural review's verdict — engine completion is the load-bearing gap
>
> **The full architecture has never operated.** Current production: edges → linear weighted-sum → fixed-fraction sizing → simple position management. Engines C/D/E are scaffolding more than operational layers. **Of course substrate-honest measurement shows weak alpha — most of the architecture isn't allowed to do anything yet.**
>
> Per-engine state (per dev review):
>
> | Engine | What's shipped | What's genuinely missing |
> |---|---|---|
> | A — Alpha | F4 inversion closed; signal_processor refactored | Continuous probability outputs (most edges still binary); explicit edge-horizon metadata; multi-timeframe primitives; orthogonality enforcement |
> | B — Risk | Asymmetric vol-target clamp; drawdown kill switch (INERT — wired but flag-OFF); 8 bare-except sites narrowed (incl. T-012 today) | **Fixed-fraction `risk_per_trade_pct: 0.025`. No portfolio-level vol-targeting. No correlation-aware sizing. No GARCH/HAR-RV vol forecasting. No event-risk auto-reduction. Drawdown kill switch sits inert.** |
> | C — Portfolio | HRP optimizer (default OFF, slices 1-3 falsified at small edge count); turnover penalty | **No mean-variance with Ledoit-Wolf shrinkage. No risk parity. No capital efficiency layer. No multi-asset scaffolding active. No tax-aware rebalancing.** |
> | D — Discovery | Vocabulary fix (Foundry wire + fundamentals-percentile); 25× speedup on Foundry loop | **Still genetic algorithm. Bayesian opt not shipped. Symbolic regression not shipped. Causal discovery not shipped. ZERO promoted edges in project history.** |
> | E — Regime | Variant C HMM passes leading-AUC | **Default OFF. Not driving a single sizing decision in production.** |
> | F — Governance | Lifecycle journal Phase 1+2 shipped; three-layer architecture | Mode-of-operation switching not done. Pre-mortem capability not done. |
>
> ## The directive going forward
>
> Three parallel tracks, all gated on engine completion before Moonshot/AI:
>
> ### 1. Engine completion track (load-bearing)
> - Engine B (propose-first per CLAUDE.md): portfolio-level vol-targeting, correlation-aware sizing, GARCH/HAR-RV vol forecast, drawdown kill switch wire from INERT, event-risk auto-reduction.
> - Engine C: MV with Ledoit-Wolf shrinkage as alternative to HRP, capital efficiency layer (gross scales with meta-learner confidence), real turnover-vs-alpha tradeoff.
> - Engine D: Bayesian opt replacing GA (now possible post-vocab-fix), first autonomously-discovered edge through gauntlet, multi-method alpha agreement requirement.
> - Engine E: Variant C HMM enable A/B (it's already validated; flip the flag), wire HMM into Engine B for regime-conditional sizing, multi-resolution + transition-warning enable.
> - Engine F: mode-of-operation switching, pre-mortem capability.
>
> ### 2. Edge expansion track (parallel, substrate-independent)
> ~30 missing edges + 12 defensive primitives haven't been built. Add 5-10 per work-week. Foundry pipeline supports cheap addition. Priority order:
> 1. Calendar anomaly battery (FOMC drift, sell-in-May, pre-holiday, January effect, Santa Claus, triple-witching, tax-loss season) — single file, 6+ features, persistent for 30+ years
> 2. Pairs trading (10-15 cointegrated pairs: KO/PEP, MA/V, MCD/QSR, HD/LOW, CVX/XOM) — uncorrelated by construction
> 3. Buyback / dividend-initiation drift — well-documented event drift
> 4. Cross-sectional momentum AS edges (12-1, 6-1) — currently exist as features only
> 5. Volatility risk premium (sell SPY weekly puts when IV >> RV)
> 6. Russell rebalance front-running — known schedule
>
> ### 3. Defensive layer track (parallel, partly Engine B)
> - Real tail hedge sleeve (long 30-delta SPY puts rolled monthly)
> - Drawdown-conditional gross reduction (wire Engine B's INERT kill switch)
> - Vol-targeting in Engine B
> - Dynamic hedge-asset auto-discovery
> - Event-risk auto-reduction (pre-FOMC, pre-CPI, pre-NFP)
> - CVaR / Expected Shortfall budgeting
> - Per-cluster risk budgets
>
> ## Re-measure gate (3-6 months out)
>
> After engines + defensive layer + 5-10 new edges:
> - Re-run substrate-honest multi-year under engines-complete geometry
> - Bootstrap CI on every metric (per CLAUDE.md 6th non-negotiable)
> - Pre-commit CI-aware kill threshold for THIS gate
> - Result vs 0.270 baseline tells us whether engine completion delivered the projected +0.55 to +1.25 lift
> - THEN evaluate Moonshot Sleeve, AI layer
>
> ## What's parked until re-measure clears
>
> - **Goal C / Moonshot Sleeve.** Same logic as parking AI layer. Building Moonshot on incomplete engines produces another inconclusive verdict (already saw this with Phase 0 trend + LEAPS). Park.
> - **Sharpe-claiming experiments.** No new headline-Sharpe claims until structural review's re-measure gate. Engineering work continues; alpha measurement pauses.
> - **DSR / PSR-claiming as headline.** Same reason.
>
> ## Why this baseline (0.270) is more useful than it looks
>
> It's the comparison point for whether each engine's completion delivers alpha lift. Without 0.270 honestly established, "did Engine B vol-targeting actually help?" has no answer. Each engine's A/B can now be measured against this number. **That's more rigorous than the previous celebrate-then-discover-it-was-an-artifact cycle.**
>
> ## Capability re-estimate
>
> Per dev review:
> - Engineering quality: top 1-2% retail
> - Discipline / falsification: top 1% retail (8-falsification record)
> - Alpha verification: materially weaker than thought; CI includes zero
> - Composite: ~55% honest current state, ~75-80% reachable in 3-6 months of disciplined engine work, ~85-90% reachable after Moonshot + LLM layer added on completed bones.
>
> ## Today's session ledger (2026-05-09)
>
> Merged + pushed:
> - T-002 substrate-honest two-arm (Arm 1 collapsed, Arm 2 neutral, kill thesis HOT)
> - T-004 factor decomp (load-bearing alpha falsified post-FF5+Mom)
> - T-005 backtest_controller narrow-except
> - T-006 Engine D vocabulary expansion (+24 Foundry columns)
> - T-007 diversified-futures trend (FALSIFIED — R2's primary recommendation)
> - T-010 in-code Sharpe gates CI-aware (Engine F + Engine D)
> - T-011 Engine A bare-except batch (7 sites)
> - T-012 Engine B drawdown-halt narrow-except (kill-switch defeat closure)
> - T-013 Engine D Foundry loop vectorization (25.5× speedup, canon md5 invariant)
> - Cloud parallel-substrate infra (Phase 1-6 verified end-to-end)
> - CLAUDE.md 6th non-negotiable (bootstrap CI + CI-aware kill thresholds)
>
> **9 substantive merges + cloud infra + discipline rule + spec drafts in one day. The engineering ratchet moved forward; the alpha measurement landed honestly weaker; the strategic reframe corrected the next-quarter path.**
>
> ---

> **2026-05-08 — DEV REVIEW CORRECTIONS TO TIER LIST + DISPATCHED PIPELINE STATUS** (now superseded by the 2026-05-09 evening structural-review reframe above)
>
> The director (this session) drafted a tier list during the substrate-honest re-measurement spec discussion. A dev review surfaced 3 real gaps that this update closes:
>
> 1. **Trend-sleeve framing was wrong.** The director's tier list said "reframe trend sleeve as Sharpe vehicle / add stop-loss / drop sleeve". That conflates **equity-trend** (which was tested and falsified twice — 115-ticker and 722-ticker) with **diversified-futures trend** (R2's actual primary recommendation, never tested). The two are structurally different bets with different academic literature (AQR / Hurst-Ooi / Moskowitz). **Diversified-futures trend on a TLT/GLD/USO/UUP/EEM/SPY/IEF/DBC basket is now T-2026-05-08-007**, spec at `docs/Measurements/2026-05/spec_diversified_futures_trend_2026_05_08.md`. Includes data acquisition for the 5 missing ETFs (USO/UUP/EEM/IEF/DBC).
>
> 2. **Engine D vocabulary fix was missing.** R1's pushback on Bayesian-opt-replaces-GA: *"a different optimizer over the same narrow space won't help."* Engine D's current Discovery vocabulary is technical-only (RSI/ATR/Bollinger/MACD/momentum-ROC). Foundry features and fundamentals-percentile-rank operators are absent — Discovery can't reach them. **T-2026-05-08-006 ships the vocabulary expansion** as a prerequisite to any Bayesian opt swap. Spec at `docs/Measurements/2026-05/spec_engine_d_vocabulary_fix_2026_05_08.md`.
>
> 3. **Bootstrap CI is tooling, not discipline.** `MetricsEngine.bootstrap_distribution` shipped 2026-05-07 and is wired into `performance_summary.json`. But "every Sharpe reports CI" should become a non-negotiable rule alongside "deterministic measurement always." Currently it's just available, not required. Going further: **kill thresholds going forward should be CI-aware, not point-estimate.** The current kill thesis (`Sharpe < 0.4`) is point-estimate; `CI lower bound < 0.3` (or similar) prevents implicit goalpost-moving. **Both are being added to CLAUDE.md as the 6th non-negotiable rule** in T-2026-05-08-009.
>
> Other tier-list items the dev review surfaced as "tracked but invisible" — adding them explicitly:
>
> - **Auto-feature engineering via tsfresh** — Tier 3. Could 10x feature count overnight; substrate-independent.
> - **Capacity testing infrastructure** — Tier 4 (deferred until live deployment is closer). Both reviewers flagged; explicit now rather than silently absent.
>
> ## Currently dispatched (2026-05-08)
>
> | Task-ID | Agent | Description | Spec |
> |---|---|---|---|
> | T-2026-05-08-002 | A | Substrate-honest re-measurement (Arm 1 + Arm 2; 7-11 hr) | `docs/Measurements/2026-05/spec_substrate_honest_remeasurement_2026_05_08.md` |
> | T-2026-05-08-005 | B | Tighten `backtest_controller.py:389` bare-except (2-3 hr) | inline brief in B's inbox |
>
> ## Dispatch-ready, queued for next agent free
>
> - T-006: Engine D vocabulary fix (Foundry + fundamentals-percentile)
> - T-007: Diversified-futures trend test (data acq + measurement)
> - T-003: C-collapses-1.5 concentration-equivalent (post-process Arm 1)
> - T-004: C-collapses-1.25 factor decomp (Arm 1 trade log)
> - T-008: Forward-plan revision (this update — director task)
> - T-009: CLAUDE.md discipline rule promotion (director task)

> **2026-05-09 NIGHT — C-engines-1 RETURNED + CORRECTION TO ENGINE-C NARRATIVE.**
>
> The C-engines-1 dispatch (commit `cae2002`, merged + pushed) closed F4
> charter inversion: HRPOptimizer + TurnoverPenalty moved out of
> `engines/engine_a_alpha/signal_processor.py` into a new
> `engines/engine_c_portfolio/composer.py`. signal_processor LOC dropped
> 715 → 522 (−193 / −27%). Charter check (`grep -rn
> "HRPOptimizer\|TurnoverPenalty" engines/engine_a_alpha/`) returns zero
> hits — was 7 hits pre-fix.
>
> **But the dispatch's premise was empirically wrong.** The brief asserted
> Engine C's `compute_target_allocations` was "defined but never called in
> the backtest loop." The agent verified that
> `backtester/backtest_controller.py:508` was already calling
> `self.portfolio.compute_target_allocations(...)` and threading the result
> into `risk.prepare_order(target_weights=...)`. **Engine C.2 was active
> all along.**
>
> **The correction:** the substrate-honest 0.5074 (B1's 9-edge mean) and
> 0.9154 (C-collapses-1's 6-edge surviving) results were measured on a
> system with Engine C.2 active — not on a "system without portfolio
> management" as the previous framing implied. Engine completion's
> expected lift from the remaining engine drift (Engine A's
> EDGE_CATEGORY_MAP import; Engine B's per-trade-only vol-targeting;
> Engine D's 0 promoted edges; Engine E's coincident HMM) is more measured
> than originally framed.
>
> **What this does NOT change:**
>
> - The kill thesis trigger HOLDS. The 2025 OOS criterion (< 0.4 net of
>   all costs) was net-of-tax negative on the 9-edge run and is even worse
>   on the 6-edge surviving set (2025 = −0.107 pre-tax). Engine C
>   activation status doesn't unwind that.
> - The structural review = engine completion direction is unchanged. The
>   remaining 4-of-6 engine charter drift is real (just not as headline-
>   severe as the inventory claimed).
> - The 6-names hypothesis remains refuted three independent ways.
>
> **Determinism caveat from the agent:** the C-engines-1 worktree had
> incomplete governor state, so the dispatch's 3-rep determinism check
> ran on zero-trade backtests (canon md5 bitwise-identical, but Sharpes
> all 0.0). Recommended follow-on: re-run determinism harness on main
> (post-merge) with full governor state to verify the relocated HRP code
> is still bitwise-equivalent to the in-place version under a non-
> degenerate path.
>
> **Updated dispatch sequence (Engine C done; remaining engines):**
>
> ```
> ✓ C-engines-1   (Engine C — F4 closure, HRP/Turnover relocated; cae2002)
>   C-engines-3   (Engine E minimal-HMM — ELEVATED priority per
>                  C-collapses-1's regime-conditional finding)
>   C-engines-5   (Engine A pure-signals — calibrated strength, holding
>                  period metadata; sequenced after C-engines-1)
>   C-engines-4   (Engine D Bayesian opt — substrate-independent infra)
>   C-engines-2   (Engine B portfolio vol-target — propose-first, awaiting
>                  Q1-Q5)
>   C-remeasure   (engine-complete substrate-honest multi-year)
> ```
>
> ---
>
> **2026-05-09 EVENING — KILL THESIS TRIGGERED. Structural review = engine completion.**
>
> Pre-committed kill thesis (this file, line ~228 below):
>
> > "If post-Foundation 2025 OOS Sharpe < 0.4 net of all costs (incl. taxes
> > + borrow), stop and run structural review."
>
> The data:
>
> | Measure | Value | Status vs 0.4 |
> |---|---:|---|
> | 2025 universe-aware Sharpe (pre-tax) | 0.436 | passes by 0.036 (cosmetic) |
> | After-tax adjustment (per `project_tax_drag_kills_after_tax_2026_05_02.md`) | est. negative | **fails** |
> | Plus 36-name missing-CSV upper-bound | pushes lower | **fails** |
>
> Strict reading of "net of all costs incl. taxes + borrow": **TRIGGERED.**
>
> **Trigger decision (2026-05-09):** treat as triggered. Don't move goalposts. The discipline framework only works if pre-commits are respected even when inconvenient.
>
> **What "triggered" means concretely:**
>
> - The project is NOT shut down. Pre-commit said "stop and run structural review" — not "abandon."
> - Forward feature work that claims Sharpe pauses for the duration of structural review.
> - Substrate-independent infrastructure work continues (engine completion is the structural review's main vehicle).
>
> **The structural review = engine completion.**
>
> The user surfaced the deeper finding the same evening: **the engines are not operating as engines.** Empirical confirmation:
>
> - Engine C's `compute_target_allocations` is defined but **never called** in the backtest loop (`orchestration/mode_controller.py`)
> - HRPOptimizer + TurnoverPenalty live at `engines/engine_a_alpha/signal_processor.py:228-242` (charter inversion F4)
> - No portfolio-level diversification, correlation-aware sizing, factor exposure caps, sector budgets — what actually runs is "Engine A produces edge votes → RiskEngine sizes per-ticker → PortfolioEngine books fills"
> - Engine D's discovery cycle has produced 0 promoted edges
> - Engine E's HMM is empirically coincident, not leading
>
> **The 0.507 substrate-honest Sharpe isn't "the strategy doesn't work" — it's "the strategy operating without portfolio management doesn't survive substrate honesty."**
>
> **The structural review's deliverable:** complete the engines per their charters, then re-measure on substrate-honest universe. The result becomes the new pre-commit baseline.
>
> ---
>
> **2026-05-09 AFTERNOON — F6 verdict COLLAPSES.** Multi-year mean Sharpe
> 1.296 → **0.5074** on substrate-honest universe (476-503 historical S&P
> 500 union). −0.789 Sharpe / −61%. Audit doc:
> `docs/Measurements/2026-05/universe_aware_verdict_2026_05_09.md`. Memory:
> `project_universe_aware_collapses_2026_05_09.md`.
>
> **Per-year breakdown:**
>
> | Year | Static (109) | Universe-aware (476-503) | Δ | Within ±0.15? |
> |---:|---:|---:|---:|---|
> | 2021 | 1.666 | 0.862 | −0.804 | NO |
> | 2022 | 0.583 | −0.321 | −0.904 | NO |
> | 2023 | 1.387 | 1.292 | −0.095 | **YES (only year)** |
> | 2024 | 1.890 | 0.268 | −1.622 | NO |
> | 2025 | 0.954 | 0.436 | −0.518 | NO |
>
> **0.507 is an upper bound.** 26-54 names per year were silently dropped
> for missing CSV files (FRC, DISCA, ATVI confirmed). Those are mostly
> delisted names — survivorship-bias signal pushing the real Sharpe lower.
> To pin down: run `scripts/fetch_universe.py` then re-measure.
>
> **What this means:**
>
> - **Path 1 ship: NOT VIABLE in current form.** 6 weeks of headline
>   Sharpe wins (1.296 Foundation Gate, 1.666 baseline, 1.890 in 2024,
>   V/Q/A 1.607 sustained-scores) were measured against a substrate
>   that implicitly selected for the same names the system was trading.
>   The math was correct; the test was easy.
> - **Pre-commit kill thesis nominally TRIGGERED** (Foundation Gate
>   measured at 0.507 vs. 0.5 gate; the gate is a clean fail when the
>   missing-CSV upper bound resolves). Honest restatement of the kill
>   criteria on substrate-honest universe is owed before the next
>   commitment cycle.
> - **The discipline framework is working.** This is what 8 months of
>   gauntlet / harness / decision-diary / external-review investment
>   was FOR. Today is the highest-value moment of that investment.
>   No live capital was risked on the biased measurement.
> - **2023 is the only year that held** (−0.095 within noise band on a
>   4.5× expanded universe). The 2026-05-09 evening trade-log
>   decomposition (`docs/Measurements/2026-05/multi_year_dilution_decomposition_2026_05_09.md`)
>   showed the substrate gap is NOT a single mechanism but three regime-
>   dependent ones:
>   - 2024 (largest collapse): 91.8% pure dilution on shared mega-caps —
>     same names, position size 4.4× smaller, signals drown
>   - 2022 (bear): defensive-concentration dominant — the 109-name list
>     dodged 331 expanded names that lost in the bear regime
>   - 2023 (the only year that held): broad participation; the 359 added
>     historical-S&P names contributed +$3,733; substrate didn't matter
>   - 2025: mixed; small magnitudes
>
>   The 6-non-S&P names hypothesis (COIN/MARA/RIOT/DKNG/PLTR/SNOW) is
>   refuted by data: those 6 contributed only 1.7% of static-109's
>   2024 PnL. **The actual mechanism is capital concentration on
>   shared mega-caps, not stock selection.**
>
> **What survives:**
>
> All infrastructure (Foundry, harness, gauntlet, decision diary,
> code-health, doc lifecycle, lifecycle automation, edge graveyard,
> V/Q/A integration, falsification framework, and the 2026-05-09
> metric-framework upgrade adding PSR + DSR + IR + tail/skew/kurt/ulcer).
> Edge code is intact; what's invalidated is the headline narrative
> around it.
>
> **C-collapses-1 result (2026-05-09 night).** Per-edge attribution lands. **Substrate-honest mean lifts from 0.5074 (9-edge) to 0.9154 (6-edge surviving) on the same window** — the 9-edge collapse is a 2-edge story (`quality_roic_v1`, `quality_gross_profitability_v1` both FALSIFIED with Δ Sharpe +1.358 / +0.503; `herding_v1` DEGRADED at +0.411). 4 of 9 edges (`gap_fill_v1`, `volume_anomaly_v1`, `value_earnings_yield_v1`, `value_book_to_market_v1`) are STRONGER on the wider universe. 2 (`accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1`) within ±0.2 noise.
>
> But — the surviving 6-edge set is **regime-conditional**: 2021/2023/2024 (bull / Mag-7) all materially better than the 9-edge ensemble; 2022 bear (−0.508) and 2025 chop (−0.107) are *worse*. The 2 falsified quality edges were apparently providing a defensive hedge the surviving set lacks.
>
> **Does this undo the kill-thesis trigger?** No. The trigger criterion was 2025 OOS Sharpe < 0.4 net of all costs (incl. taxes + borrow). Surviving-set 2025 = −0.107 (pre-tax), even worse than the 9-edge 0.436 that triggered. Engine completion remains the structural review's deliverable; the per-edge audit narrows down which edges are worth carrying THROUGH the engine-completion work, not whether to do it.
>
> Independently, the 6-names hypothesis was inverted by my isolation test (removing the 6 names from static-109 *improves* Sharpe by +1.30) — consistent with the evening trade-log decomposition's finding that the 6 names contributed only 1.7% of static-109's 2024 PnL.
>
> `data/governor/edges.yml` updated: `herding_v1` → `paused`, `quality_roic_v1` + `quality_gross_profitability_v1` → `failed`, all with `failure_reason='universe_too_small'`. Active count 9 → 6.
>
> Docs: `docs/Measurements/2026-05/six_names_isolation_2026_05_09.md`, `substrate_collapse_edge_audit_2026_05_09.md`, `surviving_edges_multi_year_2026_05_09.md`. Memory: `project_substrate_audit_2_edge_overfit_2026_05_09.md`.
>
> **What's queued (engine-completion structural review):**
>
> | Step | Dispatch | What it produces |
> |---|---|---|
> | ~~C-collapses-1 (running)~~ → **DONE 2026-05-09 night** | Per-edge audit on substrate-honest universe | 6 surviving / 1 paused / 2 failed; substrate-honest mean 0.9154 PARTIAL but bull-conditional. See result block above. |
> | C-collapses-1.25 | Factor decomp on volume_anomaly + herding under substrate-honest | Whether the two t > 4 alphas survive at t > 2 (4-bucket verdict). Note: herding_v1 is now paused per audit; rescope as needed. |
> | C-collapses-1.5 | Concentration-equivalent capital test | Does any per-name signal exist independent of concentration? |
> | **C-engines-1** | **Engine C activation** — wire `compute_target_allocations` into backtest loop; move HRP+Turnover OUT of signal_processor (closes F4); make Engine C a real portfolio composition layer | Engine C operating per charter |
> | **C-engines-2** | **Engine B portfolio vol-targeting + correlation-aware sizing** | Engine B operating per charter |
> | **C-engines-3** | **Engine E minimal-HMM on leading FRED features** + wire into Engine B de-grossing | Engine E operating per charter (also addresses the bull-conditionality of the surviving 6-edge set — see C-collapses-1 result) |
> | **C-engines-4** | **Engine D Bayesian opt scaffolding** (replaces GA noise factory) | Engine D producing real candidates |
> | **C-engines-5** | **Engine A pure-signals refactor** — charter restored | Engine A operating per charter |
> | C-remeasure | Re-run multi-year on substrate-honest universe with completed engines AND the 6-edge surviving set | The honest baseline. The next pre-commit gate gets defined here — and per the CLAUDE.md 6th non-negotiable (added 2026-05-08), it MUST be CI-aware: the trigger reads `Sharpe_ci_low < X`, not `Sharpe_point < X`. |
>
> Goal C / Moonshot Sleeve stays parked until C-remeasure verdict. As
> the user framed it: "if we can't get the bones working properly we
> shouldn't be working on the golden apple yet."
>
> **All measurements citing 1.296 / 1.666 / 1.890 / 1.607 baselines below
> this section are now KNOWN substrate-conditional AND engine-incomplete.**
> Read with two caveats: (a) substrate was biased, magnitudes are upper
> bounds; (b) engines weren't operating per charter, so the result is
> "what an incomplete system did on representative substrate" — not a
> fair test of the architecture.
>
> ---

## Pre-2026-05-09 plan (substrate-conditional — kept for reference)

> **Live plan.** Supersedes `forward_plan_2026_05_01.md` after the
> two outside-reviewer docs landed
> (`docs/Sessions/Other-dev-opinion/05-1-26_1-percent.md`
> + `05-1-26_a-and-i_full.mf`). Both converge on the same architectural
> picture and identify gaps the prior plans had underweighted.
>
> **PATH C DEFERRED — 2026-05-06:** 3-day Path C arc + regime-signal
> validation complete. Cells E/F/G/H all falsified. Cell F closest
> miss at -16.09% MDD / 4.74% CAGR; do NOT iterate further on 4-event
> sample.
>
> **Original unblock criteria from earlier today are now KNOWN-BROKEN
> per `project_regime_signal_falsified_2026_05_06.md`:** HMM is
> empirically a coincident vol detector, not forward-looking.
> AUC 0.49 on 20d-fwd drawdowns (coin flip). 2-of-3 cross-asset gate
> had **0% TPR** on -5% drawdowns over 1086 days. DXY change AUC 0.24
> (inverted from docstring's "rally = stress" theory). HMM input
> features (`spy_ret_5d`, `spy_vol_20d`) are coincident by
> construction; the architecture cannot lead.
>
> **REVISED unblock criteria** (much higher bar — multi-month, not
> weeks):
> 1. **HMM input panel rebuild** with leading features. ~~First
>    candidates: VIX term structure~~ — VIX term structure FALSIFIED
>    on 2026-05-06 (3 independent measurements agree it's coincident
>    across the entire 9d-to-6M curve; anti-predictive at canonical
>    -5% threshold). CBOE P/C historical UNOBTAINABLE in 2026 (every
>    free endpoint blocked). Remaining candidates:
>    (a) **Minimal-HMM on existing FRED features only**
>        (yield_curve_spread, credit_spread_baa_aaa, dollar_ret_63d,
>        spy_vol_20d — those carry slice-1's 78-day OOS lead).
>        Highest-ROI next step, no new data integration needed.
>    (b) IV skew (25Δ put / 25Δ call) via Schwab API — GATED on
>        historical-options-chain verification per the dev review
>        (`docs/Sessions/Other-dev-opinion/5-5-26_schwab-plan-reflection.md`).
>        If Schwab doesn't expose historical chains, IV skew is
>        forward-collection-deferred 6-12 months OR a paid-provider
>        decision.
>    (c) Earnings-revision dispersion via existing fundamentals data.
> 2. **THEN scope Engine B integration** after the input panel is
>    empirically predictive — propose-first per CLAUDE.md.
> 3. **THEN Path C overlay** at `scripts/path_c_overlays.py` becomes
>    load-bearing via regime-conditional trigger.
>
> VVIX-proxy is the lone salvageable signal from the existing
> WS-C work (AUC 0.64 in its valid window). The 2-of-3 confirmation
> architecture (`engines/engine_e_regime/cross_asset_confirm.py`) is
> a misleading standing reference, archive-pending.
>
> DO NOT reset -15% MDD target — load-bearing per design, not arbitrary.
> DO NOT scope Engine B integration until input-panel rebuild ships.
>
> **HONEST RE-ACCOUNTING — 2026-05-02 evening:**
>
> The director (this assistant) overstated workstream completion in
> the round-5 synthesis. User correctly called out: claiming "WS A
> ~90% shipped, WS D shipped, WS B in flight as if completing in one
> round" conflated *first slice shipped* with *workstream complete*.
> The 1-percent doc lists 4-7 named deliverables per workstream; we
> haven't met all of them on any workstream. Honest re-accounting
> below; future sessions should track per-deliverable, not vibes.
>
> | WS | Honest % | What's shipped | What's missing |
> |---|---|---|---|
> | A — Foundation | ~65% | Gauntlet fix ✓, cost completeness ✓ | ADV floor sweep under new gauntlet ⏳, integrated 2025 OOS rerun ⏳, health_check finding "geometry mismatch" still listed open ⏳ |
> | B — Engine C rebuild | ~25-30% (post-Path-A) | HRP slice 1 (failed), Path A slice 2 in flight (HRP composition + turnover penalty + tax-aware rebalancing) | mean-variance with shrinkage ❌, capital efficiency layer ❌, multi-asset proper ❌ |
> | C — Engine E rebuild | ~25-30% | HMM 3-state classifier shipped, default off | multi-resolution regime detection ❌, transition warning detector ❌, cross-asset confirmation ❌, regime-conditional sleeve de-gross ❌ |
> | D — Feature Foundry | ~60% | DataSource ABC ✓, @feature decorator ✓, ablation runner function ✓, twin generator ✓, dashboard tab ✓, model card schema ✓, CFTC COT proof-of-architecture ✓ | auto-ablation cron scheduler ❌, adversarial filter as runtime/CI gate ❌, 90-day archive enforcement ❌, integration with main backtest pipeline ❌ |
> | E — Edge factory expansion | 0% | (nothing) | All ~50 features (cross-sectional, event-driven, calendar, pairs, auto-engineered) ❌ |
> | F — External data sources | ~5% | CFTC COT seed ✓ | All other ~11 sources ❌; real fundamentals data layer decision ❌ (BLOCKS Path C compounder enable) |
> | G — Statistical ML upgrades | 0% | (nothing) | Bayesian opt, symbolic regression, SSL embeddings, causal, GNN ❌ |
> | H — Moonshot Sleeve | ~5% | Path C sleeve abstraction can host it ✓ | All Moonshot edges, asymmetric sizing, sleeve config ❌ |
> | I — Deployment infrastructure | 0% | (nothing) | Real OMS, vol-targeting, tail hedge, kill switches, shadow-live, chaos engineering ❌ |
> | J — Cross-cutting | ~30% | Capital allocation dashboard ✓, determinism harness ✓, ablation runner function ✓ | Decision diary ❌, DVC versioning ❌, edge graveyard structured tagging ❌, info-leakage detector ❌, data quality monitoring (Great Expectations) ❌, CI for backtests ❌, engine versioning ❌, synthetic data harness ❌ |
>
> **Honest cumulative: ~20-25% of the doc's full plan.** The doc estimated 12-18 months for 2-3 devs. We're a few intense agent-weeks in. Roughly on pace, **NOT ahead**. Prior synthesis implied ahead; that was wrong.
>
> **Discipline correction going forward:** when reporting workstream
> status, list the doc's named deliverables and mark each ✓/⚠️/❌
> explicitly. "X% complete" should mean "X% of named deliverables
> shipped with their acceptance criteria met," not "vibes."
>
> **Kill thesis status:** nominally triggered by the post-tax -0.577
> reading (cost completeness shipped). Reinterpreted as deployment-
> context drag rather than alpha refutation. But this re-accounting
> also reveals: the kill thesis was tied to "post-Foundation"
> measurement, and Foundation is genuinely ~65% not ~90% — the
> integrated rerun that would actually be "post-Foundation" hasn't
> happened. So the -0.577 is post-cost-layer-only, not post-full-
> foundation. Doesn't change the directional finding (tax drag is
> real and large) but does mean the kill thesis trigger reading is
> on incomplete data.
>
> **Deployment-context update — 2026-05-02 evening:** Alpaca (the
> deployment vehicle) may not offer Roth IRAs. Live-money deployment
> is therefore TAXABLE individual unless the user opens a separate
> Roth-supporting brokerage (non-engineering decision, deferred).
> Paper trading is tax-free but doesn't model the real-money case.
> **Tax-drag engineering (regime-conditional wash-sale gate,
> longer-hold optimizer, tax-loss harvesting / lot selection) is
> DEFERRED but HIGH PRIORITY.** Next-round dispatch prioritizes
> context-agnostic improvements (features, regime detection, data
> sources, sleeve abstractions) that help in BOTH contexts. The
> wash-sale gate multi-year falsification (2021 Δ=-0.966) confirmed
> that naive tax-drag fixes can hurt in taxable too — the
> regime-conditional design is the right answer when we get to it,
> not next round.

## What the reviewer docs added that we hadn't fully internalized

### The biggest engine gaps are C and E, not D
We'd been treating Engine D (Discovery) as the load-bearing problem because the gauntlet had visible bugs. The reviewer's engine-by-engine gap analysis ranks **C > E > A > B > D > F** by expected impact of investment. **Engine C is the thinnest engine in the system.** What looks like portfolio-construction logic is mostly happening implicitly in `signal_processor.weighted_sum`. Real portfolio construction (HRP, mean-variance with shrinkage, turnover penalty, tax-aware rebalancing, capital efficiency, multi-asset) is missing. Engine E is similarly thin — threshold-based regime detection without confidence outputs, no multi-resolution, no transition prediction, and macro signals architecturally mis-classified as edges instead of regime inputs.

### Feature Foundry as critical infrastructure
The 1-percent doc's central rule: **build the infrastructure that makes adding features cheap before adding the features.** Without auto-ablation, adversarial twins, feature lineage, and a feature audit dashboard, even 3 new features create chaos by feature #15. With the infrastructure: marginal cost of feature N is constant, not N-growing.

### Goal C reframed as Track-3 parallel, not Phase-5 deferred
The reviewer explicitly: *"Don't let core's struggles delay it. A 20-something with 40-year horizon needs this sleeve more than the core's incremental refinements."* The Moonshot Sleeve is architecturally independent (different universe, different gauntlet, different objective function). It can run parallel to core foundation work, gated by its own criteria (skewness > 0.5, hit rate ≥ 5%, sleeve CAGR ≥ 15%).

### Five non-negotiable rules (codified)
1. **Deterministic measurement always.** Every Sharpe runs through harness.
2. **Adversarial validation by default.** Every feature ships with a permuted twin.
3. **One feature per PR.** Never batch.
4. **90-day archive rule.** Auto-pruning is mandatory.
5. **Geometry of measurement matches deployment.** No standalone tests for ensemble-deployed strategies.

## The 10 workstreams (1-percent doc structure)

| # | Workstream | Status | Effort (1 dev) | Blocks |
|---|---|---|---|---|
| A | Foundation completion | **THIS ROUND PRIORITY** | 4-6 weeks | All others |
| B | Engine C rebuild (HRP, turnover, tax) | THIS ROUND | 4-6 weeks | — |
| C | Engine E rebuild (HMM, multi-res, transitions) | THIS ROUND | 4-6 weeks | — |
| D | Feature Foundry infra | THIS ROUND | 6-8 weeks | E, F, G, H |
| E | Edge factory expansion (~50 features) | After D | 6+ weeks | — |
| F | External data sources (~12 free) | After D | parallel | — |
| G | Statistical ML upgrades | After D | 8-12 weeks | — |
| H | Moonshot Sleeve | After D | 8-12 weeks | — |
| I | Deployment infrastructure | Later | 8-12 weeks | — |
| J | Cross-cutting (ablation, leakage detection, etc.) | Continuous | ongoing | — |

## Phase gates (must pass to advance)

- **Foundation Gate:** 2025 OOS Sharpe ≥ 0.5 deterministic, all 5 gauntlet gates measure correctly, 3-run reproducibility verified
- **Architecture Gate:** Combined Sharpe ≥ Foundation + 0.2; Engine C real optimizer in production; macro signals reclassified as regime inputs
- **Factory Gate:** ≥50 active features, auto-pruning < 5/month, combined Sharpe ≥ 0.7
- **Discovery Gate:** ≥1 symbolic-regression edge in production; ≥1 SSL-derived edge in production; GA replacement complete
- **Deployment Gate:** All chaos tests pass; 90 days shadow-live with Sharpe gap < 0.2 vs backtest; sustained Sharpe ≥ 1.0 over 90 days
- **Moonshot Gate:** Backtest 2010-2024 ≥ 1 5x+ winner/year average; hit rate ≥ 5%; sleeve CAGR ≥ 15%

## Pre-committed kill thesis (no goalpost moving)

If post-Foundation 2025 OOS Sharpe < 0.4 net of all costs (incl. taxes + borrow), **stop and run structural review**. Don't proceed to other workstreams.

## This round's dispatch — 5 parallel agents

The four MUST-HAVE workstreams (A foundation, B Engine C, C Engine E, D Feature Foundry) plus one NICE-TO-HAVE (cost completeness within A) all have independent code surfaces. They can run in parallel under worktree isolation without conflict.

| Agent | Workstream | Code surface | Effort |
|---|---|---|---|
| 1 | A — consolidated gauntlet fix + ADV floor verify | `engines/engine_d_discovery/`, `orchestration/`, `wfo.py` | ~3-5 days |
| 2 | D — Feature Foundry skeleton + 1 DataSource | `core/feature_foundry/` (new), `cockpit/dashboard_v2/` | ~2-3 days |
| 3 | B — Engine C HRP slice | `engines/engine_c_portfolio/`, `engines/engine_a_alpha/signal_processor.py` (config-only) | ~2-3 days |
| 4 | C — Engine E HMM slice + macro reclass | `engines/engine_e_regime/`, `data/governor/edges.yml` (4 edges) | ~2-3 days |
| 5 | A — cost completeness layer | `backtester/`, `core/` | ~1-2 days |

After this round: re-run 2025 OOS under harness to test Foundation Gate. If pass → unlock Tracks 2/3/4/5. If fail → kill thesis kicks in, structural review.

## What's queued for the round AFTER this one

Conditional on Foundation Gate passing:

- **Track E batch 1:** ~10-15 cross-sectional ranking primitives (12-1 momentum, value composite, quality composite, etc.)
- **Track F batch 1:** ~3-5 free data sources via Foundry (CFTC COT, USPTO patents, Polymarket via warproxxx/poly_data, FDA approvals/PDUFA, USAspending)
- **Track H setup:** Moonshot Sleeve universe + objective function + sleeve-level allocation primitive
- **Track G setup:** Bayesian optimization replacing GA for hyperparameter search
- **Track I start:** Real OMS scaffolding + shadow-live mode

## Round-N+1 dispatch (5 context-agnostic agents) — 2026-05-04 update

The first round shipped (5 agents, May 1-2). The next-round dispatch
focuses on **context-agnostic improvements** that help in both Roth and
taxable, with tax-drag engineering deferred per the deployment-context
update above. **All 5 agents are GATE-CONDITIONAL — fire only after the
multi-year Foundation Gate measurement (driver: `scripts/run_multi_year.py`,
artifact: `docs/Audit/multi_year_foundation_measurement.md`) reports
`Gate status: PASS` (mean Sharpe across 2021-2025 ≥ 0.5).** If
status is AMBIGUOUS or FAIL, the dispatch table below is suppressed
and the kill-thesis review path takes over instead.

| Agent | Workstream | Read/write surface | Backtest? | Time budget | Branch |
|---|---|---|---|---|---|
| 1 | F — Fundamentals data scoping (Compustat / SimFin / EDGAR / `noterminusgit/statarb`) | `docs/Core/Ideas_Pipeline/`, `docs/Audit/` (research notes only) | No | 1-2 hrs research + report | `ws-f-fundamentals-data-scoping` |
| 2 | E — Foundry batch 3 (5 more features toward 50-feature target) | `core/feature_foundry/features/`, tests | No | 2-3 hrs | `ws-e-third-batch` |
| 3 | C — Cross-asset confirmation layer + HMM smoke | `engines/engine_e_regime/`, `core/feature_foundry/features/` (HYG/LQD spread, DXY, vol-of-vol) | Yes (1 smoke) | 2-3 hrs | `ws-c-cross-asset-confirm` |
| 4 | D — Foundry close-out (auto-ablation cron + adversarial filter as CI gate + 90-day archive) | `core/feature_foundry/`, `.github/workflows/` (or pre-commit), CI scripts | Yes (ablation) | 3-4 hrs | `ws-d-closeout` |
| 5 | J — Cross-cutting trio (decision diary + edge graveyard structured tagging + info-leakage detector skeleton) | `core/observability/` (new), `data/governor/` schema only, `cockpit/dashboard_v2/` | No | 2-3 hrs | `ws-j-cross-cutting-batch` |

### Per-agent acceptance criteria

**Agent 1 — WS F fundamentals data scoping** (research only, no merged code expected this round):
- Comparison matrix of Compustat / SimFin / EDGAR (license cost, point-in-time history available, update lag, schema completeness for value + quality + accruals factors)
- Audit of `noterminusgit/statarb` repo (alpha strategies that depend on fundamentals + portfolio optimizer specifics + which can drop into our Foundry without rewrite)
- Recommendation memo: which data source for what factor family, which `statarb` modules to lift, what's the prerequisite to enable Path C compounder (currently blocked per `project_compounder_synthetic_failed_2026_05_02`)
- Deliverable: `docs/Audit/ws_f_fundamentals_data_scoping.md` plus optional `docs/Core/Ideas_Pipeline/path_c_unblock_plan.md`. No code merged.

**Agent 2 — WS E batch 3 (5 features)**:
- 5 new features in `core/feature_foundry/features/` covering calendar / event-driven / pairs primitives (e.g. `days_to_quarter_end`, `earnings_proximity_5d`, `pair_zscore_60d` for sector pairs, `month_of_year_dummy`, `vix_term_structure_slope`)
- Each ≤ 50 LOC, with adversarial twin generated, ablation-runner output captured
- Tests pass; full Foundry test regression passes
- Cumulative target: 14/10 features (50% past the 10-feature pre-batch goal — substrate validates)
- Deliverable: 5 commits or one bundled commit on `ws-e-third-batch`, model card per feature

**Agent 3 — WS C cross-asset confirmation + HMM smoke**:
- HYG/LQD credit spread, DXY (USD index), VVIX (vol-of-vol) added as Foundry features
- Cross-asset confirmation gate function in `engines/engine_e_regime/` that takes HMM transition signal + cross-asset evidence and returns confirm/veto
- Default OFF (no behavior change on main without flag flip)
- Smoke run with `hmm_enabled: true` AND cross-asset confirmation ON, single year (2024) under harness, captured in audit doc
- Acceptance: smoke run completes deterministically (3 reps bitwise-identical canon md5), report shows Sharpe-impact estimate
- Pre-req for the regime-conditional wash-sale gate when tax-drag work unfreezes
- Deliverable: code + `docs/Audit/ws_c_cross_asset_confirmation.md`

**Agent 4 — WS D close-out**:
- Auto-ablation runner triggered on every PR that touches `core/feature_foundry/features/*.py` (CI workflow OR pre-commit hook)
- Adversarial-twin filter integrated as a hard CI gate: feature must outperform its permuted twin by ≥X% margin (X to be specified by agent; conservative default suggested 30%)
- 90-day archive enforcement: features whose last-90d performance trends negative get auto-tagged for review (not auto-deleted — flag and queue for human triage)
- Deliverable: code + workflow files + `docs/Audit/ws_d_foundry_closeout.md` listing what is now AUTO vs. what still requires human in the loop
- Closes WS D from ~60% to "complete per the doc's named deliverables"

**Agent 5 — WS J cross-cutting trio**:
- Decision diary scaffold: structured log entries for each significant config flip / merge to main with rationale + expected impact + actual impact (post-hoc fillable)
- Edge graveyard structured tagging: edges with `status: failed` get a structured `failure_reason` + `superseded_by` field in `data/governor/edges.yml` (schema change only; backward-compatible)
- Info-leakage detector skeleton: function that, given a feature definition, can identify whether it uses lookahead (close vs. next-bar-close, future-window stats) and emits a diagnostic. Wired in as ADVISORY (not enforcing) to start
- Deliverable: code + tests + `docs/Audit/ws_j_cross_cutting_trio.md`
- Each of the three is high-leverage, compounds on every future agent's reporting

## Repo audit findings (from reviewer's review)

Three external repos worth real time investigation:
- `noterminusgit/statarb` — 20+ alpha strategies + portfolio optimization. Saturday-afternoon audit.
- `ScottfreeLLC/AlphaPy` — Python AutoML for trading; relevant to Foundry. May accelerate Track G.
- `warproxxx/poly_data` — Polymarket integration. Drop-in for Track F.

These are **investigation tasks, not dispatched tasks** for this round. The user can audit them at their own pace.

## Single-paragraph TL;DR

**5 agents in parallel this round: gauntlet architectural fix, Feature Foundry skeleton, Engine C HRP slice, Engine E HMM slice, cost completeness. After this round, re-run 2025 OOS under harness to test the Foundation Gate. If pass → unlock the rest of the 10-workstream plan in tiered parallel waves. If fail → pre-committed kill thesis kicks in, structural review. The reviewer's most emphatic point — "build infrastructure first, then features" — is captured by putting Foundry in this round; the engine-gap finding (C and E are biggest) is captured by putting both engines' first slices in this round. After Foundation, the path is parallel-track aggressive but discipline-gated. Real-money deployment no earlier than ~12 months out, probably mid-late Year 2.**

## V/Q/A FUNDAMENTALS EDGES STATUS — 2026-05-07 (substrate-conditional, see top-of-file caveat)

> **2026-05-09 update:** F6 verdict COLLAPSES means the 1.666 baseline
> and 1.607 sustained-scores result below were measured on a biased
> substrate. The "-0.06 drag (within noise band)" framing assumed both
> baseline and treatment were measured against the same biased universe;
> on substrate-honest universe, both magnitudes are unknown. The
> integration-mismatch fix is still architecturally correct (held
> positions need a defending vote vs. silence) — that's a software
> finding, not a measurement claim. Whether V/Q/A net-helps on
> substrate-honest universe is open: gated on C-collapses-1's per-edge
> audit. Treat the 2022 bear smoke + grid search as DEFERRED until
> per-edge audit completes.

The 6 V/Q/A edges (`value_earnings_yield_v1`, `value_book_to_market_v1`, `quality_roic_v1`, `quality_gross_profitability_v1`, `accruals_inv_sloan_v1`, `accruals_inv_asset_growth_v1`) shipped 2026-05-06. Three sequential fixes:

1. **2026-05-06 morning** — V/Q/A merged with default config. 2021 single-rep Sharpe 1.155 vs baseline 1.666 = **-0.51 drag**. Code-health agent surfaced 3 HIGH bugs (ROIC distressed-firm inflation, helper bare-except, auto-register exception swallowing).

2. **2026-05-06 PM** — bug fixes shipped + state-transition pattern (no daily over-trading). Trades 7057 → 538 (-92%). But Sharpe dropped to **0.592** = -1.07 drag. The over-trading was masking integration mismatch.

3. **2026-05-07** — sustained-score fix shipped. Edges emit `sustained_score=0.3` on held positions instead of 0.0, keeping their position-defending vote alive. **2021 Sharpe 1.607 vs baseline 1.666 = -0.06 drag** (within noise band). Integration-mismatch hypothesis confirmed.

**Current status:** active in `data/governor/edges.yml` with sustained-score logic. Smoke verified on 2021 only.

**Required before promoting default-on for production / multi-year measurement:**
- 2022 bear-regime smoke as the diagnostic test (single-year fail/pass)
- If 2022 passes: full 2021-2025 multi-year × 3 reps
- Grid-search on `sustained_score` parameter (0.0 / 0.2 / 0.3 / 0.5) — current 0.3 is a starting heuristic, not validated

**Honest note:** 16 names per top quintile is above the 8-name disaster threshold (see `project_factor_edge_first_alpha_2026_04_24`) but below the ≥200 academic convention. Per-edge OOS walk-forward required before promotion past `feature` tier.
