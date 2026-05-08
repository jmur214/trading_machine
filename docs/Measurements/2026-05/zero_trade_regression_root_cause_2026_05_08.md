# Zero-Trade Regression — Root Cause + Fix

**Date:** 2026-05-08
**Severity:** HIGH (silent catastrophic failure)
**Status:** RESOLVED in this commit

## TL;DR

Every backtest since 2026-05-07 produced **zero trades**. The other session's hypothesis (V/Q/A edges missing from `edge_weights.json`) was directionally suspicious but turned out to be incidental. The real cause is a tz-aware vs tz-naive timestamp comparison in `EarningsVolEdge._get_earnings_dates`, swallowed by a bare `except Exception` in `backtest_controller.py:389`.

## The bug

`engines/engine_a_alpha/edges/earnings_vol_edge.py:79` cached earnings dates using `dates.index.normalize().tolist()`. yfinance returns its `Ticker.earnings_dates` index as **tz-aware** (America/New_York). `.normalize()` zeroes the time component but preserves tz.

Lines 94 and 120 then compare each cached date against the bar timestamp `as_of`:

```python
future_dates = [d for d in earnings_dates if d > as_of]   # line 94
past_dates   = [d for d in earnings_dates if d <= as_of]  # line 120
```

`as_of` is tz-naive (the rest of the system uses tz-naive timestamps). pandas raises:

```
TypeError: Cannot compare tz-naive and tz-aware timestamps
```

The exception propagates up:
1. `earnings_vol_edge._pre_earnings_signal` (line 94)
2. `earnings_vol_edge.compute_signals`
3. `signal_collector._call_edge`
4. `signal_collector.collect`
5. `AlphaEngine.generate_signals`
6. `backtest_controller.run` (line 388)

…where it is **silently swallowed** by `except Exception:` at line 389. `signals = []` is set. Every bar, every ticker, every edge lost. Result: every backtest produces 0 trades, equity stays at $100k, canon md5 = empty-md5 (`d41d8cd98f00b204e9800998ecf8427e`).

`earnings_vol_v1` is the 11th edge in the registry's iteration order. The collector terminates at the first exception, so all edges before it (rsi_bounce_v1 through herding_v1) get evaluated — their raw scores show in the trace. Edges 12-22 (pead_v1, low_vol_factor_v1, …, V/Q/A) never get called. That's why the V/Q/A edges appear "silent" but it's not because their weights are missing — they never even get reached.

## Why the other session's hypothesis was wrong (but plausible)

The other session noticed: V/Q/A edges have no entries in `edge_weights.json`. They hypothesized that the governor was treating missing entries as 0.0, silently abstaining. That's been considered before as a real bug class.

But: the actual lookup uses `weights.get(edge_id, 1.0)` (verified at `alpha_engine.py:976`) — defaults to 1.0 when missing. So missing entries don't kill signals. The hypothesis didn't match the code path.

The real signal here was: **all edges silently abstain**, not just V/Q/A. The other session's bisect across recent commits (`7d54de3`, `1085069`) all reproduced the same zero-trade. That was the hint that the regression is in shared state OR a pre-existing bug rather than a recent code change. yfinance's tz-aware return on `earnings_dates` IS the shared state — it depends on the yfinance version and was likely fine before whichever yfinance update flipped the tz handling.

## The fix

```python
# engines/engine_a_alpha/edges/earnings_vol_edge.py:79
idx = dates.index
if getattr(idx, "tz", None) is not None:
    idx = idx.tz_localize(None)
date_list = sorted(idx.normalize().tolist())
```

Strip the tz before caching. Downstream comparisons against tz-naive `as_of` now work.

## Verification

```bash
PYTHONHASHSEED=0 .venv/bin/python -m mode_controller \
  --start 2025-09-01 --end 2025-09-30
# Result: Sharpe 2.019, Net Profit $174.59, 564 trades in trades.csv
```

Pre-fix: same range produced empty trades.csv (1 line = header only), Sharpe 0.0.

## Regression tests added

`tests/test_earnings_vol_tz_regression.py` — 3 tests:

1. `test_earnings_vol_compute_signals_does_not_raise_on_tz_naive_timestamp` — calls compute_signals on a real yfinance fetch with tz-naive `now`; asserts no exception. Reproduces the original failure path.
2. `test_earnings_vol_cached_dates_are_tz_naive` — asserts every cached date has `tz=None`. Catches any future regression where yfinance's tz handling changes again, or where the strip-tz line is removed.
3. `test_backtest_controller_bare_except_swallows_alpha_errors` — documents the existence of the bare-except as a known anti-pattern. Future cleanup that tightens or removes the catch makes this test fail (which is good — the test should be updated then).

## Why this happened

Two contributing factors:

1. **yfinance's API became more strict** about timezone handling in some recent version. The cached behavior worked for a while because either (a) yfinance previously returned tz-naive indices, or (b) the comparison happened to not cross a tz-aware boundary in earlier test windows. Either way, the regression is environmental.

2. **The bare `except Exception:` at `backtest_controller.py:389`** (the swallow) means any error in any edge silently kills all signals for that bar. This is too broad. Once one edge fails, ALL edges' results are discarded for that bar. A narrow catch (TypeError, AttributeError, etc.) with `raise` for programmer errors would have surfaced this immediately.

## Recommended follow-up (NOT in this commit)

- Tighten `backtest_controller.py:389` from `except Exception` to `except (KeyError, ValueError, TypeError) as e: log.warning(...); raise` so genuine code errors propagate. The current catch was added in a defensive era; today's gauntlet code is robust enough that loud failures are preferable to silent zeros.
- Add a per-edge isolation: if one edge raises, the others should still run. This requires moving the try/except inside the per-edge loop rather than around the whole signal-collection step.
- Audit other edges for similar tz-comparison bugs. yfinance is used in `news_sentiment_edge`, `pead_v1`, `pead_short_v1`, `pead_predrift_v1`. Any of these calling `Ticker.earnings_dates`, `Ticker.news`, `Ticker.history` could hit the same shape.

## Audit trail

- Other session's report flagged the symptom + bisect to mutable governor state
- This session traced the actual exception via `BACKTEST_CONTROLLER_DEBUG=1` and found the tz-error
- Fix verified with a 1-month real backtest (Sharpe 2.02, 564 trades)
- 3 regression tests added; full test suite still passes (1500+ tests)
