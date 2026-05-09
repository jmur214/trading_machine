# Bare-except audit — `engines/` (2026-05-08)

**Author:** Agent B (T-2026-05-08-005 bonus deliverable)
**Branch context:** `feature/backtest-controller-narrow-except` (parent task closed `backtester/backtest_controller.py:389`)
**Scope:** Sweep all `except Exception` sites under `engines/` and classify them as `OK`, `SUSPICIOUS`, or `INVESTIGATE` against the gauntlet narrow-catch pattern (commits `ee42ab7`, `453e04e`, plus today's `129c7ba` on the parent task).

This audit triages, it does not fix. Director decides what to action.

---

## Headline

| Metric | Count |
|---|---|
| Files in `engines/` with `except Exception` | 62 |
| Total `except Exception` sites | 201 |
| Already-narrowed (`isinstance(e, (TypeError, …)): raise` within 6 lines) | 13 |
| Still-broad (no narrow guard within 6 lines) | **188** |

Brief expected ~15-30 hits; the actual broad surface is **~6× larger**. The original grep (`grep -v "raise"`) misses the gauntlet pattern entirely because the `raise` is on a separate line.

Engine D is largely cleaned up (8 narrowed in `discovery.py`, 4 narrowed in `tree_scanner.py`, 6 broad remaining in tertiary helper paths). Every other engine has zero narrowed sites.

---

## Per-file rollup

Format: `{broad}b  {narrowed}n  path` — sorted by broad count.

### Top offenders (≥5 broad sites)

| Broad | Narrowed | File | Engine |
|---:|---:|---|---|
| 19 | 0 | `engines/data_manager/data_manager.py` | data |
| 18 | 0 | `engines/engine_f_governance/governor.py` | F |
| 13 | 0 | `engines/engine_a_alpha/alpha_engine.py` | A |
| 13 | 0 | `engines/engine_b_risk/risk_engine.py` | **B** |
| 8 | 0 | `engines/engine_a_alpha/edges/composite_edge.py` | A |
| 7 | 0 | `engines/engine_f_governance/evolution_controller.py` | F |
| 6 | 8 | `engines/engine_d_discovery/discovery.py` | D |
| 5 | 0 | `engines/engine_a_alpha/signal_processor.py` | A |
| 5 | 0 | `engines/engine_a_alpha/edges/pead_predrift_edge.py` | A |

### Mid-tier (2-4 broad sites)

`macro_unemployment_momentum_edge.py`, `macro_yield_curve_edge.py`, `macro_credit_spread_edge.py`, `macro_real_rate_edge.py` (4 each); `lifecycle_manager.py`, `evaluator.py`, `slippage_model.py`, `lt_hold_preference.py` (4); `signal_collector.py` (3b/1n), `news_sentiment_edge.py`, `pead_short_edge.py`, `pead_edge.py`, `macro_dollar_regime_edge.py`, `wash_sale_avoidance.py` (3 each); 13 files at 2 broad each.

### Long tail (1 broad site)

22 files. Mostly `__init__`-time helpers, edge constructors, defensive value coercion. Lowest leverage.

---

## Spot classification — high-leverage sites

These are the broad-except sites in production hot paths or autonomous-decision paths where a swallowed programmer error has the highest blast radius. Director should triage these first.

### `engines/engine_a_alpha/alpha_engine.py`

| Line | Action on swallow | Class | Note |
|---:|---|---|---|
| 124 | `return default` | OK | Generic numeric coercion helper |
| 130 | log + `return defaults` | OK | Config-file load fallback |
| 174 | `return default` | OK | Generic coercion helper |
| 300 | log debug | **SUSPICIOUS** | `import test_edge` failure swallowed → new edges silently absent from registry; behind debug-flag |
| 308 | log debug | **SUSPICIOUS** | Same shape, `news_sentiment_boost` import |
| 323 | log debug | **SUSPICIOUS** | `news_sentiment_edge` registration failure swallowed |
| 432 | `po_cfg_raw = None` | OK | Optimizer config load |
| 487 | reset 3 dicts to empty | INVESTIGATE | Regime-gates / edge-tiers / paused-edge-ids reset on ANY exception — masks state-load bugs as "no regimes configured" |
| 582 | `ver_str = "1"` | OK | Version-string coercion |
| 650 | log + return empty df | INVESTIGATE | SPY fetch for regime — TypeError from yfinance API change would silently disable the regime path |
| 749 | `r = 0.0` | OK | Per-edge value coercion in scoring loop |
| 770 | `agg = fmean(contribs)` | INVESTIGATE | Aggregation fallback in scoring hot path; legitimate ZeroDivision is already inline-handled, so the broad swallow is masking *unknown* failures |
| 958 | log debug | **SUSPICIOUS** | ML-inference TypeError silently skipped — same bug class as the 2026-05-08 regression |

### `engines/engine_a_alpha/signal_processor.py`

| Line | Action | Class | Note |
|---:|---|---|---|
| 183 | fall back to legacy linear sum | INVESTIGATE | MetaLearner load — comment claims "better to silently use linear sum than crash"; that's a deliberate fail-open but still hides AttributeError on sklearn upgrades |
| 235 | log debug + cache miss | INVESTIGATE | Per-ticker MetaLearner load |
| 305 | `continue` | **SUSPICIOUS** | Per-edge per-bar gate inside ML feature collection — programmer error in one edge silently drops it from the feature row |
| 324 | log debug | INVESTIGATE | MetaLearner predict-time failure |
| 404 | `continue` | OK | Numeric coercion of feature values |

### `engines/engine_a_alpha/edges/composite_edge.py`

| Line | Action | Class | Note |
|---:|---|---|---|
| 76 | `pass` (inside gene-evaluation loop) | **SUSPICIOUS** | Composite gene-eval; programmer error in one gene silently drops it from the boolean tree, distorting Discovery scoring |
| 282 | `return None` | OK | Fundamental ratio lookup — None is the documented "no data" return |
| 409 | `return None` | OK | Same shape — fundamental value lookup |
| 424 | `return None` | OK | Same shape |
| 453 | `self._macro_cache[id] = None` | INVESTIGATE | Macro fetch — None-cache means the failure is sticky; downstream sees "no data forever" |
| 479 | `return None` | OK | Macro value lookup |
| 502 | `self._earnings_cache[ticker] = None` | INVESTIGATE | Same shape as 453, earnings cache |
| 517 | `return None` | OK | Earnings value lookup |

### `engines/engine_b_risk/risk_engine.py` — **out of agent scope, flag for director**

13 broad-except sites in Engine B. Per CLAUDE.md, Engine B changes need user approval, so this audit doesn't propose fixes — only flags severity.

| Line | Action | Class |
|---:|---|---|
| 135 | log error | OK (non-fatal sector-map load) |
| 155 | `post_fill_qty = None` | INVESTIGATE |
| 159 | `pass` (wash-sale recording) | **SUSPICIOUS** — silent wash-sale failure |
| 163 | `pass` (LT-hold recording) | **SUSPICIOUS** — silent LT-hold preference failure |
| 341 | `return 0` | INVESTIGATE — gross-position-count |
| 478 | `last_close = None` | OK |
| 502 | `pass` ("Fail-open: never let the new module block normal exits") | INVESTIGATE — explicit fail-open, but no programmer-error guard |
| 550 | `current_pos = None` | INVESTIGATE |
| 597 | `pass` | INVESTIGATE |
| 737 | `pass` (vol-state fetch) | OK |
| 796 | `dd_pct = 0.0` | **SUSPICIOUS** — drawdown-halt sees "no drawdown" on any exception, defeating the kill-switch |
| 856 | force `add_qty=1, forced=True` | INVESTIGATE — exposure check fail still allows 1-share probe |
| 957 | log + `pass` | OK (final fail-open with comment) |

The line-796 finding is the most concerning: drawdown-halt is the recently-shipped kill switch. A TypeError reading `current_drawdown_pct` would silently zero it out and the halt would never fire. Director should consider this for the next Engine B touch.

### `engines/engine_f_governance/governor.py`

18 broad sites. Most are I/O around `data/governor/*.json` (save weights, save metrics, append history) — all logging via `log.debug` or `log.warning`. Class: largely **OK** (non-fatal persistence).

Two outliers worth a look:
- `360` — `total_days_covered = int(self.cfg.rolling_window_days)` on TZ-arithmetic exception; legitimate fallback but masks a TypeError class identical to today's bug.
- `549` — `metrics = {…}` dict left empty on exception; downstream feedback-history writes blank metrics.

### `engines/engine_d_discovery/discovery.py` — mostly remediated

8 narrowed (the gauntlet pattern), 6 still-broad. The 6 remaining are all tertiary helper paths:

| Line | Action | Class |
|---:|---|---|
| 253 | `pass` (registry-edge enumerate) | OK |
| 474 | log + `return []` | OK (registry read) |
| 491 | log + `existing = {"edges": []}` | OK (registry write-prep) |
| 567 | `pass` (universe-B substrate sub-load) | INVESTIGATE — silent ticker drop |
| 643 | log + `continue` (per-spec import) | OK |
| 905 | `alpha_config = {}` | OK (config fallback) |

---

## Recommended action ordering

If director wants to fix-forward, highest-leverage targets in order:

1. **`alpha_engine.py:300, 308, 323`** — module-import swallows. New edges silently never register. Trivial fix; same narrow pattern.
2. **`alpha_engine.py:958`** — ML-inference TypeError is the *exact same bug class* as today's earnings-vol regression. Same edge-shape on the alpha side. 5-minute fix.
3. **`alpha_engine.py:487, 770`** — regime-gates state reset and aggregation fallback in the scoring hot path. Higher value to investigate before patching.
4. **`composite_edge.py:76`** — gene-eval loop in Discovery scoring path. Fix narrows error visibility for the autonomous-improvement loop.
5. **`signal_processor.py:305`** — per-edge feature-collection swallow.
6. **Engine B:796** — drawdown-halt path can silently fail-open. Requires user approval per CLAUDE.md.
7. **`composite_edge.py:453, 502`** — macro/earnings None-caching. Sticky failure mode worth a closer look.

Items 1-5 are inside the agent autonomy lane (Engine A only) and could be batched into a single follow-up task on a `feature/alpha-narrow-except` branch.

Item 6 is an Engine B propose-first.

The remaining 175+ broad sites are primarily in the OK bucket (I/O fallbacks at boundaries). They could be left as-is or migrated incrementally; the leverage on the long tail is low.

---

## Methodology notes

- The brief's grep (`grep "except Exception" engines/ | grep -v "raise"`) **does not detect** the gauntlet narrow-catch pattern, because the `raise` is on the next line, not the `except` line. The 13-narrowed count above is from a 6-line lookahead for `isinstance(e, (TypeError`.
- "OK" means the swallow has documented-or-obvious defensive intent at an I/O / config / coercion boundary AND the fallback is a reasonable null-equivalent (None, 0, [], `default`).
- "SUSPICIOUS" means the swallow is in a production code path AND a TypeError / AttributeError there would silently degrade signals or feedback.
- "INVESTIGATE" means the intent is unclear from a 5-line context window — director or topic-owner should look at the surrounding code path before deciding.
