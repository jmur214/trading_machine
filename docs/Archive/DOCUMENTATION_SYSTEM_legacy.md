# The Universal Project Documentation System
### *A complete, copy-paste guide to implement this documentation architecture in any project*

> **Note (2026-04-28 update):** This document describes the system as
> implemented for a Claude Code project. For a tool-agnostic version
> with the principles abstracted out (works for Cursor, Aider, Codex,
> ChatGPT, etc.), see `UNIVERSAL_DOC_SYSTEM.md` in the project root.

---

## Overview: The Philosophy Behind the System

This documentation system was built to solve one core problem: **AI agents lose context between conversations.** Without a living, structured set of documents, every new conversation requires re-explaining the entire project. With them, an AI can be handed this doc folder and be fully operational in minutes.

The system has **6 Pillars**, each with a distinct purpose. They are not just files — they are a *workflow*. They connect to each other, enforce rules on each other, and are designed to evolve with the project rather than go stale.

The golden rule: **Documents must tell an AI what to do, what not to do, and where to look — in that order.**

---

## Directory Structure to Create

```
your-project/
├── CLAUDE.md                             # ← Entry point Claude Code auto-loads
│                                          (or AGENTS.md / .cursorrules / .aider.conf
│                                           for other tools — see Pillar 1)
│
├── .claude/                              # (was .agent/ — name reflects the tool)
│   ├── agents/
│   │   └── [agent-name].md               # Subagent definitions (specialist personas)
│   ├── skills/
│   │   └── [skill-name]/SKILL.md         # Reusable slash-command workflows
│   ├── agent-memory/                     # Persistent subagent notes (gitignored or kept)
│   │   └── [agent-name]/MEMORY.md
│   ├── settings.json                     # Project-wide tool config
│   └── settings.local.json               # Personal overrides (gitignored)
│
├── docs/
│   ├── Core/
│   │   ├── README.md                     # Navigation index for this folder (Tier 1/2/3)
│   │   ├── GOAL.md                       # North star — points to other Core docs
│   │   ├── SESSION_PROCEDURES.md         # Operational playbook ("what's next" tree)
│   │   ├── PROJECT_CONTEXT.md            # What the project is and why
│   │   ├── ROADMAP.md                    # Forward-looking phased goals
│   │   ├── execution_manual.md           # Exact CLI commands for the AI
│   │   ├── agent_instructions.md         # Coding standards & operating rules
│   │   ├── engine_charters.md            # Module/component authority boundaries
│   │   ├── roles.md                      # Cognitive lenses by task type
│   │   ├── simple_*_roles.md             # Plain-English version of charters
│   │   ├── files.md                      # High-level file map
│   │   ├── human_explanation.md          # Non-technical project summary
│   │   ├── forward_plan_<date>.md        # External-review synthesis docs (as needed)
│   │   └── Ideas_Pipeline/
│   │       ├── human.md                  # Raw idea inbox (human writes here)
│   │       ├── ideas_backlog.md          # Structured idea ledger (AI writes here)
│   │       └── idea_evaluations.md       # Deep-dive AI analysis (AI writes here)
│   │
│   ├── Audit/                            # Technical audit and blueprint docs
│   │   ├── README.md                     # Navigation for audit findings
│   │   ├── health_check.md               # ★ Living code-quality tracker (subagent-maintained)
│   │   ├── high_level-*_function.md      # What components actually do today
│   │   └── [topic].md                    # Diagnostics, deep-dives, blueprints
│   │
│   ├── Progress_Summaries/
│   │   ├── lessons_learned.md            # What worked, what failed
│   │   ├── _template.md                  # Template for new summaries
│   │   └── YYYY-MM-DD_session*.md        # Timestamped session summaries
│   │
│   └── Archive/                          # Dead/old content, never deleted
│
└── [source-code-directories]/
    └── index.md                          # Hybrid doc for each major folder
```

---

## Pillar 1: The Core Docs Layer (`docs/Core/`)

This is the AI's **command center**. Every new conversation, the AI should be directed here first. These files answer the fundamental questions an AI needs before touching code.

### `CLAUDE.md` (or equivalent entry point at the project root) — The Constitution

**Purpose:** The set of non-negotiable rules and the directive about
*where to look next*. Claude Code auto-loads this file at the start of
every conversation; for other tools it might be `AGENTS.md`,
`.cursorrules`, or `.aider.conf.yml`.

