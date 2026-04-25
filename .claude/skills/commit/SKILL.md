---
name: commit
description: Stage and commit current changes with a properly-formatted message. Use when the user says "commit this", "let's commit", "save progress", or when a logical unit of work completes and SESSION_PROCEDURES indicates a commit point. Also use proactively after finishing any substantive change if uncommitted work is accumulating.
allowed-tools: Bash(git add *) Bash(git commit *) Bash(git status *) Bash(git diff *) Bash(git log *)
---

## Before committing

1. Run `git status` to see what's changed
2. Run `git diff --staged` (or `git diff` if nothing staged) and 
   verify:
   - No secrets (`APCA_*`, API keys, tokens, passwords)
   - No large data files (anything in `data/`, `.parquet`, `.csv` 
     with runtime output)
   - No `.env` files
   - No editor cruft (`.DS_Store`, `*.swp`, etc.)
3. If anything above appears staged, unstage it and note why in 
   the commit message context

## Commit message format

Use this format:

```
<type>: <short summary under 60 chars>

<optional body explaining WHY, not what — the diff shows what>

<optional footer: related issue, breaking change notice, etc.>
```

Types:
- `feat` — new capability
- `fix` — bug fix
- `refactor` — structural change, no behavior change
- `docs` — documentation only
- `test` — tests only
- `chore` — tooling, deps, config
- `archive` — moving code/docs to Archive/
- `wip` — work in progress (use sparingly, squash before merging)

Include the engine or subsystem in the summary when relevant:
- `feat(engine-d): add PBO validation gate`
- `fix(risk): stop-loss not firing on overnight gaps`
- `refactor(alpha): extract SignalCollector from god class`
- `docs: update execution_manual with new --discover flag`

## What makes a good message

The summary answers "what changed?" The body answers "why?" 
Future-you reading the log in six months needs both. Avoid:
- "update code"
- "fix bug"
- "changes"
- "WIP"
- Any message where someone reading just the log couldn't tell 
  what happened

## Atomic commits

One logical change per commit. If the diff spans unrelated work 
(e.g., an Engine A fix and a docs update), split it:

```bash
git add engines/engine_a_alpha/
git commit -m "fix(alpha): ..."
git add docs/
git commit -m "docs: ..."
```

## After committing

Run `git log --oneline -5` to confirm the commit landed. If this 
completes a roadmap item, update `ROADMAP.md` in a follow-up 
commit (`chore: mark phase X.Y complete`).

## What NOT to do

- Never `git commit --amend` to a commit that's been pushed
- Never combine unrelated changes into one commit "for speed"
- Never commit with `-m "WIP"` and move on — if it's WIP, branch it
- Never commit during an incomplete refactor. If the codebase is 
  broken (tests failing, imports missing), either finish the 
  refactor or branch it off main first