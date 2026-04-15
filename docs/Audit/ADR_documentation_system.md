# Architecture Decision Record: Documentation System Evolution
> A complete chronological record of every design decision made during the documentation restructuring conversation. Each phase includes the full proposal text and the resulting outcome.

---

## Phase 1: Initial Documentation Improvement Plan

### Proposal (Plan v0)
The first plan proposed 6 improvements to the existing `docs/Core/` system:

1. **`agent_instructions.md` & `ROADMAP.md` Pipeline** — Remove generic coding fluff from agent_instructions, add a strict mandate prioritizing `ROADMAP.md` as the main progress tracker.
2. **`PROJECT_CONTEXT.md` Split & Rewrite** — Split into two docs: a short everyday reference and a deep-dive onboarding document. Rewrite the intro to remove "Schwab Intelligent Portfolio" phrasing, redefine "Edge," and fix Engine B & C definitions.
3. **`files.md` Strategy** — Implement a dual-file approach: a short `files.md` for daily use and a comprehensive `extensive_files.md` for deep codebase navigation.
4. **`GOAL.md` Wording** — Adjust language to remove imperative/action triggers so the AI doesn't think it needs to execute a task every time it reads it.
5. **`roles.md` Tweaks** — Defer to later but note that roles need custom adjustments.
6. **Ideas Workflow** — Establish a rule where the human writes raw thoughts into an "inbox" file and the AI processes them into `ideas_backlog.md`.

### User Decision
Approved with clarifications. Requested the AI study legacy chat transcripts in the Archive to find lost context.

### Outcome
- `agent_instructions.md` was rewritten with dynamic update rule
- `GOAL.md` was reframed as an anchor document
- Ideas Pipeline was formalized as a 3-file system: `human.md` → `ideas_backlog.md` → `idea_evaluations.md`

---

## Phase 2: Legacy Transcript Analysis

### Proposal (Plan v6 — Archive Deep Dive)
After reviewing legacy transcripts in `docs/Archive/Other/chat_transcripts/`, identified 4 major architectural visions that failed to make the jump to modern docs:

1. **The True Definition of "Sleeves"** — Archives described sleeves as Functional Strategy Blocks (Core, Technical, Fundamental, True Edge), not just asset classes.
2. **The SIP Paradigm** — Ultimate goal was to build an SIP-inspired, quant-native allocator with drift bands, rebalance scheduling, and TLH.
3. **The Centralized OMS Layer** — Legacy architecture placed immense priority on a unified OMS abstraction.
4. **The Cockpit "Big Red Button"** — Dashboard was meant to be a human-in-the-loop override center with risk sliders and mobile push notifications.

### Proposal (Plan v7 — The User's Voice)
Laser-focused on the user's own words from the transcripts (ignoring AI suggestions):

1. **The "True Edge" Philosophy** — User defined the project's Holy Grail: combined edges from multiple independent categories creating high-conviction signals.
2. **The Genesis of Engine 4** — User personally mandated Engine D (The Governor/Darwin) for discovering new edges and ruthlessly culling deprecated ones.
3. **The Cockpit as Human Override Console** — Dashboard vision included human adjustments, capital management, expected value views, and mobile notifications.
4. **The "Real Fund Manager" Mentality** — User explicitly stopped rushed coding: *"no. i want to keep planning and brainstorming. no coding yet."*
5. **AI Operating Constraints** — *"When modifying code, focus on robustness, not shortcuts."*

### Proposal (Plan v8 — Edge Doctrine)
Distilled the user's exact categorical breakdown of what an "Edge" means:
- 6 Pillars: Technical, Fundamental, News-Based, Stat/Quant, Behavioral/Psychological, "Grey"
- The Holy Grail "True Edge": only fires when multiple independent categories simultaneously align

### User Decision
Approved all findings. Directed that the "True Edge" definition and 6 edge categories be immortalized in `PROJECT_CONTEXT.md`.

### Outcome
- `PROJECT_CONTEXT.md` was substantially rewritten with accurate edge doctrine, corrected engine definitions, and the user's verbatim design philosophy
- User's direct quotes were preserved as foundational constraints
- Sleeves definition corrected, OMS layer acknowledged, Cockpit override requirements documented

---

## Phase 3: Codebase Architecture Review

### Proposal (Plan v9 — Brainstorming the Review)
Proposed 4 system audits through the lens of a "Real Fund Manager":
1. **OMS Parity Audit** — Review how signals become Order objects
2. **Portfolio Isolation (Sleeves) Audit** — Can Engine C handle isolated sub-accounts?
3. **Data Primitive Audit** — Are cross-engine communications strictly typed?
4. **Separation of Powers Audit** — Are engines bleeding into each other?

### User Decision
Approved but said: *"I don't want us to go too crazy just yet, no refactoring, just continue doing a deep dive."*

### Proposal (Plan v10-13 — The Review Findings)
Conducted bottom-up review in 3 phases:

**Phase 2A — Execution & Verification:**
- `run_shadow_paper.py` completely bypasses the 4-Engine architecture
- Test stubs are empty (39 bytes). Zero unit test coverage on core engines.
- `test_golden_path.py` explicitly tests for known bugs ("Bagholder" and "Vanity" bugs)

**Phase 2B — Orchestration & Data:**
- `ModeController` is a well-architected abstraction layer being completely ignored by newer scripts
- `DataManager` relies on brittle CSV loops; `CachedCSVLiveFeed` re-reads same CSV files continuously

**Phase 2C — Core Engines:**
- God Classes: `alpha_engine.py` is 36KB, `risk_engine.py` is 36KB
- Ghost files: `risk_engine_bak.py`, dual governors (`governor.py` + `system_governor.py`)
- Architectural schism: half the codebase uses the 4-Engine approach, half bypasses it

