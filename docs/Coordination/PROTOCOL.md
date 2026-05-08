# Three-Session Coordination Protocol

**Status:** active 2026-05-08 onward.
**Supersedes:** ad-hoc fresh-session-per-dispatch (still allowed for one-shots).

This is the canonical protocol for the three-session continuous-coordination model. The director and both worker agents should be able to operate from this doc alone.

---

## The three sessions

| Session | Where it runs | What it does |
|---|---|---|
| **Director** | IDE chat tab in main worktree (`/Users/jacksonmurphy/Dev/trading_machine-2`) | Coordinates, briefs agents, integrates results, takes on small/quick tasks itself, makes go/no-go calls. |
| **Agent A** | IDE chat tab in worktree `../trading_machine-agent-a/` | Generalist worker. Reads its inbox each turn, writes its outbox when done. |
| **Agent B** | IDE chat tab in worktree `../trading_machine-agent-b/` | Same as A; both fully interchangeable. |

The user is the message bus between sessions. The protocol is hybrid:

- **Substantive briefs** flow through ephemeral files in `data/coordination/` (gitignored under `data/`; symlinked from each agent worktree so all three sessions see the same files).
- **Tracked protocol docs** live in `docs/Coordination/` (this file, bootstraps, queue template).
- **Lightweight signals** ("check your inbox", "T-XYZ done — look at outbox") flow through the user.

---

## File layout

**Tracked protocol docs (`docs/Coordination/`):**

| Path | Owner | When written |
|---|---|---|
| `docs/Coordination/PROTOCOL.md` | Director (rare edits) | When the protocol itself changes |
| `docs/Coordination/agent_a_bootstrap.md` | Director (rare edits) | When A's bootstrap briefing changes |
| `docs/Coordination/agent_b_bootstrap.md` | Director (rare edits) | When B's bootstrap briefing changes |
| `docs/Coordination/task_queue.md.template` | Director (rare edits) | When the queue schema changes |

**Ephemeral runtime files (`data/coordination/`):** gitignored under `data/`; symlinked from each agent worktree (existing setup_agent_worktree.sh pattern, plus the symlink the director adds at first-time setup).

| Path | Owner | When written |
|---|---|---|
| `data/coordination/agent_a_inbox.md` | Director writes; A reads | When director assigns A a task |
| `data/coordination/agent_a_outbox.md` | A writes; Director reads | When A finishes a task |
| `data/coordination/agent_b_inbox.md` | Director writes; B reads | When director assigns B a task |
| `data/coordination/agent_b_outbox.md` | B writes; Director reads | When B finishes a task |
| `data/coordination/task_queue.md` | Director only | Live ledger of what's pending / in-flight / recently done |

The inbox/outbox/queue files are gitignored because they're per-machine ephemeral coordination state, not durable project history. Audit docs and code are still where durable findings live. Symlinking makes them visible across all three worktrees so the director and agents read/write the same files.

---

## Director protocol (every turn)

At the top of every user message, in this order:

