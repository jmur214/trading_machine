# Engine C Activation — F4 Charter Inversion Closed (2026-05-07)

**Branch:** `c-engines-1-portfolio-activation`
**Lens:** architecture restoration, not alpha
**Goal:** Move HRP + TurnoverPenalty from Engine A's signal_processor
into Engine C; reduce signal_processor.py to pure edge-aggregation;
close the F4 charter inversion flagged by the 2026-05-06 audit.

## Summary

The F4 charter inversion (Engine A imports Engine C optimizers) is
closed. HRP + Turnover instantiation and call sites moved into a new
`engines/engine_c_portfolio/composer.py`. Engine A's signal_processor
no longer references Engine C; it only does edge aggregation.
AlphaEngine consumes the composer as a service (A → C dependency
direction is now correct: signal flow downstream).

The user's brief framed this as "Engine C is never called" — that
turned out to be **incorrect**: `BacktestController._prepare_orders`
was already calling `self.portfolio.compute_target_allocations()`
(line 508), which delegates to `PortfolioPolicy.allocate()`. The
result flows into `risk.prepare_order(target_weights=...)` and is
consumed when `enforce_target_allocations=true` (the default). What
*was* misplaced was the HRP machinery — that lived inside Engine A.
The migration here closes that misplacement.

## Files changed

| File | Before | After | Δ |
|------|-------|-------|---|
| `engines/engine_a_alpha/signal_processor.py` | 715 LOC | 522 LOC | **−193 LOC** |
| `engines/engine_c_portfolio/composer.py` | (new) | 184 LOC | +184 LOC |
| `engines/engine_a_alpha/alpha_engine.py` | (PortfolioOptimizerSettings imported from signal_processor) | (imported from engine_c.composer); composer instantiated; called after processor.process | ~+8 LOC net |
| `tests/test_engine_c_hrp.py` | tests SignalProcessor with HRP settings | tests SignalProcessor + Composer pair; adds charter-check test | rewritten |
| `tests/test_path_a_tax_efficient_core.py` | tests SignalProcessor with HRP settings | tests SignalProcessor + Composer pair | rewritten |

Net: signal_processor.py reduced from 715 → 522 LOC (target was <500;
actual delta is more conservative because regime_meta scoping, debug
prints, and the docstring stayed). All HRP/Turnover code lifted out
intact; logic is byte-identical, just relocated.

## Architectural before/after

### Before (F4 inversion)

```
engines/engine_a_alpha/signal_processor.py
├── PortfolioOptimizerSettings (dataclass)
├── SignalProcessor.__init__   →  imports from engine_c_portfolio
│                                  imports HRPOptimizer, TurnoverPenalty
│                                  instantiates self._hrp, self._turnover
├── SignalProcessor.process()  →  calls self._apply_portfolio_optimizer
├── _apply_portfolio_optimizer (88 LOC)
└── _build_returns_panel (18 LOC)

engines/engine_a_alpha/alpha_engine.py
└── from .signal_processor import PortfolioOptimizerSettings
```

