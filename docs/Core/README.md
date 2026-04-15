# docs/Core/ — AI Command Center
> **Start here.** This folder is the central nervous system for any AI agent operating on this project. Read this file first, then follow the tiered reading order below.

---

## How to Use This Folder

Every file in `docs/Core/` has a specific role. They are not meant to be read all at once — they are organized into tiers based on *when* you need them.

### Tier 1: Orient (Read These First, Every New Session)

| File | Purpose | When to Read |
|------|---------|-------------|
| **`GOAL.md`** | Your north star. Defines the AI's role, links to all reference docs. | First thing, every session. If you feel context drifting, re-read this. |
| **`PROJECT_CONTEXT.md`** | The architecture bible. 4-Engine system, edge doctrine, current state table, design philosophy. | Once at the start. Re-read when touching engine-level logic. |

### Deep Onboarding (Optional — For Full Engine Understanding)
If you need to work on engine-level logic, are reviewing the architecture, or want the complete mental model:

| File | Purpose |
|------|---------|
| **`docs/Audit/simple_engine_roles.md`** | Plain-English "hedge fund room" metaphor — gives you the intuitive feel for each engine's personality |
| **`docs/Audit/engine_charters.md`** | Formal authority boundaries, input/output contracts, invariants, and the interaction map (⚠️ draft — will migrate to Core when finalized) |
| **`docs/Audit/high_level-engine_function.md`** | What each engine actually does TODAY in the code (⚠️ draft — compare against charters to see the gap) |
| **`docs/Audit/codebase_findings.md`** | Folder-by-folder audit of the codebase — known bugs, god classes, weak points, and the remediation hitlist |
| **`engines/*/index.md`** | Module-level documentation inside each engine directory — architecture notes + auto-generated code reference |

### Tier 2: Reference (Consult During Work)

| File | Purpose | When to Read |
|------|---------|-------------|
| **`execution_manual.md`** | Every CLI command in one place. Never guess a script path — look here. | Before running anything. |
| **`files.md`** | Quick-reference directory map of the full codebase. | When navigating unfamiliar folders. |
| **`roles.md`** | Cognitive lenses. Match the user's request to a trigger and adopt the corresponding mindset. | When starting a new type of task (risk work vs. UI work vs. architecture review). |
| **`ROADMAP.md`** | Phased development plan with checkboxes. | Before proposing new work (check what's already planned). |
| **`Human/human-system_explanation.md`** | Plain-English project descriptions at 3 audience levels. | When the user asks you to explain the project to someone. |

### Tier 3: Update (Write to These as You Work)

| File | Purpose | When to Update |
|------|---------|---------------|
| **`execution_manual.md`** | Add any new CLI commands you discover or create. | Immediately upon discovering/creating a command. |
| **`ROADMAP.md`** | Mark items `[x]` as they're completed. | After completing a roadmap item. |
| **`Ideas_Pipeline/human.md`** | Where the user dumps raw, unstructured ideas. | Never write here — only the human does. |
| **`Ideas_Pipeline/ideas_backlog.md`** | Structured idea ledger. AI extracts from `human.md` and files here. | When the user asks you to process new ideas. |
| **`Ideas_Pipeline/idea_evaluations.md`** | Deep-dive analysis of approved ideas. | When the user approves a backlog item with `[x]`. |

---

## The Document Flow

```
SESSION START
     │
     ▼
 GOAL.md ──────────── "What is this project? What are my rules?"
     │
     ▼
 PROJECT_CONTEXT.md ── "How is the system architectured? What's built vs planned?"
     │
     ├── Need to run something? ──────► execution_manual.md
     ├── Need to find a file? ────────► files.md (or index.md in each engine dir)
     ├── Need to think differently? ──► roles.md (match trigger → adopt lens)
     ├── Need to plan work? ──────────► ROADMAP.md
     └── User has a new idea? ────────► Ideas_Pipeline/human.md → ideas_backlog.md
                                                                        │
                                                                        ▼
                                                              idea_evaluations.md
                                                                        │
                                                                        ▼
                                                                  ROADMAP.md
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
| `docs/Audit/` | Engine design work & codebase analysis — start with its `README.md` for reading order. Key files: `engine_charters.md` (target design), `high_level-engine_function.md` (current state), `codebase_findings.md` (known issues) |
| `docs/Audit/engine_charters.md` | Formal authority boundaries for all 5 engines (draft — will migrate to Core when finalized) |
| `docs/Progress_Summaries/` | Historical lessons learned and phase completion logs |
| `docs/Archive/` | Deprecated content preserved for historical reference |
| `.agent/workflows/` | Slash-command automation workflows (e.g., `/1_run_backtest`) |
| `DOCUMENTATION_SYSTEM.md` (repo root) | The universal guide to how this entire documentation system works |
