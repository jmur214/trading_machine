# Doc Reference Update — Pass 2

Mechanical reference-updating pass. Captures every file checked, every edit applied, files where no change was needed, the proposed revision for `DOCUMENTATION_SYSTEM.md`, and the redundancy review against `agent_instructions.md`. No commit was attempted — this is a record of what changed and what's awaiting review.

---

## State at start of pass

The earlier restructure had repopulated `docs/Audit/` as a lean living folder:

```
docs/Audit/
├── README.md
├── check.md
├── health_check.md
└── high_level-engine_function.md
```

…and the moved files now live at:

- `docs/Core/engine_charters.md`
- `docs/Core/simple_engine_roles.md`

Historical audit material is in gitignored `docs/Archive/Audit/`.

`.claude/` now contains 10 subagents under `agents/`, a `commit` skill under `skills/commit/SKILL.md`, and a hook config at `settings.json`.

`CLAUDE.md` had also been expanded with new "Git discipline" and "Git actions that require approval" sections; `SESSION_PROCEDURES.md` had been updated to include a commit check in its session-end checklist.

Net consequence: several path references that were broken at the time of the previous audit (`DOC_AUDIT_FINDINGS.md`) are now correct, because the missing files came back. This pass focuses only on what is *still* stale.

---

## Files verified — no changes needed

### `CLAUDE.md`

- Line 52 references `docs/Audit/health_check.md` → file exists at that path.
- Line 153 references `docs/Audit/health_check.md` → same.
- No other `docs/Audit/...` references in the file.

### `docs/Core/SESSION_PROCEDURES.md`

- Path 2 references `docs/Audit/health_check.md` → file exists.
- Session-end checklist references `health_check.md` (relative) and `docs/Progress_Summaries/_template.md` → both correct.

### `.claude/settings.json`

- SessionStart hook greps `docs/Audit/health_check.md` → file exists; the empty health-check banner block in this session's startup output is now a downstream artifact (no findings yet), not a broken path.

### `docs/Core/GOAL.md`

- Reference map points to `docs/Core/PROJECT_CONTEXT.md`, `docs/Core/files.md`, `docs/Core/execution_manual.md`, `docs/Core/ROADMAP.md`, `docs/Progress_Summaries/lessons_learned.md`, `docs/Progress_Summaries/`, `docs/Core/agent_instructions.md`, `docs/Core/roles.md`, `engines/engine_a_alpha/index.md`. All resolve.

### `docs/Core/Ideas_Pipeline/*.md`

- `grep -rln "docs/Audit\|simple_engine_roles\|engine_charters\|codebase_findings\|high_level-engine_function" docs/Core/Ideas_Pipeline/` → no hits.

### `engines/**/index.md`

- `grep -rn "docs/Audit" engines/` → no hits.

---

## Edits applied

### Edit 1 — `docs/Core/README.md` (Tier 1 table)

Added `SESSION_PROCEDURES.md` as a Tier 1 entry, ahead of `GOAL.md` and `PROJECT_CONTEXT.md`, to match the reading order in `CLAUDE.md` (CLAUDE.md → SESSION_PROCEDURES.md → README.md only if needed).

```diff
 ### Tier 1: Orient (Read These First, Every New Session)

 | File | Purpose | When to Read |
 |------|---------|-------------|
+| **`SESSION_PROCEDURES.md`** | Operational playbook — "what's next" decision tree (Paths 1–6), ideas-pipeline routing, session-end checklist. | Every session, after `CLAUDE.md`. Re-readable mid-session without re-loading anything else. |
 | **`GOAL.md`** | Your north star. Defines the AI's role, links to all reference docs. | First thing, every session. If you feel context drifting, re-read this. |
 | **`PROJECT_CONTEXT.md`** | The architecture bible. 6-Engine system, edge doctrine, current state table, design philosophy. | Once at the start. Re-read when touching engine-level logic. |
```

### Edit 2 — `docs/Core/README.md` (Deep Onboarding table)

