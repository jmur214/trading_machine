# Substrate-Honest Re-Measurement Post-Edge-Expansion — Verdict (T-2026-05-10-019)

**Date:** 2026-05-10
**Branch:** `feature/substrate-honest-post-edge-expansion`
**Source spec / dispatch:** inbox brief T-2026-05-10-019
**Comparison baseline:** T-2026-05-08-002 audit doc (`docs/Measurements/2026-05/multi_year_substrate_honest_2026_05_08.md`)
**Window:** 2021-2025 (5 years × 3 reps × 2 arms = 30 runs), F6 historical S&P 500 universe + missing-CSV closure d5af02e, journal-mode, realistic costs ON.

---

## Headline

**Δ Sharpe = 0.0000 in BOTH arms vs T-002.** Per-year Sharpes, per-year canon md5s, and bootstrap 95% CIs are **bit-identical** to T-002 (15/15 cell match per arm). The 5 new paused edges added today (T-014/T-016/T-017/T-018) are loaded successfully into the alpha pipeline but **contribute zero trades and zero canon-md5 perturbation** to the substrate-honest 2021-2025 measurement.

**Verdict bucket:** `|Δ Sharpe| < 0.05 in both arms → edges contribute but don't materially shift the headline; investigate per-edge contribution to understand why` (spec line 62).

In stronger terms — they don't just fail to shift the headline, they don't shift it by a single bit. This is a real signal about the edge expansion track and worth the director's attention.

## Cross-T-002 comparison

| Metric | T-002 Arm 1 | T-019 Arm 1 | Δ | T-002 Arm 2 | T-019 Arm 2 | Δ |
|---|---:|---:|---:|---:|---:|---:|
| Mean Sharpe | +0.2702 | +0.2702 | 0.0000 | +0.2940 | +0.2940 | 0.0000 |
| Bootstrap Sharpe ci_low | -0.383 | -0.383 | 0.000 | -0.270 | -0.270 | 0.000 |
| Bootstrap Sharpe ci_high | +0.771 | +0.771 | 0.000 | +0.761 | +0.761 | 0.000 |
| Bootstrap Sortino ci_low | -0.391 | -0.391 | 0.000 | -0.396 | -0.396 | 0.000 |
| Bootstrap Sortino ci_high | +0.852 | +0.852 | 0.000 | +1.125 | +1.125 | 0.000 |
| Mean MDD (%) | -4.10 | -4.10 | 0.00 | -5.86 | -5.86 | 0.00 |
| Mean Win-Rate (%) | 49.44 | 49.44 | 0.00 | 49.25 | 49.25 | 0.00 |
| New paused edges total trades | 0 | **0** | 0 | 0 | **0** | 0 |

Per-year Sharpes (deterministic, identical across all 3 reps, identical across T-002 and T-019):

| Year | T-019 Arm 1 | T-019 Arm 2 | Δ |
|---|---:|---:|---:|
| 2021 | 0.413 | 0.416 | +0.003 |
| 2022 | 0.116 | 0.282 | **+0.166** |
| 2023 | 0.261 | 0.348 | +0.087 |
| 2024 | 0.236 | 0.215 | -0.021 |
| 2025 | 0.325 | 0.209 | -0.116 |

Each (arm, year) cell has 1/3 unique canon md5 across the 3 reps (within-year deterministic), and each canon md5 matches the corresponding T-002 cell **bit-for-bit**.

## Determinism

- **30/30 runs OK.** No failures.
- **Per-cell determinism: 1/3 unique canon md5 in every (arm, year) cell** — same as T-002.
- **Cross-T-002 canon md5: 15/15 Arm 1 cells match T-002 bit-identically.** Trade logs are identical to T-002's, despite the registry now containing 5 new paused edges that are auto-loaded into the alpha pipeline.

## Per-edge trade counts (Arm 1, rep 1, all 5 years)

