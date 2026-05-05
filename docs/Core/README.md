# docs/Core/ — Stable design docs (Core layer)

> **For system-wide navigation, see [`docs/README.md`](../README.md).** 
> This file documents the `docs/Core/` folder specifically.

`docs/Core/` holds **stable design + procedure docs** that change rarely. 
Mutating current truth (health_check, forward_plan, ROADMAP, GOAL) lives 
in `docs/State/`. Point-in-time reports live in `docs/Measurements/<YYYY-MM>/`. 
See the lifecycle rules in `SESSION_PROCEDURES.md` § "Documentation lifecycle".

---

## How to Use This Folder

Every file in `docs/Core/` has a specific role. They are not meant to be read all at once — they are organized into tiers based on *when* you need them.

### Tier 1: Orient (Read These First, Every New Session)

| File | Purpose | When to Read |
|------|---------|-------------|
| **`SESSION_PROCEDURES.md`** | Operational playbook — "what's next" decision tree (Paths 1–6), ideas-pipeline routing, session-end checklist, **and the documentation lifecycle rules (§ "Documentation lifecycle")**. | Every session, after `CLAUDE.md`. Re-readable mid-session without re-loading anything else. |
| **`MULTI_SESSION_ORCHESTRATION.md`** | Full pattern for running multiple parallel Claude Code sessions (one director + N workers). Worktree+data isolation setup, worker-prompt checklist, anti-patterns, synchronization patterns. | When the user puts you in director mode, or when you need to dispatch parallel work. Setup script: `scripts/setup_agent_worktree.sh`. |
| **`../State/GOAL.md`** | Your north star. Defines the AI's role, links to all reference docs. (Lives in State/, not Core/, because it can be reframed.) | First thing, every session. If you feel context drifting, re-read this. |
| **`PROJECT_CONTEXT.md`** | The architecture bible. 6-Engine system, edge doctrine, current state table, design philosophy. | Once at the start. Re-read when touching engine-level logic. |

### Deep Onboarding (Optional — For Full Engine Understanding)
If you need to work on engine-level logic, are reviewing the architecture, or want the complete mental model:

| File | Purpose |
|------|---------|
| **`docs/Core/simple_engine_roles.md`** | Plain-English "hedge fund room" metaphor — gives you the intuitive feel for each engine's personality |
| **`docs/Core/engine_charters.md`** | Formal authority boundaries, input/output contracts, invariants, and the interaction map |
| **`docs/Core/high_level_engine_function.md`** | What each engine actually does TODAY in the code (compare against charters to see the gap) |
| **`docs/State/health_check.md`** | Living tracker of current code-quality findings — maintained by the `engine-auditor` and `code-health` subagents |
| **`engines/*/index.md`** | Module-level documentation inside each engine directory — architecture notes + auto-generated code reference |

### Tier 2: Reference (Consult During Work)