**What it must contain:**
- Project name + one paragraph describing what the system does.
- Reading order on session start (which other Core docs to read, in what order).
- **Non-negotiable rules** — the things that must never be done. Examples
  from a real project: "Archive, never delete", "Engine boundaries are
  inviolable", "Never edit `cockpit/dashboard/` (deprecated)".
- Git discipline — commit cadence, never-commit list (secrets, large data
  files), authorized git operations, ones that require user approval.
- Autonomous-action boundaries: what the AI can do without asking, what
  it must propose first.
- Link to `docs/Core/SESSION_PROCEDURES.md` for the operational playbook.

**Critical rules:**
- This is a *short* file (~150-300 lines). Anything longer means it's
  trying to be the manual instead of pointing to the manual.
- Updates here are high-stakes — they change the AI's contract with the
  project on every future session.

---

### `docs/Core/README.md` — The Navigation Index

**Purpose:** A tiered index of every file in `docs/Core/` showing when
each one is needed. Distinct from `GOAL.md` (which is a one-paragraph
north star + pointers) — README is the *navigation map* with detailed
"when to read" guidance.

**Structure:**
```markdown
## Tier 1 — Orient (every session, in order)
| File | Purpose | When to Read |
| CLAUDE.md | Constitution | Auto-loaded by Claude Code |
| SESSION_PROCEDURES.md | Operational playbook | After CLAUDE.md, every session |
| GOAL.md | North star | First thing |
| PROJECT_CONTEXT.md | Architecture | Once at start, then when touching engine logic |

## Tier 2 — Reference (consult during work)
| execution_manual.md | CLI commands | Before running anything |
| files.md | Codebase map | When navigating unfamiliar folders |
| roles.md | Cognitive lenses | When starting a new type of task |
| ROADMAP.md | Phased plan | Before proposing new work |

## Tier 3 — Update (write to these as you work)
| ROADMAP.md | Mark items [x] | After completing one |
| execution_manual.md | Add new commands | Immediately on discovery |
| Ideas_Pipeline/* | Process ideas | When user asks |
```

**Critical rule:** Each `docs/<subdir>/` has its own README serving the
same role for that folder. Audit/, Progress_Summaries/, and any
sub-folders should each have a navigation README.

---

### `GOAL.md` — The North Star

**Purpose:** A one-page orientation document that tells the AI what project it's in and where to go for more context.

**What it must contain:**
- One paragraph describing the project's objective in plain English.
- A bulleted list of every other Core doc and what it's for.
- A "Current Mode" or "AI Directive" line telling the AI its overall mandate.

**Critical rules:**
- This should be the **first file an AI reads** at the start of any session.
- It must NEVER contain technical details — only pointers.
- It must be updated whenever any of the files it references is renamed or deleted.

**Template:**
```markdown
# [Project Name]: Master Orchestrator

## AI Alignment & Objective
[1-2 sentence description of what this project is and what the AI's role is.]

When beginning a new session or if context is drifting, use these files:
- **Architecture:** `docs/Core/PROJECT_CONTEXT.md`
- **Codebase Map:** `docs/Core/files.md`
- **Commands:** `docs/Core/execution_manual.md`
- **Progress:** `docs/Core/ROADMAP.md` and `docs/Progress_Summaries/`
- **Operating Rules:** `docs/Core/agent_instructions.md`
- **Cognitive Modes:** `docs/Core/roles.md`

## Current Mode
[One line telling the AI its current-phase mandate, e.g. "We are in Phase 2 (infrastructure refactor). Operate with caution."]
```

---

### `SESSION_PROCEDURES.md` — The Operational Playbook

**Purpose:** Answers *"what do I do right now"* when the user asks
"what's next", "highest impact", or gives an unclear directive. It is
the operational complement to `CLAUDE.md` (the constitution) — written
to be re-readable mid-session without reloading anything else.

**What it must contain:**
- **A prioritized decision tree** for "what's next" — typically 5-7
  numbered paths, where the AI stops at the first one that applies.
  Real example from this project:
  - Path 1: continuing in-progress work
  - Path 2: critical findings (`docs/Audit/health_check.md` HIGH items)
  - Path 3: charter-implementation drift
  - Path 4: code-quality degradation
  - Path 5: unprocessed ideas in the pipeline
  - Path 6: roadmap items
- **Routing for the ideas pipeline** — how to process the inbox.
- **A session-end checklist** — what to update before stopping
  (execution_manual, ROADMAP, lessons_learned, session summary).

