# docs/Audit/ — Code Health Tracking

This folder tracks the current quality state of the codebase. It 
holds operational documents that describe how the system stands 
*right now*, not historical analysis.

## Files

| File | Purpose | Maintained by |
|------|---------|---------------|
| `health_check.md` | Living tracker of current code quality issues | `engine-auditor` and `code-health` subagents |
| `high_level-engine_function.md` | What each engine actually does today (compare against charters to find drift) | Updated as engines change; compared against `docs/Core/engine_charters.md` |

## How this folder is used

`docs/Core/SESSION_PROCEDURES.md` Path 2 ("Critical findings") routes 
to `health_check.md` — it's the file that answers "what should we fix?"

The `engine-auditor` subagent reads `docs/Core/engine_charters.md` 
(target design) and the actual codebase, then appends drift findings 
to `health_check.md`.

The `code-health` subagent scans for general technical debt (god 
classes, duplicates, dead code, etc.) and appends findings the 
same way.

## What this folder is NOT

This folder does NOT hold:
- Architectural specifications (those live in `docs/Core/`)
- Historical audit reports (those live in `docs/Archive/audits/`)
- One-time external reviews (also in `docs/Archive/audits/`)
- Audit prompts or templates (those are in agent definitions in 
  `.claude/agents/`)

## Reading order for a new agent

1. `docs/Core/engine_charters.md` — target design
2. `docs/Audit/health_check.md` — what's currently degraded
3. `docs/Audit/high_level-engine_function.md` — current 
   implementation summary, only if doing detailed engine work

The gap between charter and implementation IS the refactoring work 
remaining. Don't conflate them.