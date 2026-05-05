# UNIVERSAL_DOC_SYSTEM.md
### *A tool-agnostic guide for documenting projects so AI agents can operate on them across sessions*

> **Companion doc:** `DOCUMENTATION_SYSTEM.md` in the same project root
> describes the same system as concretely implemented for Claude Code.
> This document strips out the tool-specific details and presents the
> system as a set of principles + patterns. Use this when adapting the
> system to Cursor, Aider, Codex, plain ChatGPT, or any other tool.

---

## The problem this system solves

**AI agents lose their context every time a conversation ends.** Without
external structure, every session re-derives:
- What the project is and what it's trying to do
- What the rules are (commit cadence, what's safe to change)
- What's already been tried and why it failed
- What the user actually prefers, beyond defaults
- What's broken right now vs. what's working

The cost of re-deriving this on every session compounds. The solution
is a **set of files and conventions** that act as the project's memory
*outside* the AI's conversation context, designed so that any AI agent
can become operational on the project in minutes.

---

## The five core principles

These principles are tool-agnostic. Every implementation decision
should serve them.

### 1. There is one canonical entry point

The AI must know where to start. Whether that's `CLAUDE.md` (Claude
Code), `AGENTS.md` (some Codex setups), `.cursorrules` (Cursor),
`.aider.conf.yml` (Aider), or a `README.md` you point the AI at
manually — pick one, and put it at the project root. It must be:

- **Short** (under 300 lines). It points to the manual; it isn't the manual.
- **About non-negotiables** (rules, never-do list, commit discipline,
  what crosses a charter boundary).
- **Up-to-date with reading order** — the next file the AI should read,
  and the one after that.

If you have to choose only one document to write, it's this one.

### 2. The "what's next" decision is documented, not improvised

Every project has ambiguous moments — "what should we work on?",
"highest impact?", a vague directive — where an AI without a procedure
will improvise, and improvise differently each time. Write down the
priority order *as a decision tree*:

```
1. Continue in-progress work if any
2. Address active harm (broken code, drift, regressions)
3. Address structural debt (oversized functions, duplicate code)
4. Process unprocessed user input (idea inbox)
5. Resume the planned roadmap
```

The AI evaluates these in order and stops at the first one that
applies. This single document — call it `SESSION_PROCEDURES.md` or
`OPERATING_PROCEDURE.md` — eliminates 80% of the "what should I do?"
ambiguity.

### 3. Every document points to the next document

A documentation system is a graph. Every node should have explicit
out-edges saying "for X, see Y." A doc with no out-pointers is a
dead-end leaf — that's fine if it's intentional, suspicious otherwise.

The most common failure: documents that describe the same thing in
different words. Two sources of truth means one of them is wrong.
Pick the canonical doc; make the other point to it.

### 4. The system is self-maintaining

Docs go stale unless someone keeps them fresh. The trick is to make
the AI responsible for upkeep, with explicit rules:

- "If you discover a CLI command not in the execution manual, add it
  before ending the session."
- "If you notice a recurring pattern, add it to lessons_learned.md."
- "If you find a better practice, update the agent_instructions to
  reflect it."

Self-maintenance only works if the AI's working rules say so
explicitly. Without that line in the instructions, the AI will pattern-
match to "don't change docs unless asked" and the system will rot.

### 5. Archive, never delete

Deprecated code, old transcripts, failed experiments, superseded docs
— all go into an `Archive/` folder, never deleted. Two reasons:

- **Institutional memory:** the failed approach is the most valuable
  source of "why we don't do that" for future agents.
- **Recovery:** AI agents will occasionally delete things they
  shouldn't. An archive folder is recoverable; `rm` isn't.

---

## The pillars (tool-agnostic)

Eight pillars carry the load. Each is a folder + a small set of
conventions. Implementation paths vary by tool — the pillars don't.

### Pillar 1 — Entry point + reading order

