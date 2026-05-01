# Gate 1 Reform Falsifiable-Spec Run (2026-05-01T01:45:58)

- Window: `2021-01-01 → 2024-12-31`
- Universe: 109 of 109 production tickers
- Slippage model: `realistic` (base 10.0 bps + ADV-bucketed half-spread + Almgren-Chriss impact)
- Contribution threshold: 0.10
- Gate-1 reform spec: see `docs/Audit/gate1_reform_2026_05.md`

## Verification table

| edge | baseline (3-edge) | with-candidate | **contribution** | threshold | verdict | standalone diag |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| `volume_anomaly_v1` | -0.114 | -0.232 | **-0.118** | 0.10 | **FAIL** | 0.176 |
| `herding_v1` | -0.028 | -0.085 | **-0.057** | 0.10 | **FAIL** | -0.242 |

## Per-edge ensemble baselines

- volume_anomaly_v1 baseline = `['gap_fill_v1', 'herding_v1']`
- herding_v1 baseline       = `['gap_fill_v1', 'volume_anomaly_v1']`

## Timings

- volume_anomaly_v1: 15.4 min
- herding_v1: 18.1 min

## Raw result JSON

```json
{
  "volume_anomaly_v1": {
    "edge_id": "volume_anomaly_v1",
    "standalone_sharpe": 0.1758050629403931,
    "baseline_sharpe": -0.1140608214203859,
    "with_candidate_sharpe": -0.2323199932624609,
    "contribution_sharpe": -0.11825917184207499,
    "contribution_threshold": 0.1,
    "passed": false,
    "baseline_ids": [
      "gap_fill_v1",
      "herding_v1"
    ]
  },
  "herding_v1": {
    "edge_id": "herding_v1",
    "standalone_sharpe": -0.2423998174543959,
    "baseline_sharpe": -0.028461715243231583,
    "with_candidate_sharpe": -0.08497901522364502,
    "contribution_sharpe": -0.05651729998041344,
    "contribution_threshold": 0.1,
    "passed": false,
    "baseline_ids": [
      "gap_fill_v1",
      "volume_anomaly_v1"
    ]
  }
}
```