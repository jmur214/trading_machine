# Governance Lifecycle Journal — Architecture

**Status:** F11 Phase 1 LANDED 2026-05-07. Phase 2 (production write-path rewire) PROPOSE-FIRST.

**Source proposal:** [docs/Core/Ideas_Pipeline/F11_journal_redesign_proposal_2026_05_07.md](Ideas_Pipeline/F11_journal_redesign_proposal_2026_05_07.md)

## Why this exists

A backtest is supposed to be a measurement. The pre-F11 architecture mutated the source-of-truth governor file (`data/governor/edges.yml`) mid-run from two distinct write paths:

1. `engines/engine_f_governance/governor.py:592` — `StrategyGovernor.update_from_trades()` (EMA-smoothed weights)
2. `engines/engine_f_governance/lifecycle_manager.py:289` — `LifecycleManager.evaluate()` (status changes)

Consequences:

| # | Consequence | Why this hurt live-vs-backtest fidelity |
|---|---|---|
| 1 | Same config + same window can produce different output across runs unless governor state is snapshotted | The "config" appears identical but the SHARED STATE differs → live behavior depends on state too, but live state evolves in real time, not mid-bar |
| 2 | The 4-file snapshot/restore harness in `scripts/run_isolated.py` exists ONLY to bandage this | Live trading has no "snapshot/restore" mechanism — whatever happens at bar N is what bar N+1 inherits. The harness CREATES backtest-vs-live divergence by making backtests reproducible in a way live can never be |
| 3 | The 2026-04-25 registry-stomp bug | Registry's `ensure()` silently reverted lifecycle status to `active` on every backtest startup. Same anti-pattern: in-run mutation racing with the source-of-truth file |
| 4 | Cross-run forensics are weak | To compare two runs' outcomes, you have to compare 4 files of governor state pre/post — instead of a single audit trail |

## Design — append-only journal + explicit apply

A backtest run NEVER mutates `edges.yml`. Period. All lifecycle decisions append to `data/governor/lifecycle_journal.jsonl`. A separate `scripts/journal_apply.py` CLI reads the journal and applies entries to `edges.yml` as a single transaction at a configurable cadence (end-of-cycle, end-of-day, or never for pure-measurement runs).

```
[backtest run]
    │
    ├── (eventual) governor.update_from_trades() ─────► append to lifecycle_journal.jsonl
    └── (eventual) lifecycle_manager.evaluate()  ─────► append to lifecycle_journal.jsonl
                                                │
                                                ▼
                            [edges.yml UNCHANGED during the run]
                                                │
                                                ▼
                          [end-of-run OR cycle boundary OR end-of-day]
                                                │
                                                ▼
                            [scripts/journal_apply.py reads journal,
                             applies as single transaction to edges.yml]
                                                │
                                                ▼
                            [edges.yml is the resulting source-of-truth]
```

## Invariants

1. A backtest run NEVER mutates `data/governor/edges.yml` during the run. The file is read-only.
2. All lifecycle decisions append to `data/governor/lifecycle_journal.jsonl` with: `timestamp`, `run_id`, `decision_type`, `edge_id`, `payload`, `schema_version`. Append-only; no mutation.
3. The journal IS the audit trail. Every decision visible by `run_id + timestamp`. Cross-run forensics become a single SQL-like query on the journal.
4. Apply is explicit, not implicit. The user (or a wrapping script like an autonomous-cycle driver) decides when to apply the journal to `edges.yml`. Backtest harness measurement runs do NOT auto-apply.
5. Apply is idempotent. A `.journal_apply_mark` file records the timestamp of the last applied entry; re-running with no new entries is a no-op.
6. Apply is crash-safe. The transaction is `read journal → mutate in-memory specs → write tmpfile → os.rename → write mark`. If any step crashes pre-rename, `edges.yml` is unchanged and the mark is unchanged. Next run re-applies the same entries (each apply is idempotent at the entry level: status_change overwrites, tier_change overwrites).

## Schema — `JournalEntry`

