# Workstream-C Cross-Asset Confirmation Smoke Run

Generated: 2026-05-05T01:33:05

## Cells

| Cell | Cross-asset | HMM | Reps | Sharpes | Range | Canon md5 unique | Bitwise det |
|---|---|---|---:|---|---:|---:|---|
| A (baseline) | OFF | OFF | 3 | 1.8900, 1.8900, 1.8900 | 0.000000 | 1/3 | PASS |
| B (gated) | ON | ON | 3 | 1.8900, 1.8900, 1.8900 | 0.000000 | 1/3 | PASS |

## Sharpe delta

- Cell A mean Sharpe: **1.8900**
- Cell B mean Sharpe: **1.8900**
- Delta (B - A):      **+0.0000**

### Caveat

This is a single-year smoke (one calendar year). Statistical significance of any delta requires the full multi-year measurement (2021-2025) under the determinism harness. That measurement is GAIT-CONDITIONAL on this layer being merged to main. Do NOT draw conclusions about regime-conditional alpha from one year alone — see `project_wash_sale_falsified_multiyear_2026_05_02.md` for prior evidence that single-window measurements can mislead.

Sharpe is **identical** between cells, which is the expected and correct outcome: the cross-asset gate is wired OBSERVABILITY-ONLY this round (advisory.cross_asset_confirm is read-only; Engine B does not consume). A non-zero delta would indicate inadvertent leakage into the live decision path and would block promotion.

## Raw run records

```json
{
  "off": [
    {
      "cell": "A_OFF",
      "rep": 1,
      "year": 2024,
      "run_id": "194073ba-a7ba-4555-ba83-7e2f470f0f97",
      "sharpe": 1.89,
      "cagr_pct": 7.86,
      "max_drawdown_pct": -2.89,
      "win_rate_pct": 49.8,
      "total_trades": null,
      "trades_canon_md5": "96513df9703554bb7e7e6d6667bd7084",
      "wall_time_seconds": 300.0,
      "ok": true
    },
    {
      "cell": "A_OFF",
      "rep": 2,
      "year": 2024,
      "run_id": "3ca5bbfb-4f72-480c-8c2d-b2777dbf5923",
      "sharpe": 1.89,
      "cagr_pct": 7.86,
      "max_drawdown_pct": -2.89,
      "win_rate_pct": 49.8,
      "total_trades": null,
      "trades_canon_md5": "96513df9703554bb7e7e6d6667bd7084",
      "wall_time_seconds": 306.7,
      "ok": true
    },
    {
      "cell": "A_OFF",
      "rep": 3,
      "year": 2024,
      "run_id": "0ff2a7a9-2181-4ace-a3dc-1204607a9179",
      "sharpe": 1.89,
      "cagr_pct": 7.86,
      "max_drawdown_pct": -2.89,
      "win_rate_pct": 49.8,
      "total_trades": null,
      "trades_canon_md5": "96513df9703554bb7e7e6d6667bd7084",
      "wall_time_seconds": 283.5,
      "ok": true
    }
  ],
  "on": [
    {
      "cell": "B_ON",
      "rep": 1,
      "year": 2024,
      "run_id": "1b391d1d-69e1-4bfe-9cc1-1bd88a4b43f1",
      "sharpe": 1.89,
      "cagr_pct": 7.86,
      "max_drawdown_pct": -2.89,
      "win_rate_pct": 49.8,
      "total_trades": null,
      "trades_canon_md5": "96513df9703554bb7e7e6d6667bd7084",
      "wall_time_seconds": 299.1,
      "ok": true
    },
    {
      "cell": "B_ON",
      "rep": 2,
      "year": 2024,
      "run_id": "6b4722fd-07c5-467e-b4a8-11c20e73e1be",
      "sharpe": 1.89,
      "cagr_pct": 7.86,
      "max_drawdown_pct": -2.89,
      "win_rate_pct": 49.8,
      "total_trades": null,
      "trades_canon_md5": "96513df9703554bb7e7e6d6667bd7084",
      "wall_time_seconds": 393.4,
      "ok": true
    },
    {
      "cell": "B_ON",
      "rep": 3,
      "year": 2024,
      "run_id": "c967eaf0-32d8-4c0e-a855-d35c263e05f6",
      "sharpe": 1.89,
      "cagr_pct": 7.86,
      "max_drawdown_pct": -2.89,
      "win_rate_pct": 49.8,
      "total_trades": null,
      "trades_canon_md5": "96513df9703554bb7e7e6d6667bd7084",
      "wall_time_seconds": 301.7,
      "ok": true
    }
  ]
}
```