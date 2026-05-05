# Feature Foundry — Skeleton Audit (2026-05)

Initial substrate dispatched per `docs/Core/forward_plan_2026_05_02.md`
Workstream D, in response to the reviewer's central rule from
`docs/Progress_Summaries/Other-dev-opinion/05-1-26_1-percent.md`:

> Without infrastructure: marginal cost of feature N is roughly N.
> With infrastructure: marginal cost of feature N is constant.

This document describes what the skeleton ships, the architectural
intent behind each component, the falsifiable verification (CFTC
Commitments of Traders end-to-end), and what is deliberately deferred.

## Summary

Branch: `feature-foundry-skeleton`

| # | Component | Path | Shipped |
|---|---|---|---|
| F1 | `DataSource` ABC + registry + parquet write-through cache | `core/feature_foundry/data_source.py` | ✅ |
| F2 | `@feature` decorator + registry | `core/feature_foundry/feature.py` | ✅ |
| F3 | Ablation runner (LOO contribution) | `core/feature_foundry/ablation.py` | ✅ |
| F4 | Adversarial twin generator | `core/feature_foundry/adversarial.py` | ✅ |
| F5 | Model card schema + validator | `core/feature_foundry/model_card.py` | ✅ |
| F6 | Feature audit dashboard tab | `cockpit/dashboard_v2/tabs/feature_foundry_tab.py` | ✅ |

Verification:

| Item | Status |
|---|---|
| CFTC COT DataSource end-to-end (synthetic-fixture fetcher) | ✅ |
| `cot_commercial_net_long` feature evaluates correctly | ✅ |
| Adversarial twin generation + determinism | ✅ |
| Ablation runner persists + reloads | ✅ |
| Model card validator catches missing/orphan/license-mismatch | ✅ |
| Dashboard tab renders + callbacks register | ✅ |
| 29/29 Foundry tests passing | ✅ |
| Existing capital-allocation dashboard tests still pass | ✅ |

## Architecture overview

```
core/feature_foundry/
├── __init__.py             # public surface
├── data_source.py          # F1: DataSource ABC + DataSourceRegistry
├── feature.py              # F2: @feature decorator + FeatureRegistry
├── ablation.py             # F3: run_ablation + persistence
├── adversarial.py          # F4: generate_twin (deterministic permutation)
├── model_card.py           # F5: ModelCard + validate_all_model_cards
├── sources/
│   ├── __init__.py         # imports each source for self-registration
│   └── cftc_cot.py         # CFTC COT data source (verification)
├── features/
│   ├── __init__.py         # imports each feature for self-registration
│   └── cot_commercial_net_long.py
└── model_cards/
    └── cot_commercial_net_long.yml
```

```
cockpit/dashboard_v2/
├── tabs/feature_foundry_tab.py        # F6 layout
├── callbacks/feature_foundry_callbacks.py
└── utils/feature_foundry_loader.py    # adapts substrate state → table rows
```

The Foundry is intentionally separate from `engines/engine_a_alpha/
edge_registry.py`. **Edges trade; Foundry features feed the
meta-learner.** The two registries may eventually integrate but the
substrate ships first, with no engine code modified outside the
`cockpit/dashboard_v2/` analytics-tab wiring.

## Component descriptions

### F1 — `DataSource` (`data_source.py`)

Abstract base for every external data feed (CFTC, FDA, Polymarket,
patents, etc.). Concrete subclasses set four metadata fields
(`name`, `license`, `latency`, `point_in_time_safe`) and implement
three methods (`fetch`, `schema_check`, `freshness_check`). The base
class provides a write-through parquet cache keyed on
`(name, start, end)` so the second call for any window is free.

`DataSourceRegistry` is a process-local index of source instances.
Plugins self-register at import time; the dashboard enumerates via
`list_sources()`.

**Invariant:** `point_in_time_safe=False` sources are advisory-only
and must not feed any feature used in a backtest. Cache writes call
`schema_check` first; an invalid schema raises before persisting.

### F2 — `@feature` decorator (`feature.py`)

Wraps a `(ticker, date) -> Optional[float]` function in a `Feature`
dataclass that captures `feature_id`, `tier` ∈ {A, B, adversarial},
`horizon`, `license`, `source`, and `description`. Adds the resulting
`Feature` to the global `FeatureRegistry`.

The Foundry tier vocabulary (A/B/adversarial) is **deliberately
distinct** from the existing `EdgeSpec.tier` vocabulary
(alpha/feature/context). Edges are tradeable signals with a lifecycle;
Foundry features are meta-learner inputs with adversarial filtering.
Reusing the word "tier" across both registries is a notational
overlap, not a structural one — they live in different files because
they answer different questions.

`Feature.evaluate_panel(tickers, dates)` returns a long-format
DataFrame for use by the ablation runner and twin generator.

### F3 — Ablation runner (`ablation.py`)

