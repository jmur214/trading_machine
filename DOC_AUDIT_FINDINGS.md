# Doc Audit Findings

Pure reporting pass. No files modified. Captures the state of `docs/`, `CLAUDE.md`, and `.claude/` at the time of the audit, relative to the last commit (HEAD = `912ad86`).

---

# Report 1 — Doc changes since last commit

Scope: `docs/`, `CLAUDE.md`, `.claude/`. The `git status` only flags **deletions** under `docs/Audit/` and **untracked additions** elsewhere. There are no `R` (rename) entries, but byte-for-byte size and content matches confirm that 4 of the 16 deletions are **moves**, not true deletions. The other 12 deletions paired with copies that landed under `docs/Archive/` — and `docs/Archive/` is gitignored (line 36 of `.gitignore`: `Archive/`), so git can't see those landing zones.

## 1. Files that moved

Confirmed byte-identical (`diff` returned 0) between HEAD blob and current file:

| Old path (deleted from git) | New path (untracked) | Size |
|---|---|---|
| docs/Audit/engine_charters.md | docs/Core/engine_charters.md | 29,586 B |
| docs/Audit/simple_engine_roles.md | docs/Core/simple_engine_roles.md | 6,247 B |
| docs/Audit/high_level-engine_function.md | docs/Core/Audit/high_level-engine_function.md | 18,272 B |
| docs/Audit/README.md | docs/Core/Audit/README.md | 2,201 B |

Moved into the gitignored `docs/Archive/` zone (size matches HEAD blobs, treat as moves):

| Old path | New path | Size |
|---|---|---|
| docs/Audit/ADR_documentation_system.md | docs/Archive/Audit/ADR_documentation_system.md | 11,319 B |
| docs/Audit/codebase_findings.md | docs/Archive/Audit/codebase_findings.md | 18,301 B |
| docs/Audit/outside-opinion.md | docs/Archive/Audit/outside-opinion.md | 67,348 B |
| docs/Audit/Mini-projects/key.md | docs/Archive/Audit/Mini-projects/key.md | 238 B |
| docs/Audit/Mini-projects/keykey.md | docs/Archive/Audit/Mini-projects/keykey.md | 0 B |
| docs/Audit/Mini-projects/prompts.md | docs/Archive/Audit/Mini-projects/prompts.md | 18,856 B |
| docs/Audit/Previous_Audits/11-11_audit.md | docs/Archive/Audit/Previous_Audits/11-11_audit.md | 16,517 B |
| docs/Audit/Previous_Audits/CRITICAL_SYSTEM_REVIEW.md | docs/Archive/Audit/Previous_Audits/CRITICAL_SYSTEM_REVIEW.md | 3,132 B |
| docs/Audit/Previous_Audits/FUNCTIONAL_AUDIT_LOG.md | docs/Archive/Audit/Previous_Audits/FUNCTIONAL_AUDIT_LOG.md | 6,516 B |
| docs/Audit/Previous_Audits/SYSTEM_AUDIT_REPORT_1.md | docs/Archive/Audit/Previous_Audits/SYSTEM_AUDIT_REPORT_1.md | 6,592 B |
| docs/Audit/Previous_Audits/SYSTEM_AUDIT_REPORT_2.md | docs/Archive/Audit/Previous_Audits/SYSTEM_AUDIT_REPORT_2.md | 2,107 B |
| docs/Audit/Previous_Audits/SYSTEM_MATURITY_AUDIT.md | docs/Archive/Audit/Previous_Audits/SYSTEM_MATURITY_AUDIT.md | 2,277 B |

Net effect: the entire `docs/Audit/` folder no longer exists. Some content surfaced inside `docs/Core/` and `docs/Core/Audit/` (current state); the rest sank into the gitignored `docs/Archive/Audit/` (historical).

## 2. Files that were deleted or archived (no current-state copy)

None. Every removed file is accounted for as a move above.

## 3. Files that were created (genuinely new content, no HEAD ancestor)