Updated four paths and replaced the `codebase_findings.md` reference with a pointer to the living `health_check.md`. Removed the "(⚠️ draft — will migrate to Core when finalized)" note from `engine_charters.md` since it has migrated.

```diff
 | File | Purpose |
 |------|---------|
-| **`docs/Audit/simple_engine_roles.md`** | Plain-English "hedge fund room" metaphor — gives you the intuitive feel for each engine's personality |
-| **`docs/Audit/engine_charters.md`** | Formal authority boundaries, input/output contracts, invariants, and the interaction map (⚠️ draft — will migrate to Core when finalized) |
-| **`docs/Audit/high_level-engine_function.md`** | What each engine actually does TODAY in the code (⚠️ draft — compare against charters to see the gap) |
-| **`docs/Audit/codebase_findings.md`** | Folder-by-folder audit of the codebase — known bugs, god classes, weak points, and the remediation hitlist |
+| **`docs/Core/simple_engine_roles.md`** | Plain-English "hedge fund room" metaphor — gives you the intuitive feel for each engine's personality |
+| **`docs/Core/engine_charters.md`** | Formal authority boundaries, input/output contracts, invariants, and the interaction map |
+| **`docs/Audit/high_level-engine_function.md`** | What each engine actually does TODAY in the code (compare against charters to see the gap) |
+| **`docs/Audit/health_check.md`** | Living tracker of current code-quality findings — maintained by the `engine-auditor` and `code-health` subagents |
 | **`engines/*/index.md`** | Module-level documentation inside each engine directory — architecture notes + auto-generated code reference |
```

### Edit 3 — `docs/Core/README.md` (Beyond docs/Core/ table)

Removed the `.agent/workflows/` row (replaced by `.claude/` infrastructure). Added rows for `.claude/agents/`, `.claude/skills/`, `.claude/settings.json`, and `CLAUDE.md`. Reframed `docs/Audit/` as living code-health tracking.

```diff
 ## Beyond docs/Core/

 | Location | Purpose |
 |----------|---------|
-| `docs/Audit/` | Engine design work & codebase analysis — start with its `README.md` for reading order. Key files: `engine_charters.md` (target design), `high_level-engine_function.md` (current state), `codebase_findings.md` (known issues) |
-| `docs/Audit/engine_charters.md` | Formal authority boundaries for all 6 engines (draft — will migrate to Core when finalized) |
-| `docs/Progress_Summaries/` | Historical lessons learned and phase completion logs |
-| `docs/Archive/` | Deprecated content preserved for historical reference |
-| `.agent/workflows/` | Slash-command automation workflows (e.g., `/1_run_backtest`) |
-| `DOCUMENTATION_SYSTEM.md` (repo root) | The universal guide to how this entire documentation system works |
+| `docs/Audit/` | Living code-health tracking. Contains `health_check.md` (current findings, maintained by subagents) and `high_level-engine_function.md` (what each engine does today). Compare the latter against `docs/Core/engine_charters.md` to see refactoring drift. |
+| `docs/Progress_Summaries/` | Session summaries (`YYYY-MM-DD_session.md`), `lessons_learned.md`, and the `_template.md` used for new summaries. |
+| `docs/Archive/` | Gitignored historical content — old audits, retired specs, prior roadmaps. Snapshots, not current state. |
+| `.claude/agents/` | Subagent definitions implementing the cognitive lenses in `roles.md`. |
+| `.claude/skills/` | Reusable skills (e.g. `commit/SKILL.md` for commit-message format). |
+| `.claude/settings.json` | Project hooks — SessionStart banner, Stop reminder, PostToolUse `sync_docs.py` trigger on `engines/**/*.py`. |
+| `CLAUDE.md` (repo root) | Operating constitution — non-negotiable rules, autonomy boundaries, git discipline. |
+| `DOCUMENTATION_SYSTEM.md` (repo root) | Universal guide describing the documentation system's design philosophy. |
```

### Edit 4 — `docs/Core/agent_instructions.md` (line 12)

Updated the `engine_charters.md` path. Left `high_level-engine_function.md` at its current `docs/Audit/` location.