The auto-loaded or first-read file. Establishes:
- What the project is (one paragraph)
- The reading order on session start (this file → procedures → north star → context)
- Non-negotiable rules
- Authorization boundaries (what the AI can do alone, what requires asking)

| Tool | File |
|------|------|
| Claude Code | `CLAUDE.md` (auto-loaded) |
| Cursor | `.cursor/rules` directory or `.cursorrules` |
| Aider | `.aider.conf.yml` + a referenced markdown convention file |
| Codex / OpenAI | `AGENTS.md` (some setups) |
| Plain ChatGPT / generic | `README_FOR_AI.md` referenced manually |

### Pillar 2 — Operational playbook

The "what's next" decision tree (see Principle 2). Same name across
tools: `SESSION_PROCEDURES.md` or `OPERATING_PROCEDURE.md` in
`docs/Core/`. Always prioritized; always re-readable mid-session.

### Pillar 3 — Reference docs

The reference manual the AI consults during work. Common files:

- **`PROJECT_CONTEXT.md`** — what the project is, architectural
  components, core philosophy, key terminology.
- **`ROADMAP.md`** — phased plan with checklists. Where forward-looking
  work lives.
- **`execution_manual.md`** — every CLI command, in one place. The AI
  is forbidden from guessing script paths.
- **`agent_instructions.md`** — coding standards + workflow rules
  specific to this project.
- **`engine_charters.md`** (or `module_charters.md`) — formal authority
  boundaries for each major component (see Pillar 6).
- **`roles.md`** — cognitive lenses the AI adopts based on the type of
  task (backend / UI / research / audit / etc.). Most useful when the
  project spans multiple domains.
- **`files.md`** — high-level codebase map.

Tier these by how often they're consulted. Tier 1 = read every session.
Tier 2 = consult during work. Tier 3 = update as you go.

Each `docs/<subdir>/` should have its own `README.md` serving as the
navigation index for that folder, with a tier table matching the above.

### Pillar 4 — Ideas pipeline

A controlled three-stage funnel from raw thoughts to roadmap items:

```
human.md (raw inbox)
   ↓ (AI structures)
ideas_backlog.md (categorized, IDed, [ ] checkable)
   ↓ (human approves with [x])
idea_evaluations.md (deep AI analysis with confidence scores)
   ↓ (human approves)
ROADMAP.md (formal item)
```

