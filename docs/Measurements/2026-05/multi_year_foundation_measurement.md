# Multi-Year Foundation Measurement

Generated: 2026-05-04T23:55:13
Total runs: 15 (5 years × 3 reps)

## Per-year results

| Year | Reps | Sharpe (rep1, rep2, rep3) | Sharpe range | CAGR%(mean) | Canon md5 unique | Determinism |
|---|---|---|---:|---:|---:|---|
| 2021 | 3 | 1.6660, 1.6660, 1.6660 | 0.0000 | 7.58 | 1/3 | PASS (bitwise) |
| 2022 | 3 | 0.5830, 0.5830, 0.5830 | 0.0000 | 4.09 | 1/3 | PASS (bitwise) |
| 2023 | 3 | 1.3870, 1.3870, 1.3870 | 0.0000 | 6.92 | 1/3 | PASS (bitwise) |
| 2024 | 3 | 1.8900, 1.8900, 1.8900 | 0.0000 | 7.86 | 1/3 | PASS (bitwise) |
| 2025 | 3 | 0.9540, 0.9540, 0.9540 | 0.0000 | 4.39 | 1/3 | PASS (bitwise) |

## Cross-year aggregate

- **Mean Sharpe across years:** 1.2960
- Std (across-year):              0.5299
- Min:                            0.5830 (2022)
- Max:                            1.8900 (2024)

## Foundation Gate evaluation

Gate criterion: 2025 OOS Sharpe ≥ 0.5 deterministic. Multi-year extension: **mean Sharpe across 2021-2025 ≥ 0.5**.

- **Gate status: PASS** (mean Sharpe 1.2960 ≥ 0.5)
- Worst year: 2022 (Sharpe 0.5830)
- Best year:  2024 (Sharpe 1.8900)
- Best-vs-worst spread: 1.3070 (cross-year regime sensitivity)

## Raw run records