```python
@dataclass
class JournalEntry:
    timestamp: str              # ISO-8601 UTC at decision time
    run_id: str                 # backtest run_id (or live-session id)
    decision_type: str          # one of ALLOWED_DECISION_TYPES
    edge_id: Optional[str]      # the edge being modified (None for global)
    payload: Dict[str, Any]     # decision-type-specific dict (JSON-safe)
    schema_version: int         # currently 1
```

**Closed vocabulary `decision_type`:**

| decision_type | Payload shape | Source path |
|---|---|---|
| `weight_update` | `{"new_weight": float, "prior_weight": float?}` | governor.update_from_trades EMA write (Phase 2) |
| `status_change` | `{"new_status": str, "prior_status": str?, "reason": str?}` | lifecycle_manager.evaluate (Phase 2) |
| `tier_change` | `{"new_tier": str, "prior_tier": str?}` | tier_classifier reclassification (Phase 2) |
| `regime_weight_update` | `{"regime": str, "weight": float}` | regime-conditional weight learn (Phase 2) |
| `manual` | free-form | human-initiated change (audit log only) |

## Phase plan

### Phase 1 (LANDED 2026-05-07)

Additive, non-breaking. Existing engine writers (governor.py, lifecycle_manager.py) NOT yet rewired — they still mutate edges.yml directly during backtests. The journal infrastructure ships ready for Phase 2 wire-up.

| Component | Status | Notes |
|---|---|---|
| `engines/engine_f_governance/journal.py` | LANDED | `LifecycleJournal` class — append, append_many, read_all, iter_entries, filter_since, truncate (atomic). Thread-safe within a process. |
| `scripts/journal_apply.py` | LANDED | CLI driver — reads pending entries, projects onto `EdgeRegistry`, writes via atomic temp+rename, advances mark. |
| `tests/test_lifecycle_journal.py` | LANDED | 20 tests including 8-thread concurrent-write stress. |
| `tests/test_journal_apply.py` | LANDED | 16 tests including idempotency, --since override, --dry-run, crash-safety, unknown-edge skip. |
| This architecture doc | LANDED | What you are reading. |

### Phase 2 (PROPOSE-FIRST per CLAUDE.md Engine F rules)

User must approve before code lands.

| Component | Effort | Risk |
|---|---|---|
| Modify `engines/engine_f_governance/governor.py:592` `update_from_trades` to write through journal | 2-3 hr | LOW — drops a write call, replaces with `journal.append(make_weight_update(...))` |
| Modify `engines/engine_f_governance/lifecycle_manager.py:289` `evaluate` to write through journal | 2-3 hr | LOW |
| Optional `apply_journal_at_end: bool = False` kwarg on `mode_controller.run_backtest` | 1-2 hr | LOW — explicit opt-in |
| Verify 30+ runs reproducible WITHOUT 2 redundant harness files | 2-3 hr | MEDIUM — this is the validation gate |
| Simplify `scripts/run_isolated.py` snapshot scope (4 files → 2) | 1-2 hr | MEDIUM — only after the run-validation gate passes |

**Migration sequencing (do not collapse):**

1. Build journal + apply, validate in parallel (DONE Phase 1)
2. Switch `governor.py` writes through journal (harness still active — keeps 4-file snapshot)
3. Switch `lifecycle_manager.py` writes through journal (harness still active)
4. Verify 30+ runs reproducible WITHOUT the 2 redundant harness files (edges.yml + edge_weights.json snapshots)
5. ONLY THEN remove the redundant harness coverage

The harness has caught real regressions twice (registry-stomp 2026-04-25; audit-geometry 2026-05-07). Removing it before the journal pattern is independently verified would lose that safety net.

## Backtest-vs-live fidelity (the core argument)

| Behavior | Pre-fix (today, governor.py-direct-write) | Post-Phase-2 |
|---|---|---|
| Lifecycle decisions during backtest | Mutate the file the next backtest reads | Append to journal that's separate from any backtest's state |
| Re-running the same backtest | Required snapshot/restore to be reproducible | Naturally reproducible because no mutation |
| Live trading semantics | Lifecycle decisions mutate the file in real time | Lifecycle decisions append to journal in real time; apply runs on a configured cadence |
| Backtest vs live divergence | Backtest is artificially reproducible (via snapshot bandage); live can't be | Backtest and live are SAME shape — both append-only to journal, both apply at the same cadence |