`run_ablation(feature_ids, baseline_run_uuid, backtest_fn)` performs
leave-one-out ablation: baseline Sharpe (full set) is computed once,
then dropped-Sharpe is computed for each feature. Contribution is
`baseline - dropped` (positive ⇒ useful; negative ⇒ archive
candidate per the reviewer's 90-day rule).

The runner is **deliberately decoupled** from the production backtest
pipeline. It accepts a `Callable[[set[str]], float]` so:
  - tests pass synthetic linear-contribution functions,
  - production wiring (deferred) passes a closure over the harness
    backtest entry point,
  - ad-hoc analyses pass shell-driven backtest invocations.

Results persist as JSON at `data/feature_foundry/ablation/<uuid>.json`.
`latest_ablation_for_feature(feature_id)` is the lookup the dashboard
loader uses.

### F4 — Adversarial twin generator (`adversarial.py`)

`generate_twin(real)` returns a `Feature` with `tier='adversarial'`
that exposes the real feature's per-ticker time series with the
intra-ticker temporal order shuffled. The permutation is keyed on
`(feature_id, ticker)` so the same twin is produced every run —
required for deterministic gauntlet measurement.

Twin materialisation is lazy and scoped to a ±5y window around the
first call. The non-null mask is preserved (so the twin gains no
artificial coverage advantage over the real). `tier='adversarial'`
features cannot themselves be twinned (`generate_twin` raises) — twins
are leaf nodes.

`assert_adversarial_filter_passes(real_imp, twin_imp, fid)` is the
hard guard for CI: real meta-learner importance must exceed its
twin's. A twin that ranks above its real is direct overfitting
evidence per the reviewer's adversarial-filter rule.

### F5 — Model card schema (`model_card.py`)

YAML lineage per feature, git-tracked at
`core/feature_foundry/model_cards/<feature_id>.yml`. Required fields:
`feature_id`, `source_url`, `license`, `point_in_time_safe`,
`expected_behavior`, `known_failure_modes`, `last_revalidation`.
Optional: `ablation_history` (auto-appended on every ablation run).

`validate_all_model_cards()` returns a list of human-readable error
strings. Empty list = clean. The dashboard surfaces errors as red
flags; the eventual CI gate (deferred) will fail any non-empty list.

The validator catches:
  - **missing_card** — registered feature has no card on disk,
  - **license_mismatch** — card license ≠ decorator license,
  - **orphan_card** — card exists for a feature_id not in the
    registry (likely renamed or deleted),
  - **parse_error** — card YAML is malformed.

`update_revalidation(feature_id, run_uuid, contribution)` is invoked
by the ablation runner (when integration lands) to bump
`last_revalidation` and append to `ablation_history`.

### F6 — Feature Foundry dashboard tab

`cockpit/dashboard_v2/tabs/feature_foundry_tab.py` lives as a fourth
sub-tab under Analytics, sibling to Capital Allocation. Three panels:
  - **Validation errors** — list of model-card-validator findings, or
    a green "all clean" line.
  - **Features table** — per-feature row: id, tier, source, horizon,
    license, card-presence, last-revalidated date, ablation Δ Sharpe,
    twin presence, twin id, health flag (green/yellow/red), reason.
  - **Sources table** — per-DataSource row: name, license,
    point-in-time discipline, latency, freshness state, health flag.

Loaders live in `cockpit/dashboard_v2/utils/feature_foundry_loader.py`.
Health classification is rule-based:
  - `fail` if no model card OR negative ablation contribution
  - `warn` if no twin OR never revalidated OR > 90 days stale
  - `ok` otherwise

The cockpit boots cleanly even when no Foundry plugins have been
imported — the loader catches `ImportError` and surfaces it as a
single error row.

## Falsifiable verification — CFTC COT end-to-end

The CFTC Commitments of Traders report is the highest-novelty
underused free data source per the reviewer's Track-F catalogue
(weekly, decades deep, public). Implementing it as the first
DataSource exercises every layer of the substrate:

  1. **Source plugin** at `core/feature_foundry/sources/cftc_cot.py`.
     Implements `fetch` (per-year CSV download), `schema_check`
     (required columns + numeric dtypes), `freshness_check`
     (latest-cached-row date vs `latency`). Self-registers a default
     instance at import time.

  2. **Fetcher injection.** The `fetcher: Callable[[str], str]` is
     `Optional[]`. The shipped default raises `NotImplementedError`
     with a clear message — the substrate does NOT bake a network
     call into import. Production wiring will supply a
     `urllib.request`-based fetcher; tests supply a local-fixture
     fetcher returning synthetic CSV. Both paths exercise identical
     downstream code.

  3. **Sample feature** at `core/feature_foundry/features/
     cot_commercial_net_long.py`. Computes
     `(comm_long - comm_short) / open_interest` for the most recent
     report ≤ `dt`. Returns `None` for tickers without a futures
     mapping (most single-name equities) and for dates before the
     first published report. Decorated with `@feature(tier='B',
     horizon=5, license='public', source='cftc_cot')`.

  4. **Adversarial twin** generated via `generate_twin(real)` —
     verified in tests to preserve the per-ticker marginal
     distribution while breaking temporal alignment.

  5. **Ablation** runs cleanly on a synthetic 1-feature backtest;
     persistence + reload verified.

  6. **Model card** at `core/feature_foundry/model_cards/
     cot_commercial_net_long.yml` documents source URL, license,
     point-in-time discipline, expected behaviour, four known failure
     modes (holiday-week publishing lag, exchange code drift, pre-2006
     index-trader contamination, ETF-roll tracking error).

  7. **Dashboard tab** renders the feature row with the correct
     health classification.

Verified by `tests/test_feature_foundry.py::test_cot_feature_end_to_end`.

## Ticker → market mapping (CFTC COT)

The shipped map covers ETFs whose underlying maps cleanly to a CFTC
futures market:

| Ticker | CFTC market |
|---|---|
| USO, UCO | WTI CRUDE OIL — NYMEX |
| GLD, IAU | GOLD — COMEX |
| SLV | SILVER — COMEX |
| UNG | NATURAL GAS — NYMEX |
| TLT, IEF | 10-YR US TREASURY NOTES — CBOT |
| DBA | WHEAT-SRW — CBOT |
| CORN | CORN — CBOT |
| SOYB | SOYBEANS — CBOT |
| UUP | US DOLLAR INDEX — ICE |

Tickers outside this map return `None` from the feature, which is
the correct behaviour (no spurious signals on unrelated equities).

## What is deliberately deferred

Per the dispatch boundaries, the substrate ships before integration.
Items intentionally out of scope for this round:

  1. **Cron scheduler** for the ablation runner. The runner is a pure
     callable; wrapping it in a cron (e.g. weekly via the existing
     `scripts/` infrastructure) is the next-round task.

  2. **Production backtest closure** for the ablation `backtest_fn`.
     Will be a closure over the deterministic harness entry point;
     blocks on the gauntlet architectural fix shipped on the parallel
     `gauntlet-architectural-fix` workstream.

  3. **Real CFTC fetcher.** The production fetcher (HTTP download of
     the legacy zip archive) is straightforward but kept out of the
     skeleton — the substrate is verified end-to-end with a local
     fixture.

  4. **Meta-learner integration.** Foundry features are not yet
     consumed by `engines/engine_a_alpha/signal_processor` or any
     downstream meta-learner. Both real and adversarial features will
     plug in identically once the meta-learner accepts a generic
     `(ticker, date) -> Optional[float]` panel.

  5. **CI gate** that fails any commit introducing a feature without
     a model card or with validator errors. Validator is callable
     today; wiring it into the existing pre-commit / CI path is a
     follow-up.

  6. **Track-F additional sources** (FDA, Polymarket, USPTO,
     OpenSky, EIA, USAspending, Wikipedia, etc.). The plugin pattern
     is established; each new source is a standalone PR.

  7. **Auto-pruning under the 90-day archive rule.** Today the
     dashboard surfaces stale features as warn; auto-archiving them
     into a `tier='archived'` state is a downstream addition.

  8. **Per-feature cron-driven freshness refresher.** Each
     DataSource has `fetch_cached(force_refresh=True)`; a periodic
     refresher will land alongside the ablation cron.

These deferrals are explicit so the next dispatch round can pick
them up without re-discovering scope.

## Engine boundaries respected

  - No engine code modified except `cockpit/dashboard_v2/` (the
    analytics-tab parent + new tab + callbacks + loader).
  - `engines/engine_a_alpha/edge_registry.py` untouched. The Foundry
    feature tier vocabulary is separate (A/B/adversarial vs
    alpha/feature/context).
  - `cockpit/dashboard/` (deprecated) untouched per CLAUDE.md.
  - No `data/governor/` writes. No `live_trader/` touches.
  - `data/feature_foundry/cache/` and `data/feature_foundry/ablation/`
    are new gitignored output directories.

## Test coverage

`tests/test_feature_foundry.py` — 29 tests, all passing:

  - DataSource cache: write-through, force-refresh, schema-invalid
    rejection, registry round-trip.
  - Feature decorator: metadata capture, invalid-tier rejection,
    id-collision-with-different-func rejection, panel evaluation.
  - Ablation: LOO contribution math, persistence + reload, empty-set
    handling.
  - Adversarial: twin id naming, distribution preservation +
    alignment destruction, determinism across calls, twin-of-twin
    rejection.
  - Model card: round-trip, missing-key rejection, validator catches
    missing card / license mismatch / orphan card, validator clean
    on a well-formed setup.
  - Dashboard: layout renders, callback registers against a Dash app,
    loader returns expected record shape.
  - CFTC COT: fetch with local fixture, freshness initially false,
    default fetcher raises clear error, **end-to-end** (source +
    feature + twin + ablation + model card + dashboard row).

## Follow-up work (queued for the round after this one)

  1. Wire the production CFTC fetcher (HTTP + zip extraction).
  2. Land a cron scheduler for `run_ablation` against the
     deterministic harness backtest.
  3. Add the second Foundry source (FDA approvals or Polymarket per
     reviewer Track-F priorities).
  4. Integrate Foundry features into the meta-learner consumption
     path once the meta-learner accepts a generic feature panel.
  5. Add CI gate calling `validate_all_model_cards()`.
  6. Implement `tier='archived'` auto-pruning under the 90-day rule.