| Path | Size | Purpose |
|---|---|---|
| docs/Core/SESSION_PROCEDURES.md | 8,925 B | Operational playbook: "what's next" decision tree (Paths 1–6), ideas-pipeline routing, session-end checklist. Referenced by the new `CLAUDE.md`. |
| docs/Core/Audit/health_check.md | 2,606 B | Living tracker for code-health findings (HIGH/MED/LOW). Source of truth for SESSION_PROCEDURES Path 2. Currently empty of findings. |
| docs/Core/Audit/check.md | 1,775 B | Folder-purpose blurb describing this directory as the "code-health tracking" location — reads like an intended replacement for `README.md` but was committed alongside it. |
| docs/Progress_Summaries/_template.md | 1,718 B | Template for daily session summaries (sections: worked on / decided / learned / pick up next time / files / subagents). Referenced by the SessionStart hook flow. |
| .claude/settings.json | 1,880 B | Project Claude Code settings — additionalDirectories, SessionStart hook, Stop hook, PostToolUse(Edit\|Write) → sync_docs.py. |
| .claude/settings.local.json | 16,184 B | Personal settings (gitignored by `.claude/settings.local.json` rule). |
| .claude/scheduled_tasks.lock | 130 B | Runtime lock (gitignored by `.claude/*.lock`). |
| .claude/agents/agent-architect.md | 4,903 B | Subagent: maintains `.claude/agents/` definitions. |
| .claude/agents/architect.md | 1,886 B | Subagent: read-only system architect / auditor. |
| .claude/agents/code-health.md | 2,360 B | Subagent: tech-debt scanner (god classes, dead code). |
| .claude/agents/edge-analyst.md | 1,804 B | Subagent: Engine A quant work, edges/backtests. |
| .claude/agents/engine-auditor.md | 2,035 B | Subagent: charter-vs-implementation drift checker. |
| .claude/agents/ml-architect.md | 1,923 B | Subagent: ML / external-data integration. |
| .claude/agents/quant-dev.md | 1,594 B | Subagent: latency, infra, data pipelines. |
| .claude/agents/regime-analyst.md | 1,943 B | Subagent: Engines E/F regime + governance. |
| .claude/agents/risk-ops-manager.md | 2,144 B | Subagent: Engine B + live_trader (propose-first by default). |
| .claude/agents/ux-engineer.md | 1,806 B | Subagent: cockpit/dashboard_v2 only. |

## 4. Files modified in place

| Path | Change |
|---|---|
| CLAUDE.md | Whole-file rewrite. HEAD was 3 lines pointing at `docs/Core/GOAL.md`. New version (131 lines) is a full operating constitution: project identity, reading order (`SESSION_PROCEDURES.md` → `README.md`), six non-negotiable rules (archive-not-delete, engine-boundary inviolability, no-guessed-CLI, dashboard_v2-only, no-hand-edit of edge_weights/lifecycle, `.env` handling, "historical audits ≠ current state"), delegation defaults, autonomous-improvement permissions vs. propose-first list, cognitive-lens framing, session-end checklist, brutal-realism / vectorize-over-loops constraints. Net: +129 / −3 lines. |

No other file under `docs/` shows as modified. Files like `docs/Core/README.md`, `docs/Core/agent_instructions.md`, `docs/Core/files.md`, and the moved `docs/Core/Audit/README.md` were left untouched even though their content now points at paths that no longer exist (see Report 2 mismatches).

---

# Report 2 — Current doc structure

Note: `docs/Archive/` is gitignored (`.gitignore:36 → Archive/`); its contents are real on disk but git never sees them. Folder names `*Master_prompts*`, `*System_overview*`, `*Progress_summaries` literally contain asterisks. Sizes shown in bytes.

## /Users/jacksonmurphy/Dev/trading_machine-2/CLAUDE.md
| File | Size | Purpose | Match |
|---|---:|---|---|
| CLAUDE.md | ~5,000 | Project constitution (rules, autonomy boundaries, reading order). | matches name |

