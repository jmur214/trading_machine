# Moonshot Sleeve — Scoping Document

**Status:** propose-first scoping. Capture every design decision before any code lands. User approves option per row; this doc gets rewritten as an actionable dispatch once all decisions land.

**Trigger:** R2 (no-code-access auditor) flagged that the current "Moonshot Sleeve" framing is small/mid-cap factor exposure dressed in moonshot language, not asymmetric upside. Synthesis-by-primary-dev pushed this hardest. R2's reframe shifts the candidate set materially.

**Context:** The user is 20-something with 40+ year horizon. Goal C (asymmetric upside) might be where most terminal wealth lives. The sleeve is **architecturally independent** of the core — different universe, different gauntlet, different sizing, different objective function. It does NOT depend on substrate-honest core working.

---

## Decision 1 — Universe

| Option | What it is | Pros | Cons |
|---|---|---|---|
| **(a)** | **Russell 2000 + recent IPOs + theme-tagged equities** (the original forward_plan framing) | Large universe, well-understood data sources, clean fit for momentum/breakout edges | R2's critique: this is small-cap factor exposure, not asymmetric. Premiums are real but flat-skew. Heavily traded. |
| **(b)** | **LEAPS-eligible names with binary catalysts** (FDA decisions, federal contract awards, M&A speculation, biotech readouts) | Convexity is structural — calls have positive skew by definition. Binary catalysts produce the asymmetry directly. | Smaller name pool. Requires options data (Schwab integration helps). Higher per-name research cost. |
| **(c)** | **Special situations** (spinoffs, post-bankruptcy equity, busted convertibles, complex sum-of-parts mispricings) | Greenblatt's playbook — empirically retail-tractable for 30+ years. Complexity creates analyst neglect at small-cap level. Inefficient by construction. | Idiosyncratic data needs (corporate actions, capital structure). Lower trade frequency. Requires fundamental research per name. |
| **(d)** | **Concentrated thematic exposure** (paradigm-shift names where you can defend a thesis — your existing PLTR/RKLB/photonics-style work formalized) | Builds on what the user is already doing well discretionarily. Captures large-magnitude moves. | Hard to systematize; risk of confirmation bias; concentration risk. |
| **(e)** | **Mixed: (b) + (c) for systematic; (d) layered as discretionary overlay** | Captures asymmetric structure (LEAPS), academic edge (special-sit), AND user's discretionary skill | Higher implementation complexity. Three sub-systems. |

**Recommendation:** (e) — start with (b) + (c) as the systematic core; (d) layered as an opt-in discretionary overlay. R2's specific point: long-momentum on R2K is well-arbed factor exposure that doesn't deliver the asymmetry the sleeve is designed for. Skipping (a) entirely is the right call.

**User decision:** (a) / (b) / (c) / (d) / (e) / other? ___

---

## Decision 2 — Edge candidates (conditional on Decision 1)

If (e) chosen, edges to develop in priority order:

### Phase 1 (this quarter)
1. **`leaps_catalyst_edge_v1`** — long-dated 25-delta calls on names with quantifiable upcoming catalysts. Gate: catalyst date within 18 months; calls priced at <X% of underlying; thesis defensibility documented per-name.
2. **`spinoff_edge_v1`** — equity in newly-spun-off entities (post-distribution holding window). Greenblatt's mechanism: institutional holders dump small spinoff shares to clean their book; mispricing exists for 6-18 months.
3. **`post_bankruptcy_equity_edge_v1`** — equity issued post-Chapter-11 emergence. Mechanism: pre-bankruptcy equity holders frequently extinguished → new equity holders are the recapitalized set; analyst coverage starts from zero.

### Phase 2 (next quarter, if Phase 1 produces signal)
4. **`busted_convert_edge_v1`** — convertible bonds trading at deep discount to their fixed-income value (busted because the conversion option is far out of money). Mechanism: dual-mandate of bondholders + equity-conversion-option holders creates structural mispricing.
5. **`sum_of_parts_edge_v1`** — multi-segment companies trading below sum of segment fair values (segment data from segment reporting in 10-Ks).
6. **(d-style discretionary)** — formal scaffold for user-thesis-driven concentrated bets. Manual entry; gauntlet doesn't validate; tracked separately for measurement.

**User decision:** approve Phase 1 list / modify / skip a candidate / add a candidate ___

---

## Decision 3 — Objective function

The core book uses Sharpe (and now PSR) as primary. The Moonshot sleeve should NOT use Sharpe — Sharpe penalizes the upside skew you're trying to capture.

| Option | Objective |
|---|---|
| **(a)** | Sortino ratio (penalizes only downside vol) |
| **(b)** | Sortino + skewness (rewards positive skew explicitly) |
| **(c)** | Sortino + skewness + tail ratio (top 5% / bottom 5%) — adds upside-vs-downside magnitude |
| **(d)** | Sortino + skewness + tail ratio + upside capture (during-up-period return / SPY-during-up-period return) |
| **(e)** | Custom: weighted sum of (a)-(d) components |

**Recommendation:** (d). Sortino captures downside discipline; skewness rewards asymmetry; tail ratio rewards magnitude of upside vs downside; upside capture rewards "you actually catch the bull" rather than "you avoid the bear." The four together pin down the asymmetric-upside promise concretely.