```diff
-- **Engine Boundaries:** The system uses a 6-engine architecture: A (Alpha), B (Risk), C (Portfolio), D (Discovery), E (Regime), F (Governance). Before modifying any engine's core logic, consult `docs/Audit/engine_charters.md` for authority boundaries. Cross-reference with `docs/Audit/high_level-engine_function.md` to understand what each engine currently does.
+- **Engine Boundaries:** The system uses a 6-engine architecture: A (Alpha), B (Risk), C (Portfolio), D (Discovery), E (Regime), F (Governance). Before modifying any engine's core logic, consult `docs/Core/engine_charters.md` for authority boundaries. Cross-reference with `docs/Audit/high_level-engine_function.md` to understand what each engine currently does.
```

### Edit 5 — `docs/Core/files.md` (Documentation table + new AI Configuration table)

Updated `docs/Core/` to enumerate its new contents (CLAUDE.md entry, SESSION_PROCEDURES.md, engine_charters.md, simple_engine_roles.md). Reframed `docs/Audit/` as living code-health tracking. Reframed `docs/Progress_Summaries/` to mention the per-session summary convention. Added a new "AI Configuration" table covering `.claude/agents/`, `.claude/skills/`, `.claude/settings.json`, `CLAUDE.md`, and `DOCUMENTATION_SYSTEM.md`.

```diff
 ## Documentation

 | Directory | Purpose |
 |-----------|---------|
-| `docs/Core/` | AI command center — GOAL, PROJECT_CONTEXT, ROADMAP, execution_manual, roles |
+| `docs/Core/` | AI command center — `CLAUDE.md` reading order entry, `SESSION_PROCEDURES.md`, `GOAL.md`, `PROJECT_CONTEXT.md`, `ROADMAP.md`, `engine_charters.md`, `simple_engine_roles.md`, `execution_manual.md`, `roles.md`, `agent_instructions.md`, `files.md` |
 | `docs/Core/Ideas_Pipeline/` | 3-stage idea promotion workflow (human → backlog → evaluations → ROADMAP) |
-| `docs/Audit/` | Technical audits, engine charters, codebase findings |
-| `docs/Progress_Summaries/` | Lessons learned, timestamped phase completion summaries |
-| `docs/Archive/` | Deprecated content — preserved for historical reference |
+| `docs/Audit/` | Living code-health tracking — `health_check.md` (current findings, maintained by subagents) and `high_level-engine_function.md` (what each engine does today; compare against `docs/Core/engine_charters.md`) |
+| `docs/Progress_Summaries/` | Per-session summaries (`YYYY-MM-DD_session.md`), `lessons_learned.md`, `_template.md` |
+| `docs/Archive/` | Gitignored historical content — old audits, retired specs, prior roadmaps |
+
+## AI Configuration
+
+| Directory | Purpose |
+|-----------|---------|
+| `.claude/agents/` | Subagent definitions (one `.md` per cognitive lens — `architect`, `code-health`, `edge-analyst`, `engine-auditor`, `ml-architect`, `quant-dev`, `regime-analyst`, `risk-ops-manager`, `ux-engineer`, `agent-architect`) |
+| `.claude/skills/` | Reusable skills (e.g. `commit/SKILL.md` — commit-message format) |
+| `.claude/settings.json` | Project hooks: SessionStart banner, Stop reminder, PostToolUse(Edit\|Write) → `sync_docs.py` for `engines/**/*.py`; permission boundaries |
+| `CLAUDE.md` (repo root) | Operating constitution — non-negotiable rules, autonomy boundaries, git discipline |
+| `DOCUMENTATION_SYSTEM.md` (repo root) | Universal guide describing the documentation system's design philosophy |
```

### Edit 6 — `docs/Core/roles.md` (subagent note added at top)

```diff
 # Cognitive Lenses & AI Triggers

+> These cognitive lenses are implemented as subagents in
+> `.claude/agents/`. When a task matches a lens, the matching
+> subagent will be delegated to automatically. This file
+> remains the human-readable specification of what each lens
+> prioritizes.
+
 > **CRITICAL RULE**: Do NOT roleplay or adopt a conversational "persona" …
```

