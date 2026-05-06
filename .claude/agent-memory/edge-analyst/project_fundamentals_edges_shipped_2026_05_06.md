---
name: VQA fundamentals edges shipped 2026-05-06
description: 6 SimFin V/Q/A factor edges integrated into Engine A. Smoke 2024 Sharpe 1.91 NOT validated multi-year. Universe-too-small risk live.
type: project
---

Six new fundamental edges shipped via worktree `agent-ae9a84ea103bc8b7c`:

- value_earnings_yield_v1 (TTM_NI / market_cap)
- value_book_to_market_v1 (equity / market_cap)
- quality_roic_v1 (NOPAT / (equity + LT_debt))
- quality_gross_profitability_v1 (TTM_GP / total_assets, Novy-Marx)
- accruals_inv_sloan_v1 (-sloan_accruals)
- accruals_inv_asset_growth_v1 (-asset_growth, FF5 CMA)

All 6: top-quintile cross-sectional, long-only, min_universe=30, top_quantile=0.20,
PIT via SimFin publish_date filter. Auto-registered active in edges.yml. 35 tests pass.

**Why:** Path C compounder produced +43bp CAGR vs SPY pre-deferral but the sleeve
itself is locked behind MDD ≤ -15% target. Separating factor signal from sleeve
packaging — Engine A ensemble doesn't have that MDD constraint.

**Coverage on 109-ticker prod universe:**
- 84 in SimFin (25 missing — mostly financials BAC/C/GS/JPM/MS/WFC/AXP/SCHW/PG)
- 80-81 with ≥4 published quarters in any year 2021-2025
- Top quintile = 16 names per edge per as_of
- Stable across all 5 years; min_universe=30 floor never trips

**2024 smoke (1 year, 1 rep, NOT validation):**
- Sharpe 1.91, CAGR 8.13%, MDD -2.75%, WR 53.9%
- Canon md5: 4ae83833f6d5a35ab941c979f167075b
- All 6 edges fired live in production (40 open positions across 9 edges at year-end)
- Wall time 9.2 min

**Critical: DO NOT extrapolate.** This is one bull-year window. The
universe-too-small failure mode is alive — momentum_factor_v1 had +0.13 IS
collapse to -0.62 OOS at 8 names/quintile. We're at 16 names/quintile, above
that disaster threshold but below the academic ≥200 universe convention.

**How to apply:** Before recommending any of these 6 to ship, demand:
1. Multi-year deterministic measurement 2021-2025 × 3 reps (canonical Foundation Gate)
2. Per-edge OOS walk-forward in isolation (low_vol_factor_v1 shape)
3. If any year/split fails, mark failed with failure_reason='regime_conditional' or
   'universe_too_small'. Do NOT iterate params to rescue — that's overfitting.

**Files:**
- engines/engine_a_alpha/edges/_fundamentals_helpers.py (shared cache + skeleton)
- engines/engine_a_alpha/edges/{value_earnings_yield,value_book_to_market,quality_roic,quality_gross_profitability,accruals_inv_sloan,accruals_inv_asset_growth}_edge.py
- tests/test_fundamentals_edges.py (35 tests)
- docs/Measurements/2026-05/fundamentals_edges_2026_05_06.md (full report with caveats)
- data/governor/edges.yml (6 entries appended, status=active, no existing weights modified)
- data/governor/_isolated_anchor/edges.yml (refreshed with new edges so harness preserves them)

**Restatement bias caveat on accruals edges:** SimFin's publish_date is correct
PIT join key, but underlying figures are "latest restated." This is documented
upstream but DOES inject small PIT bias on the two accruals edges.

**Long-only this round.** Sloan SHORT and asset-growth SHORT are stronger
historically; both pending borrow-cost model.
