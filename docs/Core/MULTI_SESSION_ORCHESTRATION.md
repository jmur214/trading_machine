# Multi-Session Orchestration

This doc describes how to run multiple parallel Claude Code sessions on the same project — one **director** session coordinating any number of **worker** sessions, each making independent forward progress.

This is a peer pattern to the in-session subagent delegation described in `CLAUDE.md`. Both are first-class. The decision tree is at the bottom.

---

## When to use multi-session vs. in-session subagent

| Pattern | Use when |
|---|---|
| **In-session subagent** (`Agent` tool, e.g. `Explore`, `code-health`) | The task fits inside one main session's context budget. The result is a synthesizable report you fold back into the conversation. Setup cost: zero. |
| **Multi-session orchestration** | The work spans multiple long-running tasks that would each pollute the main session's context (long backtests, multi-hour code builds, deep analytical runs). Setup cost: one worktree per worker. |
| **Single session, no delegation** | Trivial work that doesn't justify even a subagent. |

Multi-session is the right pattern when you have N independent work units and you'd rather have them run truly in parallel than serialize through one context window. The director session stays small and strategic; each worker absorbs the verbose execution.

---

## Roles

### Director session
- One session per project at any given time.
- Holds the strategic context: the forward plan, the gate criteria, the prior-session memories, the cross-task synthesis.
- Writes prompts that worker sessions execute verbatim.
- Synthesizes worker reports, makes go/no-go decisions, dispatches the next round.
- Generally stays in the **main worktree** at the project root.
- Should NOT run long-running backtests or heavy builds itself — that pollutes its context. Delegate.

### Worker session
- One session per **agent worktree** at any given time.
- Executes a focused, well-scoped task end-to-end: read context, write code, run tests, run experiments, commit, push.
- Reports back to the director with a short summary (5-line max) plus a pointer to the audit doc / branch with the detailed work.
- Stays inside its assigned worktree directory; does NOT switch branches mid-task.
- Continuity is preserved across rounds: the same physical session keeps its conversation memory, so subsequent prompts can build on prior work without re-briefing.

There can be 1 or 100 worker sessions. The pattern is identical regardless of count.

---

## Why worktrees, not just branches

A single git worktree has one HEAD. If two workers operate in the same directory and one runs `git checkout`, the other sees its files change underneath them. We've hit this multiple times — it produces silent contamination (commits landing on the wrong branch) that's painful to unwind.

A `git worktree` is a second physical directory that's a fully independent checkout of the same repo. Same git history, same project, **separate working trees and separate HEADs**. Workers in different worktrees can do anything to git state — checkout, stash, branch, switch — without affecting each other.

Worktrees are not separate projects. After the worker's branch is merged to main, the worktree can be removed and leaves no trace. You can have as many or few as you need.

---

## The data isolation problem (and why symlinks alone aren't enough)

When you create a fresh worktree, gitignored directories don't come along — that includes `data/`, where price caches and runtime state live. The naive fix is to symlink `data/` into the worktree. **That's wrong** for some subdirectories.

`data/` mixes two kinds of state:

| Subdirectory | Sharing semantics | How to set up |
|---|---|---|
| `data/processed/` | Read-only price cache | Symlink — never mutated by backtests |
| `data/macro_data/`, `data/earnings/` | Read-only external caches | Symlink |
| `data/trade_logs/` | UUID-keyed write-only | Symlink — each run creates its own UUID dir, no collision |
| `data/research/` | Mostly unique filenames | Symlink |
| `data/governor/` | **Mutable shared state** | **COPY per agent** — `edge_weights.json`, `lifecycle_history.csv`, `regime_edge_performance.json`, `metalearner_*.pkl` are all rewritten at the end of every backtest. Two concurrent backtests writing the same files race and corrupt each other. |

The setup script handles this for you. **Do not symlink `data/governor/`** — that's the failure mode that bit us when we first tried multi-session.