**Critical rules:**
- Decision-tree-first format. The AI is making a decision under
  ambiguity, not consulting a reference manual. Ordering matters.
- The "stop at first matching path" rule is the prioritization signal —
  Path 1 is more urgent than Path 2 by definition.
- This file is the canonical answer to "the user asked what's next."

---

### `engine_charters.md` (or `module_charters.md`) — Authority Boundaries

**Purpose:** Formal contracts for each major component/module/engine —
what it's authorized to do, what it explicitly is NOT authorized to do,
its inputs, its outputs, its invariants. Prevents an AI from "fixing" a
problem in the wrong layer.

**What it must contain (per component):**
- **Charter (one paragraph):** what this component is responsible for.
- **Authorized inputs:** what it's allowed to read.
- **Forbidden inputs:** what it must NOT read (e.g., a Risk engine
  reading raw signal scores would violate its layering).
- **Outputs:** what other components consume from it.
- **Invariants:** properties that must always hold (e.g., "every
  position has a stop-loss").
- **Interaction map:** which other components it talks to.

**Why this matters:** Real systems drift. Without a written charter,
"fix the bug in Engine A by adding a quick risk check" looks reasonable
but actually lets risk logic leak into the alpha layer. The charter
makes this visible.

**Pair with:** `docs/Audit/high_level-*_function.md` — what the code
ACTUALLY does today, in plain English. Comparing charter to current
implementation surfaces drift.

---

### `PROJECT_CONTEXT.md` — The Architecture Brief

**Purpose:** Answers *"What does this project actually do and how is it structured?"* in enough detail that someone who has never seen the code can understand the system.

**What it must contain:**
- What the project is in plain English.
- The core architectural components/modules and their roles.
- The project's philosophy or design principles.
- Key domain-specific terminology with definitions.

**Critical rules:**
- Must be written for a **dual audience**: non-technical stakeholders AND senior engineers.
- Must describe the intended architecture, not a catalogue of files.
- Should include a Mermaid diagram once the architecture is stable enough to visualize.

---

### `ROADMAP.md` — The Phased Master Plan

**Purpose:** The AI's source of truth for forward-looking prioritization. Before starting any major task, the AI checks here. After completing one, it updates here.

**What it must contain:**
- Phases, numbered sequentially, each with an overarching goal.
- Sub-tasks within each phase as a `[ ]` checklist.
- Phase completion status (`[x]` done, `[ ]` pending, `[/]` in-progress).
- A "blocked" annotation for tasks that cannot proceed without a prerequisite.

**Critical rules:**
- Every idea that graduates from the Ideas Pipeline **must be injected here** as a new phase item or sub-task.
- Phases must have **actionable sub-steps**, not just vague goals.
- The AI must consult this before starting work and update it when finishing a phase.

**Template for a phase entry:**
```markdown
## Phase N: [Overarching Goal Name]
- [ ] **Sub-task 1:** [Specific, actionable description]
  - [ ] Step A
  - [ ] Step B
- [ ] **Sub-task 2:** [Description] *(⚠️ BLOCKED: Dependent on Sub-task 1)*
```

---

### `execution_manual.md` — The CLI Command Bible

**Purpose:** Every runnable command in the project, in one place. The AI should **never guess** how to run something — it checks here first.

**What it must contain:**
- Grouped sections by task type (e.g., "Environment Setup," "Testing," "Running the App").
- Exact `bash` commands with flags and explanations.
- A note at the top telling the AI it must add any NEW command it discovers to this file immediately.

**Critical rules:**
- **Self-updating:** The AI is instructed that if it uses or discovers a command not listed here, it must add it before ending the session.
- The header must include: `"Never guess arbitrary script paths. Consult this manual."`
- Commands that are deprecated or replaced must be removed, not commented out.

---

### `agent_instructions.md` — The Operating Protocol

**Purpose:** Tells the AI how to *behave on this project*, above and beyond its default behavior.

**What it must contain:**
- Documentation hygiene rules (when to update ROADMAP, lessons_learned, etc.).
- Coding standards (naming conventions, style preferences, tech stack choices).
- Workflow rules (when to use the Ideas Pipeline, when to commit, etc.).
- A rule that this document must update itself when a better practice is discovered.

**Critical rules:**
- Rules must be **explicit and enforceable**, not vague suggestions.
- Must include the Ideas Pipeline as a mandatory workflow for feature requests.
- Should contain a "Dynamic Best Practices" rule: *"If you implement a better way, update this file."*

---

### `roles.md` — The Cognitive Lens System

**Purpose:** Tells the AI to dynamically switch its mental mode depending on the type of task. Prevents the AI from thinking like a backend engineer when the user needs UI/UX work.

**What it must contain:**
- 4-8 distinct roles/lenses, each with:
  - A **Trigger** (what user request activates this mode)
  - A **Focus** (what this lens optimizes for)
  - A **Mindset** (the core question this lens asks)
  - **Task Examples** (concrete examples of work for this mode)
  - **Rules** (hard constraints unique to this lens)

**Example roles for a generic project:**
- `Backend Engineer` — triggered by "fix the API," focuses on performance and reliability
- `Designer` — triggered by "update the UI," focuses on aesthetics and usability
- `Researcher` — triggered by "explore options for X," focuses on trade-offs and evidence
- `DevOps` — triggered by "deploy this," focuses on security and reproducibility
- `Auditor` — triggered by "review the codebase," focuses on technical debt and correctness

---

### `files.md` — The Quick Codebase Map

**Purpose:** A lightweight, human-readable map of the project's directories and what each does. The AI uses this to navigate without scanning the whole filesystem.

**What it must contain:**
- A table or list of every major directory/module with a one-line description.
- Notes on what is legacy/deprecated vs. active.

---

### `human_explanation.md` — The Non-Technical Summary

**Purpose:** An explanation of the whole project that could be given to someone with zero technical knowledge. Useful for aligning the AI's language with how you naturally talk about the project.

---

## Pillar 2: The Ideas Pipeline (`docs/Core/Ideas_Pipeline/`)

This is the **controlled highway that raw ideas must travel before touching code.** It is a 3-stage process with strict gates between each stage. The core problem it solves: preventing half-baked ideas from being coded immediately, while ensuring no good idea is forgotten.

### The Three Stages

```
[You write raw thoughts] → human.md
         ↓  (AI extracts + structures)
[AI organizes into items] → ideas_backlog.md
         ↓  (You approve with [x])
[AI evaluates deeply] → idea_evaluations.md
         ↓  (You approve the evaluation)
[AI injects into ROADMAP.md]
```

---

### Stage 1: `human.md` — The Raw Inbox

**What it is:** A scratchpad where you write unfiltered thoughts. Stream of consciousness, voice memo transcriptions, random ideas, URLs to articles — anything goes.

**Structure:**
```markdown
# 📥 NEW INBOX (Unprocessed)
[You write your raw thoughts here, in any format]

---
# 🗄️ PROCESSED ARCHIVE
[The AI moves processed content here after extraction]
```

**AI Workflow:**
1. AI reads **only the `NEW INBOX` section**.
2. Extracts the core concepts.
3. Structures them in `ideas_backlog.md`.
4. Cuts the processed text from `NEW INBOX` into `PROCESSED ARCHIVE`.
5. Stops and asks you to review `ideas_backlog.md`.

**Critical rule:** The AI must NEVER edit the `PROCESSED ARCHIVE` section — it is a permanent historical log.

---

### Stage 2: `ideas_backlog.md` — The Structured Ledger

**What it is:** The organized, tracked repository of all pending ideas. The AI translates messy human thoughts into clean, categorized, trackable items.

**Structure:**
```markdown
# Human Ideas Ledger (Backlog)

## [Category Name]
- [ ] **#CAT-1:** [Concise description of the idea]
- [ ] **#CAT-2:** [Concise description of the idea]

---
# 💬 User Scratchpad / Revisions
*Leave comments below referencing the ID (e.g., "For #CAT-1, focus on X first").
The AI will read this, update items above, and clear your comment.
When you approve an idea, change [ ] to [x].*
```

**AI Workflow Rules:**
- The AI provides **NO opinions or analysis** in this file. It only structures.
- Each item gets a unique, category-prefixed ID (e.g., `#ML-1`, `#ARCH-2`).
- After writing it, the AI **stops and waits for your review**.
- You leave revision notes in the `User Scratchpad` section.
- The AI reads the scratchpad, makes edits, clears the scratchpad, and asks again.
- This loop continues until you mark items with `[x]`.
- **Only `[x]`-approved items can proceed to Stage 3.**

**Critical rule:** Items are **never deleted** from this file — they are either promoted to `idea_evaluations.md` (and removed from here) or remain pending with `[ ]`.

---

### Stage 3: `idea_evaluations.md` — The AI Analysis Layer

**What it is:** The AI's "whiteboard." Each approved idea gets a full structured analysis: what it is, how feasible it is, what the risks are, and a confidence score.

**Structure:**
```markdown
# AI Idea Evaluations & Research Memos

## 🟢 [High Priority] [Idea Name] (#ID)
**Cognitive Lens:** [Which role/lens the AI adopted]
- **Core Concept:** [1-2 sentence summary of the idea]
- **Feasibility:** High / Medium / Low — [reason]
- **Impact:** High / Medium / Low — [reason]
- **Execution Risks:** [Specific risks and mitigations]
```

**Scoring Legend:**
- `🟢` High Conviction — AI recommends proceeding
- `🟡` Evaluating — More information needed
- `🔴` High Risk — Significant risk, proceed with caution
- `⚠️` Needs Clarification — AI has a blocking question for the human

**AI Workflow Rules:**
- Only items explicitly marked `[x]` in the backlog get promoted here.
- When promoted, the item is **removed from ideas_backlog.md**.
- The AI adopts the appropriate `roles.md` cognitive lens for each evaluation.
- After evaluation, AI stops and waits for your approval of the evaluation.
- When you approve an evaluation, the AI **removes it from this file** and injects it as a formal item into `ROADMAP.md`.

---

## Pillar 3: The Hybrid `index.md` System

Each major source-code directory gets its own `index.md` file. These serve as the AI's orientation file for that module — so it never has to read every single file to understand what a folder does.

### The "Hybrid" Concept

The file has two distinct halves:

**Top Half (Human-written, qualitative):** A narrative description of what the directory does architecturally, its design philosophy, key decisions, and things to be aware of.

**Bottom Half (Auto-generated, quantitative):** A code reference table of every class and function in every file in that directory, with their signatures and one-line docstrings. This is generated by a script (`sync_docs.py` or equivalent), never written by hand.

```markdown
# [Directory Name] — Module Overview

## What This Module Does
[2–4 paragraph qualitative narrative. Written by the AI, reviewed by the human.]

## Key Design Decisions
[Notable architectural choices that aren't obvious from the code]

## Things to Be Careful About
[Gotchas, known debt, performance concerns]

---
<!-- AUTO-GENERATED BELOW — DO NOT EDIT MANUALLY -->
## Code Reference

### `filename.py`
| Symbol | Type | Signature | Description |
|--------|------|-----------|-------------|
| `ClassName` | class | `ClassName(arg1, arg2)` | [docstring] |
| `function_name` | function | `function_name(x, y) → bool` | [docstring] |
```

### The Maintenance Workflow

A script (`sync_docs.py` or equivalent) parses the AST (Abstract Syntax Tree) of every Python file in the directory and regenerates the bottom half automatically. This means:
- The bottom half is always accurate — it reflects exactly what exists in the code.
- The top half needs periodic manual review to ensure it still accurately describes the module after major changes.
- The maintenance workflow (a slash command) runs the script and then asks the AI to compare the top half against the newly generated bottom half and flag discrepancies.

---

## Pillar 4: The Workflow + Agent System (`.claude/skills/`, `.claude/agents/`)

Two kinds of reusable automation, each suited to a different task shape:

- **Skills (slash commands)** — deterministic, multi-step procedures. The
  AI follows the steps in order. Good for: running tests, syncing docs,
  bootstrapping data, deployment.
- **Subagents** — specialist personas with their own system prompt and
  tool access. The main conversation delegates tasks that match the
  subagent's expertise. Good for: code reviews, audits, focused
  research, anything that would pollute the main context with verbose
  exploration.

### Skills File Format (`.claude/skills/<skill-name>/SKILL.md`)

```markdown
---
description: [Short title for what this workflow does]
---
# [Workflow Name]
[Brief explanation of what this workflow accomplishes]

// turbo-all   ← Optional: marks all steps as auto-runnable

1. [Step 1 instruction — may include code blocks with exact commands]
   ```bash
   python scripts/example.py
   ```
2. [Step 2 instruction — what the AI does after the command]
3. [Step 3 instruction — what to check or report]
```

### The `// turbo` Annotation System

- **`// turbo`** above a single step: The AI auto-runs that step without asking for approval.
- **`// turbo-all`** anywhere in the file: The AI auto-runs every command step in the file.
- Without either annotation, the AI asks for approval before each terminal command.

### Recommended Core Skills

| Slash Command | Purpose |
|---|---|
| `/commit` | Stage + commit using the project's commit-message convention |
| `/run-tests` | Run the full test suite and report failures |
| `/health-check` | Run diagnostics and report system status |
| `/docs-maintenance` | Sync the auto-generated code reference tables |
| `/deploy` | Deployment or build steps |

### Subagent File Format (`.claude/agents/<agent-name>.md`)

Each subagent is a markdown file with frontmatter declaring its name,
description, and tool access — followed by the system prompt that
defines its persona, focus, and constraints.

```markdown
---
name: [agent-name]
description: When to delegate to this agent (matters — Claude routes
             based on this). Be specific about triggers.
tools: Read, Glob, Grep, Bash, Edit, Write   # optional restriction
---

# [Agent Name]
[Persona / role / mandate]

## Focus
[What this agent specializes in]

## Constraints
[What this agent must NOT do — e.g. read-only, no commits, scope limits]

## Output format
[What the agent should return — usually a concise report]
```

### Recommended Subagent Roster

| Subagent | Mandate |
|---|---|
| `architect` | System-level audit, charter compliance review (read-only) |
| `code-health` | Scan for tech debt, dead code, oversized functions (read-only) |
| `engine-auditor` (or `module-auditor`) | Compare a specific module against its charter |
| `[domain-specialist]` | Project-specific (e.g. `risk-ops-manager`, `edge-analyst`, `ux-engineer`) — restricted to one functional area |
| `agent-architect` | Maintains the agent roster itself |

**Critical pattern:** When you find that one type of mistake recurs
(bare-except swallows bugs, charter drift, naming inconsistency), build
a subagent whose mandate is to scan for it. The agent becomes the
recurring auditor. See "Subagent Memory" below.

### Subagent Memory (`.claude/agent-memory/<agent-name>/`)

Subagents keep persistent notes across invocations. Each agent has its
own folder with:
- `MEMORY.md` — index of memory files
- `pattern_<name>.md` — recurring patterns the agent has learned to
  recognize, with examples and what to do about them

This lets the auditor agent get smarter over time. The first run might
spot a bare-except pattern; on the second run, it's looking for that
pattern by reflex.

### User Rules / Settings (`.claude/settings.json`, `.claude/settings.local.json`)

Project-wide vs personal config. Examples:
- `permissions.allow` / `permissions.deny` — bash patterns the AI can or
  cannot run without asking
- Hooks — automated commands that run on PreToolUse, PostToolUse, etc.
  (e.g., a PreToolUse hook that blocks any bash containing `rm -rf`)
- Model selection, default agent, etc.

**Critical rule:** `settings.json` is committed (team-wide); `settings.local.json` is gitignored (personal overrides).

---

## Pillar 5: The Audit Layer (`docs/Audit/`)

The Audit layer is the project's **growing technical memory and blueprint storage**. It is distinct from the Core docs in that it is not prescriptive — it documents what *was discovered*, not what *should be done*.

### What belongs here:
- **`health_check.md`** ★ — the living tracker of current code-quality
  findings (see below). The most-read file in this folder.
- **Functional audit documents:** What each major component *actually does today* at a behavioral level. Pair these with the charters in `docs/Core/engine_charters.md` — comparing the two surfaces drift.
- **Outside opinions / research:** Analysis from external sources that informed design decisions.
- **Mini-projects / investigations:** Deep dives on specific sub-problems and one-shot diagnostics (e.g., `realistic_slippage_diagnostic.md`).

### Key principle: "Source of Truth" documents

The most important audit documents act as the single source of truth for high-level system behavior. They describe *what* a component does (in business terms), not *how* the code works. This separation is critical because:
- It allows architectural discussions without reading the code.
- It gives the AI a stable reference when refactoring.
- It lets you verify intent vs. implementation.

### `docs/Audit/health_check.md` — The Living Code-Quality Tracker

**Purpose:** The single source of truth for "what's broken right now."
Maintained by the `engine-auditor` and `code-health` subagents — they
append findings as they discover them. Resolved items move to a
"Resolved" section with a date.

**Format (per finding):**
```markdown
### [HIGH | MEDIUM | LOW] One-line summary
- Engine/Module: [scope]
- First flagged: YYYY-MM-DD
- Status: not started | in progress | resolved YYYY-MM-DD | misdiagnosed
- Description: [what's wrong, with file:line refs]
- Charter reference: [quote from engine_charters.md]
- Recommended next step: [specific action]
```

**Why this file matters more than ROADMAP for "what's next":** The
roadmap captures forward-looking *features* you want to add. The
health_check captures *active harm* — code that is wrong today.
SESSION_PROCEDURES.md Path 2 explicitly checks here BEFORE the roadmap.

**Critical rules:**
- Resolved findings stay visible (move to "Resolved" with date) for ~90
  days, then archive. Loss-of-memory is the failure mode.
- Subagents append; humans approve. The auditor agent runs, writes
  findings, and the human (or main AI) decides which to action.
- Misdiagnoses get marked, not deleted — so future readers see the full
  history of what was thought to be wrong.

### Synthesis docs (e.g., `docs/Core/forward_plan_<date>.md`)

When an external review or major reframing arrives, write a **synthesis
doc** that combines it with current state:

- What was claimed in the external doc
- Where it's already accurate vs. obsolete vs. still aspirational
- The corrected priority order based on what's actually been built
- Mapping to phases/items in `ROADMAP.md` (so the roadmap stays the
  primary plan document)

These docs are dated and treated as snapshots — they don't supersede
the roadmap, they reconcile against it. After they've been merged into
the roadmap, they become historical references.

---

## Pillar 6: The Progress Layer (`docs/Progress_Summaries/`)

### `lessons_learned.md`

A running log of what has been tried, what worked, and — critically — what **failed and why**. This is the project's institutional memory, preventing the AI from recommending solutions that have already been tried and rejected.

**Format:**
```markdown
## [Date] — [Brief Topic]
**Outcome:** Success / Failure / Partial
**What was tried:** [Description]
**Why it did/didn't work:** [Explanation]
**Recommendation going forward:** [What to do or avoid]
```

### Timestamped Session Summaries

At the end of every working session, the AI writes a brief markdown
summary saved as `docs/Progress_Summaries/YYYY-MM-DD_session.md` (with
`_session_2`, `_session_3` suffixes if multiple sessions occur on the
same day). Use the `_template.md` in the same folder.

**Sections (preserve all of them, even if short):**
- **What was worked on:** 1-3 bullets, specific enough that a reader in
  a month understands what was built.
- **What was decided:** non-trivial choices made and the rationale.
  *Most valuable section* — decisions get forgotten faster than code.
- **What was learned:** new patterns, gotchas, surprises.
- **Pick up next time:** specific next actions, concrete enough to
  resume without re-deriving context.
- **Files touched:** `git diff --name-only` is fine.
- **Subagents invoked:** which ones, what they returned.

**Critical rule:** The SessionStart hook (or equivalent) should auto-load
the most recent N session summaries when a new conversation begins —
that's how the AI gets continuity from one session to the next without
the user having to re-brief.

---

## Pillar 7: The Auto-Memory Layer (cross-conversation)

The Pillars above keep the *project* documented. Auto-memory keeps the
*user and the relationship* documented. Without it, every session
starts from zero on user preferences, prior corrections, and external
references.

For Claude Code: stored at `~/.claude/projects/<project-id>/memory/`
with an `MEMORY.md` index pointing to individual memory files. Other
tools have analogous mechanisms (Cursor's chat history, Aider's
conventions file, etc.).

**Memory types:**
- **`user_*`:** the user's role, expertise, preferences (e.g., "deep Go
  background, new to React").
- **`feedback_*`:** corrections + confirmations the user has given. Save
  *both* corrections AND non-obvious approvals — otherwise the AI drifts
  away from validated approaches and grows over-cautious.
- **`project_*`:** ongoing-work facts not visible from code (in-flight
  initiatives, blockers, deadlines, key incidents).
- **`reference_*`:** pointers to external systems (Linear projects,
  Slack channels, dashboards).

**What NOT to save:**
- Code patterns, conventions, paths — these are derivable from the
  current code.
- Git history or who-changed-what — `git log` / `git blame` are
  authoritative.
- Debugging recipes — the fix is in the code; commit messages have the
  context.
- Anything already documented in CLAUDE.md or `docs/Core/`.

**Critical rules:**
- Memory entries are about what was true *at a point in time*. Verify
  against current code before acting on a memory.
- Update or remove stale memories — don't let them rot.

---

## How to Install This System in a New Project

### Step 1: Create the directory structure
Create all the directories above. The minimum from day one:
- `CLAUDE.md` (or `.cursorrules` / `AGENTS.md` per your tool)
- `docs/Core/`, `docs/Core/Ideas_Pipeline/`
- `.claude/skills/`, `.claude/agents/` (or your tool's equivalent)
- `docs/Audit/`, `docs/Progress_Summaries/`

### Step 2: Write the entry-point + minimum Core docs
Write in this order:
1. `CLAUDE.md` — non-negotiable rules + reading order pointer.
2. `docs/Core/SESSION_PROCEDURES.md` — the "what's next" decision tree.
3. `docs/Core/GOAL.md` — north star + pointers to other Core docs.
4. `docs/Core/PROJECT_CONTEXT.md` — what the project is and how it's structured.
5. `docs/Core/agent_instructions.md` — coding standards + workflow rules.

Other Core docs (ROADMAP, execution_manual, roles, engine_charters) can
be created as the project grows.

### Step 3: Bootstrap the audit + progress layers
- Create `docs/Audit/health_check.md` with the format shown in Pillar 5
  but no findings yet. Subagents will populate it.
- Create `docs/Progress_Summaries/_template.md` and copy the session-
  summary template from Pillar 6.

### Step 4: Bootstrap the ideas pipeline
Create `human.md` with just the two section headers. Create
`ideas_backlog.md` and `idea_evaluations.md` empty but with their
workflow rules quoted at the top. The AI will populate them.

### Step 5: Give the AI its first instruction
Tell the AI:
> "You are working on [project]. Start by reading `CLAUDE.md`, then
> `docs/Core/SESSION_PROCEDURES.md`, then the files they reference.
> Your job is to [high-level task]."

### Step 6: Add `index.md` to each major module
As you build out the project, add an `index.md` to each major source
code directory. Start with just the qualitative top half; the
auto-generated bottom half can be added once you write the sync script.

### Step 7: Build your first skill + first subagent
- Write a `/health-check` or `/run-tests` skill (`.claude/skills/<name>/SKILL.md`).
- Write a `code-health` or `architect` subagent (`.claude/agents/<name>.md`).
- Have the user invoke each once to confirm wiring.

### Step 8: First session-summary cycle
Even on day one, write a `docs/Progress_Summaries/<date>_session.md`
capturing what was set up. This establishes the cadence and the
SessionStart hook (if you wire one) has something to load on session 2.

---

## Key Principles That Make This System Work

1. **Documents own their domain.** Each file has one clear purpose. No file duplicates what another file covers. When two files start saying the same thing, one of them is wrong.

2. **The AI is always told where to look next.** Every document contains explicit pointers to other documents. The AI never has to guess. A doc with no out-pointers is a leaf — make sure that's intentional.

3. **The pipeline gates ideas from becoming code prematurely.** Raw thoughts → structured backlog → evaluated analysis → roadmap → implementation. Each stage requires human approval to advance.

4. **The system is self-maintaining.** `agent_instructions.md` explicitly tells the AI to update the execution manual, lessons_learned, and best practices as it discovers new information. The docs stay fresh because the AI is responsible for their upkeep.

5. **Archive, never delete.** Deprecated code, old transcripts, and legacy implementations all go into `docs/Archive/` or a project-level `Archive/` folder. This preserves institutional memory and prevents accidental loss.

6. **Hybrid index files prevent documentation rot.** The auto-generated code reference tables mean at least half the index is always factually correct. The qualitative half is reviewed periodically via the maintenance workflow, not left to chance.

7. **The decision tree comes before the reference manual.** `SESSION_PROCEDURES.md` (a prioritized "what to do next" list) is more valuable than another reference doc. Decisions under ambiguity is where AI agents drift; an ordered tree resolves it deterministically.

8. **Subagents are scaling lever for recurring auditing.** When the same class of bug shows up multiple times (e.g. interface-drift hidden by bare-except), build a subagent whose mandate is to scan for it. The subagent + its memory becomes a permanent immune response.

9. **Living trackers > static docs.** `health_check.md` is a *living* file that subagents append to and humans approve from. It's more useful than any one-shot audit because it accumulates institutional memory of what's broken and what was fixed when.

10. **The charter / current-state pair surfaces drift.** Pair `engine_charters.md` (what each component *should* do) with `docs/Audit/high_level-*_function.md` (what it actually *does* today). Comparing the two is how you find boundary violations before they become bugs.

11. **Synthesis docs reconcile external reviews against the live state.** When an outside reviewer or a major reframing arrives, write a dated synthesis doc that maps their claims onto current reality, then merge the actionable parts into ROADMAP. Don't let external docs become parallel sources of truth.

12. **Auto-memory carries the relationship across sessions.** What the user prefers, what they've corrected, what they've validated — these belong in cross-conversation memory, not in the project docs. Keep the two layers separate: project docs describe the project; memory describes the user.
