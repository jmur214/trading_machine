# Gate 1 Reform Falsifiable-Spec Run (2026-05-01T03:19:30)

- Window: `2025-01-01 → 2025-12-31`
- Universe: 108 of 109 production tickers
- Slippage model: `realistic` (base 10.0 bps + ADV-bucketed half-spread + Almgren-Chriss impact)
- Contribution threshold: 0.10
- Gate-1 reform spec: see `docs/Audit/gate1_reform_2026_05.md`

## Verification table

| edge | baseline (3-edge) | with-candidate | **contribution** | threshold | verdict | standalone diag |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| `volume_anomaly_v1` | 0.627 | 0.586 | **-0.040** | 0.10 | **FAIL** | 1.920 |
| `herding_v1` | 0.646 | 0.587 | **-0.059** | 0.10 | **FAIL** | 1.449 |

## Per-edge ensemble baselines

- volume_anomaly_v1 baseline = `['bollinger_reversion_v1', 'earnings_vol_v1', 'gap_fill_v1', 'growth_sales_v1', 'herding_v1', 'insider_cluster_v1', 'low_vol_factor_v1', 'macro_real_rate_v1', 'momentum_edge_v1', 'panic_v1', 'pead_predrift_v1', 'pead_short_v1', 'pead_v1', 'rsi_bounce_v1', 'value_deep_v1', 'value_trap_v1']`
- herding_v1 baseline       = `['bollinger_reversion_v1', 'earnings_vol_v1', 'gap_fill_v1', 'growth_sales_v1', 'insider_cluster_v1', 'low_vol_factor_v1', 'macro_real_rate_v1', 'momentum_edge_v1', 'panic_v1', 'pead_predrift_v1', 'pead_short_v1', 'pead_v1', 'rsi_bounce_v1', 'value_deep_v1', 'value_trap_v1', 'volume_anomaly_v1']`

## Timings

- volume_anomaly_v1: 6.0 min
- herding_v1: 5.8 min

## Raw result JSON

```json
{
  "volume_anomaly_v1": {
    "edge_id": "volume_anomaly_v1",
    "standalone_sharpe": 1.9203185146464468,
    "baseline_sharpe": 0.6268102051574378,
    "with_candidate_sharpe": 0.5863682427710739,
    "contribution_sharpe": -0.04044196238636388,
    "contribution_threshold": 0.1,
    "passed": false,
    "baseline_ids": [
      "bollinger_reversion_v1",
      "earnings_vol_v1",
      "gap_fill_v1",
      "growth_sales_v1",
      "herding_v1",
      "insider_cluster_v1",
      "low_vol_factor_v1",
      "macro_real_rate_v1",
      "momentum_edge_v1",
      "panic_v1",
      "pead_predrift_v1",
      "pead_short_v1",
      "pead_v1",
      "rsi_bounce_v1",
      "value_deep_v1",
      "value_trap_v1"
    ]
  },
  "herding_v1": {
    "edge_id": "herding_v1",
    "standalone_sharpe": 1.4487437774067895,
    "baseline_sharpe": 0.6459252646109418,
    "with_candidate_sharpe": 0.5867869185034309,
    "contribution_sharpe": -0.0591383461075109,
    "contribution_threshold": 0.1,
    "passed": false,
    "baseline_ids": [
      "bollinger_reversion_v1",
      "earnings_vol_v1",
      "gap_fill_v1",
      "growth_sales_v1",
      "insider_cluster_v1",
      "low_vol_factor_v1",
      "macro_real_rate_v1",
      "momentum_edge_v1",
      "panic_v1",
      "pead_predrift_v1",
      "pead_short_v1",
      "pead_v1",
      "rsi_bounce_v1",
      "value_deep_v1",
      "value_trap_v1",
      "volume_anomaly_v1"
    ]
  }
}
```