### Edit 7 — `docs/Core/roles.md` (Required Reading paths in role 7)

```diff
 - **Required Reading:** Start with `docs/Audit/README.md` for orientation. The key files are:
-  - `docs/Audit/engine_charters.md` — target design (what engines SHOULD do)
+  - `docs/Core/engine_charters.md` — target design (what engines SHOULD do)
   - `docs/Audit/high_level-engine_function.md` — current state (what engines DO today)
-  - `docs/Audit/codebase_findings.md` — known weak points and bugs
+  - `docs/Audit/health_check.md` — living tracker of current code-quality findings (maintained by subagents)
```

---

## Proposed (NOT executed) — `DOCUMENTATION_SYSTEM.md` revision

This file's core structure no longer matches reality. Per the user's instruction, the revision is proposed here rather than applied.

### What no longer matches

| Section | Current reality |
|---|---|
| Pillar 4: `.agent/workflows/` and `.agent/rules/` (slash-commands, terminal-commands.md, `// turbo` annotations) | Replaced by `.claude/agents/` (subagents) and `.claude/skills/` (e.g. `commit/SKILL.md`). The `// turbo` annotation system no longer exists. Hooks live in `.claude/settings.json`, not workflow files. |
| Pillar 5: `docs/Audit/` as "growing technical memory and blueprint storage" with engine charters, outside opinions, mini-projects | `docs/Audit/` is now a lean *living* folder — only `health_check.md` and `high_level-engine_function.md`. Charters moved to `docs/Core/`. Outside opinions, mini-projects, and historical audits sit in gitignored `docs/Archive/`. |
| No mention of `CLAUDE.md` | `CLAUDE.md` is now the operating constitution (non-negotiable rules, autonomy boundaries, git discipline). It is the project's most important AI-facing doc. |
| No mention of `SESSION_PROCEDURES.md` | This file (Path 1–6 decision tree, ideas-pipeline routing, session-end checklist) is now in Tier 1 reading. It's the operational complement to `CLAUDE.md`. |
| No mention of subagents | The cognitive-lens system from `roles.md` is now implemented via 10 subagents in `.claude/agents/`, each with its own description, tools, and routing triggers. |
| No mention of hooks | `.claude/settings.json` has SessionStart, Stop, and PostToolUse(Edit\|Write) hooks that automate context-loading, session-end reminders, and `sync_docs.py` triggering. |
| GOAL.md template (lines 76–92) | Slightly drifted — current `GOAL.md` reads more as a reference map than a north star, and the "Current Mode" line is generic. Worth updating for accuracy. |

### Proposed plan

- Add a new **Pillar 0: The Operating Constitution** describing `CLAUDE.md` and `SESSION_PROCEDURES.md`.
- Replace **Pillar 4** with a new "AI Configuration (`.claude/`)" pillar covering `agents/`, `skills/`, `settings.json` hooks, and the `commit` skill.
- Rewrite **Pillar 5** to describe the lean `Audit/` + populated `Archive/` split.
- Add a "Subagent roster" subsection under Pillar 4 enumerating the 10 lenses.
- Keep Pillars 1, 2, 3, 6 mostly intact, with path corrections where needed.

Estimated change scope: ~80–120 lines modified across the 487-line file.

**Awaiting approval before applying.**

---

## Flagged for review — operational rules in `agent_instructions.md` that may be redundant

Listing for review only. Not removed.

