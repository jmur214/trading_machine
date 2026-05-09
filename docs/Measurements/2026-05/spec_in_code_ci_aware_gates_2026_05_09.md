# Spec — T-2026-05-08-010: Make in-code Sharpe gates CI-aware

**Date drafted:** 2026-05-09
**Status:** SPEC for approval. Director-side review required (touches Engine F).
**Will be executed by:** Agent A or B once T-002 + T-013 complete.
**Output:** Modified gate sites + new tests + audit doc at `docs/Audit/in_code_ci_aware_gates_2026_05_09.md`.

---

## Why now

The CLAUDE.md 6th non-negotiable (added 2026-05-08, commit `4cf4909`) declares:

> Sharpe headlines must report bootstrap CI; kill thresholds must be CI-aware, not point-estimate. ... Kill thresholds and gating decisions follow the same rule: compare against `ci_low`, not `point_estimate`.

That rule was promoted to handle the *humans-quoting-Sharpe-in-docs* case. But the system has live in-code gates that still use point-estimate Sharpe comparisons. As long as those exist, autonomous lifecycle/promotion decisions can implicitly goalpost-move when a noisy Sharpe straddles a threshold — exactly what the rule was meant to prevent.

Surveyed 2026-05-08 (director side). Four candidate sites:

| File | Line | Current gate | Why CI-aware matters |
|---|---|---|---|
| `engines/engine_f_governance/evolution_controller.py` | 182 | `passed = oos_sharpe >= bench_threshold and degradation > 0.6` | Discovery promotion gate. A noisy candidate with point-Sharpe == bench produces unstable promotions. |
| `engines/engine_f_governance/lifecycle_manager.py` | 66 | `retirement_margin: float = 0.3  # edge_sharpe must be <= benchmark_sharpe - 0.3 to retire` | Edge retirement. Same risk: noise makes retirement chatter. |
| `engines/engine_d_discovery/wfo.py` | 184 | `"degradation": oos_sharpe / avg_is_sharpe if avg_is_sharpe > 0 else 0` | Ratio, not threshold — but read DOWNSTREAM as a threshold. CI-aware reading would be `ci_low(oos)/ci_low(is)` or equivalent. |
| `engines/engine_d_discovery/robustness.py` | 311, 376 | `survival_rate = (sharpes > 0.0).mean()` | **Exempt.** Already distributional (PBO over 50 bootstrap paths). The "survival rate > 0.7" gate is itself a CI-style statement; making it CI-aware is double-counting. Document the exemption. |

---

## What

Three additive changes, plus one explicit exemption.

### Change 1: `evolution_controller.py:182` — promotion gate uses `ci_low`

Replace:
```python
passed = oos_sharpe >= bench_threshold and degradation > 0.6
```

With:
```python
oos_ci_low = MetricsEngine.bootstrap_distribution(
    oos_returns, MetricsEngine.sharpe_ratio
)["ci_low"]
passed = oos_ci_low >= bench_threshold and degradation > 0.6
```

Where `oos_returns` is the per-day returns series of the OOS window (must be plumbed from the WFO output that already produces `oos_sharpe`).

### Change 2: `lifecycle_manager.py:66` — retirement margin uses `ci_low`

The current logic (paraphrased):
```python
retire = edge_sharpe <= benchmark_sharpe - retirement_margin
```

Replace with:
```python
edge_ci_low = MetricsEngine.bootstrap_distribution(
    edge_returns, MetricsEngine.sharpe_ratio
)["ci_low"]
retire = edge_ci_low <= benchmark_sharpe - retirement_margin
```

