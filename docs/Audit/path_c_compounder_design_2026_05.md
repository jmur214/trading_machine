# Path C — Compounder Sleeve & Multi-Sleeve Engine C Architecture

**Branch:** `path-c-compounder-sleeve-design`
**Date:** 2026-05-02
**Status:** DESIGN ONLY — no production code shipped (sleeve_base.py is a design artifact only).
**Counterpart agents:** Agent 1 (Path A — HRP slice 2 / turnover penalty / Engine B sizing in main worktree). This branch is read-only on Engine B and live_trader.

---

## 0. Why this exists (one paragraph)

The system has one strategy class — high-turnover, daily-rebalance, ensemble-of-edges — and the cost completeness measurement found that it carries a **-1.561 Sharpe gap** between pre-tax (0.984) and after-tax-in-taxable-account (-0.577) deployment contexts. That gap is *intrinsic to the strategy's deployment context* (wash-sale rule + short-term cap gains), not engineering quality. The current architecture forces the user into a binary: either deploy the high-turnover strategy in tax-advantaged accounts only (Roth IRA $7K/yr cap matches retail scale but is a hard ceiling) or run it in taxable and eat the drag. A **second sleeve** with a fundamentally different profile — low-turnover, annual rebalance, value/quality composite — converts that binary into a portfolio choice. The compounder sleeve naturally satisfies long-term capital gains rates, has near-zero wash-sale exposure, and serves Goal A (steady compounding) directly. It also sets up the architectural substrate that the Moonshot Sleeve (Goal C) will eventually plug into.

This document covers four design components:

- **D1** — Sleeve abstraction (interface, aggregation, config, migration)
- **D2** — Compounder sleeve specs (universe, cadence, edges, sizing, objective)
- **D3** — Synthetic backtest feasibility test (separate doc: `path_c_compounder_synthetic_backtest_2026_05.md`)
- **D4** — Engine C migration plan (production sequencing)

---

## D1. Sleeve Abstraction Design

### D1.1 The architectural target

The current Engine C is a single-sleeve system with implicit assumptions baked into `signal_processor.weighted_sum` + `PortfolioPolicy.allocate()`: daily cadence, equity-only, edge-aggregate-score sizing, ensemble of high-turnover technical/macro edges. To support a portfolio of sleeves, those assumptions must move from implicit-everywhere to **explicit-per-sleeve**, with Engine C aggregating sleeve-level outputs.

```
                 ┌─────────────────────────────────────────────┐
                 │           Engine C (multi-sleeve)            │
                 │                                              │
   ┌──────────┐  │   ┌──────────────────┐                     │
   │  Core    │──┼──▶│ CoreSleeve       │ ─┐                  │
   │  edges   │  │   │  (current strat) │  │                  │
   └──────────┘  │   └──────────────────┘  │                  │
                 │                          ▼                  │
   ┌──────────┐  │   ┌──────────────────┐  ┌────────────────┐ │
   │ Compnd   │──┼──▶│ CompounderSleeve │ ─▶│  Aggregator    │ │
   │  edges   │  │   │  (value/quality) │  │ (cross-sleeve  │ │
   └──────────┘  │   └──────────────────┘  │  constraints + │ │
                 │                          │  capital alloc)│ │
   ┌──────────┐  │   ┌──────────────────┐  └───────┬────────┘ │
   │ Moonshot │──┼──▶│ MoonshotSleeve   │ ─┘       │          │
   │  edges   │  │   │  (asymm payoff)  │          │          │
   └──────────┘  │   └──────────────────┘          ▼          │
                 │                          target_weights[]   │
                 └────────────────────────────────┼────────────┘
                                                  ▼
                                          PortfolioEngine
                                          (accounting layer,
                                           unchanged)
```

Key invariants:

- A sleeve produces **target weights over its own universe** at its **own cadence**, optimized for its **own objective function**. It is otherwise self-contained.
- The aggregator is the only place that knows about cross-sleeve constraints (gross exposure caps, sector diversification across sleeves, sleeve-vs-sleeve correlation).
- `PortfolioEngine` (the ledger) is untouched. It still receives `Dict[ticker -> weight]` and applies fills; it does not need to know which sleeve a position belongs to. Sleeve attribution flows via `Position.edge_group` (already exists).
- Engine B is untouched in the design phase. The aggregator emits the same shape `target_weights` that Engine C emits today.

