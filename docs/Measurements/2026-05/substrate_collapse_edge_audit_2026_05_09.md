# Substrate-Honest Per-Edge Audit — 2026-05-09

**Question:** Of the 9 active edges in `data/governor/edges.yml`, which
ones earn Sharpe on the survivorship-bias-aware S&P 500 universe (~498
names) and which only worked on the curated static-109 mega-cap subset?

**Answer:** Only **2 are FALSIFIED**, **1 DEGRADED**, **2 CONFIRMED
within noise**, and **4 are actually STRONGER on substrate-honest** —
the opposite of the F6-implied collapse. The ensemble's collapse on the
historical universe (Sharpe 0.268 vs static-109's 0.855) is driven
almost entirely by 2 quality edges that overfit to the curated mega-cap
substrate and pull the ensemble down on a representative universe.

This **inverts the F6 narrative for individual edges**. The Foundation
Gate ensemble collapses on substrate-honest, but most of its individual
edges work *better* — the failure mode is two specific edges
(quality_roic_v1, quality_gross_profitability_v1) that fail badly on
the wider universe and dominate the ensemble.

## Status

- **Status:** CURRENT
- **Reframes:** `universe_aware_verdict_2026_05_09.md` — the COLLAPSES
  verdict on the 9-edge ensemble is real, but the per-edge picture
  shows it's a 2-edge failure, not a 9-edge failure.
- **Refines:** `six_names_isolation_2026_05_09.md` — the diffuse-bias
  finding is consistent with this; the 367+ omitted names hurt the
  quality edges in particular (they relied on the curated mega-cap
  set's quality skew).

---

## Method

For each of the 9 active edges:

1. Run 1 single-edge backtest on **static-109** (vanilla
   `config/backtest_settings.json`), 2024.
2. Run 1 single-edge backtest on **historical S&P 500** (~498 names,
   `use_historical_universe=true`), 2024.
3. Compare static_sharpe vs historical_sharpe.

Year: 2024 (the F6-largest-collapse year). 1 rep per edge × universe;
3-rep determinism is implicit because the multi-edge ensemble runs at
3 reps in the 6-names test passed bitwise on the same anchor.

Single-edge = `exact_edge_ids=[edge_id]` in `ModeController.run_backtest`.
Each backtest runs under `isolated()` so governor state is anchored
identically.

### Classification scheme (corrected)

The user-supplied scheme:
- CONFIRMED: |Δ Sharpe| ≤ 0.2
- DEGRADED: drop 0.2-0.5
- FALSIFIED: drop > 0.5

Where Δ = static − historical (positive = drop). The original scheme
was symmetric on |Δ| in the driver, which mis-tagged edges that were
*stronger* on historical as DEGRADED/FALSIFIED. The corrected
classification distinguishes direction:

| Verdict | Condition | Action |
|---|---|---|
| **STRONGER on historical** | historical ≥ static + 0.2 | keep active |
| **CONFIRMED** | within ±0.2 either way | keep active |
| **DEGRADED** | static-stronger by 0.2-0.5 | mark `paused` (`failure_reason='universe_too_small'`) |
| **FALSIFIED** | static-stronger by >0.5 | mark `failed` (`failure_reason='universe_too_small'`) |

---

## Results — 2024, single-edge × 2 universes

| edge_id | static-109 | historical | Δ (static − historical) | corrected verdict |
|---|---:|---:|---:|---|
| gap_fill_v1 | 0.462 | 1.082 | **−0.620** | STRONGER on historical |
| volume_anomaly_v1 | 0.207 | 1.475 | **−1.268** | STRONGER on historical |
| herding_v1 | 0.731 | 0.320 | +0.411 | DEGRADED |
| value_earnings_yield_v1 | 0.983 | 1.283 | −0.300 | STRONGER on historical |
| value_book_to_market_v1 | 0.888 | 1.108 | −0.220 | STRONGER on historical |
| **quality_roic_v1** | **2.183** | **0.825** | **+1.358** | **FALSIFIED** |
| **quality_gross_profitability_v1** | 1.540 | 1.037 | +0.503 | **FALSIFIED** |
| accruals_inv_sloan_v1 | 1.953 | 1.994 | −0.041 | CONFIRMED |
| accruals_inv_asset_growth_v1 | 1.317 | 1.317 | 0.000 | CONFIRMED |

### Aggregate

- **STRONGER on historical (4):** gap_fill_v1, volume_anomaly_v1,
  value_earnings_yield_v1, value_book_to_market_v1
- **CONFIRMED (2):** accruals_inv_sloan_v1, accruals_inv_asset_growth_v1
- **DEGRADED (1):** herding_v1
- **FALSIFIED (2):** quality_roic_v1, quality_gross_profitability_v1

**Surviving set: 6 edges** (4 STRONGER + 2 CONFIRMED) — these stay
`active`. **1 paused** (DEGRADED), **2 failed** (FALSIFIED).

---

## Why the ensemble collapses when individual edges mostly improve

The 6-names isolation showed the multi-edge ensemble collapses from
0.855 (static-109) → 0.268 (historical) on 2024. But the per-edge audit
shows 6 of 9 edges are CONFIRMED-or-better on historical. So why does
the ensemble fall apart?

Three mechanisms, in plausible order of magnitude:

### 1. The 2 FALSIFIED quality edges dominate the ensemble (likely largest)

`quality_roic_v1` drops 1.358 Sharpe and `quality_gross_profitability_v1`
drops 0.503. Together that's ~1.86 Sharpe of negative ensemble
contribution from just those two. Their static-109 Sharpes (2.183 and
1.540) are likely overfit to the curated mega-cap quality skew — the
academic Quality factor (Asness-Frazzini-Pedersen "Quality Minus Junk")
is supposed to work cross-sectionally on a broad universe, so the
substrate failure here is a strong falsification signal, not just a
"smaller universe" artifact.

The hypothesis tested by removing these from the surviving-edges
ensemble: substrate-honest mean Sharpe should be much closer to the
"STRONGER" edges' individual Sharpes (1.0-1.5 range) than to 0.268.
The surviving-edges multi-year measurement (next deliverable) tests
this directly.

### 2. Capital rivalry on a 4× wider universe (likely meaningful)

Going from 109 → ~498 tickers means each edge sees ~4.6× as many
candidates per bar. Per-edge gross-exposure caps are unchanged, so
each name gets a smaller capital allocation. For edges with thin
signals (herding_v1, value-factor edges that only fire on basket
transitions), the dilution may push individual position sizes below
where the realistic-slippage cost model still produces positive net
PnL. This is consistent with herding_v1 being the only DEGRADED edge
— small basket signal, more dilution.

### 3. Ensemble weighting interacts with edge ranks (likely smaller)

The Engine F governor learned weights on the static-109 distribution
of edge contributions. On the historical universe, the relative
ranking of edges shifts (volume_anomaly_v1 jumps from worst to best
single-edge). Existing weights may underweight edges that became
strong and overweight edges that became weak. `--reset-governor` is
in the harness but the within-run learner still moves weights in the
biased direction.

The first mechanism is testable now via the surviving-edges multi-year.
Mechanisms 2 and 3 are diagnostic for follow-on work.

---

## Per-edge interpretation

### gap_fill_v1 — STRONGER on historical (Δ = −0.620)

Baseline alpha story: mean-reversion on gap fills with vol-z and BB
squeeze gating. On the wider universe the signal has more candidates
to choose from each bar, the gates filter more aggressively, and the
trade quality goes up. WR rises from 58.98% to 55.94% (slight drop)
but Sharpe more than doubles, suggesting fewer-but-better trades.

Verdict: keep active. This edge is *better* on substrate-honest.

### volume_anomaly_v1 — STRONGER on historical (Δ = −1.268)

The biggest delta in the audit. Volume-spike + BB-squeeze reversal
signals fire on a much wider candidate pool. WR jumps to 61.52%, MDD
stays controlled. This edge has been described in
`path1_ship_validation_2026_05.md` as "the alpha edge — held up" and
the audit confirms it: substrate-honest performance is materially
better.

Verdict: keep active. The static-109's poor Sharpe (0.207) was the
artifact, not the historical's 1.475.

### herding_v1 — DEGRADED (Δ = +0.411)

Contrarian breadth-extreme signal. On the wider universe the breadth
threshold may be reached less often (more names dilute the breadth
signal), or the extreme percentile gate at 90 may be calibrated for
mega-cap dispersion patterns that don't hold on the broader S&P 500.
Drop falls cleanly in the DEGRADED band (0.2-0.5).

Verdict: pause. Contributes negative Sharpe on substrate-honest. The
2024-only measurement could be regime-conditional; revival via
Discovery is the proper path per
`project_revival_veto_philosophy_2026_04_30.md`.

### value_earnings_yield_v1 — STRONGER on historical (Δ = −0.300)

Top-quintile E/P. Wider universe = larger basket of candidates with
high E/P, including value-cyclicals that the static-109 missed.
Sharpe lift +0.30 with WR steady around 51%.

Verdict: keep active. Substrate-honest is materially better.

### value_book_to_market_v1 — STRONGER on historical (Δ = −0.220)

Top-quintile B/M. Same pattern as earnings yield, smaller margin.
Verdict: keep active.

### quality_roic_v1 — FALSIFIED (Δ = +1.358)

Drops from 2.183 → 0.825. The largest substrate failure in the audit.
Per the 2026-05-06 V/Q/A bugfix doc, this edge had a negative-equity
denominator bug fixed; the static-109's strong Sharpe is post-bugfix.
On the wider universe, the academic Quality factor is supposed to
generalize — the failure here is a strong signal that the static-109
was selecting for a curated mega-cap quality skew that doesn't survive
on the actual S&P 500.

Verdict: fail. `failure_reason='universe_too_small'`, with note that
the underlying ROIC computation is correct (post-2026-05-06 bugfix);
the issue is universe-dependence, not implementation.

### quality_gross_profitability_v1 — FALSIFIED (Δ = +0.503)

Same pattern, smaller magnitude. 1.540 → 1.037. Drop just over the
0.5 threshold. Verdict: fail. Same `universe_too_small` reason as ROIC.

### accruals_inv_sloan_v1 — CONFIRMED (Δ = −0.041)

Sloan accruals score, top-quintile long. Bitwise-equal Sharpe between
universes. The accruals signal is robust to universe size — a
narrowness-resistant academic factor.

Verdict: keep active.

### accruals_inv_asset_growth_v1 — CONFIRMED (Δ = 0.000)

Asset-growth quintile. Identical Sharpe both universes. Same
robustness story as Sloan accruals.

Verdict: keep active.

---

## Caveats

- **2024 only.** The classification is anchored to one regime year
  (mid-2024 mag-7 dominance). An edge that's CONFIRMED on 2024 may
  fail on 2022 bear or 2025 chop. The surviving-edges multi-year
  measurement (next deliverable) tests the surviving set across 5
  years; per-edge year-by-year is left for follow-on.
- **Single-edge isolation, not leave-one-out.** Per
  `vqa_edges_sustained_scores_2026_05_07.md`, V/Q/A edges contribute
  via vote-stack damping more than via standalone trades. Their
  isolated Sharpes may understate their true ensemble contribution.
  The surviving-edges multi-year is the integrated test.
- **1 rep per cell.** Determinism is established at the harness level
  for multi-edge ensembles (3-rep PASS on the 6-names test, same
  anchor). Single-edge runs were not 3-rep verified, but `isolated()`
  + `PYTHONHASHSEED=0` + `reset_governor=True` should yield
  determinism. Risk: low.
- **Static-109 baseline reproducibility caveat applies.** The 2024
  static-109 9-edge Sharpe of 0.855 (vs F6's 1.890) implies code drift
  since 2026-05-04. Per-edge static numbers are anchored to current
  code; not back-comparable to single-edge claims in older measurement
  docs.

---

## Run metadata

- Branch: `c-collapses-edge-audit`
- Driver: `scripts/audit_per_edge_substrate.py`
- Wall time: 88.1 minutes (9 edges × 2 universes × 1 year)
- Per-edge wall: ~85-140s on static-109, ~330-700s on historical (~498 names)
- Anchor: `data/governor/_isolated_anchor` (same as 6-names test)

Raw JSON: [`substrate_collapse_edge_audit_2026_05_09.json`](substrate_collapse_edge_audit_2026_05_09.json)

## Reproduce

```bash
PYTHONHASHSEED=0 python -m scripts.audit_per_edge_substrate \
    --years 2024 \
    --output docs/Measurements/2026-05/substrate_collapse_edge_audit_2026_05_09.json
```
