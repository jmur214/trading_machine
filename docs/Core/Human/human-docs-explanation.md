# How the Documentation System Works
> This is for **you, the human**. If you're ever confused about why the docs are structured this way, what each file does, or how to improve the system — read this.

---

## The Core Idea

The documentation system is designed around one principle: **an AI agent should be able to orient itself in under 5 minutes, stay aligned across multiple sessions, and know exactly where to write things down so the next agent doesn't start from scratch.**

Every file has exactly one job. Nothing is duplicated on purpose. If two files seem to cover the same topic, one of them should be archived.

---

## The Folder Structure

```
docs/
├── Core/                    ← The AI's brain. Everything an agent needs.
│   ├── README.md            ← "Start Here" — reading order & navigation
│   ├── GOAL.md              ← Mission statement & alignment anchor
│   ├── PROJECT_CONTEXT.md   ← Architecture bible (engines, edges, current state)
│   ├── ROADMAP.md           ← What's planned, phased, with checkboxes
│   ├── execution_manual.md  ← Every CLI command in one place
│   ├── agent_instructions.md← Operating rules & coding standards
│   ├── roles.md             ← Cognitive lenses (how to think about different tasks)
│   ├── files.md             ← Quick-reference directory map
│   ├── Human/               ← Human-facing explanations (this file lives here)
│   └── Ideas_Pipeline/      ← 3-stage idea promotion workflow
│
├── Audit/                   ← Technical deep-dives, engine charters, code findings
├── Progress_Summaries/      ← Historical lessons learned
├── Archive/                 ← Deprecated content (never deleted, always archived)
└── agent_onboarding_prompt.md ← Copy-paste prompt for new AI agents
```

---

## Why Each File Exists

### `GOAL.md`
**Purpose:** The anchor. When an AI starts drifting or a new session begins, this file re-centers it.  
**Why it's separate from README.md:** GOAL.md is about *identity and mission*. README.md is about *navigation and operations*. Merging them would dilute both.

### `PROJECT_CONTEXT.md`
**Purpose:** The architecture bible. Describes the 4-engine system, the edge doctrine, the orchestration layer, and — critically — the **Current State table** that tells agents what's actually built vs. what's only planned.  
**Why it matters:** Without the Current State table, agents can't tell what's real vs. aspirational, which causes them to try building things that already exist or using features that haven't been coded yet.

### `README.md` (in docs/Core/)
**Purpose:** The librarian card. Tells new agents exactly what to read, in what order, and when.  
**Why it exists:** Having 9 files in a folder without a guide is like having a library with no catalog. This file IS the catalog.

### `execution_manual.md`
**Purpose:** Every CLI command in the project, in one place.  
**Why it's critical:** AI agents love to guess commands. This file prevents that. There's a strict rule: if you discover or create a new command, it goes here immediately.

### `agent_instructions.md`
**Purpose:** The operating rules and coding standards.  
**Self-updating rule:** This file contains an instruction to update itself when better practices are discovered. This prevents documentation rot.

### `roles.md`
**Purpose:** 7 cognitive lenses that change how the AI approaches problems (Quant Dev vs. Risk Manager vs. UI Engineer, etc.).  
**How it works:** The AI matches the user's request to a "trigger" pattern and adopts the corresponding lens. This prevents an AI from treating a risk conversation with the same mindset as a signal-generation conversation.

### `files.md`
**Purpose:** A quick-reference table mapping every directory to its purpose.  
**Separate from README:** README explains how to use docs. files.md explains how to navigate the codebase. Different domains.

### `Ideas_Pipeline/`
**Purpose:** A 3-stage workflow for turning raw human thoughts into structured, evaluated, and eventually roadmapped features.  
**The 3 stages:**
1. `human.md` — You dump raw ideas here (only you write to this)
2. `ideas_backlog.md` — AI extracts, categorizes, and assigns tracking IDs
3. `idea_evaluations.md` — AI does deep-dive analysis with feasibility/impact scores
4. Approved evaluations get promoted into `ROADMAP.md`

**Why this matters:** Without this pipeline, ideas jump straight to code. This gates them through structured thinking first.

### `ROADMAP.md`
**Purpose:** The forward-looking development plan with checkboxes.  
**Rule:** Only items that have survived the Ideas Pipeline (or were explicitly planned during architecture sessions) should be here.

---

## How to Improve the Docs

If something feels wrong, here's how to fix it:

| Problem | Solution |
|---------|----------|
| Two files say conflicting things | One is stale. Archive the less accurate one. |
| A file feels too long | Split it. Each file should have ONE job. |
| An AI keeps getting confused about X | Add the answer to the file it would logically look in first. |
| A new directory was created but isn't documented | Add it to `files.md`. |
| A new command was created but isn't documented | Add it to `execution_manual.md`. |
| The Current State table is wrong | Update it directly in `PROJECT_CONTEXT.md`. |
| You have a new idea | Write it in `Ideas_Pipeline/human.md` and ask the AI to process it. |

### The Golden Rule
> **Archive, never delete.** If a file is outdated, move it to `docs/Archive/`. Never throw away institutional memory.

---

## Quick Reference: The Full Documentation System

The project uses a **6-Pillar Documentation Architecture** (documented in depth at `DOCUMENTATION_SYSTEM.md` in the repo root):

1. **Core Docs** (`docs/Core/`) — The AI command center
2. **Ideas Pipeline** (`docs/Core/Ideas_Pipeline/`) — Raw ideas → structured backlog → evaluated → roadmapped
3. **Hybrid Indexes** (`index.md` in each engine dir) — Top half: human-written architecture notes. Bottom half: auto-generated code reference.
4. **Workflows** (`.agent/workflows/`) — Slash-command automations for common tasks
5. **Audit Layer** (`docs/Audit/`) — Technical deep-dives, engine charters, findings
6. **Progress Layer** (`docs/Sessions/`) — Historical lessons learned, phase completion logs
