# Decision Diary Backfill — 2026-05-06

**Branch:** `ws-j-diary-backfill`
**Diary path:** `data/governor/decision_diary.jsonl` (gitignored — local-only)
**Entries written:** 12
**Backfill script:** `scripts/backfill_decision_diary.py` (idempotent — keyed on `(timestamp, what_changed)`)

## Purpose

WS-J shipped decision-diary infrastructure
(`core/observability/decision_diary.py`) on 2026-05-05, but the diary
file was empty — no historical context, only go-forward entries from
new code paths. This backfill populates the diary with the 12
load-bearing decisions from the week of 2026-05-04 through
2026-05-07 so post-hoc audits and impact reviews have the same
record they would have had if the diary had shipped a week earlier.

`actual_impact` is filled in for all entries because we have
already observed the outcomes — this is the post-hoc enrichment
pattern the schema's docstring describes, condensed into single
write events rather than follow-up entries.

## Entries

| # | Timestamp (UTC)        | Type                  | Subject                                              |
|---|------------------------|-----------------------|------------------------------------------------------|
| 1 | 2026-05-04T14:00:00Z   | measurement_run       | Foundation Gate — mean Sharpe 1.296 over 2021-2025   |
| 2 | 2026-05-05T10:00:00Z   | config_change         | SimFin FREE adapter wired (3,984 tickers)            |
| 3 | 2026-05-05T18:00:00Z   | measurement_run       | Path C 4-cell harness — Cell D fails -15% MDD        |
| 4 | 2026-05-06T14:00:00Z   | measurement_run       | Path C vol overlay falsified (annual cadence)        |
| 5 | 2026-05-06T16:00:00Z   | merge                 | V/Q/A fundamentals edges merged                      |
| 6 | 2026-05-06T18:00:00Z   | edge_status_change    | V/Q/A 3 HIGH bugfixes shipped (residual drag)        |
| 7 | 2026-05-07T14:00:00Z   | edge_status_change    | V/Q/A sustained-score=0.3 fix closes drag            |
| 8 | 2026-05-06T19:00:00Z   | measurement_run       | HMM regime signal falsified (AUC 0.49 fwd-20d)       |
| 9 | 2026-05-06T21:00:00Z   | measurement_run       | Cheap regime validation Branch 3 (VIX term, P/C)     |
| 10| 2026-05-06T22:00:00Z   | config_change         | Path C deferred (3 unblock criteria written)         |
| 11| 2026-05-06T23:00:00Z   | agent_dispatch        | External audit findings consolidated F1-F11          |
| 12| 2026-05-07T18:00:00Z   | merge                 | Phase A substrate cleanup begins (A1 + A3 merged)    |

## Rationale per entry

Each entry's `rationale_link` points to the controlling memory file
under `~/.claude/projects/.../memory/` or to a session/plan doc.
Memory paths use absolute paths so the link resolves regardless of
which worktree is reading the diary. Two entries reference rationale
files that may not exist on disk yet
(`project_fundamentals_edges_shipped_2026_05_06.md`,
`project_vqa_bugfix_residual_drag_2026_05_06.md`,
`project_vqa_sustained_scores_win_2026_05_07.md`,
`project_cheap_input_validation_branch3_2026_05_06.md`,
`docs/Sessions/Other-dev-opinion/2026-05-06_consolidated_audit_findings.md`)
— `rationale_link` is a free-text pointer per the schema, so missing
target files do not invalidate entries; they will resolve once those
memory files are written.

## Schema conformance

Each line is one JSON object with the six required fields
(`timestamp`, `decision_type`, `what_changed`, `expected_impact`,
`actual_impact`, `rationale_link`) plus the implicit `schema_version`
and `extra` fields produced by `DecisionDiaryEntry`. Constraints
checked at write time by `DecisionDiaryEntry.__post_init__`:

- `decision_type` in the closed enum vocabulary
- `what_changed` non-empty and ≤200 chars
- `schema_version == 1`

The validating reader `core.observability.decision_diary.read_entries`
returns 12 entries with no warnings logged — confirming all 12
lines round-trip cleanly through the parser.

## Hard constraints honored

- `core/observability/decision_diary.py` not modified (script
  imports the public API only).
- No backtests replayed.
- All 12 entries appended via the official `append_entry` helper —
  no manual JSONL editing.

## Idempotency

Re-running `scripts/backfill_decision_diary.py` writes 0 new entries
because the script reads existing entries first and skips those
matching `(timestamp, what_changed)`. The diary remains append-only
in spirit even though backfill runs are repeatable.
