# Operational Pattern Audit

Generated: 2026-05-06T23:33:02

Captures the dev's 2026-05-09 meta-finding: the audit framework caught substrate bias (F6) but not operational pattern. This audit asks _'are decisions being made on autonomous output vs human curation, and is parameter freezing in effect?'_

## Edge-curation pattern
- Total edges in registry: **283**
- Active edges: **9**
- Active edges from autonomous discovery: **0 (0.0%)**
  - **FLAG: < 10% of active edges came from autonomous discovery.** The dev's hand-tuning critique applies. Engine D's Discovery cycle is operating as a watchdog rather than an originator.
- Active edges with `origin` field set: 0 of 9

### Status breakdown

| Status | Count |
|---|---:|
| failed | 144 |
| candidate | 57 |
| archived | 33 |
| error | 20 |
| paused | 14 |
| active | 9 |
| retired | 6 |

## F8 OOS lock status
- **OOS lock INACTIVE.** No parameter freezing in effect.
  - **FLAG: tuning scripts run unrestricted.** Per F8 + the 2026-05-09 lessons entry, every load-bearing parameter is at risk of being silently retuned on the OOS window.

## Engine D autonomous-discovery activity
- Most recent lifecycle event: 2025-12-31T00:00:00+00:00
- Total promote events ever: 0
- Lifecycle events last 90 days: 0
  - **FLAG: Discovery cycle has never promoted an edge.** Confirms the 2026-05-09 finding that the autonomous discovery machinery exists but doesn't produce. C-engines-4 (Bayesian opt) is the queued closure.

## MetaLearner status
- **MetaLearner DISABLED in production.** Memory `project_metalearner_drift_falsified_2026_05_01` documents the decision. Autonomous tuning capability remains parked.

## Recent parameter-sweep activity (best-effort)
- Found 4 sweep-related docs.
- Most recent (up to 20):
  - `docs/Measurements/2026-04/cap_bracket_sweep_2026_04.md`
  - `docs/Measurements/2026-05/path2_adv_floors_2026_05.md`
  - `docs/Measurements/2026-05/path2_adv_floors_under_new_gauntlet_2026_05.md`
  - `docs/Measurements/2026-05/vqa_edges_sustained_scores_2026_05_07.md`