1. **Read both outboxes.**
   - `data/coordination/agent_a_outbox.md`
   - `data/coordination/agent_b_outbox.md`
   - If either has a new completion since last read, integrate (review diff on the agent's branch, merge to main if clean, file follow-up tasks if needed).
2. **Update task queue.** Move completed tasks to "Recent completions"; promote next pending task if an agent just freed up.
3. **Check agent status (idle vs busy).** If either inbox is empty AND task queue has pending work, dispatch immediately — even before doing any director work.
4. **Now process the user's message.** If they brought new work:
   - **Quick (≤30 min)** → director does it. (Often: small fix, audit doc, planning, code review.)
   - **Larger (multi-hour, multi-file, long backtest)** → brief and dispatch to whichever agent is free.
5. **If both agents are busy** → take on smaller director-scoped work or wait. Don't manufacture parallel work.

The single load-bearing rule: **agents idling is the worst outcome**. When in doubt, brief it for an agent.

---

## Worker (A or B) protocol (every turn)

At the top of every user message:

1. **Read inbox.** `data/coordination/agent_<x>_inbox.md`.
2. **If inbox has a NEW task** (different Task-ID from last completion):
   - Run the workspace check: `pwd && git rev-parse --show-toplevel && git branch --show-current`.
   - Confirm pwd is the agent's worktree.
   - Run `git fetch origin && git rebase origin/main` to stay current.
   - If rebase has conflicts: STOP, write `BLOCKED — rebase conflict on <files>` to outbox, ask director.
   - Otherwise: execute the task per the brief.
3. **If inbox is empty or shows the task you just completed**: ask user "what's next?" (do not invent work).
4. **When task is done**: WRITE the result to `data/coordination/agent_<x>_outbox.md` (overwriting prior contents) BEFORE summarizing in chat. Then say "T-XYZ done, see outbox" so the user can ping the director.

Workers never push to main. Workers push to their own feature branch only. The director merges.

---

## Brief format (director writes to inbox)

```markdown
# Task T-YYYY-MM-DD-NNN — <one-line goal>

**Branch:** `feature/<descriptive-name>` (off origin/main)
**Time budget:** ~<estimate>

## What

<2-4 sentences on what to build / fix / measure>

## Why

<1-2 sentences on motivation; link to audit doc / health_check entry>

## Acceptance

- <verifiable criterion 1>
- <verifiable criterion 2>
- <test count expected>
- <audit doc path if a verdict is needed>

## Hard constraints

- <e.g., don't touch Engine B>
- <e.g., must preserve determinism harness PASS>

## When done

Overwrite `data/coordination/agent_<x>_outbox.md` with:
- Branch name + final commit hash
- Status: DONE / PARTIAL / BLOCKED
- 5-line headline (what changed, what passes, what's deferred, what surprised you, anything blocking)
- Test results (pass count + any failures)
- Pointer to audit doc if you wrote one

Then in chat: "T-YYYY-MM-DD-NNN done, see outbox".
```

## Outbox format (worker writes)

```markdown
# Task T-YYYY-MM-DD-NNN — <one-line goal>

**Status:** DONE | PARTIAL | BLOCKED
**Branch:** feature/<name>
**Final commit:** <hash>
**Wall time:** <duration>

## Headline

<5 lines max: what changed, what passes, what's deferred, what surprised you, anything blocking>

## Test results

<count_passed> passed, <count_failed> failed. New tests: <count_new>.
<list of failures if any, with one-line cause>

## Audit doc

<path to audit doc, or "none — code-only change">

## Notes for director

<anything that affects integration: file conflicts to expect, tests that need re-running on main, follow-up tasks worth queuing>
```

## Task queue format (director-only ledger)

See `task_queue.md.template`.

---

## Conflict avoidance

1. **Each agent works on its own feature branch.** Director merges to main after review.
2. **Agents `git fetch origin main && git rebase origin/main` at start of each new task** (in their bootstrap message + every brief).
3. **Director's substantive commits go to a director branch first** if agents are mid-task on overlapping files. Coordination-file-only commits (`docs/Coordination/*`) go to main directly.
4. **Task queue tracks "files-touched" hint** per task so director can spot overlap before dispatching.
5. **Conflict resolution is the director's job** — agents don't merge into main themselves.

---

## When to use multi-session vs in-session subagent

The decision tree from `MULTI_SESSION_ORCHESTRATION.md` still applies. This continuous-coordination model is for ongoing parallel work. For single-shot tasks that fit in one director turn, in-session subagents (`Agent` tool with `Explore`, `code-health`, etc.) are still the right choice — zero setup cost.

Use this protocol when:
- Multiple multi-hour tasks need to run in parallel
- Forward plan has enough sustained work that agents will be re-used across rounds
- The director's context budget would be polluted by long-running execution detail

Skip this protocol when:
- It's a one-off task that fits in one turn
- The user has explicitly asked director to do it
- The task is exploratory and ill-scoped (frame it in director first, then dispatch)

---

## Failure modes & known risks

- **User forgets to nudge.** If user doesn't ping A "check inbox" after director writes a brief, A doesn't know work is waiting. Mitigation: director ALWAYS says "Brief T-XYZ ready for A — please ping A" in chat after writing the inbox.
- **Agent forgets to rebase.** Agents start on stale branches and hit merge conflicts later. Mitigation: rebase is the first action specified in every brief.
- **Same-workspace file races.** All three sessions see the IDE workspace. If an agent forgets to `cd` into its worktree, edits land in main. Mitigation: bootstrap message hard-codes the cd; workspace check at top of every task confirms `pwd`.
- **Director loses chat memory on compaction.** Substantive integration summaries should land in git (commit messages, audit docs) so the durable record survives.
- **Outbox file races.** If A writes outbox while director is reading, half-write is possible. Mitigation: write entire file in one shot (Write tool, not append). Read-after-write is safe in practice.