The user's stated framing on F11 approval was: *"we never ever want to overfit our system via backtest so it doesn't hold up live. The goal always is that our system will perform live as close to as how it performs in the backtest."* The journal pattern makes backtest mechanics IDENTICAL to live mechanics by construction.

## Operations

### Where files live

| Path | Purpose | gitignored? |
|---|---|---|
| `data/governor/lifecycle_journal.jsonl` | The journal | YES (under `data/`) |
| `data/governor/.journal_apply_mark` | ISO-8601 timestamp of the last applied entry | YES (under `data/`) |
| `data/governor/edges.yml` | The post-apply source of truth | YES (under `data/`) |
| `engines/engine_f_governance/journal.py` | Writer/reader | tracked |
| `scripts/journal_apply.py` | Apply driver | tracked |

### Common queries

```bash
# Apply pending entries (dry-run first)
python -m scripts.journal_apply --dry-run
python -m scripts.journal_apply

# JSON output for machine consumption
python -m scripts.journal_apply --json

# Re-apply from a specific cutoff (override the mark)
python -m scripts.journal_apply --since "2026-05-07T00:00:00+00:00"
```

### Cross-run forensics

Journal is JSONL — `jq` and standard text tools work directly:

```bash
# All status changes for one edge across history
grep '"edge_id":"momentum_edge_v1"' data/governor/lifecycle_journal.jsonl \
  | grep status_change | jq .

# Decisions made within a specific run_id
grep '"run_id":"abc-123"' data/governor/lifecycle_journal.jsonl | jq .

# Total decision count by type (Phase 1)
jq -r '.decision_type' data/governor/lifecycle_journal.jsonl | sort | uniq -c
```

## Why this design choice over alternatives

- **Why JSONL vs SQLite for the journal?** JSONL is append-only by construction (no database file format risk; no ALTER TABLE migrations; corrupt-line resilience via `iter_entries` skip-on-malformed). The per-line cost is negligible at expected volume (~thousands of entries/year). Cross-tool friendliness (jq, grep, awk) outweighs the ergonomics of SQL.

- **Why "apply" as an explicit step rather than auto-apply at end of run?** Auto-apply re-introduces the exact failure mode F11 set out to remove: in-backtest mutation of `edges.yml`. By making apply explicit, measurement runs are pure measurement (mark unchanged, edges.yml unchanged) and only the autonomous-cycle driver applies as part of its post-cycle bookkeeping.

- **Why per-process thread lock and not multi-process?** The apply layer holds an exclusive file lock on `edges.yml` during the read+apply transaction (POSIX `os.replace`). Within a process, threaded backtests append to the journal under the per-process lock. Multi-process concurrent appends would need filelock-style coordination — deferred until live-deployment shows it's needed.

- **Why is `weight_update` counted but not persisted in Phase 1?** Weights live in `edge_weights.json`, not `edges.yml`. Phase 2 will route weight_update entries to the right store; Phase 1 ships the schema + counter so the journal is shape-correct before the wiring lands.

## Verification (Phase 1)

- 36 tests across `test_lifecycle_journal.py` (20) + `test_journal_apply.py` (16)
- Includes 8-thread × 25-write concurrent-append stress with no torn writes
- Includes idempotency, --since override, --dry-run no-mutation invariant
- Phase-1 invariant test: instantiating + appending the journal does NOT touch `edges.yml`

## Phase 2 acceptance bar

Before Phase 2 lands, the user must approve:
- The two engine modifications (governor.py:592, lifecycle_manager.py:289)
- The verification protocol: 30+ deterministic-harness reps reproducible WITHOUT the 2 redundant snapshot files
- The harness-simplification step (only after the verification gate passes)

Phase 2 dispatch is staged in `docs/Core/Ideas_Pipeline/dispatchable_prompts_2026_05_07.md`.