### D1.2 The `Sleeve` interface

The minimal abstract base lives at `engines/engine_c_portfolio/sleeves/sleeve_base.py`. The interface is intentionally **narrow** — just enough to describe what a sleeve is, not enough to dictate how it computes.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Dict, List, Optional, Literal
import pandas as pd

RebalanceCadence = Literal["bar", "daily", "weekly", "monthly", "quarterly", "annual"]

@dataclass(frozen=True)
class SleeveSpec:
    """Static identity + config of a sleeve. Loaded from config/sleeves.json."""
    name: str                          # "core", "compounder", "moonshot"
    capital_pct: float                 # 0.0 – 1.0; sums across sleeves to ≤ 1.0
    rebalance_cadence: RebalanceCadence
    universe_id: str                   # references universe registry
    edge_set: List[str]                # edge_ids this sleeve consumes
    sizing_rule: str                   # "equal_weight" | "hrp" | "mcap_weight" | "weighted_sum"
    objective_function: str            # "sharpe" | "after_tax_cagr_floor_mdd" | "sortino_skew_upside"
    enabled: bool = True
    # Optional sleeve-level constraints
    max_position_weight: float = 1.0   # cap on any single ticker within sleeve
    target_volatility: Optional[float] = None  # None = no vol targeting at sleeve level

@dataclass
class SleeveOutput:
    """What a sleeve hands to the aggregator each call."""
    sleeve_name: str
    target_weights: Dict[str, float]   # ticker -> weight WITHIN sleeve (sum = 1.0 long, may be 0 if no positions)
    rebalance_due: bool                # True iff cadence triggered THIS call
    last_rebalance: Optional[pd.Timestamp]
    objective_value: Optional[float]   # current value of the sleeve's objective (for monitoring)
    diagnostics: Dict[str, float]      # arbitrary extras for dashboards

class Sleeve(ABC):
    """Abstract base. Each concrete sleeve implements `propose_weights`."""

    def __init__(self, spec: SleeveSpec):
        self.spec = spec
        self._last_rebalance: Optional[pd.Timestamp] = None

    @abstractmethod
    def propose_weights(
        self,
        as_of: pd.Timestamp,
        signals: Dict[str, float],          # edge-aggregate scores for sleeve's universe
        price_data: Dict[str, pd.DataFrame],
        regime_meta: Optional[Dict] = None,
    ) -> SleeveOutput:
        """Return target weights within this sleeve's mandate.

        MUST honor self.spec.rebalance_cadence — if cadence not triggered,
        return SleeveOutput with rebalance_due=False and the previous weights
        (or empty dict on first call before first rebalance).
        """

    def is_rebalance_due(self, as_of: pd.Timestamp) -> bool:
        """Cadence check. Concrete sleeves may override for custom triggers."""
        if self._last_rebalance is None:
            return True
        cadence = self.spec.rebalance_cadence
        delta = as_of - self._last_rebalance
        # daily / weekly / monthly / quarterly / annual implementations
        # (see sleeve_base.py for the table)
        ...
```

**Why this shape.**
- Frozen `SleeveSpec` makes config deterministic and JSON-serializable.
- `propose_weights` is the only required method. Cadence enforcement is in the base class so concrete sleeves can't accidentally over-trade.
- Weights are *within-sleeve* (sum to 1.0 of the sleeve's allocated capital). The aggregator scales by `capital_pct`. This decouples sleeve logic from system-level capital.
- `signals` is keyed by **the sleeve's universe**, not the global universe. Sleeves see only their own world.
- `regime_meta` is passed but optional — the compounder sleeve will likely ignore it; the moonshot sleeve may use it for risk-off de-grossing.

### D1.3 How Engine C aggregates sleeves

Aggregation lives in a new `MultiSleeveAggregator` class. The flow per bar:

```
1. For each sleeve s in registered_sleeves:
     output_s = s.propose_weights(as_of, signals[s.universe], prices, regime)
2. Stitch: global_weights = Σ_s ( capital_pct_s × output_s.target_weights )
3. Apply cross-sleeve constraints:
     a. Gross exposure cap (across all sleeves combined)
     b. Sector diversification (no sector > X% across the union)
     c. Sleeve-vs-sleeve correlation guard (if rolling 60d sleeve-return correlation
        between any two sleeves > 0.85, log warning; do not auto-deallocate — the
        user/Engine F decides whether to act)
     d. Single-name overlap soft cap (no ticker > Y% across the union)
