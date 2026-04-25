# Code Health Tracker

Living document tracking the current quality state of the codebase. 
Maintained by the `engine-auditor` and `code-health` subagents — they 
append findings as they discover them. Resolved items move to the 
"Resolved" section with a date.

This is the source of truth for SESSION_PROCEDURES.md Path 2 
("Critical findings"). When the user asks what's next, this file is 
checked before the roadmap.

If this file appears empty or stale, run the engine-auditor against 
recently-touched engines or the code-health subagent across the 
codebase to populate it.

---

## Active Issues

Findings are listed in priority order: HIGH first, then MEDIUM, 
then LOW. Within each severity, list newest at the top.

### HIGH

*No active HIGH-severity findings.*

### MEDIUM

*No active MEDIUM-severity findings.*

### LOW

*No active LOW-severity findings.*

---

## Resolved (last 90 days)

*No resolved findings yet.*

---

## Archived (older than 90 days)

When resolved items pass 90 days, move them here. Keep this section 
trimmed — if it grows beyond ~50 items, archive the oldest to 
`docs/Archive/audits/health_check_resolved_<year>.md`.

*No archived findings yet.*

---

## Severity guide

- **HIGH**: Actively breaks things or causes silent harm. Examples: 
  broken imports still being called, deprecated paths in active use, 
  bugs that produce wrong outputs, code that bypasses charter 
  boundaries in ways that affect runtime behavior.
- **MEDIUM**: Structural debt that doesn't break the system today 
  but compounds. Examples: god classes (>500 lines), duplicate 
  implementations, oversized functions (>200 lines), missing test 
  coverage on critical paths, charter drift that hasn't yet caused 
  visible problems.
- **LOW**: Hygiene issues. Examples: stale TODOs (>90 days), unused 
  imports, empty test stubs, formatting inconsistencies, outdated 
  comments.

## Format

Findings appended by subagents follow one of two formats:

**From engine-auditor:**
```
### [SEVERITY] <one-line summary>
- Engine: <A/B/C/D/E/F>
- First flagged: <YYYY-MM-DD>
- Status: not started
- Description: <what's wrong>
- Charter reference: <quote or section from engine_charters.md>
- Recommended next step: <specific action>
```

**From code-health:**
```
### [SEVERITY] <one-line summary>
- Category: <duplicate/god-class/dead-code/stale-todo/other>
- Files: <path(s)>
- First flagged: <YYYY-MM-DD>
- Status: not started
- Recommended next step: <specific action>
```

When a finding is resolved, move the entry to the Resolved section 
and add a `- Resolved: <YYYY-MM-DD>` line.