### User Decision
User directed: *"I don't want to make any code changes yet. I want to continue doing a deep dive."*
All findings logged to `docs/Audit/codebase_findings.md` as a living ledger.

### Outcome
- Comprehensive `docs/Audit/codebase_findings.md` created with folder-by-folder analysis
- Remediation hitlist prioritized: execution convergence → test overhaul → data modernization → engine cleanup

---

## Phase 4: Modular Documentation Strategy

### Proposal (Plan v15-17)
The `extensive_files.md` (382KB code dump) was identified as the core problem — it bloated AI context windows while providing little structural intelligence. Proposed replacement:

1. **High-Level System Map** — `docs/Core/system_architecture.md` as a macro-flow TOC
2. **Hierarchical Directory Indexes** — `index.md` files in every major directory
3. **Unified Archival Protocol** — Move legacy bloat to `Archive/`

User asked: *"Manual or automated generation for the index files?"*

### The "Mullet" Hybrid Decision
User loved both approaches. The final design was the "Mullet":
- **Top Half (Qualitative):** Hand-written by AI using audit findings — explains *why* the folder exists, its architectural role, dependencies, known weaknesses
- **Bottom Half (Automated):** A Python script (`scripts/sync_docs.py`) auto-generates a "Code Reference" table by parsing Python files and extracting classes, functions, and docstrings
- **The Magic:** Script uses a markdown tag (`<!-- AUTO-GENERATED: DO NOT EDIT BELOW -->`) to only overwrite the bottom half, keeping qualitative notes safe

### Documentation Maintenance Workflow
Created `/6_docs_maintenance` slash command workflow:
1. AI runs `python -m scripts.sync_docs` to update code references
2. AI compares new auto-generated sections against manual qualitative sections
3. AI flags disconnects and proposes updates
4. Human approves

### Outcome
- `scripts/sync_docs.py` created and functional
- `index.md` files created in all engine directories, `orchestration/`, and `scripts/`
- `.agent/workflows/6_docs_maintenance.md` created
- `extensive_files.md` archived

---

## Phase 5: Engine Audit & Chartering

### Context
User brought in an external AI opinion (`docs/Audit/Mini-projects/outside-opinion.md`) for an independent assessment of the engine architecture.

### Key Decisions
1. **Engine A (Forecast)** — Needs much looser signal filtering; currently too restrictive
2. **Engine C (Portfolio)** — Explored the idea of dual portfolios (actual + paper for testing optimal variations)
3. **Engine D (Governor)** — Most ambitious but least defined; transitioning from autonomous controller to advisory role
4. **Engine E (Regime Intelligence)** — Formally chartered as the single source of macro truth, replacing the regime logic previously scattered across A and D

### Outcome
- `docs/Audit/engine_charters.md` created with formal authority boundaries for all 5 engines
- `docs/Audit/simple_engine_roles.md` created with plain-English role definitions
- Double-counting prevention matrix defined
- `docs/Audit/high_level-engine_function.md` populated with business-rule descriptions of Engines A–D + Data Manager

---

## Phase 6: Documentation Systemization

### Proposal
The documentation system had proven so effective that the user wanted to make it portable — a universal framework that could be applied to any project.

### Outcome
- `DOCUMENTATION_SYSTEM.md` created at repo root — a complete, self-contained guide to the 6-Pillar Documentation Architecture
- Pillars: Core Docs, Ideas Pipeline, Hybrid Index, Workflows, Audit Layer, Progress Layer

---

## Phase 7: GitHub Preparation & Security Audit

### Security Audit Findings
- ✅ No hardcoded secrets — all API key references use `os.getenv()`
- ✅ `.env` and `config/alpaca_keys.json` gitignored
- ✅ No `.pem`, `.key`, or credential files exist
- ⚠️ `.gitignore` expanded to cover `evolution.log`, `.env.*`, `storage/*.json`, `.pytest_cache/`, IDE directories
- ⚠️ Previously-committed data files (`data/trade_logs/`, `data/governor/`) removed from git tracking via `git rm --cached`

### README Overhaul
Complete rewrite of root `README.md` with:
- ASCII architecture diagram of the 5-engine system
- Edge categories, risk management, and learning capabilities
- Full project directory tree, quick start guide, tech stack table
- Security section and financial disclaimer

### Branding Decision
After extensive brainstorming (40+ name candidates), the project was named **ArchonDEX** — a portmanteau of "Archon" (Greek: ruler/governor, reflecting Engine D) and "Dex/Index" (financial product energy).

---

## Phase 8: Documentation Usability Audit (Current)

### AI-Usability Scorecard
- **Orientation speed:** 8/10
- **Single source of truth:** 5/10
- **Self-maintenance:** 7/10
- **Context-drift resistance:** 4/10
- **Completeness:** 6/10
- **Consistency:** 5/10

### Fixes Executed
1. Merged Orchestration Layer section from `system_architecture.md` into `PROJECT_CONTEXT.md`
2. Added Engine E charter mention to `PROJECT_CONTEXT.md`
3. Added "Current State" table to `PROJECT_CONTEXT.md`
4. Archived `system_architecture.md` to `docs/Archive/`
5. Fixed `GOAL.md` dead reference — now points to `index.md` files
6. Fixed `execution_manual.md` typo (`--debugt` → `--debug`)
7. Fixed `agent_instructions.md` — CLI args ref now points to `execution_manual.md`
8. Expanded `files.md` to cover all 20+ project directories
9. Added "System Architect / Auditor" cognitive lens to `roles.md`