4. Return Dict[ticker -> weight] to PortfolioEngine, unchanged signature.
```

**Cross-sleeve constraints** are deliberately *advisory + cap-style*, not optimization-coupled. Each sleeve optimizes its own objective; the aggregator only enforces gross/sector/single-name ceilings. This keeps the math tractable and matches the Schwab Intelligent Portfolio mental model the project explicitly references in `docs/Core/PROJECT_CONTEXT.md`: separate sleeves, each well-defined, top-level constraints applied at the portfolio level.

**What the aggregator deliberately does NOT do.**
- It does NOT re-optimize sleeve weights jointly. That would re-introduce the matrix-inversion fragility HRP slice 1 was designed to avoid, *and* it would couple the sleeves' objectives, which defeats the entire point of having sleeves with different mandates.
- It does NOT touch sizing (Engine B's job). The aggregator emits target weights; Engine B converts to qty.
- It does NOT enforce sleeve-level vol targeting. That is internal to each sleeve.

### D1.4 Config schema (`config/sleeves.json`)

```json
{
  "version": 1,
  "sleeves": [
    {
      "name": "core",
      "capital_pct": 0.70,
      "rebalance_cadence": "daily",
      "universe_id": "prod_109",
      "edge_set": ["volume_anomaly_v1", "herding_v1", "gap_fill_v1", "<all current active+paused>"],
      "sizing_rule": "weighted_sum",
      "objective_function": "sharpe",
      "enabled": true,
      "max_position_weight": 0.25,
      "target_volatility": 0.15
    },
    {
      "name": "compounder",
      "capital_pct": 0.15,
      "rebalance_cadence": "annual",
      "universe_id": "sp500_membership",
      "edge_set": ["value_composite_v1", "quality_composite_v1", "low_vol_v1", "asset_growth_low_v1", "net_issuance_v1"],
      "sizing_rule": "equal_weight",
      "objective_function": "after_tax_cagr_floor_mdd",
      "enabled": false,
      "max_position_weight": 0.05,
      "target_volatility": null
    },
    {
      "name": "moonshot",
      "capital_pct": 0.15,
      "rebalance_cadence": "weekly",
      "universe_id": "russell_2000_plus_themes",
      "edge_set": ["__placeholder__"],
      "sizing_rule": "equal_weight",
      "objective_function": "sortino_skew_upside",
      "enabled": false,
      "max_position_weight": 0.02
    }
  ],
  "cross_sleeve": {
    "max_gross_exposure": 1.30,
    "max_sector_pct": 0.35,
    "max_single_name_pct": 0.10,
    "correlation_warn_threshold": 0.85,
    "correlation_lookback_days": 60
  }
}
```

**Validation rules** (enforced at load time in `MultiSleeveAggregator.__init__`):
- `Σ capital_pct ≤ 1.00` (the residual stays in cash; allocator does not auto-fill).
- Exactly one sleeve named `"core"` exists when `version == 1` (migration constraint).
- `enabled=false` sleeves are loaded but skipped during aggregation (output is empty dict, no PnL impact).
- Universe IDs must resolve via the existing universe registry (`data/universe/`).

### D1.5 Migration path — backward-compatible single-sleeve flip

The migration is designed so the **first ship of the abstraction is a no-op**: the current single-sleeve system becomes a 1-sleeve `core` sleeve with the same behavior, no Sharpe delta beyond noise floor.

**Phase M0 — abstraction-only ship (NO behavior change):**
1. Land `Sleeve` ABC + `MultiSleeveAggregator` + config loader.
2. Create `CoreSleeve(Sleeve)` that simply delegates to the existing `PortfolioPolicy.allocate()`.
3. Wire `MultiSleeveAggregator` into `PortfolioEngine.compute_target_allocations()` as an optional path, gated by `config/sleeves.json` existence + a `sleeves_enabled: false` global flag (default false).
4. **Acceptance gate:** under deterministic harness, 3-run identical canon md5 to baseline (proves the wrapper is bit-exact when only `core` is present).

**Phase M1 — compounder sleeve added but `enabled: false`:**
1. Land `CompounderSleeve` implementation (D2 specs below) + its edge code via Foundry.
2. Config loaded but `enabled: false` — sleeve is initialized, never produces weights.
3. **Acceptance gate:** same canon md5 as M0 (proves disabled sleeves don't leak state).

**Phase M2 — compounder enabled at small allocation:**
1. Flip `enabled: true` and `capital_pct: 0.05` (5% allocation).
2. Re-run 2025 OOS under harness. Measure A/B vs M1 baseline.
3. **Acceptance gate:** combined Sharpe within ±0.05 of baseline (compounder is small; impact should be small). After-tax Sharpe expected to *improve* meaningfully because compounder eats LT cap gains rates.

**Phase M3 — compounder ramped:**
1. Increase `capital_pct` to 0.10 → 0.15 over 2 measurement cycles.
2. Re-measure both pre-tax and after-tax Sharpe at each step.
3. **Acceptance gate:** after-tax CAGR strictly improves at each ramp step, OR ramp stops.

**Backward compat hard rules:**
- If `config/sleeves.json` is missing, system uses the *legacy* single-sleeve path verbatim. No multi-sleeve overhead is incurred.
- Trade attribution: `Position.edge_group` is already populated; sleeves stamp their name on it via the edge-id → sleeve-name map. No schema change.
- The existing `PortfolioPolicy` class is **kept intact**. `CoreSleeve` wraps it; nothing inside the policy changes.
- The existing `signal_processor.weighted_sum` is **kept intact**. Compounder sleeve doesn't go through it (sleeves can pick their own sizing rule); core sleeve does, exactly as today.

---

## D2. Compounder Sleeve Specs

### D2.1 Universe — recommendation: **S&P 500 (broader)**, not prod-109

Tradeoffs:

| Choice | Pros | Cons |
|---|---|---|
| prod-109 | shares ops with core; one ticker pool to maintain; can reuse cached prices | mega-cap-tech curated; value composite would be concentrated in 5-10 names; quality composite collapses to "buy AAPL/MSFT/GOOGL"; same overfitting trap that killed `momentum_factor_v1` (memory: `project_factor_edge_first_alpha_2026_04_24.md`) |
| S&P 500 (~500 names, current+historical membership via `data/universe/sp500_membership.parquet`) | broad enough that top-quintile = ~100 names → real diversification; matches academic factor literature; survivorship-aware via membership panel | requires loading +400 ticker price histories; data layer needs work but the membership panel already exists |
| Russell 1000 / Russell 3000 | even broader; better small-cap factor exposure | more data eng overhead; not currently cached; deferral risk |

**Recommendation: S&P 500 with point-in-time membership.** The 109-ticker universe has been *repeatedly diagnosed* as too small for cross-sectional factor work — `momentum_factor_v1` and `low_vol_factor_v1` both falsified specifically because top-quintile concentrated to 8 names. The compounder sleeve has the same architecture (rank long top-quintile of composite) and would inherit the same pathology on prod-109. S&P 500 is the minimum viable universe.

The compounder sleeve carrying its own universe (different from core's prod-109) is *load-bearing for the design.* It's the first concrete payoff of the sleeve abstraction: each sleeve owns its universe.

**Operational consequence:** Foundry needs to bring S&P 500 historical price data online (yfinance bulk pull + parquet cache). This is a Workstream F dependency for the compounder, not an Engine C blocker — sleeve abstraction can ship first with `enabled: false`.

### D2.2 Rebalance cadence — recommendation: **annual** (Jan rebalance + mid-year drift check)

Tradeoffs:

| Cadence | Pros | Cons |
|---|---|---|
| Annual (Jan 1) | maximum LT cap gains rate exposure (15% vs 30%); lowest turnover (~50%/yr); minimal wash-sale risk | slow to react to factor regime shifts; whole-year drag if a position deteriorates |
| Quarterly | better factor regime adaptation; modest tax penalty (some ST gains); 4× rebalance turnover | partial loss of LT cap gains advantage; turnover ~150-200%/yr |
| Monthly | matches academic factor lit (Fama-French monthly rebalance) | nearly all gains short-term; defeats compounder thesis |

**Recommendation: annual rebalance on first trading day of January, with a mid-year drift check.**

- The compounder sleeve's *entire reason for existing* is tax efficiency. Annual rebalance + holding period > 365d ensures every realized gain is long-term cap gains (15% federal vs 30% short-term), and the wash-sale rule is structurally not in play.
- The mid-year drift check (around July 1) only acts on *outliers*: any position whose weight has drifted to >1.5× or <0.5× of target gets re-sized within sleeve. Closed positions only via a stop (factor-rank exit, see below). This is opt-in via `compounder.midyear_drift_enabled: true`.
- A position that drops out of top-quintile by mid-year is **not closed** until the next January — the compounder bets on the fact pattern that factor signals are noisy intra-year and the annual rebalance is the optimal sampling cadence (Asness, Frazzini & Pedersen 2013; "Quality Minus Junk").

### D2.3 Edge set — 5 edges, all cross-sectional ranking

The compounder sleeve does **not** consume the core sleeve's edges. Its edges are cross-sectional rank-based factor primitives, ingested as Foundry features and consumed via a sleeve-internal "rank-and-equal-weight-top-quintile" sizing rule.

| # | Edge | Inputs | Direction | Academic ref |
|---|---|---|---|---|
| 1 | `value_composite_v1` | rank-avg of: P/E (low), P/B (low), EV/EBITDA (low), EV/Sales (low) | long top quintile | Asness, Frazzini, Pedersen "QMJ"; Fama-French HML extension |
| 2 | `quality_composite_v1` | rank-avg of: ROIC (high), gross margin (high), debt/equity (low), accruals (low) | long top quintile | Novy-Marx "Other Side of Value"; Sloan accruals anomaly |
| 3 | `profitability_v1` | gross profitability (gross profit / total assets) | long top quintile | Novy-Marx 2013 |
| 4 | `asset_growth_low_v1` | rank by year-over-year asset growth, **low** is long | long bottom quintile (low growth = good) | Cooper, Gulen, Schill 2008 |
| 5 | `net_issuance_v1` | (shares_outstanding(t) - shares_outstanding(t-1y)) / shares_outstanding(t-1y), low/negative is long | long bottom quintile (buybacks) | Pontiff & Woodgate 2008; Daniel & Titman |

**Optional 6th edge (deferred to Phase M3):** `low_vol_v1` — rank by 252d realized vol, low is long. Strong academic support (Frazzini-Pedersen "Betting Against Beta") but already shown FALSIFIED on prod-109 in this project (memory: `project_low_vol_regime_conditional_2026_04_25.md`). Worth re-testing on the broader S&P 500 universe but not load-bearing. Defer.

**Composite formation:** for each name, on rebalance date, compute each of the 5 edges as a 1-100 percentile rank. Then form the **compounder composite score** as the equal-weighted average of the 5 percentile ranks. Long the top quintile (top 20% of composite score) of the universe. Equal-weight within the long basket.

**Why NOT use the core sleeve's edges?** The core's edges are technical/event-driven, optimized for daily holding periods. Their alpha decays at the 5-30 day horizon. Holding for 365+ days inverts the bet — the core's "buy this when RSI < 30" doesn't hold over a year, it just sits there bleeding to slippage and drift.

**Why NOT use HRP for sizing?** The compounder is deliberately concentrated by design (top-quintile, ~100 names → equal-weight). HRP would dilute the concentration toward equal-vol-bucketed bins, which on a value/quality long basket means buying *more* of the lower-vol names — exactly inverting the intended factor exposure (value + quality stocks tend to be lower-vol; HRP would over-allocate to them, but at the cost of single-name concentration that the academic factor literature shows you actually *want*). Equal-weight is the methodologically correct choice for cross-sectional factor portfolios.

### D2.4 Sizing rule — recommendation: **equal-weight within top quintile**

Tradeoffs:

| Rule | Pros | Cons |
|---|---|---|
| Equal-weight within top quintile (RECOMMENDED) | matches Fama-French/QMJ academic methodology; no estimation error from cov matrix; transparent | each position 1/N where N≈100; some concentration risk in high-quality mega-caps if they cluster in top quintile |
| Market-cap weighted | matches passive index logic; lower turnover | dominated by 5-10 mega-caps; defeats the "broad value/quality exposure" thesis |
| HRP within sleeve | lower portfolio vol; better drawdown profile | dilutes factor exposure; estimation error on 100-name cov matrix; computationally heavy at annual cadence |

**Equal-weight is the academic methodology** for cross-sectional factor portfolios (every QMJ/HML/SMB paper since Fama-French 1992). It is also the path of least architectural complexity: no estimation, no cov matrix, no per-name vol scaling. The compounder is supposed to be *boring and mechanical* — equal-weight gets that property for free.

Single-name cap (`max_position_weight: 0.05`) prevents any one name from exceeding 5% of sleeve. With 100 positions targeted, equal-weight gives 1% per name; the cap is only binding if the universe shrinks to <20 names, which only happens if data quality fails — a fail-safe, not a constraint.

### D2.5 Objective function — **after-tax CAGR with MDD floor**

The compounder sleeve is **not** Sharpe-optimized. Its objective is:

```
maximize  after_tax_CAGR
subject to  max_drawdown ≥ -15%
            holding_period_avg ≥ 365 days
            wash_sale_violations == 0
