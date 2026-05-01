# Capital Allocation Diagnostic Dashboard

**Date:** 2026-05-01
**Branch:** `dashboard-capital-allocation-view`
**Worktree:** `/Users/jacksonmurphy/Dev/trading_machine-dashboard`
**Trigger:** 2026-04-30 outside reviewer noted that the 2025 rivalry pathology
took weeks of after-the-fact pandas analysis (Agent A,
`scripts/analyze_oos_2025.py`) to surface, when "a live view of per-edge fill
share vs PnL contribution, updated daily, would have caught the rivalry bug
in real time. Cheap, high signal forever after."

This dashboard tab makes that view available during every backtest run.

## What it shows

A new sub-tab **"Capital Allocation"** under the Analytics Hub, alongside
Performance / Governor / Evolution. Three panels + KPI strip + bonus regime
view. Run-UUID dropdown lets the user inspect any historical run; cap and
rolling-window inputs are tunable.

### Panel 1 — Per-edge fill-share vs PnL table

For the selected run UUID:
- `edge`, `status` (active / paused / retired from `edges.yml`)
- `fill_count`, `fill_pct` (share of all fills)
- `total_pnl`, `pnl_pct` (share of total |PnL|)
- `mean_pnl_per_fill` (signed)
- `tier` (lifecycle tier)
- Rivalry-flagged rows highlighted with red left-border and red-tinted background

**Rivalry flag heuristic:** `fill_pct >= 10% AND (total_pnl < 0 OR pnl_pct < fill_pct/2)`.
Catches edges that "consume capital share without earning it back."

### Panel 2 — Fill-share vs PnL-contribution scatter

x = fill share %, y = PnL contribution %, size = fill count, color =
status. Diagonal y=x is "neutral allocation." Below-diagonal edges are
**starving** the system; above-diagonal edges are **starved by** the system.
Zero-PnL reference line drawn dotted-red.

### Panel 3 — Cap-binding diagnostic (rolling fill-share time-series)

Top-8 edges by total fills as line series; rolling window (default 20 days)
of fill share over time. Red dashed horizontal line at the configured cap.
**When a series sits at the cap line, `fill_share_capper` is binding for that
edge.** Below-the-chart text reports binding-day count + top-3 binding edges.

This is a proxy view — the live capper computes share over a rolling
lookback and scales signal strength when an edge is over `cap`. We see
post-cap fill counts in the trade log, so series sitting at the cap line
is the clearest evidence the cap was actively binding (and ringing the
bell on which edge it was binding for).

### Panel 4 (bonus) — Per-regime PnL by edge

Stacked horizontal bars: per edge, realized PnL split by regime
(`robust_expansion`, `emerging_expansion`, `cautious_decline`,
`market_turmoil`, `transitional`). Reveals whether rivalry losses are
regime-specific (audit found `low_vol_factor_v1` lost -$1,180 in
`market_turmoil` alone — visible at a glance here).

### KPI strip

Four cards at top:
1. **Rivalry-flagged edges** — count of red-flagged rows
2. **Top-3-by-fills share** — sum of top-3 fill-share %
3. **Top-3-by-fills PnL** — sum of their realised PnL ($)
4. **Cap-binding days @ cap** — % of days where cap was binding

## Verification — populated against 2025 OOS anchor

**Anchor UUID:** `72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34`
(2025-01-03 → 2025-12-31, prod 109, soft-paused defaults, Sharpe -0.049,
the same trade log
`docs/Audit/oos_2025_decomposition_2026_04.md` analysed).

**Panel 1 output (text-rendered):**

```
edge                       status    fills   fill%     PnL($)    PnL%  mean$/fill  rivalry
momentum_edge_v1           paused     2203  40.07%    -883.23  -9.97%       -0.40    YES
low_vol_factor_v1          paused     1613  29.34%   -2532.67 -28.58%       -1.57    YES
atr_breakout_v1            retired     768  13.97%   -2229.07 -25.15%       -2.90    YES
macro_credit_spread_v1     retired     239   4.35%    +231.08  +2.61%       +0.97
gap_fill_v1                active      234   4.26%    +173.85  +1.96%       +0.74
volume_anomaly_v1          active      191   3.47%   +1933.73 +21.82%      +10.12
growth_sales_v1            paused      122   2.22%     +75.18  +0.85%       +0.62
herding_v1                 active       44   0.80%    +546.59  +6.17%      +12.42
value_trap_v1              paused       33   0.60%     -51.22  -0.58%       -1.55
…
```

The bottom-3-by-PnL edges (`momentum_edge_v1`, `low_vol_factor_v1`,
`atr_breakout_v1`) consume **83.4%** of fills and contribute **-$5,645** of
realised PnL — exact match to audit doc § 1-2. The two starved heroes
(`volume_anomaly_v1` at +$10.12/fill, `herding_v1` at +$12.42/fill) are
visually obvious at the bottom of a fills-sorted table because they have
the highest mean-PnL-per-fill in the entire system.

**Panel 2 (scatter) — sample positions:**

| Edge | fill_share | pnl_share | Δ (pp from diagonal) | Visual |
|---|---|---|---|---|
| momentum_edge_v1 | 40.07% | -9.97% | -50.03 | far below |
| low_vol_factor_v1 | 29.34% | -28.58% | -57.91 | far below |
| atr_breakout_v1 | 13.97% | -25.15% | -39.12 | far below |
| volume_anomaly_v1 | 3.47% | +21.82% | +18.34 | far above |
| herding_v1 | 0.80% | +6.17% | +5.37 | above |