| # | Line(s) | Rule | Now also covered by |
|---|---|---|---|
| 1 | 4 | "CLI Tracking" — update `execution_manual.md` for any new command. | `CLAUDE.md` "Never guess CLI commands"; `SESSION_PROCEDURES.md` end-of-session checklist. **Triple-stated.** |
| 2 | 5 | "Git Commits" — descriptive, atomic. | `CLAUDE.md` "Git discipline" section + `commit` skill at `.claude/skills/commit/SKILL.md` (skill owns the message format). |
| 3 | 7 | Update `ROADMAP.md` before/after major features. | `SESSION_PROCEDURES.md` Path 6 + session-end checklist. |
| 4 | 8 | Log significant changes / failures in `lessons_learned.md`. | `SESSION_PROCEDURES.md` "When you encounter a surprise" + session-end checklist. |
| 5 | 9 | Log feature additions in `Progress_Summaries/` with timestamped file. | `SESSION_PROCEDURES.md` end-of-session checklist + `_template.md`; Stop hook in `settings.json` reminds about it. |
| 6 | 10 | Run `/6_docs_maintenance` slash command or `python scripts/sync_docs.py`. | `/6_docs_maintenance` no longer exists in the new layout. PostToolUse(Edit\|Write) hook in `settings.json` runs `sync_docs.py` automatically when an `engines/**/*.py` file is touched. **Manual instruction is largely obsolete.** |
| 7 | 11 | "Command Tracking (CRITICAL)" — same content as line 4. | Internal duplicate within the file itself. |
| 8 | 13 | "Environment Variables" — secrets in `.env`, never commit. | `CLAUDE.md` `.env` rule + Git discipline ("Never commit secrets"). |
| 9 | 16 | "Execution Commands" — don't guess script paths, consult execution_manual. | Same content as `CLAUDE.md` "Never guess CLI commands". |
| 10 | 17 | "Idea Ingestion" — route through Ideas_Pipeline. | `SESSION_PROCEDURES.md` "Ideas pipeline routing" (more detailed; source of truth). |
| 11 | 18 | "UI Architecture" — `cockpit/dashboard/` deprecated, use `dashboard_v2/`. | Same content as `CLAUDE.md` non-negotiable "Never edit `cockpit/dashboard/`". |
| 12 | 21 | "Edge Registry" — never manually edit `edge_weights.json`. | Same content as `CLAUDE.md` non-negotiable "Never manually edit `data/governor/edge_weights.json`". |
| 13 | 31 | "Dynamic Best Practices" — update this file when better practices found. | Self-update rule still functionally relevant, but the broader self-update pattern is now distributed across `CLAUDE.md`, `SESSION_PROCEDURES.md`, `lessons_learned.md`, `health_check.md`. `agent_instructions.md` may no longer be the natural home. |
| 14 | 32 | "Performance" — pandas vectorization, Parquet over CSV. | Same content as `CLAUDE.md` "Operating constraints" final paragraph. |
| 15 | 34 | "AI Operating Constraints" — brutal realism over blind code generation. | Same content as `CLAUDE.md` "Operating constraints" first paragraph. |

**Net assessment:** Roughly 60–70% of `agent_instructions.md` now duplicates content in `CLAUDE.md`, `SESSION_PROCEDURES.md`, hooks, or skills. Lines 22–25 (Edge & Strategy Lifecycle internals — discovery cycle, GA pipeline, debug system, run isolation) and line 28 (Modularity / functions small / no UI-data mixing) appear unique to this file and worth keeping.

---

## Diff summary for this pass only

| File | Lines changed |
|---|---|
| `docs/Core/README.md` | 23 (Tier 1 + Deep Onboarding paths + Beyond docs/Core/) |
| `docs/Core/agent_instructions.md` | 2 (`engine_charters.md` path) |
| `docs/Core/files.md` | 18 (Documentation table + new AI Configuration table) |
| `docs/Core/roles.md` | 10 (subagent note + Required Reading paths) |

**4 files modified, ~53 lines changed in this pass.**

The wider `git diff --stat` for `CLAUDE.md docs/ .claude/` shows many additional changes — those are the prior restructure that was already in flight before this pass and are not part of this update.

---

## Awaiting decisions

1. The 4 file edits above (review and accept, revise, or revert).
2. The proposed `DOCUMENTATION_SYSTEM.md` revision plan (approve, modify, or skip).
3. The 15-item redundancy review against `agent_instructions.md` (no action taken — trim list, full rewrite, or leave).
4. Whether to commit at this point and, if so, with which scope.