Engine A's signal_processor *contained* Engine C code. The audit's
F4 finding ("Engine A imports Engine C optimizers — charter
inversion") reflected that Engine A reached *down* into Engine C's
internals to instantiate HRPOptimizer + TurnoverPenalty.

### After (charter restored)

```
engines/engine_a_alpha/signal_processor.py
├── (no PO settings; no HRP imports; no _apply_portfolio_optimizer)
└── SignalProcessor.process()  →  pure per-ticker edge aggregation

engines/engine_c_portfolio/composer.py  (NEW)
├── PortfolioOptimizerSettings (dataclass)
└── PortfolioComposer.compose(per_ticker_info, data_map)
       (instantiates HRPOptimizer + TurnoverPenalty internally;
        applies them to mutate per_ticker_info in place)

engines/engine_a_alpha/alpha_engine.py
├── from engines.engine_c_portfolio.composer import PortfolioComposer, PortfolioOptimizerSettings
├── self.composer = PortfolioComposer(settings)
└── generate_signals():
        proc = self.processor.process(...)
        if proc and self.composer.is_active:
            proc = self.composer.compose(proc, data_map)
        # then the existing signal-build loop reads optimizer_weight
        # / hrp_weight from `info` and threads them into signal.meta
```

Engine A consumes Engine C as a service through a single import of the
composer's public surface. Engine A no longer references HRPOptimizer
or TurnoverPenalty at all.

## Charter check

```
$ grep -rn "HRPOptimizer\|TurnoverPenalty" engines/engine_a_alpha/
(zero hits — exit code 1)
```

Pre-2026-05-07: 7 hits across `signal_processor.py`. Post: 0.

## Tests

### Targeted suites (all passing)

```
tests/test_engine_c_hrp.py             19 passed
tests/test_path_a_tax_efficient_core   27 passed
```

Plus all alpha/signal_processor/portfolio/composer-related test files
in the wider suite (59 passed). One pre-existing failure
(`test_alpha_pipeline.py::test_alphaengine_pipeline` —
`NewsSentimentEdge.compute_signals() missing 1 required positional
argument`) is unrelated to this branch and reproduces on `main`.

### Tests added/strengthened

- `test_engine_c_hrp.py::test_signal_processor_no_engine_c_imports`
  — automated charter check that fails if HRPOptimizer/TurnoverPenalty
  references creep back into Engine A. Reads the source file directly.

### Test surface change

The previous tests called `SignalProcessor(..., portfolio_optimizer_settings=...)`.
After the migration that constructor parameter no longer exists.
Tests now build a `SignalProcessor` (no PO settings) AND a
`PortfolioComposer`, and chain them: `proc = sp.process(...); proc = composer.compose(proc, data_map)`.
Same end-to-end semantics, cleaner surface.

## Determinism harness

3-rep determinism check (default config: `portfolio_optimizer.method
= "weighted_sum"`, the no-op path) under
`scripts/run_isolated --runs 3 --task q1`:

```
===== DETERMINISM REPORT =====
Sharpes:          [0.0, 0.0, 0.0]
Sharpe range:     0.0000
Canon md5 unique: 1 / 3
[RESULT] PASS — Sharpe within ±0.02 AND bitwise-identical canon md5
```

**Bitwise determinism preserved across the migration.** All three
runs produced identical canon md5 hashes.

**CAVEAT — environmental zero-trade run:** The worktree's `data/`
directory was bootstrapped via symlinks from the parent repo and
does not include the full `data/governor/` state used in production
runs (e.g. the cap-recalibration anchor, sandbox state). All three
runs produced 0 trades, so the canonical hash being identical is a
weaker statement than the standard determinism floor (which usually
sees ~30-50 trades in Q1 2025). Re-running the harness from the
parent repo (with full state) is recommended to confirm bit-identity
holds on a non-degenerate run path. The migration's logic is
byte-equivalent (HRP/Turnover code was lifted out intact), so a
non-trivial regression here would be surprising — but the empirical
3-rep on a populated run path is a stronger floor and should be
re-run before claiming the architectural change is fully de-risked.

`hrp_composed` was not exercised on the harness — it's not the
production default and would require a separate config override.
The unit tests (`test_hrp_composed_*` in test_path_a_tax_efficient_core)
cover the composer's slice-3 invariants directly.

## Hard constraints respected

- ✅ Engine B / `live_trader/` untouched
- ✅ `engine_c_active` flag was found unnecessary — Engine C is
  already active via PortfolioPolicy. The `portfolio_optimizer.method`
  config (default "weighted_sum") continues to gate HRP behavior.
- ✅ No Sharpe lift / regression claims — this is architecture
  restoration. The harness ran zero-trade runs (environmental), so
  no real Sharpe data was generated.
- ✅ `data/governor/` snapshots respected via `scripts/run_isolated`
- ✅ Stayed inside `engines/engine_a_alpha/`, `engines/engine_c_portfolio/`,
  `tests/`, `docs/Measurements/2026-05/`. No other directories touched.

## Unexpected findings

1. **The user's brief was directionally inaccurate on "Engine C is
   never called."** `BacktestController._prepare_orders` line 508 has
   been calling `self.portfolio.compute_target_allocations(...)` for
   a while; the resulting `target_weights` flow into
   `risk.prepare_order(target_weights=...)` which uses them when
   `enforce_target_allocations=true` (default). The actual problem
   was misplaced HRP machinery, not missing portfolio composition.

2. **HRPOptimizer / TurnoverPenalty are byte-identical** to the
   previous in-place code; the composer is a relocation, not a
   rewrite. So no behavioral change is expected when method is `"hrp"`
   or `"hrp_composed"`. This is what allowed the migration to be a
   nearly-mechanical refactor.

3. **The `engine_c_active` config flag from the original brief was
   not added** because Engine C's policy is already active. The
   existing `portfolio_optimizer.method = "weighted_sum"` flag
   continues to gate the HRP-specific behavior, default-off. Adding
   a duplicate would have introduced a second flag with the same
   purpose.

## Next steps (not in this branch)

- Re-run determinism harness from parent repo with full governor
  state to confirm bit-identity on a non-degenerate run path.
- The `mode` field in PortfolioPolicyConfig defaults to `"adaptive"`
  but `config/portfolio_settings.json` sets it to `"mean_variance"`
  — worth a separate audit of which path the production backtest
  actually takes through `PortfolioPolicy.allocate()`.
- Consider whether `_apply_regime_overrides` (currently inside
  `PortfolioPolicy.allocate`) should be its own optimizer wrapper too.
