# docs/Audit/ — Technical Deep-Dives & Engine Design

This folder contains the architectural research, engine design work, and codebase analysis that informs the system's evolution. These are **working documents** — some describe what IS, others describe what SHOULD BE.

---

## Reading Order

| # | File | What It Is | Status |
|---|------|-----------|--------|
| 1 | `high_level-engine_function.md` | **What each engine does TODAY** — current business rules as-implemented | 🚧 Draft |
| 2 | `outside-opinion.md` | Independent external review of the engine design — pros, cons, recommendations | 📖 Reference |
| 3 | `engine_charters.md` | **What each engine SHOULD do** — formal authority boundaries, contracts, invariants | 🚧 Draft (will migrate to Core when finalized) |
| 4 | `simple_engine_roles.md` | Plain-English "hedge fund room" metaphor explaining each engine role | ✅ Stable |
| 5 | `codebase_findings.md` | Folder-by-folder codebase audit — bugs, god classes, weak points, hitlist | 📸 Snapshot (from initial deep-dive) |

## The Key Distinction

> **`high_level-engine_function.md`** describes the system as it exists in code right now.
> **`engine_charters.md`** describes the system as it *should* exist once refactoring is complete.
>
> The gap between these two files IS the refactoring work remaining. Comparing them reveals exactly where the implementation has converged toward — or diverged from — the charter design.

## How to Use These Files

- **Before modifying engine logic:** Read the relevant engine's charter in `engine_charters.md` to understand the target authority boundaries.
- **Before proposing architectural changes:** Read `outside-opinion.md` (start with the TL;DR at the top) to understand the external critique that shaped the charters.
- **Before debugging system behavior:** Check `codebase_findings.md` for known weak points in that area.
- **When explaining the system to someone new:** Use `simple_engine_roles.md` — it's the most accessible overview.

## Subfolders

| Folder | Contents |
|--------|----------|
| `Mini-projects/` | Standalone research tasks and prompts |
| `Previous_Audits/` | Historical audit results |
