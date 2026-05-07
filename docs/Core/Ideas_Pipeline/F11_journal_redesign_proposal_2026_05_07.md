# F11 Architectural Redesign — Journal-and-Apply Proposal

**Status:** PROPOSE-FIRST per CLAUDE.md. Engine F changes that span engines need explicit user approval before code lands. This doc captures the design rationale, scope, and trade-offs. User approves before implementation begins.

**Trigger:** R1 (codebase-access auditor) §8: *"F11 write-back smell is deeper than labeled. Two distinct write paths into `data/governor/edges.yml` during a backtest: `governor.py:592` and `lifecycle_manager.py:289`. `run_isolated.py` had to grow a 4-file snapshot harness to bound this. Real fix is structural — write to a journal + apply at next-cycle boundary, not snapshot/restore around the smell."*

User's specific framing on approval: *"we never ever want to overfit our system via backtest so it doesn't hold up live. The goal always is that our system will perform live as close to as how it performs in the backtest."*

This redesign is **directly aligned with that goal** — it removes a category of backtest-vs-live divergence by construction.

---

## Problem statement (concrete)

A backtest is supposed to be a measurement. But the current architecture mutates the source-of-truth governor file MID-RUN.

### Two write paths into `data/governor/edges.yml` during a backtest:

1. **`engines/engine_f_governance/governor.py:592`** — `StrategyGovernor.update_from_trades()` writes EMA-smoothed edge weights based on intra-run trade attribution.
2. **`engines/engine_f_governance/lifecycle_manager.py:289`** — `LifecycleManager.evaluate()` writes status changes (`active` → `paused` → `retired`) when edges fail lifecycle gates.

### Consequences

| # | Consequence | Why this hurts live-vs-backtest fidelity |
|---|---|---|
| 1 | Same config + same window can produce different output across runs unless governor state is snapshotted | The "config" appears identical but the SHARED STATE differs → live behavior depends on state too, but live state evolves in real time, not mid-bar |
| 2 | The 4-file snapshot/restore harness exists ONLY to bandage this | Live trading has no "snapshot/restore" mechanism — whatever happens at bar N is what bar N+1 inherits. So the harness CREATES the backtest-vs-live divergence by making backtests reproducible in a way live can never be |
| 3 | The 2026-04-25 registry-stomp bug was a manifestation | Registry's `ensure()` silently reverted lifecycle status to `active` on every backtest startup. Same anti-pattern: in-run mutation that races with the source-of-truth file |
| 4 | Cross-run forensics are weak | To compare two runs' outcomes, you have to compare 4 files of governor state pre/post — instead of a single audit trail |
| 5 | Discovery cycle's audit-geometry surfaced last night IS this same shape | `BacktestController._prepare_orders` vs `mode_controller.run_backtest` produce different governor state mutations because they take different paths through the same shared file |

---

## Proposed design — Journal-and-Apply

### Current shape

```
[backtest run]
    │
    ├── governor.update_from_trades() ─────► edges.yml (mutates mid-run)
    └── lifecycle_manager.evaluate() ──────► edges.yml (mutates mid-run)
                                                │
                                                ▼
                            [run_isolated.py snapshots/restores 4 files]
                                                │
                                                ▼
                              [reproducible measurement, but only via bandage]
```

### Journal-and-Apply shape

```
[backtest run]
    │
    ├── governor.update_from_trades() ────► append to lifecycle_journal.jsonl
    └── lifecycle_manager.evaluate() ─────► append to lifecycle_journal.jsonl
                                                │
                                                ▼
                            [edges.yml UNCHANGED during the run]
                                                │
                                                ▼
                          [end-of-run OR cycle boundary]
                                                │
                                                ▼
                            [scripts/journal_apply.py reads journal,
                             applies as single transaction to edges.yml]
                                                │
                                                ▼
                            [edges.yml is the resulting source-of-truth]
```

### Key invariants of the new design

