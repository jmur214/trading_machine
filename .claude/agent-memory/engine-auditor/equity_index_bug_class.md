---
name: Equity-series-without-datetime-index bug class
description: Building pd.Series from history list without datetime index breaks MetricsEngine.cagr
type: project
---

**Bug class:** `pd.Series([h["equity"] for h in history])` produces a RangeIndex (integers). `MetricsEngine.cagr()` (core/metrics_engine.py:90) does `(end - start).days / 365.25` where `start` and `end` are taken from the index. On an integer index, `(int - int).days` raises `AttributeError: 'int' object has no attribute 'days'`. `MetricsEngine.calculate_all` calls `cagr` unconditionally, so this AttributeError propagates upward and crashes any caller that passes a no-index equity series.

**Fix:** Always build with `index=pd.to_datetime([h["timestamp"] for h in history])`.

**Known sites:**
- `engines/engine_d_discovery/discovery.py:653` — Gate 1 (fixed in commit dda474c on 2026-04-28).
- `engines/engine_d_discovery/discovery.py:806` — Gate 5 universe-B (still broken as of 2026-04-28; flagged HIGH in health_check).

**Why this recurs:** The pattern "build equity series from history rows" is duplicated rather than centralized. There is no shared helper. Each call site is a fresh opportunity to omit the index. Look for any new code that does `pd.Series([... for ... in history])` against a `BacktestController.run` output.

**How to apply:** When auditing any code that constructs equity series for metrics, verify the index. If a metric call wraps the construction in `try/except`, also verify the except block — bare-except converts this AttributeError into a silent skip, hiding the bug for indefinite periods.