**Stale internal references in CLAUDE.md itself:** lines 52 and 112 cite `docs/Audit/health_check.md`. The actual file lives at `docs/Core/Audit/health_check.md`. Two broken paths inside the file the user just rewrote.

## docs/ (root)
| File | Size | Purpose | Match |
|---|---:|---|---|
| .DS_Store | 6,148 | macOS noise; gitignored. | n/a |
| agent_onboarding_prompt.md | 166 | 4-line stub: "read `docs/Core/GOAL.md`". | near-empty (<500 B); appears orphaned — `CLAUDE.md` now sends agents through `SESSION_PROCEDURES.md`, not `GOAL.md`. Candidate for archive or update. |

## docs/Core/
| File | Size | Purpose | Match |
|---|---:|---|---|
| .DS_Store | 6,148 | macOS noise. | n/a |
| GOAL.md | 2,030 | "North star" doc — AI role, reference links. | tracked, unchanged |
| PROJECT_CONTEXT.md | 11,307 | Architecture bible (6 engines, edge doctrine, current state). | unchanged |
| README.md | 6,120 | "AI Command Center" tier guide. | **stale** — Tier 1 + Tier 2 tables and the closing index point at `docs/Audit/simple_engine_roles.md`, `docs/Audit/engine_charters.md`, `docs/Audit/high_level-engine_function.md`, `docs/Audit/codebase_findings.md`, `docs/Audit/` (folder); the first three moved to `docs/Core/` and `docs/Core/Audit/`, the fourth lives in `docs/Archive/Audit/`, and `docs/Audit/` is gone. Six broken links. |
| ROADMAP.md | 22,867 | Phased dev plan w/ checkboxes. | OK |
| SESSION_PROCEDURES.md | 8,925 | New operational playbook (Path 1–6 routing, session-end checklist). | Path 2 cites `docs/Audit/health_check.md` — **broken path** (file is `docs/Core/Audit/health_check.md`). |
| agent_instructions.md | 5,562 | Doc-maintenance rules for agents. | line 12 references `docs/Audit/engine_charters.md` and `docs/Audit/high_level-engine_function.md` — both moved. |
| engine_charters.md | 29,586 | Formal authority boundaries for all 6 engines. | moved here from `docs/Audit/`. Now in canonical location. |
| execution_manual.md | 13,244 | Every CLI command in one place. | OK |
| files.md | 4,874 | Directory-map quick reference. | line 70 still describes `docs/Audit/` as a folder; that folder no longer exists. |
| roles.md | 6,467 | Seven cognitive lenses. | OK |
| simple_engine_roles.md | 6,247 | "Hedge fund room" plain-English engine metaphor. | moved here from `docs/Audit/`. |

## docs/Core/Audit/
| File | Size | Purpose | Match |
|---|---:|---|---|
| README.md | 2,201 | Folder-purpose doc — original `docs/Audit/` README, byte-for-byte. | **content–location mismatch.** Title still says "docs/Audit/ — Technical Deep-Dives & Engine Design"; the reading-order table lists `outside-opinion.md`, `codebase_findings.md`, `engine_charters.md`, `simple_engine_roles.md` as siblings — none are in this directory. `engine_charters.md` and `simple_engine_roles.md` are in `docs/Core/`; the other two are in `docs/Archive/Audit/`. Subfolders `Mini-projects/` and `Previous_Audits/` are also referenced — those are in `docs/Archive/Audit/`, not here. Sits next to `check.md` which appears to be the intended replacement. |
| check.md | 1,775 | Describes this folder as code-health tracking; lists `health_check.md` + `high_level-engine_function.md` as the two members. | matches the actual folder contents. Looks like a draft README that should replace the stale `README.md` next to it. |
| health_check.md | 2,606 | Living code-health tracker; currently no findings. | OK |
| high_level-engine_function.md | 18,272 | What each engine actually does today. | moved here from `docs/Audit/`. |