**User decision:** (a) / (b) / (c) / (d) / (e) ___

---

## Decision 4 — Sizing

Asymmetric sizing means many small bets, with structural caps that protect against any single bet ruining the sleeve.

| Parameter | Recommended default | Alternatives |
|---|---|---|
| Per-bet size | 1-2% of sleeve capital | (0.5% / 2% / 3%) |
| Max concurrent positions | 30-50 | (20 / 100 / unlimited) |
| Trailing stop | 50% from peak | (30% / 70% / no stop) |
| Time stop | 24 months for LEAPS-style; 36 months for special-sit | (varies by edge) |
| Position concentration cap | No single name >5% of sleeve | (3% / 7%) |
| Concentration cap by sector | No single sector >25% of sleeve | (15% / 35%) |

**Recommendation:** the defaults above. Many small bets, tight per-name cap, trail wide enough to let winners compound (50% from peak loses 50% of an unrealized gain but lets you keep 5x and 10x runners through normal volatility).

**User decision:** approve defaults / modify specific values ___

---

## Decision 5 — Capital allocation

| Option | Sleeve weight | Rationale |
|---|---|---|
| **(a)** | 10% of total system capital | Conservative — sleeve is novel + speculative |
| **(b)** | 15-20% (existing forward_plan default) | Material exposure but not dominant |
| **(c)** | 25-30% | Aggressive — reflects "Goal C is where terminal wealth lives" framing |
| **(d)** | Dynamic — start at 10%, scale to 25% if Phase 1 produces 12-month positive Sortino + cleared gauntlet |

**Recommendation:** (d). Dynamic allocation respects discipline framework: scale exposure with evidence. Start small, prove out, scale up. Treats the sleeve as an experiment-with-graduation, not a commitment.

**User decision:** (a) / (b) / (c) / (d) / other ___

---

## Decision 6 — Architectural placement

The system has sleeve scaffolding at `engines/engine_c_portfolio/sleeves/sleeve_base.py:80` (per R1's audit, currently abstract design artifact).

| Option | Where Moonshot lives |
|---|---|
| **(a)** | New top-level engine (`engines/engine_g_moonshot/`) — clean separation but adds 7th engine |
| **(b)** | First concrete sleeve in `engines/engine_c_portfolio/sleeves/` per existing scaffolding | Charter-clean — sleeves were designed for exactly this |
| **(c)** | Outside engines tree (e.g., `sleeves/moonshot/`) — most independence; but loses Engine C's composition logic |

**Recommendation:** (b). The sleeve scaffolding exists for this purpose. Forcing the first real sleeve to use it validates the architectural pattern. If the trend-following sleeve also lands here, the sleeve aggregator naturally evolves.

**User decision:** (a) / (b) / (c) ___

---

## Decision 7 — Success / kill criteria

The discipline framework requires pre-committed criteria, not goalpost-moving after results land.

**Recommended success criteria** (Phase 1, end of quarter 1 of Moonshot work):
- 3+ edges from list above shipped + validated through their own gauntlet
- Sleeve-level 12-month measured Sortino > 1.5
- Sleeve-level 12-month skewness > 0.5
- At least 1 ≥3x bet realized (proves the "catch the moonshot" thesis)
- DSR > 0.80 on sleeve-level Sortino (statistical significance)

**Recommended kill criteria:**
- Sleeve-level 12-month Sortino < 0.3
- 12-month max drawdown > 35% of sleeve capital
- Skewness flat or negative (means the sleeve is actually short-volatility wrapped in moonshot framing — same anti-pattern R2 critiqued)
- Per-bet success rate < 25% AND average winning bet < 2x (means we're losing on a hit-rate that doesn't compensate)

**User decision:** approve / modify thresholds ___

---

## Implementation timeline (post all decisions approved)

| Phase | Effort | Output |
|---|---|---|
| Scoping (this doc → approved) | 1-2 hr discussion | Approved scoping; rewritten as actionable dispatch |
| Sleeve scaffolding ship | 4-8 hr | Concrete `MoonshotSleeve(SleeveBase)` class, sleeve aggregator, capital allocation logic, separate gauntlet driver |
| Edge 1 (`leaps_catalyst_edge_v1`) | 1-2 weeks | Edge code, gauntlet pass on the new objective function, measurement doc |
| Edge 2 (`spinoff_edge_v1`) | 1-2 weeks | Same |
| Edge 3 (`post_bankruptcy_equity_edge_v1`) | 1-2 weeks | Same |
| Phase 1 review at end of quarter | — | Decision: scale to Phase 2 vs kill vs extend |

**This is a quarter-long workstream**, not a week's work. The scoping doc is the gate; once approved, work proceeds autonomously by week-scale dispatches.

---

## Open questions for the user

1. **Decisions 1-7 above — any divergence from recommendations?**
2. **Schwab API integration** for OPRA options data — is that on the critical path for `leaps_catalyst_edge_v1`? Yes/no determines whether Phase 1 starts now or after Schwab unblock.
3. **Discretionary overlay** (option d) — is this a priority for you, or pure systematic for Phase 1?
4. **Run timing** — does Phase 1 begin now (parallel to engine completion) or after C-remeasure?