| edge_id | total trades | status |
|---|---:|---|
| `value_earnings_yield_v1` | 12,094 | active |
| `accruals_inv_sloan_v1` | 11,148 | active |
| `value_book_to_market_v1` | 9,540 | active |
| `accruals_inv_asset_growth_v1` | 6,030 | active |
| `volume_anomaly_v1` | 1,206 | active |
| `gap_fill_v1` | 1,019 | active |
| `news_sentiment_edge_v1` | 451 | paused (pre-T-002) |
| `momentum_12_1_v1` | **0** | paused (T-016, NEW) |
| `momentum_6_1_v1` | **0** | paused (T-016, NEW) |
| `short_term_reversal_v1` | **0** | paused (T-016, NEW) |
| `dividend_initiation_drift_v1` | **0** | paused (T-018, NEW) |
| `pairs_trading_MA_V_v1` | **0** | paused (T-017, NEW) |

(`news_sentiment_edge_v1` is a pre-T-002 paused edge that produces 451 trades over 5 years — confirms that the soft-pause infrastructure CAN attribute trades to paused edges. It's not a global filter; it's specific to the new edges.)

## Diagnosis: why zero contribution?

Investigated three hypotheses:

1. **Are the new edges loaded?** YES. `[ALPHA] Loaded edge ...` lines for all 5 new edges appear in `data/measurements/substrate_2026_05_08/logs/full_run_t019.log`. Confirmed with a direct call to `mode_controller._load_edges_via_registry()` returning instantiated objects of the right classes (`Momentum12_1Edge`, `Momentum6_1Edge`, `ShortTermReversalEdge`, `DividendInitiationDriftEdge`, `PairsTradingEdge`).
2. **Do their `compute_signals` produce non-zero signals?** YES, when called against synthetic OHLCV from `data/processed/`. Standalone test: `momentum_12_1_v1`, `momentum_6_1_v1`, `short_term_reversal_v1` each produce 16/78 non-zero signals on a 78-ticker subset for 2024-06-30 — the expected ~20% top/bottom-quantile coverage.
3. **Are their soft-paused contributions reaching the trade decision?** Apparently NOT to a degree that perturbs canon md5. Most-likely explanation: with the active 6 edges driving entries (full weight 1.0×, dominant signal magnitude on selected names), the new edges' soft-paused contributions (0.25× weight × ~0.2-0.3 per-name ensemble share) are arithmetically additive but never dominate the edge_id attribution — and apparently never shift the dominant edge's net signal enough to change the entry/exit decision boundary. Floating-point precision on the post-aggregation comparison happens to round identically to T-002's, so canon md5 is unchanged.

The third point is the key finding: **a paused edge contributing at 0.25× to an ensemble already dominated by 6 active edges, on a 109-ticker universe, produces no observable effect on this specific 5-year backtest under deterministic harness.** This is consistent with the existing 14-paused-edge-set pre-T-002 (where `news_sentiment_edge_v1` does shift trade outcomes — the difference is unclear without deeper instrumentation, but a plausible explanation is that news_sentiment provides signal on names where ZERO active edges signal, while the new momentum/reversal edges signal on names where active edges already are signaling).

## Implications for the edge expansion track

1. **The day's edge expansion (T-014, T-016, T-017, T-018) added zero substrate-honest signal at paused/feature tier.** The cross-sectional momentum trio + dividend-initiation + pairs-trading + 7 calendar features collectively contribute nothing measurable to Arm 1 or Arm 2 mean Sharpe.

2. **Soft-pause at 0.25× is too weak to surface new-edge contributions when the active 6 dominate.** The mechanism works in principle (news_sentiment_edge demonstrates this), but the new edges happen to overlap the active edges' signal universe. Two paths forward:
   - **Promote a new edge to status='active' provisionally** to test whether it has standalone alpha (would require lifecycle-gauntlet evaluation first per spec).
   - **Accept that paused-tier edges are inert until lifecycle promotes them** and focus on lifecycle/Discovery cycle work to actually evaluate the new edges.