## docs/Core/Human/
| File | Size | Purpose | Match |
|---|---:|---|---|
| human-docs-explanation.md | 6,467 | Plain-English doc-system explanation. | OK |
| human-system_explanation.md | 1,904 | Plain-English project description. | OK |

## docs/Core/Ideas_Pipeline/
| File | Size | Purpose | Match |
|---|---:|---|---|
| autonomous_lifecycle_plan.md | 15,843 | Multi-phase plan for the autonomous edge-lifecycle work. | OK |
| human.md | 8,978 | User-facing inbox + processed archive for raw ideas. | OK |
| idea_evaluations.md | 4,104 | Stage-2 evaluations w/ cognitive-lens analysis. | OK |
| ideas_backlog.md | 3,858 | Stage-1 categorized backlog with tracking IDs. | OK |

## docs/Progress_Summaries/
| File | Size | Purpose | Match |
|---|---:|---|---|
| 11-9.txt | 13,369 | Old session log (Nov 9). | byte-identical duplicate at `docs/Archive/*Progress_summaries/11-9.txt`. |
| 11-12.txt | 5,059 | Old session log (Nov 12). | duplicate at `docs/Archive/*Progress_summaries/11-12.txt`. |
| _template.md | 1,718 | Session-summary template. | new. |
| lessons_learned.md | 76,876 | Cross-session lessons. | OK |

## docs/Sources/ (research PDFs and reviews)
| File | Size | Purpose | Match |
|---|---:|---|---|
| .DS_Store | 6,148 | macOS noise. | n/a |
| Alpha/Finding-Alpha-in-an-Increasingly-Concentrated-us-market.pdf | 265,510 | Research PDF. | OK |
| Regime_Detection/2019-Mayo-Zhu_Nam.pdf | 751,767 | PDF. | OK |
| Regime_Detection/212236006---James-Mc-Greevy---MCGREEVY_JAMES_01075416.pdf | 9,646,707 | Thesis PDF (largest file in tree). | OK |
| Regime_Detection/HMM_Presentation_Final_Martin.pdf | 1,142,211 | PDF. | OK |
| Regime_Detection/Machine-Learning-Approach-to-Regime-Modeling_.pdf | 3,875,111 | PDF. | OK |
| Regime_Detection/1-s2.0-S0167637722000311-am.pdf | 549,924 | PDF. | OK |
| Regime_Detection/966100a067.pdf | 355,205 | PDF. | OK |
| Regime_Detection/content.pdf | 1,120,241 | PDF. | generic filename — content not identifiable from name. |
| Regime_Detection/decoding-market-regimes-with-machine-learning.pdf | 362,826 | PDF. | OK |
| Technical_Indicators/PubSub10294_702a_McGinnity.pdf | 1,911,549 | PDF. | OK |
| Technical_Indicators/Z05120207212.pdf | 320,135 | PDF. | opaque filename. |
| Unsure/bensdorp_combining_strategies_review.md | 9,721 | Markdown review. | byte-identical duplicate at `docs/Archive/Other/credits/bensdorp_combining_strategies_review.md`. |
| Unsure/parrondo_rebalancing_review.md | 8,020 | Markdown review. | duplicate at `docs/Archive/Other/credits/parrondo_rebalancing_review.md`. |
| Unsure/paradoxofdiversification.pdf | 109,622 | PDF. | OK |

## docs/Archive/ (gitignored — invisible to git)

Tree at depth 2: `Audit/`, `Master+Roadmap/`, `Other/`, `specs/`, `*Master_prompts*/`, `*Progress_summaries/`. Nine of the 16 deleted `docs/Audit/*` files now live under `docs/Archive/Audit/` — sizes already listed in Report 1 §1. Other contents (chat transcripts, old roadmaps, master-context files, archived all.txt at 1,164,811 B) predate this change. Two `.DS_Store` noise files inside (`docs/Archive/Audit/.DS_Store`, `docs/Archive/*Master_prompts*` subtree, etc.) — harmless, gitignored. **Empty file: `docs/Archive/Audit/Mini-projects/keykey.md` (0 B)** and **`docs/Archive/*Master_prompts*/Core_files/reminders.txt` (0 B)** — both are pre-existing zero-byte files that traveled into Archive.

