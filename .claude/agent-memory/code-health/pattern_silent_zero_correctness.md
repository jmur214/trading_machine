---
name: Silent-zero correctness pattern in fundamentals factor edges
description: When edges compute denominators from financial-statement items that can be negative or zero (equity, invested capital), the code tends to silently substitute 0 instead of dropping the ticker — distressed firms then score as top-quintile in the wrong direction. Different files in the same package handle this inconsistently; one file may explicitly drop while a neighbor zero-substitutes.
type: project
---

Confirmed instance 2026-05-06:

- `engines/engine_a_alpha/edges/quality_roic_edge.py:87-88` silently zeros
  negative equity in the ROIC denominator: `(equity if equity > 0 else 0.0) +
  (lt_debt if lt_debt > 0 else 0.0)`. A negative-equity firm with any LT debt
  scores `NOPAT / lt_debt` — small denominator, huge ROIC, top-quintile
  selection.
- `engines/engine_a_alpha/edges/value_book_to_market_edge.py:76-78` (same
  package, same edge cohort, four files away) explicitly drops negative-equity
  firms with `if equity <= 0 or shares <= 0: return None` and a comment
  "Negative-equity firms produce misleading signs for B/P".
- `scripts/path_c_synthetic_compounder.py:663-664` duplicates the same
  silent-zero in the Path C real-fundamentals composite — same author or
  same copy-paste origin as the ROIC edge.

**Why this is a recurring shape:**
- Authors writing fundamentals edges tend to think defensively about *missing*
  data (None / NaN) but not about *legitimate-but-pathological* values
  (negative equity, zero assets). The defensive pattern they default to is
  "if x is None or x <= 0: substitute 0", which is wrong for denominator
  components.
- The new factor cohort lands as 6 files at once, copy-edited from a
  template. If the template has the bug, all 6 do — but reviewers see
  individual diffs, not the pattern.

**How to apply:** When auditing newly-added factor edges:

1. Identify every denominator computation. Trace each contributing variable
   through its missing-data and negative-value handling.
2. Compare two random files in the cohort that share a denominator type
   (equity, assets). If they handle the same nullability question
   differently, one of them is wrong — look up the academic factor's
   convention to determine which.
3. The 109-ticker prod universe is mostly mature mega-caps with positive
   equity, so this class of bug doesn't bite on the smoke test. It only
   surfaces on universe expansion (Workstream H) or when a healthy mega-cap
   incurs a one-quarter equity dip.

**Related shape:** This is structurally identical to the wash-sale gate's
turnover bug (memory `project_wash_sale_exposes_turnover_bug_2026_05_02`):
the gate doesn't have a bug, but exposes a precondition the rest of the
system silently violated. ROIC's "use negative equity as 0" is the same
class — a silent precondition violation that only surfaces on the right
universe slice.