Each agent's `data/governor/` starts as a copy of main's, mutates locally during the agent's runs, and is **not merged back automatically**. Lifecycle decisions made by one agent's runs do NOT propagate to other agents' worktrees. That's intentional for diagnostic experiments (we use `--reset-governor` anyway), but if a workflow ever needs cross-agent state propagation, it has to be done explicitly.

---

## Setup

One command per worker:

```bash
./scripts/setup_agent_worktree.sh <agent-name> <branch-name>
```

Example:

```bash
./scripts/setup_agent_worktree.sh alpha cap-recalibration
./scripts/setup_agent_worktree.sh beta  per-ticker-score-logging
./scripts/setup_agent_worktree.sh gamma metalearner-portfolio-enable
```

The script:
1. Fetches origin
2. Creates the worktree at `../trading_machine-<name>/` on a fresh branch from `origin/main`
3. Symlinks the read-only / append-only `data/` subdirectories
4. Copies `data/governor/` (per-agent isolation)
5. Prints the path the worker session should `cd` into

After running, start the worker's Claude Code session with that path as its working directory.

### Cleanup

When the worker's branch has been merged to main:

```bash
./scripts/cleanup_agent_worktree.sh <agent-name>
```

The branch is preserved by default — delete with `git branch -d <branch-name>` once you're sure no follow-up work is needed.

---

## Writing a worker prompt — the checklist

A good worker prompt is self-contained. The worker may be a fresh cold-start session with no prior context, or a continuity session that already has memory from earlier rounds. Either way, the prompt must work.

### Required elements

1. **Workspace check first.** The worker's first action should be:
   ```
   pwd && git rev-parse --show-toplevel && git branch --show-current
   ```
   This confirms they're in the right worktree and on the right branch. If the worker's pwd doesn't match the expected agent worktree, they should pause and bounce up.

2. **Read-list of context.** Point the worker at specific docs that contain the strategic context — typically the live `forward_plan_<date>.md`, the most recent audit docs, and any relevant memory files. Don't make the worker hunt.

3. **The one question.** State the worker's task in one sentence. If you can't, the task is too broad — split it.

4. **The method.** Concrete enough that the worker doesn't have to invent the approach: which files to modify, which scripts to run, which window/universe/config to use.

5. **The output.** Specify the audit doc path (typically `docs/Audit/<topic>_<YYYY_MM>.md`), what tables/sections it must contain, and the branch name.

6. **The boundaries.** What the worker MUST NOT touch. Other workers' branches; out-of-scope engines (Engine B/Risk requires user approval per `CLAUDE.md`); whatever else.

7. **The report-back format.** A 5-line summary stating: branch name, headline result, the surprising finding, anything unresolved, run UUIDs if applicable.

### Continuity vs. cold-start

