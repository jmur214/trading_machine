# Six-Names Isolation Test — 2026-05-09

**Question:** How much of the static-109 vs historical-S&P-500 Sharpe
gap (the F6 COLLAPSES finding) is explained by 6 non-S&P 500 ultra-vol
names that the static-109 carries: COIN, MARA, RIOT, DKNG, PLTR, SNOW?

**Answer:** **The hypothesis is inverted.** The 6 names are a *drag*
on static-109, not a prop. Removing them improves Sharpe from 0.855 to
**2.150** (+1.295). The substrate-bias gap (static-103 → historical
S&P 500) is **diffuse across the 367+ other names**, not concentrated
in the 6 ultra-vol picks.

The "asymmetric upside lottery" interpretation of static-109 is wrong.
What the static config actually does is select a curated mid-large-cap
subset on which the strategy works (Sharpe 2.15 with 103 names), then
muddy that subset by adding 6 ultra-vol names that hurt by ~1.3 Sharpe.
The substrate-honest collapse remains real — it just doesn't trace to
the obvious 6 names.

## Status

- **Status:** CURRENT
- **Falsifies (partially):** the hypothesis section in
  `project_universe_aware_collapses_2026_05_09.md` that 6-name
  ultra-vol exposure was meaningful upside in static-109. It was net
  *negative*, not net positive.
- **Reframes:** the "asymmetric-upside sleeve" pivot recommendation
  from `project_retail_capital_constraint_2026_05_01.md` — those 6
  names specifically are not the asymmetric-upside engine; cleaner
  curation around the 103-name subset would be. The pivot rationale
  still holds; the candidate names list does not.

---

## Three universes, one year, three reps each

