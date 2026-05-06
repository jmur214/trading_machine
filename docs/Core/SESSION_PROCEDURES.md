# Session Procedures

This file holds the procedural rules for how to operate during a 
working session. It is the operational complement to `CLAUDE.md` 
(which is the constitution) and `agent_instructions.md` (which 
covers documentation maintenance specifics).

If you're ever uncertain about what to do procedurally, re-read 
this file. It's written to be re-readable mid-session without 
re-loading anything else.

---

## When the user asks "what's next" or "highest impact"

Don't ask for clarification. Decide. Use this procedure, stopping 
at the first path that applies:

### Path 1 — Continuing work
If the current session has in-progress work that isn't complete, 
continue it. Check conversation context first, then `ROADMAP.md` 
for items marked `[~]` (in progress).

### Path 2 — Critical findings
Check `docs/State/health_check.md` for unresolved HIGH-severity 
items. These are technical debt actively harming the system. 
Prioritize them before adding features.

If `health_check.md` is empty or missing, run the engine-auditor 
subagent against the engines worked on most recently to populate 
findings, then proceed with the highest-priority result.

### Path 3 — Charter-implementation drift
Compare the latest engine work against `docs/Core/engine_charters.md`. 
If an engine is drifting from its intended boundaries (risk logic in 
Engine A, signal generation in Engine B, accounting outside Engine C, 
etc.), fixing that drift is higher-impact than new features.

Delegate this comparison to the engine-auditor subagent. The auditor 
returns findings; you propose a fix.

### Path 4 — Code quality degradation
Look for signs the system is accumulating debt:
- Duplicate files (`*_bak.py`, dual implementations of one concept)
- Functions over 200 lines or files over 500 lines
- Test files that are empty stubs (under 1KB)
- TODO comments older than 90 days
- Imports that no longer resolve
- Dead branches in conditionals (always-true or always-false)

Delegate scanning to the code-health subagent if it exists. 
Propose cleanup based on what it returns.

### Path 5 — Unprocessed ideas
Check `docs/Core/Ideas_Pipeline/human.md` under `# 📥 NEW INBOX`. 
If 3+ items are present, the inbox itself is friction — process it 
through the ideas pipeline (see "Ideas pipeline routing" below).

If 1-2 items are present, leave them for now unless the user 
explicitly asks to process the inbox.

### Path 6 — Roadmap progression
Propose the next `[ ]` item in the earliest incomplete Phase of 
`ROADMAP.md`. Don't skip phases. Don't pick the most exciting item; 
pick the next one in order.

### Procedure rules
- State which path applies in one sentence, then proceed
- Paths 1-5 are about improving what exists. Prefer them over Path 6 
  when reasonable candidates exist
- Most sessions should find work in paths 1-5
- If genuinely no path applies (system is clean, roadmap empty, 
  no findings, no ideas), say so plainly and ask the user what 
  they want to do

### The mental check
Ask yourself: "If no one added any new ideas or roadmap items, is 
the codebase done?" The answer is always no. There's always 
refactoring, test coverage, boundaries to tighten, patterns to 
extract. Finding that work is part of your job, not the user's.

---

## Ideas pipeline routing

Three files at three stages. Workflow rules are also embedded in 
each file's header — those are the source of truth; this is a 
summary.

**Stage 1: Inbox → Backlog**
- Source: `docs/Core/Ideas_Pipeline/human.md` under `# 📥 NEW INBOX`
- Action: Extract concepts, categorize them, assign tracking IDs 
  (`#ML-1`, `#RISK-2`, etc.) in `ideas_backlog.md`
- After: CUT the processed text into `# 🗄️ PROCESSED ARCHIVE` in 
  `human.md`
- Stop: Tell the user to review `ideas_backlog.md` and either 
  leave revisions in the scratchpad or mark items `[x]` to 
  approve them