If the worker is **continuing** a session that has prior task memory (e.g., they've done previous tasks on the project), the prompt can be tighter — reference what they already know. Open the prompt with "Continuation — ..." and assume the prior conversation is loaded.

If the worker is **cold start** (fresh session, no prior context), the prompt must brief them on the project from zero. Open with "Cold start. You are a worker session in a multi-session dispatch on the ArchonDEX project." and include enough context-doc pointers that they can orient.

In either case, the prompt is otherwise identical in shape.

---

## Anti-patterns to avoid

### Concurrent writes to mutable shared state
The setup script's per-agent `data/governor/` copy is the fix for this *across* agents. But within a single worker, **back-to-back backtests in the same worktree still serialize** because they share that worktree's `data/governor/`. If a worker plans multiple backtest runs, those must run sequentially within their own worktree — they can run in parallel with other workers' runs (different worktrees), but not within the same worktree concurrently.

### Workers running long blocking tasks the director also depends on
A worker can run a 2-hour build, but the director shouldn't be idle waiting. Dispatch the slow worker first, then the fast workers, then synthesize as fast workers report. The slow worker's report comes last but doesn't block the others.

### Worker switching branches mid-task
If a worker's HEAD is unexpectedly different from what they started with, they've been contaminated. They should:
1. `git status` to see what's there
2. `git stash --include-untracked` if there are uncommitted changes
3. Switch back to their assigned branch
4. Resolve carefully (cherry-pick, revert) and report up

This shouldn't happen with proper worktree isolation. If it does, the setup got skipped.

### Worker pushing to main directly
Workers push to their own feature branch only. The director merges to main. This preserves the director's gatekeeping role and avoids parallel pushes racing.

### Director running long-running work itself
The director's context is for strategic synthesis. A 60-minute backtest run inside the director's session burns its context budget on per-fill log spam. Dispatch instead — the director gets the audit doc summary, not the run output.

### Adding workers without a clear independent task for each
N workers should mean N independent tasks. Don't manufacture parallelism — if there's only one real task, run it in a single worker. If two workers' tasks are tightly coupled (worker B's input depends on worker A's output), serialize them as separate dispatches in separate rounds, not concurrent workers.

---

## Synchronization patterns

### Pure parallel
N workers, all independent. Director dispatches all of them, waits for all reports, synthesizes. Best when the tasks are orthogonal and you want answers fast.

### Fan-out / fan-in
N workers diverge from one strategic question. Director dispatches them in parallel, then synthesizes their findings into a single decision. (This is what we did for Phase 2.10c diagnostics — three workers explored different cuts of "what's broken with capital allocation" and the fan-in produced the unified diagnosis.)

### Sequential rounds
After round 1's workers report, the director may dispatch a round 2 conditional on round 1's results. Workers can be reused with continuity (if they're the natural continuation) or replaced with fresh cold-start sessions.

### One slow + N fast
Dispatch the slow worker first, then the fast workers shortly after. Fast workers report and director synthesizes their early signal while the slow worker continues. Slow worker reports last; director updates synthesis.

### Hub-and-spoke (single worker per round)
Sometimes one focused worker is better than N. The director dispatches a single worker for a single task, gets the report, then dispatches the next round. This is multi-session orchestration with N=1 — the worktree isolation still applies because the director shouldn't run the worker's heavy task in their own context.

---

## When NOT to use multi-session

- Trivial tasks (file edits, doc updates, single-line fixes). Just do them in the director.
- Tasks where the in-session `Agent` subagent (`Explore`, `code-health`, etc.) returns a small synthesizable result. Subagents are zero-setup; reach for them first.
- Exploratory work where the question itself isn't well-scoped yet. Multi-session pays off when you know the task. If you don't, frame the question first in the director.

---

## Decision tree

```
                              ┌─────────────────────────────────────┐
                              │ Is this work I can do in <10 min in │
                              │ the director session without        │
                              │ polluting context?                  │
                              └────────────┬────────────────────────┘
                                           │
                                  ┌────────┴────────┐
                                 YES                NO
                                  │                  │
                                  ▼                  ▼
                          Just do it       ┌────────────────────────┐
                          in director      │ Will the result fit in │
                                           │ a small synthesizable  │
                                           │ report?                │
                                           └──────┬─────────────────┘
                                                  │
                                          ┌───────┴───────┐
                                         YES              NO
                                          │                │
                                          ▼                ▼
                                  In-session         Multi-session
                                  subagent           orchestration
                                  (Agent tool)       (worktree per worker)
```

---

## Reference

- Setup script: `scripts/setup_agent_worktree.sh`
- Cleanup script: `scripts/cleanup_agent_worktree.sh`
- The high-level convention pointer: `docs/Core/SESSION_PROCEDURES.md` "Coordinating parallel agents"
- Why this matters historically: across the Phase 2.10b-2.10d work in 2026-04-29 / 2026-04-30, three separate cross-branch contamination incidents happened due to shared-worktree dispatches before the worktree+governor-isolation pattern was codified. Each was recoverable but produced extra reverts, audit-trail noise, and director-time spent on cleanup. The pattern in this doc is the lesson learned.