```

**Why not Sharpe?**

- Sharpe penalizes upside vol, which long-only factor portfolios absorb naturally and the user is fine carrying.
- Sharpe rewards *consistent* returns; the compounder is allowed to deliver lumpy returns as long as the trough is bounded by the MDD floor and the trajectory beats SPY after taxes.
- The high-turnover core sleeve is already Sharpe-optimized; layering a *second* Sharpe-optimized sleeve adds marginal Sharpe at marginal capital cost. Layering an after-tax-CAGR-optimized sleeve adds an *orthogonal* return stream.

**MDD floor of -15%** is the user's "boring sleeve" risk tolerance. Tighter than core's -10% to -15% sleeve drag because the compounder is meant to be the *defensive* portion of the portfolio in addition to its tax-efficiency role. If MDD floor breaches, the kill thesis triggers and the sleeve allocation drops to 0 pending review. This is encoded as `compounder.mdd_kill_threshold: -0.15` and checked in the aggregator as a sleeve-level kill switch.

**Holding period constraint** is structural: annual rebalance plus equal-weight-stable composite means the typical position is held 12+ months (only the bottom-of-quintile rotators get cycled out at January rebalance, and the top of the quintile typically persists for multiple years).

**Wash-sale = 0** is enforced by a tax-aware rebalance check: at January rebalance, if the system would *sell* a position at a loss and *buy* the same ticker (or substantially identical) within the next 30 days, the sale is **deferred** to ≥31 days post the conflicting buy. This rarely binds at annual cadence but is a hard rule.

---

## D4. Engine C Migration Plan

This is the production sequencing for Phase M0 → M2 from §D1.5. Each sub-task lists what's added new, what's touched, and any cross-engine implications.

### D4.1 Sub-task list

| # | Sub-task | Added/touched | Effort | Touches Engine B? | Approval gate? |
|---|---|---|---|---|---|
| 1 | `Sleeve` ABC + `SleeveSpec` + `SleeveOutput` + `MultiSleeveAggregator` skeleton | NEW: `engines/engine_c_portfolio/sleeves/{sleeve_base.py, aggregator.py}` | 1.5 d | No | No (within Engine C) |
| 2 | Config loader for `config/sleeves.json` + JSON schema validator | NEW: `engines/engine_c_portfolio/sleeves/config_loader.py`; NEW config file | 0.5 d | No | No |
| 3 | `CoreSleeve` (legacy delegator) wrapping current `PortfolioPolicy.allocate()` | NEW: `engines/engine_c_portfolio/sleeves/core_sleeve.py` | 1 d | No | No |
| 4 | Wire `MultiSleeveAggregator` into `PortfolioEngine.compute_target_allocations()` behind feature flag | TOUCHED: `engines/engine_c_portfolio/portfolio_engine.py` (~30 lines, opt-in only); TOUCHED: `orchestration/mode_controller.py` (config plumb-through) | 1 d | **Indirect** — `mode_controller` already builds Engine B; no Engine B code change but the wire-through must not regress sizing inputs | No (config-flag-gated; default off) |
| 5 | M0 acceptance gate: 3-run deterministic harness verification, single-sleeve canon md5 = baseline | None (test only) | 0.5 d | No | No |
| 6 | S&P 500 universe data layer: yfinance bulk pull + parquet cache + point-in-time membership join | NEW: `core/feature_foundry/sources/sp500_prices.py`; cached parquet under `data/raw/sp500/` | 2-3 d | No | No (Foundry / data layer) |
| 7 | 5 compounder edges as Foundry features (value/quality/profitability/asset_growth/net_issuance) — **fundamentals data dependency** | NEW: 5 files under `core/feature_foundry/features/`; 5 model cards; ONE shared fundamentals data source | 3-5 d | No | No (Foundry) |
| 8 | `CompounderSleeve` concrete implementation + sleeve-internal sizing (rank → top quintile → equal weight) | NEW: `engines/engine_c_portfolio/sleeves/compounder_sleeve.py` | 2 d | No | No |
| 9 | Sleeve-level kill switch (MDD floor, wash-sale = 0) hooked into aggregator | TOUCHED: `engines/engine_c_portfolio/sleeves/aggregator.py` | 1 d | No | No |
| 10 | Cross-sleeve constraints (gross cap, sector cap, single-name cap, correlation warn) | TOUCHED: `engines/engine_c_portfolio/sleeves/aggregator.py` | 1.5 d | No | No |
| 11 | Per-sleeve attribution in `Position.edge_group` + dashboard tab for sleeve-level PnL | TOUCHED: edge → sleeve mapping (config-driven); NEW: `cockpit/dashboard_v2/tabs/sleeves_tab.py` | 1.5 d | No | No (UX work) |
| 12 | M2 acceptance gate: 2025 OOS under harness with compounder enabled at 5% capital | None (test only) | 0.5 d | No | No |
| 13 | **Sleeve-aware sizing in Engine B** (DEFERRED, Phase M3+) — Engine B currently sizes per-edge globally; with sleeves it should size per-sleeve so the compounder's annual-cadence positions don't share a vol-target denominator with core's daily-cadence positions | TOUCHED: `engines/engine_b_risk/risk_engine.py` | 2-3 d | **YES** | **YES — user approval required per CLAUDE.md** |
| 14 | **Tax-aware rebalance check in compounder sleeve** (wash-sale deferral) — needs realized-loss state from PortfolioEngine which lives across the Engine B/C boundary | TOUCHED: `engines/engine_c_portfolio/sleeves/compounder_sleeve.py`; light TOUCH to `PortfolioEngine.realized_pnl` query API | 1.5 d | Indirect | No (Engine C only) |

**Total effort estimate (sub-tasks 1-12 + 14):** ~17-22 working days for one developer. Sub-task 13 is a deferred Engine B item requiring user approval.

### D4.2 Sequencing — what's parallel, what's serial

```
SERIAL CHAIN (must be in order):
  1 → 2 → 3 → 4 → 5  (M0 ship: abstraction-only)
                  ↓
                  M0 PASSES (canon md5 identical) — gates everything below
                  ↓
