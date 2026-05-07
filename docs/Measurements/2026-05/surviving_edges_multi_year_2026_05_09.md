# Surviving-Edges Substrate-Honest Multi-Year — 2026-05-09

**Question:** With the 2 FALSIFIED quality edges and 1 DEGRADED herding
edge removed, what does multi-year Sharpe look like on the substrate-
honest S&P 500 universe — the substrate-honest "real" Foundation Gate
number?

**Answer:** **Mean Sharpe 0.9154** (2021-2025 × 1 rep). Lifts the
verdict bucket from F6's **COLLAPSES** (0.5074, 0.3-0.5 band) into
**PARTIAL** (0.7-1.1 band, "recalibrate") — a +0.408 Sharpe improvement
on the same universe just by dropping 3 edges.

But the surviving set is **strongly regime-conditional**: huge wins in
2021/2023/2024 (bull and mag-7-dominance), and *worse* in 2022 (bear)
and 2025 (chop) than the 9-edge ensemble. The dropped quality edges
were apparently providing some defensive hedge that the surviving set
lacks.

## Status

- **Status:** CURRENT
- **Refines:** `universe_aware_verdict_2026_05_09.md` — F6's COLLAPSES
  verdict on the 9-edge ensemble does NOT mean the strategy lacks
  substrate-honest alpha. Removing the 2 quality edges that overfit
  to the curated mega-cap quality skew rescues the substrate-honest
  Sharpe from 0.507 → 0.915 on the same window.
- **Reframes:** `path_c_deferred_2026_05_06.md` — the regime-conditional
  story is back, but the conditioning is now *bull-vs-bear/chop*, not
  *static-109-vs-historical*. The next workstream is a defensive
  layer/hedge/regime gate, not a universe rebuild.

---

## Method

- **Edges:** 6 surviving edges from
  `substrate_collapse_edge_audit_2026_05_09.md`:
  - 4 STRONGER on historical: gap_fill_v1, volume_anomaly_v1,
    value_earnings_yield_v1, value_book_to_market_v1
  - 2 CONFIRMED within ±0.2: accruals_inv_sloan_v1,
    accruals_inv_asset_growth_v1
- **Universe:** historical S&P 500 union (~498 names per anchor year
  via `use_historical_universe=true`).
- **Years:** 2021, 2022, 2023, 2024, 2025 (all calendar-year backtests).
- **Reps:** 1 per year (within-year determinism implicit from prior
  bitwise-PASS measurements on the same anchor).
- **Driver:** `scripts/audit_surviving_edges_multi_year.py` with
  `exact_edge_ids` pinning the 6 surviving edges. Each year run
  inside `isolated()` for governor anchor consistency.

---

## Results

### Per-year Sharpe

| Year | F6 9-edge (universe-aware) | Surviving 6-edge | Δ | regime |
|---|---:|---:|---:|---|
| 2021 | 0.862 | **2.811** | +1.949 | bull / megacap concentration |
| 2022 | −0.321 | **−0.508** | −0.187 | bear |
| 2023 | 1.292 | **1.799** | +0.507 | bull / Mag-7 |
| 2024 | 0.268 | **0.582** | +0.314 | Mag-7 dominance |
| 2025 | 0.436 | **−0.107** | −0.543 | chop |
| **Mean** | **0.5074** | **0.9154** | **+0.408** | |

### Per-year auxiliary metrics

| Year | CAGR % | MDD % | Win Rate % | Wall (s) |
|---|---:|---:|---:|---:|
| 2021 | 13.34 | −2.35 | 60.09 | 851 |
| 2022 | −4.29 | −9.11 | 37.61 | 1106 |
| 2023 | 8.00 | −3.78 | 58.96 | 735 |
| 2024 | 2.24 | −2.31 | 45.76 | 731 |
| 2025 | −0.85 | −7.79 | 46.81 | 712 |

### Verdict bucket (per F6 schema)

| Bucket | Mean range | Verdict | This run |
|---|---|---|---|
| Substrate-real | within ±0.15 of 1.296 | downstream confirmed | — |
| Universe artifact partial | 0.7-1.1 | **recalibrate** | **0.915 ← here** |
| Most "alpha" was selection bias | 0.3-0.5 | reset directive | (was: 0.507) |

The surviving-edges run lands cleanly in the PARTIAL band. Reading the
F6 verdict table: "recalibrate." This is a real lift from the COLLAPSES
verdict, but it doesn't claim substrate-real alpha (≥1.15).

---

## What changed vs the 9-edge ensemble

The 9-edge ensemble lost on substrate-honest because of 2 specific
edges: `quality_roic_v1` (per-edge audit Δ = +1.358) and
`quality_gross_profitability_v1` (Δ = +0.503). Both are top-quintile
quality factors. On a curated mega-cap subset, the static-109 selection
implicitly carried a quality skew — most of the names had high ROIC
already — and the top-quintile-of-109 was a meaningful subset. On the
broader S&P 500, the academic Quality factor was supposed to generalize
but doesn't on this implementation. The full failure mode requires
deeper investigation; in the meantime, both are tagged
`failure_reason='universe_too_small'` and parked.

The 1 DEGRADED edge (`herding_v1`, Δ = +0.411) is a contrarian breadth-
extreme signal whose 90th-percentile threshold is calibrated for
mega-cap dispersion patterns. On a wider universe the breadth signal
fires less sharply, hence the drop. Tagged `paused` with the same
`universe_too_small` reason.

---

## The regime-conditional caveat

