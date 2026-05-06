# V/Q/A edges — bug-fix audit

Generated: 2026-05-06
Branch: `vqa-edges-bugfixes` (worktree-isolated at
`.claude/worktrees/agent-a9dd506a191d53f21`)
Commit: `6c9b4af` — `fix(engine_a/edges): four V/Q/A bug-fixes from
2026-05-06 health-check`

## Why this audit

Yesterday (2026-05-05) shipped 6 V/Q/A factor edges to Engine A. Today's
multi-year measurement first reps showed V/Q/A-on Sharpe 1.155 vs
baseline 1.666 = **-0.51 drag**. Code-health surfaced 3 HIGH findings
plus a trade-log over-trading diagnostic. This audit closes those 4
bugs and reports the residual.

## What the bugs were

### Bug #1 (HIGH) — ROIC silently treated negative-equity firms as high-quality

**Files:** `engines/engine_a_alpha/edges/quality_roic_edge.py:87-88`,
`scripts/path_c_synthetic_compounder.py:663-664`.

The ROIC denominator was

```python
invested_capital = (equity if equity > 0 else 0.0) + \
                   (lt_debt if lt_debt > 0 else 0.0)
```

For distressed firms with negative equity but positive long-term debt,
the equity term silently fell to 0 and the denominator collapsed to
`lt_debt` alone. NOPAT divided by a small denominator inflated ROIC
into the top quintile — exactly the OPPOSITE of the academic Quality
factor (Asness-Frazzini-Pedersen, "Quality Minus Junk" 2019). The same
pattern was duplicated in the Path C compounder.

`value_book_to_market_edge.py:76-78` already has the correct guard
(`equity <= 0 → return None`); the fix mirrors that contract in both
sites.

### Bug #2 (HIGH) — Helper swallowed ALL exceptions in score_fn

**File:** `engines/engine_a_alpha/edges/_fundamentals_helpers.py:205-208`

```python
try:
    raw = score_fn(panel, ticker, asof_ts, df)
except Exception:
    raw = None
```

Programmer errors (`AttributeError` from method-on-None,
`NameError` from missing import, `ImportError` from a moved helper)
were caught identically to legitimate data-missing cases and quietly
turned into "ticker has no signal." Same failure mode as the gauntlet-
consolidated-fix from 2026-05-02 (memory
`project_gauntlet_consolidated_fix_2026_05_01.md`).

The fix: narrow to `_DATA_MISSING_ERRORS = (KeyError, IndexError,
ValueError, ZeroDivisionError, TypeError)` with DEBUG-log of swallowed
exceptions; re-raise programmer errors.

### Bug #3 (HIGH) — Auto-register `except Exception: pass` on all 6 edges

Every new edge ended with:

```python
try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(... status="active"))
except Exception:
    pass
```

Future `EdgeSpec` schema drift, corrupted yaml, or a registry write
race would silently drop registrations while the import succeeded.
AlphaEngine would still load the class but the lifecycle layer
wouldn't see the spec. Same shape as the 2026-04-25 registry-status-
stomp bug.

The fix: narrow to `except (FileNotFoundError, PermissionError,
OSError) as exc: log.warning(...)`; programmer errors propagate.

### Bug #4 — V/Q/A edges over-traded against quarterly-cadence data

Yesterday's 2021 trade log (`b173e1c2-...`):

| edge_id | trades | notes |
|---|---:|---|
| momentum_edge_v1 | 2839 | -52% from baseline 5867 |
| value_book_to_market_v1 | 931 |  |
| value_earnings_yield_v1 | 847 | ~50/ticker/year on 16-name basket |
| accruals_inv_sloan_v1 | 797 |  |
| quality_roic_v1 | 499 |  |
| **VQA total** | **3569** | dominant share of trades |
| **All trades** | **7057** |  |

Win rate on V/Q/A 5-7%; AMGN flipped long ↔ short on `value_earnings_
yield_v1` daily across May-July (12 entries inside 30 days — half
long, half short, despite long-only edge intent). Mechanism: the
edges emit `1.0` for the 16-name basket every bar; the per-ticker
aggregator combines with momentum's daily-changing sign; the resulting
aggregate score jiggles enough to cross the entry threshold daily; and
Engine B's `rebalance_within_tolerance` doesn't fully suppress the
churn.