Three rivalry edges sit visibly far below the diagonal; the two starved
heroes sit visibly above. Even without reading the labels, the cluster
geometry — three big circles in the bottom-right quadrant, two tiny
circles in the top-left — diagnoses the pathology.

**Panel 3 (cap-binding) — anchor result:**

```
Cap-binding days: 197 / 197 (100.0% of trading days).
Top binders: momentum_edge_v1 (151 days), low_vol_factor_v1 (46 days).
Rolling window: 20 days. Slack: 0.5pp.
```

This matches the cap_bracket sweep audit's "binding 99.5% of entry-days at
cap=0.20 predominantly on momentum_edge_v1." Visually, the
`momentum_edge_v1` series rides the cap line essentially the entire 2025
window, with `low_vol_factor_v1` pinned at the cap during the
April-2025 turmoil window when momentum_edge tags loosened.

**Did the rivalry pattern surface visually as expected?** Yes —
unambiguously, on a cold-look at the rendered tab a viewer would diagnose
the system's 2025 disease in under 60 seconds.

## Usage

From the dashboard root:

```bash
cd /Users/jacksonmurphy/Dev/trading_machine
python -m cockpit.dashboard_v2.app
# open http://127.0.0.1:8050
# click "Analytics" tab → "Capital Allocation" sub-tab
```

In the tab:
1. Select a Run UUID from the dropdown (newest first; preview shows date
   range, fill count, edge count).
2. Adjust **Fill-share cap** to test sensitivity (default 0.20 — current
   production).
3. Adjust **Rolling window (days)** to control smoothing in panel 3
   (default 20).

For automated post-backtest review the loaders are also pure-pandas and
importable from any script:

```python
from cockpit.dashboard_v2.utils.capital_allocation_loader import (
    load_trades, compute_edge_summary, flag_rivalry,
    compute_rolling_fill_share, cap_binding_summary,
)
trades = load_trades("<run_uuid>")
print(flag_rivalry(compute_edge_summary(trades)))
```

## Files added / modified

```
cockpit/dashboard_v2/utils/capital_allocation_loader.py   (new)
cockpit/dashboard_v2/tabs/capital_allocation_tab.py       (new)
cockpit/dashboard_v2/callbacks/capital_allocation_callbacks.py  (new)
cockpit/dashboard_v2/tabs/analytics_parent_tab.py         (+5 lines: nav tab)
cockpit/dashboard_v2/callbacks/analytics_navigation_callbacks.py  (+3 lines)
cockpit/dashboard_v2/app.py                               (+2 lines: register)
tests/test_capital_allocation_dashboard.py                (new — 7 tests)
docs/Audit/dashboard_capital_allocation_2026_05.md        (this doc)
```

`cockpit/dashboard/` was NOT touched (deprecated per CLAUDE.md).
No engine code was modified. No data files were modified.

## Smoke-test results

All 7 tests pass (28-second total runtime):

```
tests/test_capital_allocation_dashboard.py::test_anchor_trades_load PASSED
tests/test_capital_allocation_dashboard.py::test_per_edge_summary_matches_audit_numbers PASSED
tests/test_capital_allocation_dashboard.py::test_rivalry_flag_catches_bottom_three PASSED
tests/test_capital_allocation_dashboard.py::test_cap_binding_dominantly_momentum PASSED
tests/test_capital_allocation_dashboard.py::test_layout_renders_without_error PASSED
tests/test_capital_allocation_dashboard.py::test_callbacks_register_without_error PASSED
tests/test_capital_allocation_dashboard.py::test_callback_executes_against_anchor_uuid PASSED
```

The numeric assertions (`volume_anomaly_v1` PnL = +$1933.73 ± $0.50 on 191
fills; `momentum_edge_v1` 2203 fills; cap binding ≥ 95% of days
dominated by momentum_edge_v1) directly encode the rivalry pattern, so
these tests will fail loudly if a future change accidentally hides it.

## Caveats / unresolved

1. **Cap-binding is a proxy, not a direct measurement.** The live
   `fill_share_capper` scales an edge's **signal strength** when its
   trailing share would exceed `cap`; we observe the post-cap fill counts
   in the trade log and read off "an edge sitting at the cap line" as
   evidence the cap was binding. This is what the human-readable shape of
   the curve looks like — accurate enough for at-a-glance diagnosis,
   but if a future agent wants the exact strength-scaling history, that
   would require logging it from `signal_processor` (engine work, out
   of scope).
2. **PnL is realised only.** Same caveat as the source audit doc —
   open-position unrealised PnL at run-end is excluded. For Q1 2025 the
   gap was tiny (~$430 difference between equity and realised); for runs
   ending mid-trade-cycle the gap could be larger.
3. **No multi-run comparison view yet.** The dropdown selects one UUID at
   a time. A side-by-side A/B comparison of two runs (e.g., post-fix vs
   pre-fix) would be a natural next addition but adds layout complexity;
   shipped one-run-at-a-time per the 2-3hr scoping.
4. **Run-UUID listing is mtime-sorted, not metadata-sorted.** A run that
   starts in 2021 but was generated yesterday will list above a run
   that ran for 2025 weeks ago. The dropdown label includes start/end
   dates so the operator can disambiguate; not worth a rebuild today.
5. **`dash_table.DataTable` is deprecated** in upcoming Dash versions in
   favour of `dash-ag-grid`. Existing dashboard tabs use `DataTable` so
   the new tab matches that idiom; migrate together if/when the rest of
   the dashboard moves.