| File | Purpose | When to Read |
|------|---------|-------------|
| **`execution_manual.md`** | Every CLI command in one place. Never guess a script path — look here. | Before running anything. |
| **`files.md`** | Quick-reference directory map of the full codebase. | When navigating unfamiliar folders. |
| **`roles.md`** | Cognitive lenses. Match the user's request to a trigger and adopt the corresponding mindset. | When starting a new type of task (risk work vs. UI work vs. architecture review). |
| **`../State/ROADMAP.md`** | Phased development plan with checkboxes. (Lives in State/.) | Before proposing new work (check what's already planned). |
| **`Human/human-system_explanation.md`** | Plain-English project descriptions at 3 audience levels. | When the user asks you to explain the project to someone. |

### Tier 3: Update (Write to These as You Work)

| File | Purpose | When to Update |
|------|---------|---------------|
| **`execution_manual.md`** | Add any new CLI commands you discover or create. | Immediately upon discovering/creating a command. |
| **`../State/ROADMAP.md`** | Mark items `[x]` as they're completed. (State/, not Core/.) | After completing a roadmap item. |
| **`../State/health_check.md`** | Append findings or mark `[HIGH → RESOLVED]`. | When you find or fix a code-quality issue. |
| **`../State/lessons_learned.md`** | Append non-obvious learnings. | When you learn something that surprised you. |
| **`../State/forward_plan.md`** | Update in place when strategy changes; archive prior version to `Archive/forward_plans/` first. | When a substantive plan reframe happens. |
| **`Ideas_Pipeline/human.md`** | Where the user dumps raw, unstructured ideas. | Never write here — only the human does. |
| **`Ideas_Pipeline/ideas_backlog.md`** | Structured idea ledger. AI extracts from `human.md` and files here. | When the user asks you to process new ideas. |
| **`Ideas_Pipeline/idea_evaluations.md`** | Deep-dive analysis of approved ideas. | When the user approves a backlog item with `[x]`. |

---

## The Document Flow

```
SESSION START
     │
     ▼
 ../State/GOAL.md ──── "What is this project? What are my rules?"
     │
     ▼
 PROJECT_CONTEXT.md ── "How is the system architectured? What's built vs planned?"
     │
     ├── Need to navigate docs? ──────► ../README.md (canonical nav index)
     ├── Need to run something? ──────► execution_manual.md
     ├── Need to find a file? ────────► files.md (or index.md in each engine dir)
     ├── Need to think differently? ──► roles.md (match trigger → adopt lens)
     ├── Need to plan work? ──────────► ../State/ROADMAP.md
     ├── Need to know what's broken? ─► ../State/health_check.md
     ├── Need current strategy? ──────► ../State/forward_plan.md
     └── User has a new idea? ────────► Ideas_Pipeline/human.md → ideas_backlog.md
                                                                        │
                                                                        ▼
                                                              idea_evaluations.md
                                                                        │
                                                                        ▼
                                                              ../State/ROADMAP.md
```

---

## Important Rules

1. **Never guess CLI commands.** Always check `execution_manual.md` first.
2. **Never execute new ideas directly.** Route them through the Ideas Pipeline.
3. **Never edit `cockpit/dashboard/`.** It is deprecated. Use `cockpit/dashboard_v2/` exclusively.
4. **If you add or discover a new command,** immediately log it in `execution_manual.md`.
5. **If you find a better practice,** update `agent_instructions.md` with the new standard.
6. **For deep module-level details,** read the `index.md` file inside the relevant engine or component directory (e.g., `engines/engine_a_alpha/index.md`).

---

## Beyond docs/Core/

| Location | Purpose |
|----------|---------|
| `docs/Audit/` | Living code-health tracking. Contains `health_check.md` (current findings, maintained by subagents) and `high_level-engine_function.md` (what each engine does today). Compare the latter against `docs/Core/engine_charters.md` to see refactoring drift. |
| `docs/Sessions/` | Session summaries (`YYYY-MM-DD_session.md`), `lessons_learned.md`, and the `_template.md` used for new summaries. |
| `docs/Sessions/Other-dev-opinion/` | Outside-reviewer takes captured at end-of-session after a push. The user typically asks a separate Claude instance to review what shipped; that response is saved here as `<MM-DD-YY>_<tag>.md`. Multiple user follow-ups within one file are separated by horizontal underscore dividers (`_____________________`). When acting on one of these files, also update `docs/Core/forward_plan_<YYYY-MM-DD>.md` and `ROADMAP.md` if the review proposes new phases or re-sequencing. See `SESSION_PROCEDURES.md` "Post-push outside-opinion review" for the full convention. |
| `docs/Archive/` | Gitignored historical content — old audits, retired specs, prior roadmaps. Snapshots, not current state. |
| `.claude/agents/` | Subagent definitions implementing the cognitive lenses in `roles.md`. |
| `.claude/skills/` | Reusable skills (e.g. `commit/SKILL.md` for commit-message format). |
| `.claude/settings.json` | Project hooks — SessionStart banner, Stop reminder, PostToolUse `sync_docs.py` trigger on `engines/**/*.py`. |
| `CLAUDE.md` (repo root) | Operating constitution — non-negotiable rules, autonomy boundaries, git discipline. |
| `DOCUMENTATION_SYSTEM.md` (repo root) | Universal guide describing the documentation system's design philosophy. |
