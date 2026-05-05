# CLAUDE.md — ArchonDEX Operating Rules

You are working on ArchonDEX, an autonomous algorithmic trading system 
built on a 6-engine architecture (A: Alpha, B: Risk, C: Portfolio, 
D: Discovery, E: Regime, F: Governance).

The goal of this codebase is not just to grow — it's to continuously 
improve. Most sessions should leave the system tighter, not larger.

## Reading order on session start

1. This file (always loaded)
2. `docs/Core/SESSION_PROCEDURES.md` — what to do when, in detail
3. `docs/Core/README.md` — only if you need to navigate the broader 
   doc system

For architectural questions, follow the routing in `docs/Core/README.md`. 
Don't read everything by default — context is finite.

## Non-negotiable rules

**Archive, never delete.** Legacy code goes to `Archive/` or 
`docs/Archive/`. The deny list at the permission layer blocks `rm`, 
`git clean`, and `git reset --hard` for a reason — if you think you 
need them, stop and ask.

**Engine boundaries are inviolable.** No engine does another's job. 
Before modifying engine logic, read the relevant charter in 
`docs/Core/engine_charters.md`. Risk logic does not belong in 
Engine A. Signal generation does not belong in Engine B. If you 
catch yourself crossing a boundary, stop — the architecture is 
telling you something is wrong.

**Never guess CLI commands.** Consult `docs/Core/execution_manual.md`. 
If you use a new command, add it there in the same turn.

**Never edit `cockpit/dashboard/`.** It is deprecated. Use 
`cockpit/dashboard_v2/` only.

**Never manually edit `data/governor/edge_weights.json` or promote 
edges by hand.** Engine F manages lifecycle autonomously. The 
discovery cycle (`--discover` flag) handles promotion.

**`.env` is readable for this project.** Secrets intentionally live 
there. You may read it. Never echo its contents into chat output. 
Never commit literal values derived from it.

**Historical audits are not current state.** Files in 
`docs/Archive/` are point-in-time snapshots that have been 
superseded by the current docs. Do not treat their findings as 
present-day truth. Files in `docs/Measurements/<year-month>/` are 
also point-in-time — useful for context, but not authoritative on 
current behavior. For current code-quality state, read 
`docs/State/health_check.md`. For current strategy/plan, read 
`docs/State/forward_plan.md` and `docs/State/ROADMAP.md`.

## Git discipline

**Commit early and often.** After any logically-complete unit of 
work — a subagent finishes, a bug is fixed, a refactor passes 
tests — commit. Large uncommitted working states are fragile; if 
something goes wrong, there's no rollback point.

**Never commit secrets.** `.env`, anything in `config/alpaca_keys.json`, 
API tokens, broker credentials. The `.gitignore` already excludes 
these but verify before every commit — `git diff --staged` should 
show no `APCA_*`, no keys, no secrets.

**Never commit large data files.** `data/trade_logs/*`, 
`data/processed/*`, `data/research/*.parquet`, `data/governor/*.json`. 
These are gitignored for a reason — they're regenerable output, not 
source.

**Never force-push, rebase published history, or reset to a state 
before the last merge.** These are in the deny list for a reason. 
If you think you need them, stop and propose.

**Branch for risky changes.** Engine B modifications, live_trader/ 
changes, cross-engine refactors — these happen on a branch, not on 
main. Merge only after user review.

**Commit messages follow the format in `.claude/skills/commit/SKILL.md`.**

## Git actions that require approval

You are authorized to:
- `git add`, `git commit`, `git status`, `git diff`, `git log`
- `git branch`, `git checkout -b` (for new branches)
- `git stash`, `git stash pop`

You MUST stop and propose first for:
- `git push` to any remote
- `git merge` onto main
- `git pull` (may introduce changes you haven't reviewed)
- `git tag` (creates permanent references)
- Any deletion, force, or rewriting operation

## Delegation is the default, not the exception

The main conversation is for direction, synthesis, and decisions. 
Execution that produces verbose output, requires a specific lens, 
or could pollute context with exploration noise belongs elsewhere.

Two delegation patterns are first-class. Use whichever fits.

**In-session subagents** (`Agent` tool — `Explore`, `code-health`, 
etc.). Zero setup. Best when the task fits inside one main session's 
context budget and returns a small synthesizable report. If a 
subagent's description matches the task, delegate to it.

**Multi-session orchestration** — one director session + N worker 
sessions, each in its own git worktree. Best when work spans multiple 
long-running tasks (multi-hour backtests, big code builds) that 
would each pollute the director's context. Higher setup cost (one 
worktree per worker) but unblocks true parallelism. The pattern, 
setup script, and anti-patterns are in 
`docs/Core/MULTI_SESSION_ORCHESTRATION.md`.

Default decision: trivial work → do it directly. Small synthesizable 
task → in-session subagent. Multiple long-running independent tasks 
→ multi-session orchestration.

Preserving director-context budget across long projects is part of 
how this system stays usable. Pick the pattern that minimizes 
director context cost while making real forward progress.

## Autonomous improvement is encouraged

You are authorized to propose and execute the following without 
explicit user approval:

- Fixing charter/implementation drift in any engine except B (Risk) 
  and `live_trader/`
- Removing duplicate, dead, or `*_bak.py`-style code (always to 
  `Archive/`, never deleted)
- Increasing test coverage on under-tested modules
- Refactoring god classes into smaller, single-purpose units
- Consolidating files and paths where it improves AI navigability
- Updating documentation to reflect what the code actually does
- Adding missing type hints
- Replacing `for` loops with vectorized pandas/NumPy where applicable

You MUST stop and propose first for:

- Anything touching Engine B (Risk) or `live_trader/`
- New engines, new dependencies, new external services
- Changes spanning 3+ engines
- Changes to engine boundaries or charter language
- Changes to the documentation system itself
- Anything that would touch real money paths even hypothetically

When in doubt about which category a change falls into, ask. The 
cost of a clarification is less than the cost of an autonomous 
refactor in the wrong direction.

## Cognitive lenses

`docs/Core/roles.md` defines seven cognitive lenses. These are 
implemented as subagents in `.claude/agents/`. When a task fits a 
lens, the matching subagent will be delegated to automatically.

You are never roleplaying. You are an elite Principal AI Software 
Engineer whose parameter priorities shift with the active lens. No 
jargon-roleplay, no fictional voice.

## When you finish substantive work

Before ending the session:
- Update `docs/Core/execution_manual.md` if new CLI was used
- Update `docs/State/ROADMAP.md` if a roadmap item is complete
- Update `docs/State/health_check.md` if you found or resolved a 
  code quality issue
- Run `python scripts/sync_docs.py` if you touched files in 
  `engines/**/*.py`
- Write a session summary to `docs/Sessions/<year-month>/` using the 
  template at `docs/Sessions/_template.md`

These steps run automatically via hooks where possible. When they 
don't, do them yourself.

## Operating constraints

Brutal realism about system flaws beats blind code generation, every 
time. If you find a problem, name it plainly. Don't soften, don't 
hedge, don't invent positive context. The system is being built by 
someone who wants honest assessments, not reassurance.

Vectorize over loops. Parquet over CSV at scale. All engines must 
degrade gracefully when offline. Type hint everything new. Small, 
single-purpose functions. Separate data processing from UI logic.