The fix: state-transition emission in `top_quintile_long_signals`.
Each edge instance owns a `_basket_state: dict`. The helper compares
the current top-quintile basket against the prior call's cached
basket and emits `long_score` only on entries (new members) and
`0.0` on exits (departures). Sustained members emit `0.0` —
their position is held (or not) by the rest of the per-ticker
aggregator's edges. State is cleared when coverage drops below
`min_universe`, so a recovery bar doesn't fire spurious bursts.

## What changed

```
engines/engine_a_alpha/edges/_fundamentals_helpers.py
    - +35 lines for _PROGRAMMER_ERRORS / _DATA_MISSING_ERRORS tuples
      and narrowed exception handling with DEBUG log
    - +50 lines for state-transition emission (entries/exits/sustained
      semantics, state-clear on min_universe abstention)
    - signature change: + state: Optional[dict] = None,
                        + edge_id: str = ""

engines/engine_a_alpha/edges/{value_earnings_yield, value_book_to_market,
                              quality_roic, quality_gross_profitability,
                              accruals_inv_sloan,
                              accruals_inv_asset_growth}_edge.py
    - +1 line in __init__: self._basket_state: dict = {}
    - +2 lines in compute_signals: state=self._basket_state, edge_id=...
    - replaced try/except Exception:pass auto-register with narrow
      I/O-only catch + WARNING log

engines/engine_a_alpha/edges/quality_roic_edge.py
    - score_fn: explicit `if equity <= 0: return None` (Bug #1)
    - drops the silent-zero `(equity if equity>0 else 0.0)` fallback

scripts/path_c_synthetic_compounder.py
    - same negative-equity drop applied to compute_composite_score_real
      (Bug #1, duplicate site)
```

## Tests

44 unit tests pass (35 existing + 9 new):

| New test | Validates |
|---|---|
| `test_quality_roic_drops_negative_equity_ticker` | Bug #1 — synthetic distressed firm dropped from top quintile |
| `test_helper_reraises_attribute_error_from_score_fn` | Bug #2 — programmer error propagates |
| `test_helper_suppresses_value_error_from_score_fn` | Bug #2 — data-shape error silenced (legitimate) |
| `test_auto_register_propagates_programmer_errors` | Bug #3 — TypeError on schema drift propagates |
| `test_auto_register_swallows_io_error` | Bug #3 — FileNotFoundError degrades gracefully + WARNING log |
| `test_helper_emits_only_on_basket_transitions` | Bug #4 — second call with stable basket emits zero |
| `test_helper_emits_exits_when_basket_changes` | Bug #4 — entry+exit emission semantics |
| `test_helper_state_resets_below_min_universe` | Bug #4 — coverage-recovery doesn't burst-emit |
| `test_per_edge_state_isolation` | Bug #4 — multiple instances/edges don't share state |

## 2021 single-year smoke verification

Run UUID: `328be630-d442-464f-ab5e-a5a65d0d4755`
Canon md5: `308294a9f66e3a0261c079e5c5e26f1d`
Wall time: 15.0 min (1 year × 1 rep)

| Configuration | Sharpe | CAGR % | MDD % | Trades | Notes |
|---|---:|---:|---:|---:|---|
| **Baseline (pre-V/Q/A, 2026-05-02)** | **1.666** | 7.58 | -3.58 | 521 | wash-sale verification, cell A |
| V/Q/A merged (2026-05-05, BROKEN) | 1.155 | — | — | 7057 | yesterday's first rep, killed run |
| **V/Q/A bugs fixed (this run)** | **0.592** | 6.55 | -9.79 | 538 | post-fix smoke |

| edge_id | post-fix entries | yesterday's entries | Δ |
|---|---:|---:|---:|
| momentum_edge_v1 | 297 | 2839 | -90% |
| volume_anomaly_v1 | 83 | 249 | -67% |
| low_vol_factor_v1 | 58 | 141 | -59% |
| gap_fill_v1 | 39 | 114 | -66% |
| herding_v1 | 24 | 98 | -76% |
| value_book_to_market_v1 | 10 | 931 | **-99%** |
| accruals_inv_sloan_v1 | 9 | 797 | **-99%** |
| value_earnings_yield_v1 | 8 | 847 | **-99%** |
| quality_roic_v1 | 5 | 499 | **-99%** |
| **All trades** | **538** | **7057** | **-92%** |