1. **A backtest run NEVER mutates `data/governor/edges.yml`.** Period. The file is read-only during a run.
2. **All lifecycle decisions append to `data/governor/lifecycle_journal.jsonl`** with: `timestamp`, `run_id`, `decision_type`, `edge_id`, `payload`. Append-only, no mutation.
3. **The journal IS the audit trail.** Every decision visible by `run_id + timestamp`. Cross-run forensics become a single SQL-like query on the journal.
4. **Apply is explicit, not implicit.** The user (or a wrapping script like `run_autonomous_cycle.py`) explicitly decides when to apply the journal to `edges.yml`. Backtest harness measurement runs do NOT auto-apply.
5. **Snapshot/restore harness simplifies.** Currently snapshots 4 files (edges.yml, edge_weights.json, regime_edge_performance.json, lifecycle_history.csv); journal-side fix means edges.yml + edge_weights.json no longer need snapshotting. Reduces to 2 files (or zero, if edge_weights.json migrates to journal too).

### Backtest-vs-live fidelity (your stated concern)

| Behavior | Pre-fix | Post-fix |
|---|---|---|
| Lifecycle decisions during backtest | Mutate the file the next backtest reads | Append to a journal that's separate from any backtest's state |
| Re-running the SAME backtest | Required snapshot/restore to be reproducible | Naturally reproducible because no mutation |
| Live trading semantics | Lifecycle decisions mutate the file in real time | Lifecycle decisions append to journal in real time; apply runs on a configured cadence (e.g., end-of-day, end-of-cycle) |
| Backtest vs live divergence | Backtest is artificially reproducible (via snapshot bandage); live can't be | Backtest and live are SAME shape — both append-only to journal, both apply at the same cadence |

**This is the key insight for your concern:** the journal pattern makes backtest mechanics IDENTICAL to live mechanics. There's no special "snapshot/restore" only-in-backtest behavior. What you measure in backtest is exactly what live does, structurally.

---

## Files affected

### New files

| File | Purpose |
|---|---|
| `engines/engine_f_governance/journal.py` | `LifecycleJournal` class — append-only writer with structured schema, JSONL on-disk format |
| `data/governor/lifecycle_journal.jsonl` | The journal itself (gitignored — runtime artifact) |
| `scripts/journal_apply.py` | CLI driver — reads journal entries since last apply, transactionally updates edges.yml |
| `tests/test_lifecycle_journal.py` | Unit tests (append, schema validation, idempotent apply, transaction-failure rollback) |
| `docs/Core/governance_lifecycle_journal_design.md` | Architecture doc (charter-level) |

### Modified files

