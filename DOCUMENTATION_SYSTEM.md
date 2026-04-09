# The Universal Project Documentation System
### *A complete, copy-paste guide to implement this documentation architecture in any project*

---

## Overview: The Philosophy Behind the System

This documentation system was built to solve one core problem: **AI agents lose context between conversations.** Without a living, structured set of documents, every new conversation requires re-explaining the entire project. With them, an AI can be handed this doc folder and be fully operational in minutes.

The system has **6 Pillars**, each with a distinct purpose. They are not just files — they are a *workflow*. They connect to each other, enforce rules on each other, and are designed to evolve with the project rather than go stale.

The golden rule: **Documents must tell an AI what to do, what not to do, and where to look — in that order.**

---

## Directory Structure to Create

```
your-project/
├── .agent/
│   ├── rules/
│   │   └── terminal-commands.md          # User rules for the AI
│   ├── workflows/
│   │   └── [slash-command-name].md       # Reusable automation workflows
│   └── rules.md                          # Master rules index (optional)
│
├── docs/
│   ├── Core/
│   │   ├── GOAL.md                       # AI entry point / north star
│   │   ├── PROJECT_CONTEXT.md            # What the project is and why
│   │   ├── ROADMAP.md                    # Forward-looking phased goals
│   │   ├── execution_manual.md           # Exact CLI commands for the AI
│   │   ├── agent_instructions.md         # Coding standards & operating rules
│   │   ├── roles.md                      # Cognitive lenses by task type
│   │   ├── files.md                      # High-level file map
│   │   ├── human_explanation.md          # Non-technical project summary
│   │   └── Ideas_Pipeline/
│   │       ├── human.md                  # Raw idea inbox (human writes here)
│   │       ├── ideas_backlog.md          # Structured idea ledger (AI writes here)
│   │       └── idea_evaluations.md       # Deep-dive AI analysis (AI writes here)
│   │
│   ├── Audit/                            # Technical audit and blueprint docs
│   │   └── [topic].md
│   │
│   ├── Progress_Summaries/
│   │   ├── lessons_learned.md            # What worked, what failed
│   │   └── [YYYY-MM-phase-name].md       # Timestamped phase completion notes
│   │
│   └── Archive/                          # Dead/old content, never deleted
│
└── [source-code-directories]/
    └── index.md                          # Hybrid doc for each major folder
```

---

## Pillar 1: The Core Docs Layer (`docs/Core/`)

This is the AI's **command center**. Every new conversation, the AI should be directed here first. These files answer the fundamental questions an AI needs before touching code.

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

## Pillar 4: The Slash Command Workflow System (`.agent/workflows/`)

Workflows encode **repeatable, multi-step automation tasks** as slash commands. Instead of instructing the AI with long natural language descriptions every time, you invoke a slash command and the AI follows the pre-defined steps precisely.

### File Format

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

### Recommended Core Workflows to Create

| Slash Command | Purpose |
|---|---|
| `/run-tests` | Run the full test suite and report failures |
| `/health-check` | Run diagnostics and report system status |
| `/docs-maintenance` | Sync the auto-generated code reference tables |
| `/full-lifecycle` | End-to-end run of the complete application |
| `/deploy` | Deployment or build steps |

### User Rules (`.agent/rules/`)

User rules are constraints that override AI defaults for this specific project. Each rule is a `.md` file in `.agent/rules/`. Examples:
- `terminal-commands.md` — Specifies which commands the AI can auto-run vs. must ask for approval.
- `style-guide.md` — Custom code style preferences.
- `secrets.md` — Rules about never committing API keys, handling env vars, etc.

---

## Pillar 5: The Audit Layer (`docs/Audit/`)

The Audit layer is the project's **growing technical memory and blueprint storage**. It is distinct from the Core docs in that it is not prescriptive — it documents what *was discovered*, not what *should be done*.

### What belongs here:
- **Functional audit documents:** What each major component actually does at a behavioral level (not code-level).
- **Engine/module charters:** The formal authority boundaries and contracts for major components.
- **Outside opinions / research:** Analysis from external sources that informed design decisions.
- **Mini-projects / investigations:** Deep dives on specific sub-problems.

### Key principle: "Source of Truth" documents

The most important audit documents act as the single source of truth for high-level system behavior. They describe *what* a component does (in business terms), not *how* the code works. This separation is critical because:
- It allows architectural discussions without reading the code.
- It gives the AI a stable reference when refactoring.
- It lets you verify intent vs. implementation.

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

### Timestamped Phase Summaries

After completing a major phase, the AI writes a brief markdown summary saved as `docs/Progress_Summaries/YYYY-MM-phase-name.md`. This captures:
- What was built
- Key architectural decisions made
- What is still pending
- Any blockers or open questions

---

## How to Install This System in a New Project

### Step 1: Create the directory structure
Create all the directories above. The key ones that must exist from day one: `docs/Core/`, `docs/Core/Ideas_Pipeline/`, `.agent/workflows/`, `.agent/rules/`.

### Step 2: Create the Core docs
Write `GOAL.md`, `PROJECT_CONTEXT.md`, and `agent_instructions.md` first — these three are the minimum viable set. The others (ROADMAP, execution_manual, roles) can be created as the project grows.

### Step 3: Write the pipeline file bootstraps
Create `human.md` with just the two section headers. Create `ideas_backlog.md` and `idea_evaluations.md` empty but with their header rules quoted at the top. The AI will populate them.

### Step 4: Give the AI its first instruction
Tell the AI:
> "You are working on [project]. Start by reading `docs/Core/GOAL.md` and then the files it references. Your job is to [high-level task]. Before doing anything else, read those files."

### Step 5: Add `index.md` to each major module
As you build out the project, add an `index.md` to each major source code directory. Start with just the qualitative top half; the auto-generated bottom half can be added once you write the sync script.

### Step 6: Build your first workflow
Write a `/health-check` or `/run-tests` workflow. This gives you immediate value and tests that the workflow system is working.

---

## Key Principles That Make This System Work

1. **Documents own their domain.** Each file has one clear purpose. No file duplicates what another file covers.

2. **The AI is always told where to look next.** Every document contains explicit pointers to other documents. The AI never has to guess.

3. **The pipeline gates ideas from becoming code prematurely.** Raw thoughts → structured backlog → evaluated analysis → roadmap → implementation. Each stage requires human approval to advance.

4. **The system is self-maintaining.** The `agent_instructions.md` explicitly tells the AI to update the execution manual, lessons_learned, and best practices as it discovers new information. The docs stay fresh because the AI is responsible for their upkeep.

5. **Archive, never delete.** Deprecated code, old transcripts, and legacy implementations all go into `docs/Archive/` or a project-level `Archive/` folder. This preserves institutional memory and prevents accidental loss.

6. **Hybrid index files prevent documentation rot.** The auto-generated code reference tables mean at least half the index is always factually correct. The qualitative half is reviewed periodically via the maintenance workflow, not left to chance.