Note the asymmetry: `edge_ci_low` is the variable (CI-aware), `benchmark_sharpe` stays point-estimate (it's a fixed reference, the SPY/comparable). This is intentional — bootstrapping a fixed benchmark wastes compute.

### Change 3: `wfo.py:184` — degradation ratio reports CI-aware

Replace:
```python
"degradation": oos_sharpe / avg_is_sharpe if avg_is_sharpe > 0 else 0
```

With (preserving the existing point-estimate ratio AND adding the CI-aware variant):
```python
oos_ci_low = MetricsEngine.bootstrap_distribution(oos_returns, MetricsEngine.sharpe_ratio)["ci_low"]
is_ci_low  = MetricsEngine.bootstrap_distribution(is_returns,  MetricsEngine.sharpe_ratio)["ci_low"]
result["degradation"]        = oos_sharpe / avg_is_sharpe if avg_is_sharpe > 0 else 0
result["degradation_ci_low"] = (oos_ci_low / is_ci_low) if is_ci_low > 0 else 0
```

Then update the Discovery downstream consumers in `evolution_controller.py` to read `degradation_ci_low` for the promotion decision (replacing the use of `degradation`).

### Exemption: `robustness.py` PBO survival

Document explicitly that PBO survival is exempt — it's already a distributional gate over 50 bootstrap paths. Leave the existing `(sharpes > 0.0).mean() > 0.7` test untouched. Add a comment block above it explaining the exemption.

---

## Why these specific sites and not others

The director's grep landed 18 hits across `engines/` and `core/` for `sharpe.*>` / `sharpe.*<` / etc. patterns. Most are read-side / display-side, not gate-side. The four above are the ONLY sites where a Sharpe comparison directly drives an autonomous lifecycle decision. Read-side display sites (e.g., per-edge breakdown tables in audit docs) are downstream of the gate and don't need CI-aware reading at the comparison level — they just need their reported Sharpe to be paired with a CI.

---

## Plumbing required

The change is straightforward at each gate site IF the per-period returns series is reachable. Survey of plumbing complexity per site:

- **evolution_controller.py:182**: WFO already produces `oos_sharpe`, must surface `oos_returns` (per-day pd.Series). Inspect `wfo.py` output dict; if `oos_returns` not already there, add it. Estimated 30 min.
- **lifecycle_manager.py:66**: edge-level rolling Sharpe is computed from a returns series that's already in scope (the `_get_edge_recent_returns()` helper or equivalent). Reachable. Estimated 15 min.
- **wfo.py:184**: `is_returns` and `oos_returns` are computed inside the function already. Estimated 10 min.

Total plumbing: ~1 hr. Total spec scope: ~3-5 hr including tests + audit doc.

---

## Acceptance

1. **Code changes** at the three sites above. Each change must:
   - Continue to use `MetricsEngine.bootstrap_distribution` (the project standard, Künsch 1989 block-bootstrap, default 1000 iter, auto block length per Politis-White).
   - Apply CI-aware reading to the variable being gated, leave fixed references (benchmark_sharpe) as point-estimate.
   - Preserve the existing point-estimate fields in any downstream-consumed dict (don't break call sites that read `oos_sharpe`); add the new `*_ci_low` fields alongside.

2. **Determinism guard:** the determinism harness must produce a canon md5 IDENTICAL to a clean main checkout when run on the same input. **Bootstrap inside Discovery introduces randomness, but `MetricsEngine.bootstrap_distribution` is seeded (`seed=0` default) — it should remain deterministic.** Verify this; if md5 drifts, audit the seed plumbing.

3. **Tests:** new file `tests/test_in_code_ci_aware_gates.py` with at minimum:
   - `test_evolution_controller_uses_ci_low` — synthesize a candidate where point Sharpe ≥ bench but ci_low < bench; assert NOT promoted (would have passed under old gate).
   - `test_evolution_controller_promotes_clean_signal` — synthesize a candidate where ci_low ≥ bench; assert promoted.
   - `test_lifecycle_manager_uses_ci_low` — synthesize an edge where point Sharpe is below the retirement threshold but ci_low is comfortably above; assert NOT retired.
   - `test_lifecycle_manager_retires_clearly_dead_edge` — synthesize an edge where ci_low ≤ benchmark - 0.3; assert retired.
   - `test_wfo_emits_degradation_ci_low` — assert the new field is present in the WFO output dict.
   - `test_pbo_exemption_documented` — sanity that the comment-block exemption is in place at `robustness.py:311` (regex match against the source).

4. **Existing tests:** all relevant Engine F + Engine D tests still pass. Particularly `test_evolution_controller*`, `test_lifecycle_manager*`, `test_wfo*`, `test_robustness*`.

5. **Audit doc:** `docs/Audit/in_code_ci_aware_gates_2026_05_09.md` covering:
   - Which sites changed, which exempted, why
   - Before/after behavior on a representative test fixture: how often does CI-aware reading flip a borderline decision?
   - Determinism evidence (canon md5 from harness, before vs after change — must match)
   - Forward-looking note: which DOWNSTREAM gates also exist that consume these (e.g., journal-and-apply at `scripts/journal_apply.py`)? Are they CI-aware too, or do they need a follow-up?

6. **Branch:** `feature/in-code-ci-aware-gates`. Push only; director merges. **Engine F change requires director-side review** per CLAUDE.md non-negotiable; do not merge to main yourself.

---

## Hard constraints

- DO NOT modify Engine B (Risk) or `live_trader/` — out of scope; Engine B's drawdown kill-switch is a separate gate handled by T-012.
- DO NOT change the bootstrap parameters from project standard (1000 iter, auto block length). If a site genuinely needs different parameters, document and propose, don't quietly change.
- DO NOT modify the *value* of the existing thresholds (e.g., 0.6 degradation, 0.3 retirement margin). Those were tuned at the point-estimate level; whether they're correctly tuned for ci_low reading is a Phase 2 question. This task is mechanical CI-aware substitution at the same threshold values — interpretation review can come later.
- DO NOT touch `core/metrics_engine.py` itself unless a bug is found in `bootstrap_distribution`.
- Branch: `feature/in-code-ci-aware-gates`; do NOT merge to main.

---

## Time budget

3-5 hr total: ~1 hr plumbing + ~1 hr code + ~1 hr tests + ~1 hr audit doc + buffer for debugging the determinism md5 invariance.

---

## Open questions for the agent (surface in the audit doc, not block)

1. **Block length tuning.** The project default Politis-White rule of thumb (`max(5, int(round(n ** (1/3))))`) is reasonable for daily-return series of 60-200 days. For very short OOS windows (e.g., a 21-day OOS slice from WFO), the block length defaults to 5, leaving very few effectively-independent blocks. Document any window where this becomes a concern.

2. **Bootstrap CI vs deflated Sharpe ratio (DSR).** Discovery already implements DSR at Gate 8 (`validate_candidate`, `engines/engine_d_discovery/discovery.py`). DSR penalizes for selection bias / multiple-testing. The promotion gate at `evolution_controller.py:182` is a SEPARATE check (post-DSR). Document the relationship and whether DSR effectively subsumes the CI-aware reading at that site.

3. **Performance.** Each `bootstrap_distribution` call is 1000 iter × ~5-10ms each = ~5-10 sec. With ~50-100 candidates per Discovery cycle, that's 5-15 min added to a Discovery run. Document the wall-clock impact in the audit doc; if it's > +30 min on a representative cycle, flag for follow-up (caching, parallelization).

4. **Forward path beyond T-010.** Are there OTHER lifecycle/promotion code paths that should also become CI-aware? E.g., `scripts/journal_apply.py` reads decisions and applies them; if its decision-source is now CI-aware, it inherits. Verify and document.

---

## Sequencing

- This task **does NOT depend on T-002** (substrate measurement) — the in-code gates are exercised at Discovery + lifecycle time, not at substrate-measurement time.
- This task **does depend on T-006** being in main — uses Foundry-expanded vocabulary indirectly (via Discovery's pipeline). T-006 is on main as of `82c77b3`.
- This task **does depend on T-013** if T-013 changes how feature_engineering produces output — recheck before merging T-010 if T-013 lands first.
- Substrate-independent. Can run while A is on T-002 OR after.
- Engine F change requires director review per CLAUDE.md. Worker pushes branch; director reviews + merges.
