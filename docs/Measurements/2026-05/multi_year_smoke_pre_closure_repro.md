# Multi-Year Foundation Measurement

Generated: 2026-05-08T02:19:26
Universe mode: historical (survivorship-aware S&P 500)
Total runs: 1 successful + 0 failed across 1 years; 1 reps

## Per-year results

| Year | Sharpe | PSR(>0) | Sortino | Calmar | IR vs SPY | Skew | Kurt | Tail | Ulcer | MDD% | Determinism |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| 2024 | 0.0000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.00 | 0.00 | PASS (bitwise) |

## Cross-year aggregate

- **Mean Sharpe across years:** 0.0000
- Std (across-year):              0.0000
- Min:                            0.0000 (2024)
- Max:                            0.0000 (2024)

## Foundation Gate evaluation

Gate criterion: 2025 OOS Sharpe ≥ 0.5 deterministic. Multi-year extension: **mean Sharpe across 2021-2025 ≥ 0.5**.

- **Gate status: FAIL** (mean Sharpe 0.0000 < 0.4 — kill thesis re-engages on multi-year data)
- Worst year: 2024 (Sharpe 0.0000)
- Best year:  2024 (Sharpe 0.0000)
- Best-vs-worst spread: 0.0000 (cross-year regime sensitivity)

## Extended metric framework (2026-05-09 upgrade)

- **PSR(SR>0) median across years: 0.000** (min 0.000, max 0.000)
  Interpretation: probability the true Sharpe is > 0 in each year. PSR ≥ 0.95 = strong evidence of skill; ≥ 0.80 = moderate; < 0.50 = no evidence.
- **IR vs SPY median: 0.000** (positive = beating SPY on tracking error; negative = underperforming)
- Calmar median: 0.000  (drawdown-adjusted; relevant for Goal A — compound)
- Skewness mean: 0.000  (roughly symmetric)

**Headline metric (per 2026-05-09 framework upgrade):** PSR median, not Sharpe mean. Sharpe mean kept above for backward compatibility.

## Raw run records

```json
[
  {
    "year": 2024,
    "rep": 1,
    "run_id": "20a3dafc-4a1f-410c-8d24-5195235233c8",
    "sharpe": 0.0,
    "cagr_pct": null,
    "max_drawdown_pct": null,
    "win_rate_pct": null,
    "total_trades": null,
    "trades_canon_md5": "d41d8cd98f00b204e9800998ecf8427e",
    "wall_time_seconds": 2192.1,
    "ok": true
  }
]
```