# Workstream J — Cross-Cutting Trio

**Branch:** `ws-j-cross-cutting-batch`
**Date:** 2026-05-04
**Lens:** Quantitative Developer

Three small, high-leverage cross-cutters that compound on every future
agent's reporting. Bundled in one branch because (a) they share zero
runtime coupling, (b) they're each ~1 file of code, and (c) merging them
together avoids three separate review cycles.

The unifying property: each makes the system more **legible** to its
future self. Decisions become auditable, failures become tagged, and
features are screened for the most common silent backtest leak.

---

## 1. Decision Diary

**Files:**
- `core/observability/__init__.py` — package surface
- `core/observability/decision_diary.py` — append-only JSONL writer/reader
- Wired into `orchestration/mode_controller.py::run_backtest`
  (post-summary hook)
- Tests: `tests/test_decision_diary.py` (11 tests)

**Storage:** `data/governor/decision_diary.jsonl` (gitignored — operational
state, regenerable per run).

**Schema (per line):**

| field             | type            | required | notes                                    |
|-------------------|-----------------|----------|------------------------------------------|
| `timestamp`       | str (ISO-8601)  | yes      | UTC, second resolution                   |
| `decision_type`   | str (enum)      | yes      | closed vocabulary, see below             |
| `what_changed`    | str             | yes      | ≤200 chars, validated                    |
| `expected_impact` | str or null     | no       | free-text                                |
| `actual_impact`   | str or null     | no       | left null at write time, filled post-hoc |
| `rationale_link`  | str or null     | no       | memory file path or commit/PR hash       |
| `schema_version`  | int             | yes      | currently `1`                            |
| `extra`           | dict            | no       | per-record metadata (e.g. Sharpe)        |

**`decision_type` vocabulary** (`DecisionType`):

- `flag_flip` — config flag toggled (e.g. `lifecycle_enabled: true`)
- `merge` — branch merged to main
- `edge_status_change` — Engine F lifecycle transition
- `config_change` — non-flag config edit (weights, thresholds)
- `measurement_run` — backtest completed
- `agent_dispatch` — multi-session orchestration kicked off

**Append-only invariant.** Writes use `open(..., "a")`. The
`test_append_is_append_only` test asserts that the byte prefix of an
older file is preserved after subsequent writes. To "update" an entry's
`actual_impact` post-hoc, append a new follow-up entry referencing the
original via `rationale_link` — never edit prior lines.

**Crash safety.** Each call opens, writes one terminated line, closes.
Partial writes leave at most one unparseable trailing line, which
`read_entries` skips with a `WARNING` log.

**Mode-controller wiring.** A `measurement_run` entry is emitted at the
end of every `run_backtest`. The hook is wrapped in `try/except` —
diary failures cannot crash a backtest. The `extra` field carries
`sharpe`, `cagr`, `max_drawdown`, `n_tickers`, `n_edges_loaded`,
`mode`, `start`, `end`, `no_governor`, `discover` so downstream
analytics don't have to JOIN against `performance_summary.json`.

---

## 2. Edge Graveyard Structured Tagging

**Files:**
- `engines/engine_a_alpha/edge_registry.py` — schema extension
- `scripts/migrate_edge_graveyard_tags.py` — one-time migration
- Tests: `tests/test_edge_graveyard_tagging.py` (11 tests)

**New optional fields on `EdgeSpec` / `edges.yml`:**

- `failure_reason` — closed vocabulary (`VALID_FAILURE_REASONS` constant):
  - `regime_conditional` — signal real but only fires in some regimes
  - `universe_too_small` — cross-sectional work below stat threshold
  - `data_quality` — source-side issue
  - `overfit` — in-sample win, OOS collapse
  - `cost_dominated` — alpha exists pre-cost, gone post-cost
  - `other` — explicit unknown (better than null)
- `superseded_by` — `edge_id` of replacement, or null

**Backward compatibility.** The fields are emitted in YAML only when
non-None. Existing entries without them parse identically; round-tripped
output omits them. The `extra` catch-all (e.g. `reclassified_to` from
the 2026-05-02 macro audit) continues to round-trip independently.

**Validation.** `EdgeRegistry.set_failure_metadata(edge_id, ...)`:

- Raises `ValueError` on `failure_reason` outside the closed vocabulary
- Raises `ValueError` on `superseded_by` referencing an unknown edge_id
- Raises `ValueError` on self-supersession
- Raises `KeyError` on unknown target edge_id
- Empty-string sentinel (`""`) clears a field

**Migration applied (2026-05-04).** Two canonical failed/marked-failed
edges tagged via `python -m scripts.migrate_edge_graveyard_tags
--registry-path data/governor/edges.yml`:

