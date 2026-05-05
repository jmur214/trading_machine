# `docs/` — Navigation Index

This is the canonical "where do I find X" index. The folder
structure is organized by **lifecycle** (how does the doc age),
not by topic. See
`docs/Core/SESSION_PROCEDURES.md` § "Documentation lifecycle" for
the rules behind it.

---

## Quick links — current truth

If you only read 5 docs, read these:

| What you need | Where |
|---|---|
| **Current strategy / forward plan** | [`State/forward_plan.md`](State/forward_plan.md) |
| **Current code-quality findings** | [`State/health_check.md`](State/health_check.md) |
| **Roadmap (phased plan, what's next)** | [`State/ROADMAP.md`](State/ROADMAP.md) |
| **North-star goal + AI orientation** | [`State/GOAL.md`](State/GOAL.md) |
| **Hard-won lessons (running collection)** | [`State/lessons_learned.md`](State/lessons_learned.md) |

---

## The 6 folders

### `Core/` — stable design (rarely changes)

Architecture, procedure, philosophy. Treat as constitution-adjacent.

| Doc | Purpose |
|---|---|
| [`PROJECT_CONTEXT.md`](Core/PROJECT_CONTEXT.md) | Architecture brief — read first |
| [`engine_charters.md`](Core/engine_charters.md) | Formal authority boundaries for the 6 engines |
| [`simple_engine_roles.md`](Core/simple_engine_roles.md) | Plain-English "hedge fund room" metaphor |
| [`high_level_engine_function.md`](Core/high_level_engine_function.md) | What each engine actually does today (compare against `engine_charters.md`) |
| [`SESSION_PROCEDURES.md`](Core/SESSION_PROCEDURES.md) | Operational rules for working sessions |
| [`MULTI_SESSION_ORCHESTRATION.md`](Core/MULTI_SESSION_ORCHESTRATION.md) | Director + worker session pattern |
| [`execution_manual.md`](Core/execution_manual.md) | Every CLI command in one place |
| [`agent_instructions.md`](Core/agent_instructions.md) | AI operating rules + coding standards |
| [`roles.md`](Core/roles.md) | The 7 cognitive lenses |
| [`files.md`](Core/files.md) | Repo-tree key file inventory |
| [`README.md`](Core/README.md) | Core-folder reading order |
| [`Human/`](Core/Human/) | Human-facing project explanations |
| [`Ideas_Pipeline/`](Core/Ideas_Pipeline/) | 3-stage idea intake (backlog → evaluation → plan) |

### `State/` — current truth (mutates in place)

These files **mutate in place** — no date suffixes. `git log` is the history.

| Doc | Updated when |
|---|---|
| [`forward_plan.md`](State/forward_plan.md) | Strategy / dispatch changes |
| [`health_check.md`](State/health_check.md) | Code-quality finding opened or resolved |
| [`ROADMAP.md`](State/ROADMAP.md) | Roadmap item completed or re-prioritized |
| [`GOAL.md`](State/GOAL.md) | North-star reframe (rare) |
| [`lessons_learned.md`](State/lessons_learned.md) | Non-obvious thing learned |
| [`deployment_boundary.md`](State/deployment_boundary.md) | Deployment-context shift (e.g. tax-treatment, broker) |

### `Measurements/<YYYY-MM>/` — point-in-time reports (frozen)

Backtests, ablations, audits, workstream close-outs. **Append-only.** A measurement is a point-in-time fact; never edited after the run.

Current month: [`Measurements/2026-05/`](Measurements/2026-05/) — recent measurements (Foundation Gate, Path C harness, WS A-J close-outs)

Prior months: [`Measurements/2026-04/`](Measurements/2026-04/) — gauntlet validation, OOS decomposition, lifecycle triggers, etc.

If you find yourself editing a measurement file post-run, you probably want to:
- Add a `Status: SUPERSEDED-BY-<newfile>` line to the old one, OR
- Write a new measurement file and link to it from the State layer

### `Sessions/<YYYY-MM>/` — per-session summaries (frozen)

Date-stamped session summaries. Same append-only lifecycle as Measurements. The `Sessions/Other-dev-opinion/` subfolder is flat (not month-bucketed) and contains outside-reviewer pastes.

Template: [`Sessions/_template.md`](Sessions/_template.md)

### `Archive/` — explicitly retired (frozen)

Don't read for current truth. Useful for "what did we believe at time X".

Notable contents:
- [`Archive/forward_plans/`](Archive/forward_plans/) — superseded `forward_plan_*.md` files
- [`Archive/Audit/`](Archive/Audit/) — pre-restructure audit folder, kept for context
- [`Archive/DOCUMENTATION_SYSTEM_legacy.md`](Archive/DOCUMENTATION_SYSTEM_legacy.md) — describes the prior doc structure

### `Sources/` — external references

Paper reviews, third-party analysis. Cite freely; treat like a bibliography.

---

## "I want to..." cheat-sheet

| I want to... | Read |
|---|---|
| Understand the project from cold start | `Core/PROJECT_CONTEXT.md` → `Core/Human/` |
| Know what's broken right now | `State/health_check.md` |
| Know what we're working on right now | `State/forward_plan.md` |
| Know what's being measured / shipped | `Measurements/<latest-month>/` |
| Know what an agent did last session | `Sessions/<latest-month>/` |
| Know how to run a CLI command | `Core/execution_manual.md` |
| Understand the doc system itself | `Core/SESSION_PROCEDURES.md` § "Documentation lifecycle" |
| Find a measurement from N months ago | `Measurements/<that-month>/` then grep |
| See what we considered + abandoned | `Archive/` |

---

## Lifecycle rules in 30 seconds

- **Will this still be true in 90 days?** Yes → `State/` or `Core/`. No → `Measurements/` (dated, frozen).
- **Stable design?** `Core/`. **Mutating current truth?** `State/`. **Point-in-time fact?** `Measurements/`.
- **Don't keep two copies of "current".** When State changes, archive the old one to `Archive/`.
- **Measurements are append-only.** If you supersede one, edit only the `Status:` block.
- **Session summaries are append-only.** Write to `Sessions/<YYYY-MM>/YYYY-MM-DD_session.md` per the template.

Full rules: `docs/Core/SESSION_PROCEDURES.md` § "Documentation lifecycle".