The pipeline prevents two failure modes:
- **Half-baked ideas getting coded immediately** (skip the backlog gate)
- **Good ideas getting forgotten** (raw thoughts are captured, not held
  in the user's head)

Strict rules: AI never deletes from human.md; never adds opinions in
backlog (backlog is structuring only); only `[x]`-approved items
graduate to evaluation; evaluations get removed from this file once
they reach the roadmap.

### Pillar 5 — Workflows + specialist agents

Two complementary forms of automation:

- **Workflows / skills / slash commands.** Deterministic multi-step
  procedures the AI can execute. Good for: tests, deploys, docs sync,
  repeated bootstrapping.
- **Subagents / specialist personas.** Self-contained AI roles with
  their own system prompt, tool access, and (often) persistent memory.
  Good for: code reviews, audits, focused research that would pollute
  the main context.

| Tool | Workflows | Subagents |
|------|-----------|-----------|
| Claude Code | `.claude/skills/<name>/SKILL.md` | `.claude/agents/<name>.md` (plus `.claude/agent-memory/`) |
| Cursor | `.cursor/rules` with task-specific files | "@" mentions of role files (no built-in agent system) |
| Aider | `--commands` shortcuts in conf | Multiple model configs, each its own role |
| Generic | A `workflows/` folder of `.md` files; manual delegation | Role-specific prompts in a `prompts/` folder |

**The most powerful pattern this system enables:** when one type of
issue keeps recurring (interface drift, charter violations, bare
exception swallowing), build a specialist agent whose entire mandate
is to scan for that pattern. The agent gets smarter over time via its
memory file. This turns repeating mistakes into a one-time setup cost.

### Pillar 6 — The audit + charter pair

The single most underrated pattern. Two parallel sets of docs:

- **Charters** (`docs/Core/engine_charters.md`): what each component
  *should* do, with formal input/output contracts and forbidden
  operations.
- **Functional audit** (`docs/Audit/high_level-<area>_function.md`):
  what each component *actually does today*, in plain English.

The charter is aspirational; the audit is descriptive. **Comparing the
two is how you find boundary violations before they become bugs.**

Plus the living tracker:

- **`docs/Audit/health_check.md`**: the source of truth for "what's
  broken right now." Maintained by the audit subagent; consulted by
  SESSION_PROCEDURES Path 2 ("active harm") before the roadmap. Format:
  HIGH/MEDIUM/LOW findings with first-flagged dates and resolution
  status. Resolved items stay visible for ~90 days, then archive.

### Pillar 7 — Progress / institutional memory

Two files in `docs/Progress_Summaries/`:

- **`lessons_learned.md`** — running log of what's been tried, what
  worked, what failed and why. Prevents the AI from re-recommending
  rejected approaches.
- **Session summaries** — `YYYY-MM-DD_session.md` written at the end of
  every working session. Sections: what was worked on, what was decided,
  what was learned, pick up next time, files touched, subagents
  invoked. **Decisions get forgotten faster than code; the "what was
  decided" section is the most valuable.**

If your tool supports session-start hooks, auto-load the most recent
2-3 session summaries when a new conversation begins. That's how the AI
gets continuity across sessions without the user having to re-brief.

### Pillar 8 — Cross-conversation user memory

Distinct from Pillar 7 (which captures the *project*). This captures
the *user and the relationship*: their role, their preferences, their
prior corrections, their validated approvals.

Memory categories:
- **`user_*`** — role, expertise, communication preferences.
- **`feedback_*`** — both corrections and non-obvious approvals. Saving
  only corrections leads to over-cautious drift; save validated
  judgment calls too.
- **`project_*`** — facts about ongoing work that aren't visible from
  code (in-flight initiatives, deadlines, key incidents).
- **`reference_*`** — pointers to external systems (Linear, Slack
  channels, dashboards).

What NOT to save:
- Anything derivable from `git log` / `git blame` / current code
- Convention or pattern info (that's project docs, not user memory)
- Ephemeral session state (in-progress work; that's session summaries)

| Tool | Memory location |
|------|-----------------|
| Claude Code | `~/.claude/projects/<project-id>/memory/` (auto) |
| Cursor | Long-term chat history (limited) |
| Aider | `.aider.input.history` + an explicit conventions file |
| Generic | A `notes/user_*.md` folder you maintain by hand |

Verify memories against current code before acting on them. Memory is
a snapshot in time; production state may have moved.

---

## The patterns we learned the hard way

### Pattern A — Bare-except is the enemy

The most common failure mode in living codebases:

```python
try:
    do_thing()
except Exception as e:
    print(f"thing skipped: {e}")
    return default_value
```

This swallows programmer errors (typos, missing methods, type errors)
on equal footing with legitimate runtime issues, and the system *appears*
to work while a critical path silently does nothing. Build a subagent
whose mandate is to flag bare-except patterns and propose narrowing
them. Have it run on a recurring schedule.

### Pattern B — The decision tree before the reference manual

A reference manual answers "what's the command for X?" A decision tree
answers "what should I do next?" — a different question that's more
valuable for AI agents because the second one is where they drift.
Always write the decision tree before the manual. Both belong in the
system; the tree gets more out of less.

### Pattern C — Synthesis docs reconcile reviews against reality

When an external reviewer drops a major plan, don't treat it as a new
source of truth. Write a *synthesis doc* (`docs/Core/forward_plan_<date>.md`)
that:
1. Captures what the reviewer claimed
2. Maps each claim to current reality (already true / partially true / aspirational)
3. Proposes the corrected priority order
4. Identifies which parts merge into ROADMAP.md vs. stay as background

Then merge the actionable parts into the roadmap. The synthesis doc
becomes a dated historical reference — not a parallel master plan.

### Pattern D — Subagent memory turns one-off insight into permanent skill

When a subagent surfaces a finding for the first time, also write a
short "pattern" memo into `<agent-name>/MEMORY.md`. Next run, the agent
reads its own memory and recognizes the pattern faster. Over time the
agent's effective expertise grows without re-prompting.

### Pattern E — Living trackers beat one-shot audits

A `health_check.md` that subagents append to and humans approve from is
worth more than any single static audit document. The static doc tells
you what was true on its write date; the living tracker tells you the
*current* state with a complete history of what was found, fixed, and
misdiagnosed.

### Pattern F — Charter + functional-audit pair surfaces drift

Boundary violations don't show up as bugs until they cause incidents.
The charter / current-function pair surfaces them as design drift
*before* they cause incidents. Run a "compare charter to function"
review monthly or at every major refactor — far cheaper than the
incident.

---

## Setup checklist (any tool)

Day 1, ranked by leverage:

1. **Entry-point file** with the project's non-negotiable rules + reading order.
2. **`SESSION_PROCEDURES.md`** with the "what's next" decision tree.
3. **`PROJECT_CONTEXT.md`** with what the project is and how it's structured.
4. **`agent_instructions.md`** with self-maintenance rules.
5. **`docs/Audit/health_check.md`** empty but with the format documented at the top.
6. **`docs/Progress_Summaries/_template.md`** so session summaries have a consistent shape.
7. **Ideas pipeline files** (`human.md`, `ideas_backlog.md`, `idea_evaluations.md`) bootstrapped empty.
8. **First session summary** capturing day-1 setup. Establishes the cadence.

Add over the first month:
- `engine_charters.md` once you have stable component boundaries
- `roles.md` once you've felt the AI think in the wrong mode 2-3 times
- `execution_manual.md` populated as you discover commands
- A first specialist subagent (likely `code-health` or an auditor)
- A first reusable workflow / slash command (likely `run-tests` or `commit`)

Add over the first quarter:
- A charter / functional-audit pair if components have stabilized
- Per-folder `index.md` files for major source-code directories
- An auto-generated code reference table inside the index files (sync script)
- Cross-conversation memory entries for user preferences as they surface

---

## What this system is NOT

- **It's not a substitute for the AI's tool config.** Settings, hooks,
  permissions — those live in the tool's native config (`.claude/settings.json`,
  `.cursor/settings.json`, etc.). The doc system is the *content*; the
  tool config is the *plumbing*.
- **It's not optional once installed.** A half-followed system is
  worse than none — the AI sees the structure and makes assumptions
  that turn out to be wrong because key pieces are stale. Either
  commit to maintaining it or strip it out.
- **It's not for solo "ChatGPT one-off" projects.** The overhead is
  worth it for projects with: multiple AI sessions, long-running goals,
  multiple stakeholders, or the need to onboard a fresh agent. Don't
  install this for a weekend script.
- **It's not the manual.** The manual lives in the codebase (docstrings,
  type signatures, tests). This system is the *meta* — the layer above
  the code that captures intent, decisions, and operating rules.

---

## The single most important paragraph

If you do nothing else from this document, install **the entry-point file
+ `SESSION_PROCEDURES.md` + `agent_instructions.md` self-maintenance
clause + `health_check.md` living tracker.** Those four together
deliver ~70% of the value with about a day of setup. The rest is
optimization — useful, but optional. Without those four, every other
piece of the system is built on sand.

The AI has to know (1) where to start, (2) what to do under
ambiguity, (3) that it's responsible for keeping the docs fresh, and
(4) what's broken right now. Everything else flows from those.
