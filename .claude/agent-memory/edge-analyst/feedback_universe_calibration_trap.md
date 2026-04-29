---
name: Universe-size calibration trap
description: Thresholds calibrated on 39-ticker mega-cap universes systematically under-fire on 109-ticker mixed-cap universes
type: feedback
---

When an edge is calibrated on a curated mega-cap universe (low idiosyncratic vol, tightly correlated, low BB width), porting it to a broader S&P universe with mid-caps will lower fire rates because the broader universe has higher dispersion. BB width thresholds, breadth thresholds, vol z-score thresholds all need to be re-anchored to percentiles of the actual universe, not magic numbers.

**Why:** The 39-ticker mega-cap baseline produced Sharpe 0.98; on 109-ticker the same code produces 0.40 (per memory `project_lifecycle_vindicated_universe_expansion_2026_04_25.md`). A meaningful fraction of that gap is signal starvation in active edges, not alpha decay.

**How to apply:**
1. Before recommending a threshold value, compute its empirical percentile on the actual production universe over the actual backtest window.
2. Prefer percentile-based thresholds (e.g., "fire when in top 5% of trailing-90d distribution") over absolute thresholds (e.g., "fire when vol_z > 2.5").
3. Per-edge target fire rate: 1-5% of ticker-bars to be considered "alive" for governance evidence accumulation. Below 0.1% is structurally dead.
4. Mid-cap S&P names (XOM, F, SLB, CAT, etc.) have BB widths typically 5-15% — bb_width < 0.03 only catches the very lowest-vol mega-caps and is a near-impossibility for the broader names.