The surviving 6-edge set produces a **bull-driven mean**: 2021's 2.811
Sharpe is the heaviest weight by far, with 2023's 1.799 second. In the
two adverse regimes (2022 bear, 2025 chop), the surviving set produces
*more negative* Sharpe than the 9-edge ensemble:

- 2022: F6 = −0.321 vs Surviving = −0.508 (worse by 0.187)
- 2025: F6 = +0.436 vs Surviving = −0.107 (worse by 0.543)

The implication: the falsified quality edges were a *defensive layer*
that the surviving set lacks. In bear/chop, top-quintile high-ROIC
names tend to be defensives (consumer staples, healthcare, utilities)
that resist drawdowns. Removing them from the active set means the
surviving long-biased value/factor edges have no offsetting position.

This is not a reason to put the FALSIFIED edges back. They overfit on
the curated universe and the implementation has a real generalization
problem. The right next move is to design a deliberate
**substrate-honest defensive layer** — either:

1. A regime-conditional gate on the existing edges (turn long exposure
   off / down in bear and chop), or
2. A new defensive edge that earns Sharpe specifically in bear/chop
   regimes.

Neither is in scope for this audit. The audit's job was substrate
honesty; the regime-conditional finding is the next workstream.

---

## What this means for forward planning

1. **The substrate-honest mean is 0.915, not 0.507.** F6's COLLAPSES
   verdict was correct on the 9-edge ensemble; with the falsified
   edges removed, the strategy is in PARTIAL territory. That's a
   meaningful upgrade but not enough to claim substrate-real alpha.

2. **The asymmetric-upside-sleeve pivot is NOT the right next move.**
   The 6-names test inverted the small-universe-tail-capture
   hypothesis: those specific 6 names hurt static-109. The path
   forward is substrate-honest with the surviving edges, not a pivot
   to a deliberately curated small universe.

3. **The next workstream is a regime-conditional defensive layer.**
   2022 and 2025 negative Sharpes need to be addressed via bear/chop
   gating or a new defensive edge that's substrate-honest by design.
   Engine E HMM work (per `regime_signal_falsified_2026_05_06.md`) is
   blocked on rebuilding the input panel; that work becomes
   higher-priority now.

4. **The 0.915 mean is fragile to single-year regime variance.** The
   max-min spread across 5 years is 3.319 Sharpe (2.811 in 2021,
   −0.508 in 2022). Reporting any single-year peak from 2021/2023/2024
   without the regime caveat would re-introduce the same kind of
   reporting bias F6 corrected.

---

## Caveats

- **1 rep per year.** Determinism is implicit from the bitwise-PASS
  on the 6-names test using the same anchor. Risk is low but
  ideally re-run with `--runs 3` for the canonical Foundation Gate
  measurement.
- **Code-drift caveat applies.** All numbers are anchored to current
  code (post-2026-05-07 V/Q/A sustained-scores). Not back-comparable
  to pre-2026-05-09 measurement docs that cited 1.296-mean baselines
  on static-109.
- **2022 −0.508 is the load-bearing concern.** Any defensive-layer
  proposal needs to clear that single-year number before the
  surviving-edges set can be considered ship-ready in the substrate-
  honest framing.
- **Missing-CSV ceiling still applies.** Per the F6 doc, 26-54 names
  per year are silently dropped because their CSVs aren't on disk.
  The current 0.915 is therefore an upper bound; running
  `scripts/fetch_universe.py` to backfill those names should be done
  before any commitment cycle.

---

## Run metadata

- Branch: `c-collapses-edge-audit`
- Driver: `scripts/audit_surviving_edges_multi_year.py`
- Wall time total: 68.9 minutes (excluding the failed first attempt
  killed by an OSError on 2022 due to disk pressure)
- Anchor: `data/governor/_isolated_anchor` (same anchor as 6-names
  and per-edge audits)
- Determinism: `PYTHONHASHSEED=0`, `isolated()` per year

| Year | Run ID | Canon md5 | Sharpe |
|---|---|---|---:|
| 2021 | `22dafe52-a5cb-4845-a2dd-e6ef85ddc95e` | `911bb40fccc3ce749e8ac3c008fe50ba` | 2.811 |
| 2022 | `cff81341-b91a-4a3e-9a85-f209249d7912` | `05f4017ad7724114153bd0cdc20077bc` | −0.508 |
| 2023 | `7cb1ba09-7d7e-4175-b69e-77263a747b41` | `72f42af43da04927569d0f32d774749d` | 1.799 |
| 2024 | `e2276077-7dac-442c-ba2b-8d48e57890fb` | `0e6679455f7fa77552324eb3068c8249` | 0.582 |
| 2025 | `35e2f3dd-49e9-45bd-b72f-828efba624a7` | `47a2d04dcd9b2fb7790ddbe8f54bef08` | −0.107 |

Note: 2021 reproduces bitwise-identical to the killed first attempt
(canon md5 `911bb40fccc3ce749e8ac3c008fe50ba` on both runs), confirming
within-year determinism on this anchor.

Raw JSON: [`surviving_edges_multi_year_2026_05_09.json`](surviving_edges_multi_year_2026_05_09.json)

## Reproduce

```bash
PYTHONHASHSEED=0 python -m scripts.audit_surviving_edges_multi_year \
    --years 2021,2022,2023,2024,2025 --runs 1 \
    --edges gap_fill_v1,volume_anomaly_v1,value_earnings_yield_v1,value_book_to_market_v1,accruals_inv_sloan_v1,accruals_inv_asset_growth_v1 \
    --output docs/Measurements/2026-05/surviving_edges_multi_year_2026_05_09.json
```