Year: **2024** (the largest substrate-collapse year per F6,
ΔSharpe = −1.622 in F6's static-vs-historical comparison).
Anchor: `data/governor/_isolated_anchor` (current code state, post
2026-05-07 V/Q/A sustained-scores fix).
Determinism: bitwise PASS — all 3 reps within each variant produced
identical canon md5s and identical Sharpes.

| Variant | Universe | n_tickers | Sharpe (3 reps) | CAGR % | MDD % | WR % | Wall (s/rep) |
|---|---|---:|---:|---:|---:|---:|---:|
| **A** | static-109 (default) | 109 | **0.855, 0.855, 0.855** | 3.27 | −3.25 | 48.50 | ~360 |
| **B** | static-103 (drop 6 non-S&P) | 103 | **2.150, 2.150, 2.150** | 9.23 | −2.63 | 49.61 | ~330 |
| **C** | historical S&P 500 union | ~498 | **0.268, 0.268, 0.268** | 1.11 | −3.52 | 41.41 | ~1900 |

**6 dropped names in variant B:** COIN, DKNG, MARA, PLTR, RIOT, SNOW.

### Deltas

| Comparison | ΔSharpe | Interpretation |
|---|---:|---|
| **A − B** | **−1.295** | The 6 ultra-vol names HURT static-109 by 1.30 Sharpe. They are net-negative inclusions, not asymmetric upside. |
| **A − C** | **+0.587** | Substrate-honest collapse from static-109 baseline. Smaller than F6's documented 1.622 because of code drift since 2026-05-04 (see "Reproducibility note" below). |
| **B − C** | **+1.882** | Substrate-honest collapse from the cleaner 103-name peak. This is the actual size of the substrate-curation effect. |

### Pct-of-gap explained by the 6 names

The original framing was: "if A − B ≈ A − C, the 6 names are the entire
substrate-bias story." The result is the opposite — A − B is *negative*
while A − C is positive. The arithmetic ratio (A − B) / (A − C) is
**−220.6%** — meaning the 6 names explain less than 0% of the substrate
gap; they actively work *against* the supposed bias direction.

The honest read: the 6 names contribute negative alpha; the strategy on
static-103 is stronger than static-109; the 103 → 498 substrate
expansion is what destroys the strategy.

---

## What this changes about the F6 verdict

F6 said: COLLAPSES (mean Sharpe 1.296 → 0.507, −0.789, −61%).

This isolation test refines that:

1. **The static-109 baseline of 1.296 was understating the static
   strategy's "biased peak."** The same code on static-103 yields 2.15
   on 2024 (vs 0.855 on static-109). If the historical baseline of
   1.296 had been measured on static-103 instead, the F6 collapse would
   have looked even *worse*.
2. **The collapse is universe-substrate-driven, not 6-name-driven.**
   The diffuse 367+ S&P 500 names that the static config omits — broad
   defensive sectors, smaller financials, real estate, healthcare,
   cyclicals — are where the strategy fails to find alpha and where
   diversification dilutes signal.
3. **The "deliberate asymmetric-upside sleeve" pivot needs different
   ingredients than the 6 names.** COIN/MARA/RIOT/DKNG/PLTR/SNOW
   contributed negative Sharpe (−1.30) under current code with realistic
   slippage and 2024 conditions. A genuine asymmetric-upside sleeve
   would need a different selection methodology, not those names.

---

## Reproducibility note (important)

The F6 verdict cited 2024 Sharpes of **1.890 (static-109)** and
**0.268 (historical)**, ΔSharpe = −1.622. In this isolation test, the
2024 historical-universe Sharpe reproduced exactly (0.268, same canon
md5 as the F6 run: `965d5a4513c52a4357a244a88e74b791`). But the 2024
static-109 Sharpe came back as **0.855**, not 1.890 — a **−1.04
discrepancy from the 2026-05-04 baseline on the supposedly identical
config**.

Hypothesis: code drift since 2026-05-04 has degraded static-109
performance. Candidates:
- 2026-05-07 V/Q/A sustained-scores fix
  (`vqa_edges_sustained_scores_2026_05_07.md`) — added 6 V/Q/A
  fundamental edges to the active set, changed signal aggregation
  semantics. The 2026-05-04 baseline only had the 3 technical edges
  (gap_fill, volume_anomaly, herding) active; the current 9-edge active
  set materially changes the signal mix.
- Phase A determinism-cleanup work (A1+A2+A3 merged 2026-05-07) may
  have changed module init / governor reset ordering, though these
  passed determinism harness verification.

**Implication for this audit:** the static-109 baseline used by F6
(1.890) is no longer reproducible on current code. All comparisons
in this isolation test and the per-edge audit are anchored to current
code on the same governor anchor — internally coherent, but **not
backwards-comparable to numbers cited in pre-2026-05-09 docs and
memory entries.**

This also means the F6 verdict's documented ΔSharpe of −1.622 should
be re-stated as −0.587 on current code (0.855 − 0.268). The qualitative
COLLAPSES verdict still holds — substrate-honest 0.268 is dramatically
worse than any reasonable target — but the magnitude reported in F6 was
inflated by stale-baseline comparison.

---

## Run metadata

- Branch: `c-collapses-edge-audit`
- Driver: `scripts/audit_six_names_isolation.py` (new)
- Anchor: `data/governor/_isolated_anchor` (md5s identical to F6 run)
- Wall time total: 130.2 minutes
- Deterministic harness: `PYTHONHASHSEED=0`, `isolated()` per rep
- Variant B mechanism: atomic backup/restore of
  `config/backtest_settings.json` with the 6 names removed; original
  restored on exit (verified post-run)

| Variant | Run IDs |
|---|---|
| A rep1 | `f2c5559f-e3c5-4852-8423-e5481f42a4ea` |
| A rep2 | `80e74343-b372-45e9-82ee-348e46de1bba` |
| A rep3 | `ccc2c6fd-02fa-4bfd-a5ed-f882fa72add3` |
| B rep1 | `9068cdf0-b586-4330-a1fa-9c2ad3cb105d` |
| B rep2 | `56ddd494-53f7-41b1-a939-cbf23b998171` |
| B rep3 | `db7eb21e-4480-41ff-af8e-8411c467ecfa` |
| C rep1 | `45514a19-e9ec-4d09-8fbf-733707f18b41` |
| C rep2 | `b6504096-9eff-4573-87af-cd7e30aad8ab` |
| C rep3 | `87f083a9-610e-4aae-bf84-de1485a42588` |

| Variant | Canon md5 (all 3 reps identical within variant) |
|---|---|
| A | `9a6b12b86a7468905785b89fd3cfccbd` |
| B | `a9ab47bbedf56cf421c5fdb353a02783` |
| C | `965d5a4513c52a4357a244a88e74b791` |

Raw JSON: [`six_names_isolation_2026_05_09.json`](six_names_isolation_2026_05_09.json)

## Reproduce

```bash
PYTHONHASHSEED=0 python -m scripts.audit_six_names_isolation \
    --year 2024 --runs 3 \
    --output docs/Measurements/2026-05/six_names_isolation_2026_05_09.json
```