PARALLEL after M0:
  ┌── 6 (S&P 500 data layer)
  ├── 7 (5 compounder edges via Foundry)  — depends on 6 for price data, but
  │                                          fundamentals are independent
  └── 11 (dashboard tab, attribution)

SERIAL after 6+7+8:
  8 (CompounderSleeve impl, depends on edges existing in Foundry)
  → 9 (kill switch)
  → 10 (cross-sleeve constraints)
  → 12 (M2 acceptance gate)
  → 14 (wash-sale deferral; can ship after M2 baseline established)

DEFERRED:
  13 (Engine B sleeve-aware sizing — user approval gate)
```

**Critical path:** sub-tasks 1-5 (abstraction ship). Until M0 acceptance is verified, no compounder work is unblocked.

### D4.3 Risk register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| M0 wrapper introduces non-determinism in single-sleeve path | LOW | HIGH (would require rollback) | Mandatory canon md5 acceptance gate before any further work |
| S&P 500 fundamentals data has survivorship bias / point-in-time issues | MED | MED (compounder backtest looks better than reality) | Use `sp500_membership.parquet` PIT join; document data lineage in model cards; the universe panel must be PIT-validated |
| Compounder universe overlap with core sleeve creates correlated whipsaws | MED | LOW | Cross-sleeve correlation warn at 0.85 threshold (config); manual review point, not auto-action |
| HRP slice 2 (Agent 1's path) lands turnover penalty that conflicts with compounder's annual cadence | MED | LOW | Compounder bypasses turnover penalty entirely (different sizing path); core sleeve continues to use it. No conflict if sleeve abstraction is correctly enforced. |
| Engine B sizes compounder positions with same daily vol-target machinery as core | HIGH | MED (sleeve thesis half-works) | Sub-task 13 must ship eventually; user-approval-gated; design doc filed today so Engine B work is pre-scoped |
| Fundamentals data source has license/cost concerns | MED | MED-HIGH | yfinance is free for non-commercial; document in model cards; long-term path is to swap to a paid/clean source (FactSet, Compustat) when commercial deployment matters |

### D4.4 What needs user approval (CLAUDE.md compliance)

- **Sub-task 13** (Engine B sleeve-aware sizing) — touches `engines/engine_b_risk/`. Per CLAUDE.md "anything touching Engine B (Risk) or `live_trader/`" requires the propose-first protocol. This sub-task is filed in this design doc as **deferred to Phase M3+** and will be raised with the user before any code is touched.
- **Phase M2 ramp to >5% capital_pct** — the user explicitly authorized "design only" in this round. Actually allocating 15% of system capital to a new sleeve crosses into "real money paths even hypothetically" territory and is gated by user approval at each ramp step.

Everything else (sub-tasks 1-12, 14) falls within autonomous improvement bounds: no Engine B code, no live_trader, no governance contract changes, no new external services.

---

## What this design doc does NOT do

- **Does not commit to a particular meta-learner integration.** The compounder sleeve outputs target weights via a sizing rule it owns internally; whether the meta-learner ever consumes compounder edges is a future decision. For now, the meta-learner sees core-sleeve signals only.
- **Does not implement any production code.** The sleeve_base.py file in this branch is a design artifact (interface only, no concrete logic).
- **Does not solve the universe expansion problem for the core sleeve.** Compounder uses S&P 500; core stays on prod-109. Whether core should expand to S&P 500 too is a separate Workstream A question.
- **Does not assume HRP slice 2 lands successfully.** The compounder design is independent of Agent 1's Path A work; if HRP slice 2 ships, it benefits the core sleeve only — the compounder uses equal-weight regardless.
- **Does not specify the moonshot sleeve.** Architecturally provisioned (placeholder in config), specs deferred to a later round.

---

## Open questions (not blocking the design)

1. **Should the compounder universe be S&P 500 or Russell 1000?** S&P 500 has better data; Russell 1000 has better small-mid-cap factor exposure. Recommendation is S&P 500 first, Russell 1000 as a Phase M3+ extension once the data layer exists.

2. **Should the compounder's MDD floor be -15% or -20%?** -15% is conservative and matches the user's stated retail risk tolerance from `project_retail_capital_constraint_2026_05_01.md`. -20% gives more headroom for 2008/2020-class drawdowns. Recommendation is -15% with explicit user override available.

3. **How should rebalance attribution flow into Engine F?** Engine F currently scores edges via rolling Sharpe over a window. Compounder edges have a 365d minimum measurement window; Engine F's existing windows (60d, 90d) are wrong for them. This is a Phase M3+ Engine F integration item — for now, compounder sleeve self-monitors via its `objective_value` field.

4. **Tax accounting integration with `backtester/tax_drag_model.py`?** That module ships disabled by default. The compounder backtest should run with `tax_drag.enabled=true` and `tax_drag.long_term_rate=0.15` to honestly measure after-tax CAGR. Coordination point with the cost completeness work; not a blocker.

---

## Cross-references

- `docs/Core/forward_plan_2026_05_02.md` — current live plan; multi-asset/multi-sleeve scaffolding listed under Workstream B
- `docs/Core/PROJECT_CONTEXT.md` — Schwab Intelligent Portfolio reference + retail capital + asymmetric upside framing
- `memory/project_tax_drag_kills_after_tax_2026_05_02.md` — drives the entire compounder thesis
- `memory/project_retail_capital_constraint_2026_05_01.md` — retail capital math, Goal A (steady compounding) target
- `memory/project_engine_c_hrp_slice1_falsified_2026_05_02.md` — why HRP-as-magnitude-replacement failed; informs why compounder uses equal-weight, not HRP
- `memory/project_factor_edge_first_alpha_2026_04_24.md` — `momentum_factor_v1` falsified at prod-109 size; same risk for compounder if universe stays at 109; argues for S&P 500
- `memory/project_low_vol_regime_conditional_2026_04_25.md` — `low_vol_factor_v1` falsified; argues for low-vol being deferred (optional 6th edge)
- `docs/Audit/path_c_compounder_synthetic_backtest_2026_05.md` — D3 feasibility test result (separate doc)
- `engines/engine_c_portfolio/sleeves/sleeve_base.py` — design artifact (abstract class only)