State-transition pattern works as designed — V/Q/A edges fire ~0
entries/year on stable quarterly data (about right for a quintile
that turns over every 4-8 quarters in mature mega-caps). Total trades
collapsed by 92%, momentum_edge_v1 stops being crowded out (-90% but
that's because the *whole* trade volume contracted; relative share
recovered).

## Acceptance criterion: NOT met

Dispatch's acceptance: V/Q/A-on Sharpe within ±0.10 of baseline 1.666.
Got 0.592 — **-1.074 drag, well outside the ±0.10 band.**

The fix is technically correct (4 bugs closed, 9 tests verify) but
does NOT recover baseline. Per dispatch instruction: "If still
dragging significantly, document the residual issue but don't iterate
further this round — it's a data point for the next dispatch."

## Residual hypothesis

The +0.51 Sharpe drag from V/Q/A-on yesterday (1.155 vs baseline 1.666)
was already a real signal. Today's V/Q/A-on-with-fix Sharpe 0.592 is
WORSE than yesterday's broken 1.155, not better. Plausible explanation:
yesterday's spurious daily rebalance trades happened to capture some
favorable noise — they were noise but the 2021 strong-bull regime
made some of them profitable accidents. With the fix, V/Q/A edges
are essentially silent intra-quarter; their contribution to the
ensemble is near-zero except on quarterly-rebalance days. The
pre-fix version's +0.51 drag was a real cost, but smaller than the
"V/Q/A-as-additional-factor-tilt-with-no-net-edge-but-real-cost"
of the post-fix version.

Three competing hypotheses for the residual:

1. **The factor signal is real but its integration into the active
   ensemble is structurally wrong.** Path C cell D showed +43bp CAGR
   vs SPY post-tax — but Path C is a *standalone* synthetic-portfolio
   driver, not an Engine-A ensemble member. Adding the same signal
   to a turnover-driven daily-bar ensemble is not the same operation.
   This is the dominant hypothesis given the same factor signal that
   wins standalone loses on integration.

2. **The 16-name top-quintile basket is too small.** Memory
   `project_factor_edge_first_alpha_2026_04_24.md` documented exactly
   this failure mode for momentum_factor_v1 at 8 names/quintile.
   We're at 16 names/quintile, above the disaster threshold, but
   below the academic ≥200-name convention. Universe expansion
   (Workstream H) would address this.

3. **2021 was the wrong window for value-tilted edges.** 2021 was
   peak growth-leadership (NVDA, TSLA, mega-cap tech) — the exact
   regime where V/Q/A factors have historically struggled. A 5-year
   measurement (2021-2025) might show better mean Sharpe than the
   2021-only smoke. But that would require running the full multi-
   year campaign (out of scope for this dispatch).

## Recommended next-dispatch follow-up

The fix should land regardless of the residual — the 4 bugs were real
correctness issues independent of the factor-signal economic question.
Don't iterate the integration further until one of:

- Universe expansion to ~200+ names lands (Workstream H prerequisite)
- A multi-year measurement campaign is run to test whether the
  drag reverses across regimes (2022 vs 2021 sign-flip would be
  diagnostic)
- The factor signal is moved out of Engine A's per-bar ensemble into
  a slower-cadence sleeve (Engine C / Path C target-portfolio)

In the meantime, the V/Q/A edges should probably be moved to status
`paused` or `failed` in `edges.yml` until the integration question
resolves. That's an Engine F lifecycle decision, not an Engine A
edge-fix decision; out of scope for this dispatch.

## Hard constraints honored

- Engine B / live_trader untouched ✓
- `data/governor/` not edited mid-fix ✓ (anchor was copied in for the
  worktree to find existing state, no new mutations)
- Single-year smoke only (no full 5y × 3 reps) ✓
- Branch `vqa-edges-bugfixes`, worktree-isolated ✓
- Stayed inside `engines/engine_a_alpha/edges/`, `tests/`,
  `docs/Measurements/2026-05/`, `docs/State/health_check.md` ✓