## .claude/
| File | Size | Purpose | Match |
|---|---:|---|---|
| settings.json | 1,880 | Project hooks: SessionStart (header + summaries + git log + health-check grep), Stop (reminder text), PostToolUse on Edit\|Write → `scripts/sync_docs.py` for `engines/*.py`. | **broken path** — SessionStart hook greps `docs/Audit/health_check.md`; file is at `docs/Core/Audit/health_check.md`. The `=== HEALTH CHECK STATE ===` block in this session's startup banner came back empty for that reason. |
| settings.local.json | 16,184 | User-local settings; gitignored. | OK |
| scheduled_tasks.lock | 130 | Runtime lock; gitignored. | OK |
| agents/agent-architect.md | 4,903 | Subagent maintainer. | OK |
| agents/architect.md | 1,886 | Read-only system auditor. | OK |
| agents/code-health.md | 2,360 | Tech-debt scanner. | OK |
| agents/edge-analyst.md | 1,804 | Engine A quant lens. | OK |
| agents/engine-auditor.md | 2,035 | Charter-vs-implementation drift checker. | OK |
| agents/ml-architect.md | 1,923 | ML / external-data integration. | OK |
| agents/quant-dev.md | 1,594 | Latency / infra / data pipelines. | OK |
| agents/regime-analyst.md | 1,943 | Engines E + F lens. | OK |
| agents/risk-ops-manager.md | 2,144 | Engine B + live_trader (propose-first). | OK |
| agents/ux-engineer.md | 1,806 | dashboard_v2-only UX lens. | OK |

---

## Summary of mismatches and orphan candidates

**Stale path references (`docs/Audit/...` → file no longer there):**

1. `CLAUDE.md:52` — `docs/Audit/health_check.md`
2. `CLAUDE.md:112` — `docs/Audit/health_check.md`
3. `docs/Core/SESSION_PROCEDURES.md` Path 2 — `docs/Audit/health_check.md`
4. `docs/Core/README.md:22` — `docs/Audit/simple_engine_roles.md`
5. `docs/Core/README.md:23` — `docs/Audit/engine_charters.md`
6. `docs/Core/README.md:24` — `docs/Audit/high_level-engine_function.md`
7. `docs/Core/README.md:25` — `docs/Audit/codebase_findings.md`
8. `docs/Core/README.md:91-92` — `docs/Audit/` folder + `docs/Audit/engine_charters.md`
9. `docs/Core/agent_instructions.md:12` — `docs/Audit/engine_charters.md` and `docs/Audit/high_level-engine_function.md`
10. `docs/Core/files.md:70` — `docs/Audit/` folder
11. `.claude/settings.json` SessionStart hook — `docs/Audit/health_check.md`
12. `docs/Core/Audit/README.md` (whole file) — describes a folder layout that no longer matches its location

**Empty / near-empty files:**

- `docs/agent_onboarding_prompt.md` (166 B) — likely orphaned by the new CLAUDE.md / SESSION_PROCEDURES flow.
- `docs/Archive/Audit/Mini-projects/keykey.md` (0 B) — pre-existing empty file.
- `docs/Archive/*Master_prompts*/Core_files/reminders.txt` (0 B) — pre-existing.

**Apparent duplicate of intent (not file content) inside docs/Core/Audit/:**

- `README.md` and `check.md` both try to describe the folder; `README.md` is stale, `check.md` matches reality. Looks like one was meant to replace the other.

**Folder duplication:**

- `docs/Progress_Summaries/11-9.txt` and `docs/Progress_Summaries/11-12.txt` are byte-duplicated under `docs/Archive/*Progress_summaries/`.
- `docs/Sources/Unsure/{parrondo,bensdorp}_*.md` are byte-duplicated under `docs/Archive/Other/credits/`.