| File | Change |
|---|---|
| `engines/engine_f_governance/governor.py:592` | `update_from_trades` writes through journal instead of direct edges.yml mutation |
| `engines/engine_f_governance/lifecycle_manager.py:289` | `evaluate` writes through journal instead of direct mutation |
| `scripts/run_isolated.py` | Snapshot-restore set reduces from 4 files to 2 (edges.yml + edge_weights.json removed; lifecycle_history.csv + regime_edge_performance.json kept until they're also migrated to journal pattern) |
| `orchestration/mode_controller.py` | Optional `apply_journal_at_end: bool = False` parameter on `run_backtest` (default false → backtest is pure measurement; explicit `True` for autonomous cycles that should apply lifecycle decisions) |
| `engines/engine_f_governance/lifecycle_history.csv` | Stays as-is for now; could migrate to journal in a follow-on |

### Files NOT affected (charter boundary preserved)

- `engines/engine_a_alpha/` — no changes (Engine A's read of edges.yml unaffected)
- `engines/engine_b_risk/` — no changes
- `engines/engine_c_portfolio/` — no changes
- `engines/engine_d_discovery/` — no changes (Discovery's gauntlet stays the same)
- `engines/engine_e_regime/` — no changes
- `live_trader/` — no changes (still a stub; future live integration uses the same journal pattern)

---

## Scope estimate

| Phase | Time | Deliverable |
|---|---|---|
| Design doc + propose-first approval | This doc + your sign-off | (current state) |
| `LifecycleJournal` module + tests | 4-6 hr | Append-only writer, schema, JSONL format, tests |
| `journal_apply.py` CLI + tests | 4-6 hr | Apply with transactional safety, idempotency, dry-run mode, test coverage |
| Wire `governor.py:592` writes through journal | 2-3 hr | Modify `StrategyGovernor.update_from_trades` |
| Wire `lifecycle_manager.py:289` writes through journal | 2-3 hr | Modify `LifecycleManager.evaluate` |
| Update `mode_controller.py` for optional apply-at-end | 1-2 hr | New kwarg, threading through |
| Simplify snapshot harness (remove 2 of 4 files) | 1-2 hr | `run_isolated.py` updated; 3-rep determinism still PASSES |
| End-to-end integration test | 2-4 hr | Backtest → journal entries → apply → edges.yml updated correctly; idempotency verified |
| Architecture doc | 2-3 hr | `governance_lifecycle_journal_design.md` |
| **Total** | **18-29 hr (≈ 2-3 days focused)** | |

---

## Risks

| Risk | Mitigation |
|---|---|
| Apply transaction fails mid-edges-yml-write → corrupt edges.yml | Atomic write: write to `.tmp` file then `os.rename` — POSIX guarantees atomic rename |
| Two concurrent applies (e.g., autonomous cycle + manual apply) → race | File lock on edges.yml during apply; second apply waits or aborts |
| Journal file grows unboundedly | Truncate (or archive) journal entries pre-last-apply during apply itself |
| Existing tests / scripts that assume in-run mutation | Inventory + update; the audit-geometry finding from yesterday already shows this is rare |
| Live deployment far in the future may need different cadence | The journal pattern is cadence-agnostic — apply can run end-of-day, end-of-bar, end-of-week, manually. No design lock-in |

---

## Risk vs. value

**Pre-fix steady state today:**
- 4-file snapshot/restore harness exists permanently
- Backtest reproducibility is bandaged, not structural
- Backtest-vs-live divergence is built into the architecture
- Audit findings (registry-stomp, audit-geometry, F11) all derive from this shape

**Post-fix steady state:**
- Backtest reproducibility is structural (no mutation, no race possible)
- Backtest mechanics === live mechanics (your stated goal)
- Cross-run forensics: single journal query
- The category of bug R1's audit just surfaced is impossible by construction

**One-time cost: 2-3 days focused work.**

**Honest caveat:** the snapshot harness has caught real regressions twice this month (the registry-stomp bug 2026-04-25; the audit-geometry finding 2026-05-07). Removing the harness BEFORE the journal pattern is fully validated would lose that safety net. The migration MUST keep the harness operational until the journal pattern is independently verified.

Migration sequencing:
1. Build journal + apply, validate in parallel
2. Switch governor.py writes through journal (harness still active)
3. Switch lifecycle_manager.py writes through journal (harness still active)
4. Verify 30+ runs reproducible WITHOUT the 2 redundant harness files (edges.yml, edge_weights.json snapshots)
5. ONLY THEN remove the redundant harness coverage

---

## User decision points

1. **Approve the journal-and-apply design as scoped above?** Yes / no / modify
2. **Sequence priority** — is this "this month" (per synthesis-by-primary-dev's monthly slot) or sooner? My read: "this month" — not urgent but valuable; should land before the next major architectural addition (Moonshot Sleeve scaffolding) so sleeves are built on the new pattern.
3. **lifecycle_history.csv migration** — stay on CSV-append-during-run (current) or migrate to journal too? My read: stay on CSV for now; migrate in a follow-on if it's worth the effort. Different shape (history is informational, not state-mutating).
4. **edge_weights.json migration** — same question. My read: yes, migrate. It IS state-mutating during runs (governor writes it). Cleaner if both governor outputs go through the same journal.

---

## What this enables downstream

The journal pattern is foundational for:

- **Live deployment when it eventually happens** — same cadence model as live trading uses
- **Cleaner audit trails** — a single SQL-able journal vs four files to grep across
- **Discovery cycle architecture** — autonomous cycle's lifecycle decisions become visible per-cycle without state-spelunking
- **A second human reviewer** (R2 mentioned this as a top-1% gap) — single journal makes outside review tractable
- **Cross-cycle forensics** — "show me every lifecycle decision on edge X across the last 90 days" becomes a single query

This isn't a polish refactor. It's the structural fix that closes a class of audit findings AND moves backtest mechanics toward live mechanics.

**User decision:** approve / modify / defer ___
