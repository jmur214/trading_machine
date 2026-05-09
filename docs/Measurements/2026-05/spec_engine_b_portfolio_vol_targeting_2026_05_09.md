# Spec — T-XXX: Engine B portfolio-level vol-targeting (engine completion track)

**Date drafted:** 2026-05-09 evening
**Status:** SPEC for approval. **Engine B change — requires explicit user propose-first per CLAUDE.md.**
**Will be executed by:** Agent A or B once approved (~6-10 hr).
**Output:** Modified Engine B + new tests + A/B audit doc at `docs/Measurements/2026-05/engine_b_vol_targeting_ab_2026_05_09.{md,json}`.

---

## Why now

The substrate-honest 0.270 baseline was measured on Engine B's current state: **fixed-fraction `risk_per_trade_pct: 0.025`**. No portfolio-level vol-targeting. No correlation-aware sizing. No forecasted vol. This is the largest single gap per the dev review's bottom-up engine-completion estimate (+0.2 to +0.4 Sharpe from this alone).

Per the engines-first directive (`docs/State/forward_plan.md` 2026-05-09 evening update), Engine B portfolio vol-targeting is the highest-expected-lift engine completion item.

---

## What

Add a portfolio-level vol-targeting layer in Engine B. **Tightly scoped**: vol-targeting only. NOT bundled with:
- Correlation-aware position sizing (separate spec)
- GARCH/HAR-RV vol forecasting (separate spec; this uses realized vol)
- Drawdown-conditional gross reduction (separate spec; the kill switch is already wired but flag-OFF)

The rationale for tight scope: each of the four pieces should A/B against the 0.270 baseline independently. Bundling them obscures attribution.

### Mechanism

Compute the realized 60-day annualized portfolio volatility on rolling daily returns:

```python
realized_vol_60d = portfolio_returns.rolling(60).std() * sqrt(252)
```

Then compute a portfolio-level scalar:

```python
target_vol = 0.15  # 15% annualized — institutional default
gross_scalar = clamp(target_vol / max(realized_vol_60d, 1e-6),
                    0.5,   # don't degross below 50% in calm regimes
                    2.0)   # don't lever above 200%
```

Apply `gross_scalar` to per-position dollar sizes AT THE PORTFOLIO LEVEL — i.e., AFTER edge weights and per-trade sizing, BEFORE Engine C composition. This is the gross-up/gross-down dial.

### Policy interaction

The asymmetric vol-target clamp (shipped 2026-05-07 in Engine B) is currently applied per-trade. The new portfolio-level scalar is a SECOND scalar that multiplies on top:

```python
final_size = base_size × per_trade_vol_clamp × portfolio_gross_scalar
```

Both are bounded; both can be inactive (return 1.0). Independent code paths so we can toggle one without breaking the other.

### Configuration

New config flag in `config/risk_settings.json`:

```json
"portfolio_vol_target": {
  "enabled": false,            // default OFF — A/B opt-in
  "target_vol_annualized": 0.15,
  "lookback_days": 60,
  "min_scalar": 0.5,
  "max_scalar": 2.0,
  "warmup_days": 60            // first 60 trading days of any backtest, scalar = 1.0 (insufficient data)
}
```

Default OFF preserves bit-for-bit determinism. Flipping the flag is the A/B switch.

---

## How this differs from the existing vol-target clamp

| | Existing per-trade vol-target clamp | New portfolio vol-targeting |
|---|---|---|
| Scope | Per-position size adjustment | Portfolio-level gross scalar |
| Input | Per-asset realized vol | Portfolio-level realized 60d vol |
| Bounds | Asymmetric (1.0 in adverse, 1.4 in transitional, 2.0 in benign) | Symmetric (0.5 to 2.0) |
| Driven by | Per-trade context | Rolling portfolio history |
| Already shipped | YES | NO (this spec) |

They COMPOSE, don't conflict. Both apply.

---

## Acceptance

1. **Code:** modifications confined to:
   - `engines/engine_b_risk/risk_engine.py`: add the portfolio-vol-scalar computation + config-driven application path. Look at how the existing per-trade vol-target clamp was added in commit `ee42ab7` or similar — same shape.
   - `config/risk_settings.json`: add the `portfolio_vol_target` block per the schema above.
   - NO modifications to Engine A, Engine C, Engine D, Engine E, Engine F.

2. **Determinism guard:** with `enabled: false` (default), the harness must produce canon md5 IDENTICAL to a clean main checkout. **This is the gate before anything else.**

3. **A/B measurement:** new harness or extension of `scripts/run_substrate_arms.py` to support a 2-cell HMM-OFF / vol-target-OFF vs HMM-OFF / vol-target-ON A/B. 1 rep × 5 years × 2 cells = 10 runs. Determinism within each cell must be bitwise-stable.

4. **Tests:** new file `tests/test_portfolio_vol_targeting.py` with at minimum:
   - `test_default_off_preserves_determinism` — run a small backtest with `enabled: false`; assert no risk_engine call site references the new scalar
   - `test_warmup_period_returns_unity_scalar` — assert during the first `warmup_days` (default 60) the gross_scalar is 1.0
   - `test_realized_vol_above_target_degross` — synthesize portfolio returns with annualized vol > 0.15; assert gross_scalar < 1.0
   - `test_realized_vol_below_target_lever_up` — synthesize portfolio returns with annualized vol < 0.15; assert gross_scalar > 1.0 (capped at max_scalar)
   - `test_clamp_floors_apply` — synthesize extreme vol; assert min_scalar / max_scalar bounds hold
   - `test_compose_with_per_trade_vol_clamp` — verify both scalars apply together; assert no double-counting bug

