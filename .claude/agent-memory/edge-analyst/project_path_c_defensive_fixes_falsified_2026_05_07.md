---
name: Path C defensive fixes (F/G/H) all failed -15% MDD target — Cell F closest miss (2026-05-07)
description: 8-cell harness on 2022-01-01 → 2025-04-30. Cell F (vol-rank pre-screen) cushioned 2022 bear (-4.55% vs Cell D -10.24%) but surrendered 17pp of 2023 recovery upside. Cell G (70/30 IEF) failed because IEF lost 17% in 2022. Cell H combined drag without compounding benefit. No cell PASSES both criteria.
type: project
---

## 8-cell harness on 2022-01-01 → 2025-04-30, S&P 500 ex-Financials (359 tickers)

| Cell | Strategy | CAGR after | Sharpe | MDD |
|---|---|---:|---:|---:|
| A | spy_buyhold | 5.21% | 0.406 | -24.50% |
| B | 60/40 SPY/IEF | 2.46% | 0.379 | -17.16% |
| C | compounder_synthetic | 3.13% | 0.387 | -15.74% |
| D | compounder_real_fundamentals | 5.83% | 0.468 | -21.84% |
| E | + vol overlay | 3.40% | 0.332 | -21.84% |
| **F** | **+ defensive_pre_screen (top-200 vol-rank)** | **4.74%** | **0.439** | **-16.09%** |
| **G** | **+ 70/30 IEF buffer** | **3.67%** | **0.390** | **-20.12%** |
| **H** | **F + G combined** | **3.09%** | **0.343** | **-15.79%** |

## Pass criterion (-15% MDD load-bearing per design doc, NOT a moved goalpost)

NO CELL PASSES BOTH:
- Cell F: missed MDD by 1.09pp, missed SPY-CAGR by 0.47pp — closest miss in any Path C iteration
- Cell G: missed MDD by 5.12pp (bond buffer barely helped; IEF -17% in 2022 rate shock)
- Cell H: missed MDD by 0.79pp BUT CAGR 3.09% is 41% below SPY (3.09 / 5.21 = 59%)

## Mechanism diagnosis

Cell F annual decomposition reveals the trade exactly:
- 2022 (bear): F = -4.55%, D = -10.24%, A = -18.65% — pre-screen cushioned by 5.7pp vs D, 14.1pp vs SPY
- 2023 (recovery): F = +9.13%, D = +26.16%, A = +26.71% — pre-screen filtered OUT high-vol recovery names (META, NVDA), surrendered 17pp
- 2024 (bull): F = +16.93% ≈ D = +16.82% — keeps pace in steady bull
- 2025 YTD: F = -1.34%, D = -4.91% — gentler

**The pre-screen does exactly what it was designed to do — cushion bear years.** It just gives up too much upside to net positive vs SPY.

Cell G failed because the naive arithmetic ("70% × Cell D MDD = -15.3%") doesn't account for IEF crashing alongside equities in 2022. Bonds were not a 2022 diversifier (Cell B 60/40 also failed at -17.16%). This may not generalize to credit-driven bears (e.g. 2008-style where Treasuries rallied) but the test window doesn't include one.

## Why this is Branch 3 (defer with unblock criteria), not Branch 1 or 2

Branch 1 (one fix works) is impossible given F's 1.09pp MDD shortfall + 0.47pp CAGR shortfall together. Branch 2 (one fix kills MDD but loses to SPY) is technically what F is doing, but F doesn't quite kill MDD (still -16.09% > -15%). H is the only cell that actually kills MDD by getting close (-15.79% > -15%, only 0.79pp short) — but at 3.09% CAGR it's the worst CAGR of any non-trivial cell.

Recommendation persisted in audit doc: defer with three explicit unblock criteria:
1. Engine E HMM produces actionable regime-state signal callable outside Engine E (currently observability-only)
2. Engine B de-grosses on regime-change events within days, not at next annual rebalance
3. Vol-overlay infrastructure (`scripts/path_c_overlays.py`, already shipped + 15 tests pass) becomes load-bearing with regime-change-event trigger

## Statistical-traps takeaways (anti-curve-fitting)

- 4 rebalance events on a 4-year window means each cell's outcome is determined by ~4 basket choices. Adding a third tuning knob (e.g. top-N tighter) on this thin sample would cross into curve-fitting territory. **Do not iterate on F/G/H parameters on this window** — wait for a wider data window or a regime-conditional architecture before tuning.
- Cell F's apparent "elegant near-miss" (1.09pp from target on MDD) is statistically fragile: a single different basket pick at a single rebalance could push it into PASS or 5pp deeper into FAIL. The 4-year backtest cannot distinguish "F is robustly close" from "F got lucky on 4 coin flips."
- The 2022 rate shock is one bear regime. Path C's tax-efficient compounder thesis IS regime-coupled (works best when bonds DO diversify), so a sample that includes only 2022 systematically under-rates bond-buffer strategies. Without 2008 in window, Cell G's failure cannot be cleanly generalized.

## Files

- Audit: `docs/Measurements/2026-05/path_c_defensive_fixes_2026_05_07.md`
- JSON: `data/research/path_c_synthetic_backtest.json` (gitignored)
- Code: `scripts/path_c_synthetic_compounder.py` (added: `apply_defensive_prescreen`, `defensive_pre_screen` and `bond_buffer_weight` kwargs on `run_compounder_backtest`, Cells F/G/H in `main()`, extended-history `prescreen_lookback_prices` panel)
- Branch: `path-c-defensive-fixes` (worktree-local, not pushed)
- Pre-existing infrastructure used: `scripts/path_c_overlays.py` (vol overlay helpers; not load-bearing in F/G/H but kept for HMM future-work)
