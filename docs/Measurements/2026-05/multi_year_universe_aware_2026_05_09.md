# Multi-Year Foundation Measurement

Generated: 2026-05-06T19:38:27
Universe mode: historical (survivorship-aware S&P 500)
Total runs: 5 (5 years × 1 reps)

## Per-year results

| Year | Reps | Sharpe (rep1, rep2, rep3) | Sharpe range | CAGR%(mean) | Canon md5 unique | Determinism |
|---|---|---|---:|---:|---:|---|
| 2021 | 1 | 0.8620 | 0.0000 | 3.25 | 1/1 | PASS (bitwise) |
| 2022 | 1 | -0.3210 | 0.0000 | -3.05 | 1/1 | PASS (bitwise) |
| 2023 | 1 | 1.2920 | 0.0000 | 7.42 | 1/1 | PASS (bitwise) |
| 2024 | 1 | 0.2680 | 0.0000 | 1.11 | 1/1 | PASS (bitwise) |
| 2025 | 1 | 0.4360 | 0.0000 | 1.91 | 1/1 | PASS (bitwise) |

## Cross-year aggregate

- **Mean Sharpe across years:** 0.5074
- Std (across-year):              0.6103
- Min:                            -0.3210 (2022)
- Max:                            1.2920 (2023)

## Foundation Gate evaluation

Gate criterion: 2025 OOS Sharpe ≥ 0.5 deterministic. Multi-year extension: **mean Sharpe across 2021-2025 ≥ 0.5**.

- **Gate status: PASS** (mean Sharpe 0.5074 ≥ 0.5)
- Worst year: 2022 (Sharpe -0.3210)
- Best year:  2023 (Sharpe 1.2920)
- Best-vs-worst spread: 1.6130 (cross-year regime sensitivity)

## Raw run records

```json
[
  {
    "year": 2021,
    "rep": 1,
    "run_id": "90c9c89d-e36b-444b-9397-845f820cabf7",
    "sharpe": 0.862,
    "cagr_pct": 3.25,
    "max_drawdown_pct": -3.24,
    "win_rate_pct": 46.51,
    "total_trades": null,
    "trades_canon_md5": "e18bea36b4ac262faea089ba0635151e",
    "wall_time_seconds": 1452.9,
    "ok": true
  },
  {
    "year": 2022,
    "rep": 1,
    "run_id": "ba0a1d15-62f6-4a45-a7bb-6eae1a4064ef",
    "sharpe": -0.321,
    "cagr_pct": -3.05,
    "max_drawdown_pct": -9.46,
    "win_rate_pct": 45.05,
    "total_trades": null,
    "trades_canon_md5": "6d739af61d39cac8a936d625dfeb1f76",
    "wall_time_seconds": 1505.0,
    "ok": true
  },
  {
    "year": 2023,
    "rep": 1,
    "run_id": "d585059e-f8ad-4d59-9c1c-f98b87a70d6e",
    "sharpe": 1.292,
    "cagr_pct": 7.42,
    "max_drawdown_pct": -4.46,
    "win_rate_pct": 50.23,
    "total_trades": null,
    "trades_canon_md5": "9c00df4b733b99756e771dbb5b06050b",
    "wall_time_seconds": 1398.9,
    "ok": true
  },
  {
    "year": 2024,
    "rep": 1,
    "run_id": "9b760b5c-3cd0-4f76-9e4e-acdec423730e",
    "sharpe": 0.268,
    "cagr_pct": 1.11,
    "max_drawdown_pct": -3.52,
    "win_rate_pct": 41.41,
    "total_trades": null,
    "trades_canon_md5": "965d5a4513c52a4357a244a88e74b791",
    "wall_time_seconds": 1708.0,
    "ok": true
  },
  {
    "year": 2025,
    "rep": 1,
    "run_id": "31be49d3-b5de-443e-84dc-f0c8495223a2",
    "sharpe": 0.436,
    "cagr_pct": 1.91,
    "max_drawdown_pct": -2.86,
    "win_rate_pct": 47.02,
    "total_trades": null,
    "trades_canon_md5": "bafacca2f317c3f033c5aca0e98c2a4f",
    "wall_time_seconds": 1445.6,
    "ok": true
  }
]
```