5. **Existing tests:** all `tests/test_risk_engine*.py`, `tests/test_engine_b*.py`, `tests/test_drawdown_kill_switch*.py` (if exists), `tests/test_engine_b_drawdown_halt_narrow_except.py` (T-012) continue to pass.

6. **Audit doc:** `docs/Measurements/2026-05/engine_b_vol_targeting_ab_2026_05_09.md` covering:
   - A/B verdict bucket per the engines-first comparison-point framework (Δ Sharpe vs 0.270 baseline)
   - Per-year breakdown (does vol-targeting help in 2022 bear / 2023 chop more than 2024-25 calm bull, mirroring T-002's HMM finding?)
   - Bootstrap 95% CI on Sharpe + Sortino (per CLAUDE.md 6th non-negotiable)
   - Realized portfolio vol pre/post — does the policy actually deliver the 15% target?
   - MDD comparison — drawdown reduction is a secondary win
   - Determinism evidence (canon md5 stable within each cell)

7. **Branch:** `feature/engine-b-portfolio-vol-targeting`. Push only; **director DOES NOT merge to main without explicit user approval per CLAUDE.md Engine B rule.**

---

## Hard constraints

- DO NOT modify any other Engine B mechanism (per-trade vol-target clamp, drawdown kill switch logic, advisory exposure cap). Tightly scoped.
- DO NOT change the existing per-trade vol-target clamp default values or behavior. Compose, don't replace.
- DO NOT touch `live_trader/`. Engine B's API surface is unchanged; live_trader path inherits the new behavior automatically once flag is flipped (which won't happen without separate user approval).
- DO NOT change `risk_per_trade_pct: 0.025` default. The whole point of the new policy is to gross-up/down ON TOP of the existing per-trade sizing — replacing the fixed-fraction would be a separate, more invasive change.
- DO NOT enable by default. The flag stays OFF on the default config; A/B uses an override file or env var.
- DO NOT touch the asymmetric clamp (commit `ee42ab7`). Independent.

---

## Open questions to surface in audit doc (don't block)

1. **Target vol value (0.15 vs alternatives).** Institutional defaults span 0.10-0.20. 0.15 is conservative middle-ground. A/B with 0.10 and 0.20 in follow-up dispatches if 0.15 produces a borderline result. Document the choice.
2. **Lookback window (60d vs 30d/120d).** 60d is the default for realized-vol forecasting. Shorter (30d) is more responsive but noisier; longer (120d) is more stable but slower to react to regime changes. Document.
3. **Warmup behavior.** If we fire from a cold start (no rolling 60d available), the policy is inactive. This biases the first 60 days of any backtest. Document and note the warmup window in the A/B audit.
4. **Compound interaction with per-trade clamp.** Is there ever a case where both scalars produce excessive gross or net-zero gross? Surface the worst-case observed in the A/B sample.
5. **Tax interaction.** Vol-targeting can increase turnover (rebalancing toward target as realized vol drifts). For taxable accounts, this raises wash-sale and short-term tax drag. Per memory `project_deployment_context_taxable_default_2026_05_02.md`, deployment is taxable by default. Document expected turnover lift; flag if ≥ +30% turnover vs baseline.

---

## Realistic Sharpe lift target

Per dev review's bottom-up: portfolio-level vol-targeting projected +0.2 to +0.4 Sharpe vs 0.270 baseline. Verdict bucket against the 0.270 baseline:

| Δ Sharpe (point) | ci_low(Δ) | Bucket | Action |
|---|---|---|---|
| ≥ +0.2 | > 0 | DEPLOY (with director approval) | Flip flag default to ON, propose-first per CLAUDE.md governor-settings rule |
| +0.1 to +0.2 | borderline | PARTIAL | Document; combine with correlation-aware sizing (next spec) before deciding |
| < +0.1 | any | NEUTRAL | Document; revisit with GARCH/HAR-RV vol forecast (separate spec) — current realized-vol may be too lagged |
| < 0 | any | NEGATIVE | Investigate. The literature is unanimous that institutional portfolios benefit from vol-targeting; a negative result on this substrate would suggest something specific to the universe / edge mix |

---

## Time budget

6-10 hr total: 2-3 hr code (Engine B addition + config), 2-3 hr A/B harness + 10-run substrate, 1-2 hr audit doc, buffer for determinism debugging.

---

## Sequencing

- **Substrate-independent at the Foundry/feature level** — doesn't touch any features.
- **Engine B touch — requires user propose-first approval before dispatch.**
- Best execution after T-015 (Engine E HMM A/B) lands so we have a clean baseline of "engine completion lift attributable to HMM enable" before piling on vol-targeting attribution.
- Ideally, the 0.270 baseline + T-015 HMM lift + this T-? vol-targeting lift compose to the +0.55 to +1.25 dev-review-projected total over 3-6 months.