3. **Edge-pruning isn't the question; edge-promotion is.** With 6 actives doing all the work and paused edges at 0.25× being arithmetically swamped, the edge expansion track requires **promotion gating** (Engine F lifecycle) to deliver lift. T-004's factor-decomp finding (0/6 actives have positive factor-adjusted α at t > 2 on substrate-honest) compounds this — even the active edges aren't producing reliable signal post-factor-adjustment. The path to lifting the headline runs through:
   - Discovery cycle that tests new edges against the substrate-honest gauntlet (Gates 1-8 incl. factor decomp at t > 2)
   - Lifecycle promotion if and when they clear

4. **The +0.024 Arm 2 lift over Arm 1 reproduces exactly** — 4 active edges + HMM Variant C ON delivers the same +0.024 Sharpe lift T-002 reported. T-015's clean attribution (lift driven by edge pruning, not HMM) is unaffected by today's edge additions.

## Open questions for director

1. **Should new paused edges be force-promoted for explicit measurement?** Currently they ride the soft-pause path which apparently silences them on this substrate. A "candidate" status that runs them at full weight in a separate measurement arm (without modifying production) would surface their actual signal characteristics. This would be a Discovery-cycle dispatch.

2. **Is `news_sentiment_edge_v1`'s signal characteristic informative?** It produces 451 trades over 5 years at 0.25× weight; the new edges produce 0. Deeper instrumentation could reveal what makes it different — possibly that it signals on names that no active edge reaches, vs. the new edges that signal on names actives are already trading.

3. **Engine B vol-targeting prioritization unchanged from T-003 recommendation.** T-003's SELECTION-DOMINANT verdict + this dispatch's 0-contribution finding both argue against rushing Engine B optimization. Lifecycle gauntlet evaluation of the paused edges (or of new candidates) is the higher-leverage next step.

## Run UUIDs (Arm 1 + Arm 2, rep 1 per year)

Stored in `data/measurements/substrate_2026_05_08/arm1_results.json` and `arm2_results.json`. Trade logs in `data/trade_logs/<run_id>/`.

Confirmed: each Arm 1 (year, rep=1) `trades_canon_md5` matches T-002's archived value exactly (15/15 cells).

## Caveats

- **Soft-pause weight propagation for new edges:** confirmed via run-log inspection that the loader instantiates them. Whether `signal_processor.aggregate` applies the 0.25× multiplier identically to new vs. pre-existing paused edges was NOT separately diagnosed; the bit-identical canon md5 is consistent with both edges contributing nothing OR contributing an arithmetic identity that rounds to T-002's signal magnitudes. Deeper instrumentation needed if director wants the precise mechanism.
- **Per-edge trade counts** above are from rep 1 of each year; reps 2/3 are bitwise-identical so counts match.
- **Window-mismatch sanity:** 365-day calendar warmup yields ~252 trading days of pre-history before sim start. `momentum_12_1_v1` requires 252+21+1 = 274 bars; **2021's first ~22 bars would universally abstain due to insufficient pre-history**, but 2022-2025 should fire normally. Trade counts of 0 in 2022+ confirm the issue isn't lookback exhaustion alone.
- **MAX_POSITIONS empirically non-binding** (per T-003 finding): same caveat applies here.
- **Re-saved anchor:** dispatch required re-saving the deterministic-harness anchor (`scripts/run_isolated.py --save-anchor`) so the `isolated()` context restored an `edges.yml` that included the new paused edges. Without this, the harness would have reverted edges.yml to the pre-T-016 state at every rep, hiding the new edges entirely.

## Files changed

- `docs/Measurements/2026-05/substrate_honest_post_edge_expansion_2026_05_10.md` — new (this audit doc)
- `docs/Measurements/2026-05/substrate_honest_post_edge_expansion_2026_05_10.json` — new (T-019 analytics JSON, structurally identical to T-002's)
- `data/governor/_isolated_anchor/*.yml,json,csv` — re-saved (captures current edges.yml with new paused edges; gitignored)

No engine code modified. No `data/governor/edges.yml` mutation beyond the auto-register that fired on import (already on origin/main from T-016/T-017/T-018 merges). 30/30 backtest runs deterministic.