**Stage 2: Backlog → Evaluations**
- Trigger: User has marked items `[x]` in `ideas_backlog.md`
- Action: Move those items to `idea_evaluations.md` with full 
  Cognitive Lens analysis (Core Concept, Feasibility, Impact, 
  Execution Risks, conviction flag 🟢🟡🔴⚠️)
- Remove from backlog after promotion

**Stage 3: Evaluations → Roadmap**
- Trigger: User explicitly approves an evaluation
- Action: Synthesize into a main goal with actionable sub-steps, 
  inject into appropriate Phase in `ROADMAP.md`
- Remove from evaluations after promotion

You may proactively start Stage 1 when the inbox has 3+ items and 
the user hasn't asked. Stages 2 and 3 require explicit user 
approval — do not promote without it.

---

## When you propose architectural changes

For anything in the "must propose first" list in `CLAUDE.md`:

1. Describe the change in 3-5 sentences
2. Name the engines and files affected
3. Identify the charter implications — is this within current 
   boundaries, or does it require updating charters?
4. State the rollback path if it goes wrong
5. Wait for explicit approval before executing

For Engine B (Risk) and `live_trader/` specifically, also include:
- What real-money paths could be affected
- What testing would precede a live deployment of this change
- Whether the change should be gated behind a new flag or config

---

## During substantive work

**Before writing code**: read the relevant engine's `index.md` if it 
exists. The hybrid index files combine human-written architectural 
notes with auto-generated code references — both are useful.

**Before running new CLI**: check `execution_manual.md`. If the 
command isn't there, either find an equivalent that is, or add the 
new command to the manual immediately.

**Before assuming a file does what its name implies**: read it. 
This codebase has known cases where filenames lie (deprecated 
`cockpit/dashboard/`, `*_bak.py` files, dual-governor situation). 
Trust the code, not the path.

**When you encounter a surprise**: log it to `lessons_learned.md` 
in the same session. Surprises forgotten are surprises that 
recur.

---

## At session end

Run through this checklist before stopping. Most steps run 
automatically via hooks; do them manually if hooks didn't fire.

- [ ] Did I add a new CLI command? → update `execution_manual.md`
- [ ] Did I complete a roadmap item? → mark `[x]` in `ROADMAP.md`
- [ ] Did I find or resolve a code quality issue? → update 
      `health_check.md`
- [ ] Did I touch `engines/**/*.py`? → run 
      `python scripts/sync_docs.py`
- [ ] Did I learn something non-obvious? → append to 
      `lessons_learned.md`
- [ ] Was substantive work done this session? → write a summary to 
      `docs/Sessions/YYYY-MM/YYYY-MM-DD_session.md` using the 
      template at `docs/Sessions/_template.md`
- [ ] Is there uncommitted work? → review with `git status`, commit 
      logical units via `/commit` skill, stash only if genuinely 
      interrupting mid-thought

The session summary is what makes the next session start with 
context instead of starting cold. The SessionStart hook reads the 
most recent summaries to orient the next instance of you. Write 
them well; future-you depends on it.

---

## Post-push outside-opinion review (when user requests)

After committing and pushing at the end of a session, the user 
sometimes asks Claude (typically a separate instance, in another 
window or a fresh chat) to review what just shipped — read the 
docs, see how things have changed, where the project stands, and 
how to move forward. Those reviewer responses are saved to:

```
docs/Sessions/Other-dev-opinion/<MM-DD-YY>_<short-tag>.md
```

(Example: `04-29-26_a-and-i.md` — "audit-and-improvements" review 
following the 2026-04-29 push that completed Phase 1.)

**Convention for these files:** if the user sends multiple messages 
to the reviewer, each follow-up is separated from the previous 
section by a horizontal underscore divider — a line of underscores 
(length varies, typically `_____________________`). Each segment 
below a divider is a new user prompt + the reviewer's response. 
Treat the file as an interleaved transcript, not a single 
monolithic essay.