| edge_id              | failure_reason       | rationale (memory)                                       |
|----------------------|----------------------|----------------------------------------------------------|
| `momentum_factor_v1` | `universe_too_small` | `project_factor_edge_first_alpha_2026_04_24.md`          |
| `low_vol_factor_v1`  | `regime_conditional` | `project_low_vol_regime_conditional_2026_04_25.md`       |

Re-running the migration is a no-op (idempotency tested).

---

## 3. Info-Leakage Detector

**Files:**
- `core/observability/leakage_detector.py` — AST-based scanner
- Wired into `core/feature_foundry/feature.py::feature` decorator
- Tests: `tests/test_leakage_detector.py` (15 tests)

**Patterns flagged (`LeakagePattern` enum):**

| pattern               | description                                                       |
|-----------------------|-------------------------------------------------------------------|
| `negative_shift`      | `series.shift(-N)` for any positive `N` — forward read            |
| `forward_return`      | BinOp containing a negative shift — `(close.shift(-1)/close - 1)` |
| `unsafe_resample`     | `.resample(rule).last/max/min/first/agg(...)` without both       |
|                       | `closed='left'` and `label='left'` — pandas default leaks the    |
|                       | bar's own close into "as of bar open" queries                     |
| `future_index_slice`  | `df.loc[t + N:]` with positive `N` — heuristic                    |

**Why AST-based, not regex.** Variable names, parens, whitespace, and
multi-line continuations all defeat regexes. The AST sees through
`(((df['close']))).shift(  -1  )` correctly. Only literal int constants
(including unary-negated) are inspected; dynamic values produce
false-negatives by design — accepting silence over false alarms.

**Advisory mode.** Each warning includes line number, column, snippet,
and a one-sentence reason. Warnings are emitted via
`logging.WARNING`. The Foundry decorator scans at registration time
but **never blocks registration**. Next round upgrades to a CI gate
once the false-positive rate is calibrated.

**Example firing.** A synthetic feature with `df['close'].shift(-1)`:

```
core.observability.leakage_detector WARNING
  leakage_detector: <stdin>:4:15: [negative_shift]
  shift(-1) reads 1 bar(s) into the future — forbidden in any feature
  evaluated at time t | snippet: return df['close'].shift(-1).iloc[-1]
```

The same function still registers in the Foundry — the advisory does
not block the import (asserted by
`test_decorator_registers_leaky_feature_with_warning`).

**Coverage limits (acknowledged).**

- Does NOT chase imports — only scans the source of the function passed in
- Does NOT track aliases (`s = df['close']; s.shift(-1)` is caught only
  because the `.shift(-1)` call itself is flagged regardless of receiver)
- Does NOT understand `groupby().shift(-1)` distinctly from a top-level
  shift — but the warning still fires (same call site)
- False positives possible on `future_index_slice` heuristic
  (`df.loc[t + 1:]` is sometimes legitimate row-offset arithmetic)

---

## Acceptance criteria — verification

| Criterion                                                 | Status |
|-----------------------------------------------------------|--------|
| Diary writes successfully on simulated post-run          | PASS (`test_simulated_measurement_run_entry`) |
| Diary file is valid JSONL                                 | PASS (`test_jsonl_format_one_record_per_line`) |
| 2 failed edges migrated with correct `failure_reason`     | PASS (migration script output, citations above) |
| Leakage detector flags synthetic `close.shift(-1)`        | PASS (`test_negative_shift_is_flagged`) |
| Leakage detector passes a clean feature                   | PASS (`test_clean_feature_emits_no_warnings`) |
| All three components have unit tests                      | PASS (37 new tests across 3 files) |

**Hard constraints honoured:**

- Schema change to `edges.yml` is backward-compatible — existing tooling
  loads it unchanged (`test_legacy_yaml_without_new_fields_loads_clean`)
- Decision diary is append-only (`test_append_is_append_only`)
- Leakage detector is advisory, not blocking
  (`test_decorator_registers_leaky_feature_with_warning`)
- No full backtest run — synthetic test data only
- No edges.yml content modification during a measurement run
  (verified `ps aux` showed no active runs at migration time)

---

## Future work (out of scope this round)

1. **Diary follow-up entries.** A separate utility populates
   `actual_impact` for `measurement_run` entries by reading the diary
   forward (find the next `merge` or `flag_flip` and diff the Sharpe).
   Append-only via follow-up entries, never mutating originals.
2. **Leakage gate.** Once advisory warnings are calibrated against the
   real Foundry feature set, promote `feature_foundry.feature` to raise
   on leakage rather than warn.
3. **More patterns.** `pd.merge_asof` with `direction='forward'`,
   rolling windows on a forward-shifted series, `cumsum` after a
   negative shift — all candidates for the next round.
4. **Graveyard analytics.** Dashboard tab joining
   `failure_reason` × tier × age to surface which categories to
   re-examine when the universe expands.