```json
[
  {
    "year": 2021,
    "rep": 1,
    "run_id": "068be96a-8df4-441d-9a2b-cc46d6de2c21",
    "sharpe": 1.666,
    "cagr_pct": 7.58,
    "max_drawdown_pct": -3.58,
    "win_rate_pct": 51.13,
    "total_trades": null,
    "trades_canon_md5": "d84603459fc6a51dacdda05175684b3c",
    "wall_time_seconds": 266.8,
    "ok": true
  },
  {
    "year": 2021,
    "rep": 2,
    "run_id": "eefec584-6d74-40ca-a7f3-1de85afe3dc4",
    "sharpe": 1.666,
    "cagr_pct": 7.58,
    "max_drawdown_pct": -3.58,
    "win_rate_pct": 51.13,
    "total_trades": null,
    "trades_canon_md5": "d84603459fc6a51dacdda05175684b3c",
    "wall_time_seconds": 255.5,
    "ok": true
  },
  {
    "year": 2021,
    "rep": 3,
    "run_id": "49ecfb70-b039-419c-8479-2b2ce117a548",
    "sharpe": 1.666,
    "cagr_pct": 7.58,
    "max_drawdown_pct": -3.58,
    "win_rate_pct": 51.13,
    "total_trades": null,
    "trades_canon_md5": "d84603459fc6a51dacdda05175684b3c",
    "wall_time_seconds": 255.5,
    "ok": true
  },
  {
    "year": 2022,
    "rep": 1,
    "run_id": "1654675a-d964-4c31-8c60-1f6f0793afaf",
    "sharpe": 0.583,
    "cagr_pct": 4.09,
    "max_drawdown_pct": -5.03,
    "win_rate_pct": 42.99,
    "total_trades": null,
    "trades_canon_md5": "3c63e8a1bc68829ea4d7c399bc51d7e3",
    "wall_time_seconds": 259.6,
    "ok": true
  },
  {
    "year": 2022,
    "rep": 2,
    "run_id": "a3bd4f41-dd92-4913-adbf-47a61e04179e",
    "sharpe": 0.583,
    "cagr_pct": 4.09,
    "max_drawdown_pct": -5.03,
    "win_rate_pct": 42.99,
    "total_trades": null,
    "trades_canon_md5": "3c63e8a1bc68829ea4d7c399bc51d7e3",
    "wall_time_seconds": 280.5,
    "ok": true
  },
  {
    "year": 2022,
    "rep": 3,
    "run_id": "3b8577de-c51c-4c8f-ac88-2e29f6499830",
    "sharpe": 0.583,
    "cagr_pct": 4.09,
    "max_drawdown_pct": -5.03,
    "win_rate_pct": 42.99,
    "total_trades": null,
    "trades_canon_md5": "3c63e8a1bc68829ea4d7c399bc51d7e3",
    "wall_time_seconds": 287.4,
    "ok": true
  },
  {
    "year": 2023,
    "rep": 1,
    "run_id": "18da77b7-7e95-4ff6-85ef-956209151cef",
    "sharpe": 1.387,
    "cagr_pct": 6.92,
    "max_drawdown_pct": -3.3,
    "win_rate_pct": 52.96,
    "total_trades": null,
    "trades_canon_md5": "6783917ed64df3081d2af703184cec81",
    "wall_time_seconds": 278.0,
    "ok": true
  },
  {
    "year": 2023,
    "rep": 2,
    "run_id": "a577bbde-80ac-4b95-a73a-12964f3e1ab8",
    "sharpe": 1.387,
    "cagr_pct": 6.92,
    "max_drawdown_pct": -3.3,
    "win_rate_pct": 52.96,
    "total_trades": null,
    "trades_canon_md5": "6783917ed64df3081d2af703184cec81",
    "wall_time_seconds": 301.7,
    "ok": true
  },
  {
    "year": 2023,
    "rep": 3,
    "run_id": "b1f88ae3-6ba9-4a83-bd03-7a35a76f3b31",
    "sharpe": 1.387,
    "cagr_pct": 6.92,
    "max_drawdown_pct": -3.3,
    "win_rate_pct": 52.96,
    "total_trades": null,
    "trades_canon_md5": "6783917ed64df3081d2af703184cec81",
    "wall_time_seconds": 296.0,
    "ok": true
  },
  {
    "year": 2024,
    "rep": 1,
    "run_id": "c65da497-6384-4ca7-9ba6-034d55246462",
    "sharpe": 1.89,
    "cagr_pct": 7.86,
    "max_drawdown_pct": -2.89,
    "win_rate_pct": 49.8,
    "total_trades": null,
    "trades_canon_md5": "96513df9703554bb7e7e6d6667bd7084",
    "wall_time_seconds": 289.5,
    "ok": true
  },
  {
    "year": 2024,
    "rep": 2,
    "run_id": "8de6d570-d124-4481-a8fa-0292e86e0dfb",
    "sharpe": 1.89,
    "cagr_pct": 7.86,
    "max_drawdown_pct": -2.89,
    "win_rate_pct": 49.8,
    "total_trades": null,
    "trades_canon_md5": "96513df9703554bb7e7e6d6667bd7084",
    "wall_time_seconds": 304.9,
    "ok": true
  },
  {
    "year": 2024,
    "rep": 3,
    "run_id": "b53ba7e1-5450-4dd6-94aa-d9dbe6fc35e4",
    "sharpe": 1.89,
    "cagr_pct": 7.86,
    "max_drawdown_pct": -2.89,
    "win_rate_pct": 49.8,
    "total_trades": null,
    "trades_canon_md5": "96513df9703554bb7e7e6d6667bd7084",
    "wall_time_seconds": 304.8,
    "ok": true
  },
  {
    "year": 2025,
    "rep": 1,
    "run_id": "f908f26a-76a8-458a-9b7c-84df8a98db83",
    "sharpe": 0.954,
    "cagr_pct": 4.39,
    "max_drawdown_pct": -3.13,
    "win_rate_pct": 49.18,
    "total_trades": null,
    "trades_canon_md5": "1ee035b19048611c9907473417599366",
    "wall_time_seconds": 316.8,
    "ok": true
  },
  {
    "year": 2025,
    "rep": 2,
    "run_id": "d2375ab0-5dc3-48d6-a3b7-2df5a14ce021",
    "sharpe": 0.954,
    "cagr_pct": 4.39,
    "max_drawdown_pct": -3.13,
    "win_rate_pct": 49.18,
    "total_trades": null,
    "trades_canon_md5": "1ee035b19048611c9907473417599366",
    "wall_time_seconds": 280.3,
    "ok": true
  },
  {
    "year": 2025,
    "rep": 3,
    "run_id": "0d1a2343-f01f-49ed-8c9a-f09590b8a2d2",
    "sharpe": 0.954,
    "cagr_pct": 4.39,
    "max_drawdown_pct": -3.13,
    "win_rate_pct": 49.18,
    "total_trades": null,
    "trades_canon_md5": "1ee035b19048611c9907473417599366",
    "wall_time_seconds": 274.0,
    "ok": true
  }
]
```