**When you're invoked AS the reviewer** (the session opens with 
"review this doc" or similar after the user has just pushed):
1. Read the latest file in `docs/Sessions/Other-dev-opinion/` 
   for context on what the prior reviewer said — your assessment 
   should build on that, not repeat it.
2. Read `git log --oneline origin/main~20..HEAD` to see what 
   actually shipped between reviews.
3. Read the most recent session summary (or two) in 
   `docs/Sessions/<latest-month>/`.
4. Compare claims-in-summaries to code reality. Be brutally 
   honest — that's the whole point of an outside opinion.

**When you're invoked AFTER the reviewer has written their take** 
(the user pastes a path to a new `Other-dev-opinion/` doc and asks 
you to act on it, as in the 2026-04-29 case):
1. Read it at length.
2. Synthesize a forward-plan update if the doc proposes 
   architectural or sequencing changes — UPDATE 
   `docs/State/forward_plan.md` in place. Prior versions live in 
   `docs/Archive/forward_plans/` (auto-archived when superseded).
3. Update `ROADMAP.md` with any new phases or re-ordering the 
   plan implies.
4. Note outstanding empirical questions (e.g., "OOS validation of 
   X is now load-bearing") in the plan — those become the next 
   session's first work items.

---

## Coordinating parallel agents (director mode)

When the user puts you in **director mode** — you write prompts that 
the user pastes to one or more separate Claude Code sessions running 
on the same project — the full pattern is documented in 
`docs/Core/MULTI_SESSION_ORCHESTRATION.md`. Read that for the 
end-to-end flow, including:

- When multi-session beats in-session subagents
- The director vs worker role split
- The worktree + data isolation setup (run 
  `./scripts/setup_agent_worktree.sh <name> <branch>` per worker)
- Writing self-contained worker prompts (continuity vs cold-start)
- Anti-patterns (concurrent writes to `data/governor/`, branch 
  switching mid-task, etc.)
- Synchronization patterns (pure parallel, fan-out/fan-in, sequential 
  rounds, hub-and-spoke, one-slow-plus-N-fast)

The pattern works for any number of concurrent workers — same setup 
for 1 or 100. **Hard rule:** each concurrent worker gets its own 
`git worktree` produced by the setup script; never share a single 
worktree across concurrent workers.

Single-agent dispatches and sequential rounds (one worker finishes 
before the next starts) don't need a worktree — they can run in the 
main worktree on different branches. Worktrees pay off the moment 
two workers run at the same time.

---

## When you're stuck

Common stuck states and what to do:

**The user asked for X but I'm not sure if X is in scope**: 
Default to scope. If the user asks you to refactor the dashboard, 
refactor the dashboard — don't expand to "while we're at it, let's 
also reorganize Engine A." Keep changes focused.

**Two paths look equally valid**: Pick the one with lower estimated 
effort and state the tie. Don't ask the user to choose between 
two equivalent options — that's offloading decision work.

**A finding I want to fix is in `live_trader/` or Engine B**: 
Stop. Propose first. The autonomous improvement permissions don't 
extend there. State what you'd want to do and wait.

**The roadmap and the codebase disagree about what's done**: 
Trust the codebase. Update the roadmap to match reality, not 
the other way around. Note the discrepancy in `lessons_learned.md`.

**A subagent returned conflicting findings from the last time I 
ran it**: Treat the newer one as authoritative. Subagent memory 
accumulates over time and later findings have more context. Note 
the conflict in the subagent's memory if it persists.

**An audit file in `Archive/` contradicts current docs**: Trust 
current docs. `Archive/audits/` contains historical snapshots from 
earlier system states and most of their findings have been 
addressed. If something in there genuinely seems still relevant, 
note it in `health_check.md` rather than re-opening the old audit.

---

## Tone and communication

When reporting to the user:
- Lead with the outcome, not the process
- If something failed, say so plainly. Don't bury it
- Don't apologize unless you actually broke something
- Don't ask "would you like me to continue?" after every step. 
  If the next step is obvious and within autonomous scope, take it
- "Brutal realism" applies to your own work too. If a change you 
  made looks worse than you hoped, say that — don't oversell it
---

## Documentation lifecycle (the A layer)

The `docs/` tree is organized by **lifecycle**, not by topic. Knowing 
which folder a doc belongs in is mostly about answering "how does 
this doc age?"

### The 6 folders, by lifecycle

| Folder | What lives here | Lifecycle |
|---|---|---|
| `docs/Core/` | Stable design (engine charters, procedures, philosophy) | **Rarely changes.** When it does, the change is itself a substantive decision. |
| `docs/State/` | Current truth (`health_check.md`, `forward_plan.md`, `ROADMAP.md`, `GOAL.md`, `lessons_learned.md`, `deployment_boundary.md`) | **Mutates in place.** No date suffixes. `git log` is the history. When `forward_plan.md` is superseded, the prior version moves to `Archive/forward_plans/`. |
| `docs/Measurements/<YYYY-MM>/` | One-shot reports — backtests, ablations, audits, workstream close-outs | **Append-only, frozen.** A measurement is a point-in-time fact. Bucketed by month. Never edited after the run. Cite by full path. |
| `docs/Sessions/<YYYY-MM>/` | Per-session summaries + outside reviewer pastes | **Append-only, frozen.** Same lifecycle as Measurements. The `Other-dev-opinion/` subfolder is flat (not month-bucketed) per the existing convention. |
| `docs/Archive/` | Anything explicitly retired — old forward plans, deprecated design docs, superseded audits | **Frozen.** Don't read for current truth. Useful for "what did we believe at time X". |
| `docs/Sources/` | External reference material (paper reviews, third-party analysis) | **Append-only.** Cite freely; treat like a bibliography. |

### Naming conventions

- **State files:** `health_check.md`, `forward_plan.md`, `ROADMAP.md` 
  — no date suffix. The file *is* the current state.
- **Measurement files:** `<topic>_<YYYY_MM_DD>.md` or 
  `ws_<letter>_<short_name>.md` — date in filename if dated, 
  workstream-prefix if WS-tagged.
- **Session files:** `YYYY-MM-DD_session.md` (single session) or 
  `YYYY-MM-DD_session_<N>.md` (multi-session day) or 
  `YYYY-MM-DD_<short_descriptor>.md`.

### Supersession discipline

When you update a State doc, the **prior content is in `git log`**. 
You don't need to keep both versions in the tree.

When you supersede a `forward_plan.md`:
1. Move the existing `forward_plan.md` to `docs/Archive/forward_plans/forward_plan_<YYYY_MM_DD>.md` (preserve as historical context).
2. Write the new content into `docs/State/forward_plan.md`.

Same pattern applies if a Core design doc gets fundamentally redone — 
`git mv` the old version to `Archive/` first, then write the new one 
clean.

### When you write a measurement report

Always include in the doc:
- **Date** of the measurement (in filename + frontmatter)
- **What was measured** (one sentence)
- **What was decided/learned** (one paragraph)
- **Reproduce command** if applicable
- **Status block** if the result is reversible: 
  `Status: CURRENT | SUPERSEDED-BY-<file> | OBSOLETE`

If a later run supersedes this one, edit just the status block — 
don't delete the file. Future-you may need to compare measurements.

### Archive trigger (90-day rule)

Anything in `docs/Measurements/<old-month>/` that hasn't been cited 
or referenced in 90 days is a candidate for `docs/Archive/`. Don't 
auto-move on a cron — but as part of any major doc cleanup pass, 
move stale measurement folders to `Archive/measurements/<YYYY-MM>/`.

### What goes WHERE — a worked example

- I just ran a multi-year measurement → `docs/Measurements/2026-05/multi_year_foundation_measurement.md`
- That measurement found a bug → append finding to `docs/State/health_check.md`
- The bug is fixed and the finding is closed → edit the same `health_check.md` entry to mark `[HIGH → RESOLVED]`
- The fix was substantial enough to write up → `docs/Sessions/2026-05/2026-05-05_session.md`
- A new architectural pattern was learned → append to `docs/State/lessons_learned.md`
- The roadmap item is done → mark `[x]` in `docs/State/ROADMAP.md`

If you can't decide where something goes, ask: **"will this still be 
true in 90 days?"** If yes → State or Core. If no → Measurements 
(dated, frozen).

---

## Trade-log cleanup procedure

`data/trade_logs/<uuid>/` accumulates fast — every backtest writes a 
new dir (8 KB to 140+ MB depending on universe + horizon). Several 
hundred can pile up in 1-2 weeks of intensive development. They are 
gitignored and CLAUDE.md describes them as "regenerable output," 
**but this is only true in spirit** — old runs can't be reproduced 
under current code, only re-derived as fresh runs with current code.

### Why naïve mass-delete is unsafe

Some scripts and audit docs **hardcode specific run UUIDs** as their 
input or as cited reference data:

- `scripts/per_edge_per_year_attribution.py` hardcodes `ANCHOR_UUID` 
  and `OOS_UUID` as input data sources
- `scripts/analyze_oos_2025.py` hardcodes 3 UUIDs in its module 
  docstring + uses them as input
- `docs/Measurements/<YYYY-MM>/multi_year_foundation_measurement.json` 
  cites 15 specific run_ids as the canonical Foundation Gate baseline
- Many audit docs cite run_ids in their "reproduce" sections

Deleting any of these breaks the script or makes the audit 
non-reproducible. A blanket "delete everything older than N days" is 
NOT safe.

### The safe procedure

Run a reference scan first, then delete only the unreferenced.

```bash
# 1. Find every UUID hardcoded in code/docs
grep -rEn "[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}" \
  --include="*.py" --include="*.md" --include="*.json" --include="*.yml" \
  scripts/ engines/ orchestration/ core/ docs/ \
  | grep -vE "\.venv|worktrees|/Archive/" \
  | grep -oE "[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}" \
  | sort -u > /tmp/referenced_uuids.txt

# 2. List every UUID-named dir on disk
ls -1 data/trade_logs/ \
  | grep -E "^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$" \
  > /tmp/all_dirs.txt

# 3. Diff: dirs on disk that are NOT referenced anywhere
comm -23 <(sort /tmp/all_dirs.txt) <(sort /tmp/referenced_uuids.txt) \
  > /tmp/unreferenced_dirs.txt

# 4. (Always confirm with user before deleting — `rm` is on the deny list)
while IFS= read -r uuid; do
  rm -rf "data/trade_logs/$uuid"
done < /tmp/unreferenced_dirs.txt
```

### When to run cleanup

- Before a long-running measurement when `df -h` shows under 2 GB free
- As an end-of-session sweep if disk has crossed 90% capacity
- After a major refactor where many old runs are no longer relevant
- **Never as a routine cron** — too risky without a human eye on what's about to go

### Memory-of-cleanup discipline

Before cleanup, snapshot the deletion list to `/tmp/cleanup_<YYYY_MM_DD>.txt` 
so the post-cleanup state is auditable for at least the current session. 
Verify after running:
- All referenced UUIDs still on disk
- Number of dead refs (referenced UUIDs missing) — pre-existing dead 
  refs are fine; new ones mean the cleanup script malfunctioned

### Why "the system might lose context" is real

The system's "memory of what worked / what didn't" lives in:
1. `data/governor/` files (mutated end-of-run, NOT in trade_logs)
2. Audit docs in `docs/Measurements/` and `docs/State/`
3. Memory files in `.claude/projects/.../memory/`
4. Hardcoded run_ids in scripts that consume specific runs as input

Categories 1-3 are independent of trade_logs cleanup. Category 4 IS 
the load-bearing constraint — that's why the reference-scan procedure 
above exists.
