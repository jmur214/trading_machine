# Spec — T-2026-05-12-042: Engine D input-library expansion (insider audit + short interest + GDELT regime feed)

**Date drafted:** 2026-05-12 (director-side, ~50 min)
**Status:** SPEC for approval. Engine D scope (autonomous-improvement allowance per CLAUDE.md) but adds Engine E regime input — at the boundary, propose-first applied.
**Will be executed by:** Agent A or B in two phases (~3 hr Phase 1, then conditional ~6-8 hr Phase 2).
**Sequencing:** can run in parallel with T-040 (different file surfaces). After A's current measurement chain lands.
**Output:** Phase 1 = inventory audit; Phase 2 = 2-3 new features in Foundry library + Engine D gene-vocabulary update + GDELT regime feature for Engine E + tests.

---

## Why now

T-021, T-025, T-026 Discovery cycles found Engine D's GA only produces variations of existing archetypes. T-022 fixed gene-encoding so foundry_feature genes can appear in candidates. T-024 enriched seed population. The mechanical bottleneck is now closed — but the next bottleneck is **input vocabulary**.

Engine D currently combinatorially searches over a feature library that's still mostly price-momentum + value-quality + calendar derivatives. The library doesn't include:

- **Insider trading activity** — Form 4 filings. We already have a `data/insider/` directory but it's under-used (last referenced in `project_lifecycle_phase_abg_shipped_2026_04_24.md`, never wired into Foundry).
- **Short interest** — FINRA biweekly free data. Well-documented anomaly source (Diether-Lee-Werner 2009 et al). Currently zero presence in the system.
- **News-flow regime signal** — GDELT v2 free event-coded news archive. Per 2026-05-12 user-clarified scope: aggregate market-level, not per-ticker. Feeds Engine E (regime) and optionally Engine A (market-state gate).

The bet: Engine D's GA will find combinations once the library is wide enough. We don't need a new ML architecture; we need richer raw inputs. **Two cheap wins already on disk or free, one strategic addition.**

Cost ranking by leverage:

| Source | Cost | Hypothesized lift |
|---|---|---|
| `data/insider/` audit | $0 (data already on disk) | medium — Form 4 signal value is documented; coverage TBD |
| FINRA short interest | $0 (free public data, biweekly cadence) | high — squeeze + decay anomalies are well-documented |
| GDELT v2 regime feature | $0 (free, structured event-coded news) | unclear — first-time validation of news regime signal in our system |

---

## What — Phase 1 (audit, ~3 hr)

Phase 1 is pure investigation + planning. No feature integration. Output is an audit doc that ENABLES Phase 2 dispatch decisions.

### 1.1 Audit `data/insider/`

- Inventory: file list, schema (column names, types), date coverage, ticker coverage
- Sample a few records: are they Form 4 transactions? Aggregated? Cleaned?
- Look for completeness gaps: missing months, missing tickers from F6 universe
- Identify the data source (SEC EDGAR Form 4 scraper? Quandl/SimFin export? Bought dataset?)
- Determine point-in-time semantics: is the data filed-date timestamped, or is it event-date (transaction-date) only? Filed date is what a real trader sees; event date is look-ahead-leaky.

### 1.2 Survey FINRA short interest sources

- FINRA's free biweekly short interest data is at https://www.finra.org/finra-data/browse-catalog/short-sale-volume-data
- Coverage: typically NYSE + NASDAQ from 2017+. Free CSV download per settlement date.
- Settlement date vs reporting date: short interest is reported with ~7-9 day lag from settlement date. Point-in-time alignment: only use data with `reporting_date <= current_bar_date`.
- Alternative free source: Yahoo Finance `Ticker.info` has `shortPercentOfFloat` and `sharesShort` but only current (not historical).
- Yfinance `Ticker.shares` has historical short interest in some cases — verify coverage.

### 1.3 Verify GDELT v2 access

- Endpoint: `https://api.gdeltproject.org/api/v2/doc/doc?...`
- BigQuery public dataset for bulk historical access: `gdelt-bq.gdeltv2.events`
- Free for non-commercial use; commercial use requires accommodation
- Output is event-coded news (politic, economic, etc.) with timestamps + tone scores
- For our use: aggregate daily counts of (event_type, tone) — gives us "news-flow volume" + "average news tone" per day, market-wide

### 1.4 Look-ahead safety verification

For each data source, document:
- What timestamp do we have (filed/reported/event)?
- What lag exists between the event and the timestamp?
- Is there any way the backtest could "see" a data point before a real trader could?

### 1.5 Phase 1 audit doc

`docs/Audit/engine_d_input_expansion_phase1_2026_05_12.md`:
- Insider data inventory
- Short interest source choice + coverage
- GDELT integration sketch
- Look-ahead safety matrix per source
- Recommended Phase 2 priority ordering (which feature first; which deferred)
- Stop/go decision: if any source has fatal look-ahead issues, abort Phase 2 for that source

---

## What — Phase 2 (build, conditional on Phase 1, ~6-8 hr)

Phase 2 dispatches only after Phase 1 audit doc lands + user reviews. Implementer picks the top 2-3 features per Phase 1 prioritization.

### 2.1 Insider activity feature(s)

Likely candidates (Phase 1 audit will refine):
- `insider_buy_intensity_60d`: rolling 60-day count of net-positive Form 4 transactions per ticker
- `insider_sell_intensity_60d`: opposite
- `insider_net_signal_60d`: buy - sell (could be a single composite)

Wire into `engines/engine_d_discovery/foundry/feature_factory.py`:
- New feature class with `compute(market_data, lookback)` method
- Point-in-time enforced: only Form 4 filings with `filing_date <= bar_date`

### 2.2 Short interest feature(s)

- `short_interest_ratio`: shares short / float
- `short_interest_change_30d`: 30-day delta of short interest ratio
- `days_to_cover`: shares short / 20d avg volume

Same Foundry integration as 2.1. Biweekly cadence means feature is updated every 2 weeks; forward-fill between updates.

### 2.3 GDELT regime feature

- `gdelt_news_volume_market`: total event count today vs 30-day rolling mean
- `gdelt_tone_market`: average tone score across all events today
- `gdelt_crisis_event_count`: count of negative-tone events with specific event codes (e.g., MAKEPUBLICSTATEMENT, THREATEN, CONFRONT)

Wire into:
1. **Engine D Foundry**: as a feature available for GA combinatorial use
2. **Engine E regime classifier** (`engines/engine_e_regime/hmm_regime.py` or equivalent): as a candidate feature input. Phase 2 ADDS the feature panel; does NOT retrain HMM with it (that's a separate decision per regime-analyst lens). Document as "available for future HMM input panel rebuild."

### 2.4 Engine D gene-vocabulary update

`engines/engine_d_discovery/gene_encoding.py` (or wherever `_create_random_gene` lives, per the 2026-05-11 memory entry):
- Add gene types: `foundry_feature_insider_*`, `foundry_feature_shortinterest_*`, `foundry_feature_gdelt_*`
- Update seed-population enricher to include 1-2 candidates per new feature type
- Verify with smoke test: cap=3 Discovery cycle produces ≥1 candidate referencing a new feature

### 2.5 Smoke validation

Cap=3 Discovery cycle on substrate-honest, journal-mode, with new features available:
- Should produce ≥1 candidate with a new-feature gene (vocab-extension check)
- Per-gate pass-rate same or better than current (no regression)
- Wall-time within 2× pre-fix (no catastrophic slowdown from new features)

### 2.6 Audit doc + state updates

`docs/Audit/engine_d_input_expansion_phase2_2026_05_12.md`:
- Features added (with code references)
- Point-in-time evidence per feature
- Smoke Discovery cycle output: candidate-level diagnostics
- Forward-look: cap=30 Discovery cycle as a separate dispatch (T-042b) once cockpit-fix-rebaselined canon is established

State-doc updates:
- `forward_plan.md`: Engine D input library now includes [N] new feature types
- `health_check.md`: any look-ahead issues found in Phase 1 surfaced as MEDIUM entries
- `lessons_learned.md`: what we learned about each data source's quality

---

## Acceptance

### Phase 1

1. **Audit doc complete** with sections for insider, short interest, GDELT.
2. **Look-ahead safety matrix** filled out per source.
3. **Phase 2 priority ordering** documented with rationale.
4. **Stop/go decision** explicit: which sources clear for Phase 2, which deferred or rejected.
5. **Branch:** `feature/engine-d-input-expansion-phase1-audit`. Push only.

### Phase 2 (conditional on Phase 1)

1. **≥2 new features** in `engines/engine_d_discovery/foundry/feature_factory.py`.
2. **Engine D gene vocabulary updated** to expose new feature types to GA.
3. **GDELT feature** available in Engine E feature panel (NOT yet wired into HMM training — separate decision).
4. **Smoke Discovery cycle**: cap=3 produces ≥1 candidate with new-feature gene.
5. **Tests** in `tests/test_engine_d_input_expansion.py`:
   - `test_insider_feature_point_in_time` — filing_date enforcement
   - `test_short_interest_feature_lag_correct` — settlement-vs-reporting date
   - `test_gdelt_feature_aggregate_market_level` — daily aggregate, not per-ticker
   - `test_gene_vocabulary_includes_new_features` — encoder produces new-feature genes
   - `test_seed_population_enriched_with_new_features` — at least 1 seed per new feature type
6. **Audit doc** at `docs/Audit/engine_d_input_expansion_phase2_2026_05_12.md`.
7. **Branch:** `feature/engine-d-input-expansion-phase2-build`. Push only.

---

## Hard constraints

- DO NOT retrain HMM in Phase 2. GDELT feature is ADDED to the panel; HMM retraining is a separate dispatch (regime-analyst lens, propose-first).
- DO NOT modify Engine A, Engine B, Engine C, or Engine F.
- DO NOT use any data with look-ahead bias. Phase 1 audit must explicitly verify timestamps per source.
- DO NOT modify the gauntlet thresholds. New features must clear t > 2 α like every other feature.
- Phase 2 dispatch is CONDITIONAL on Phase 1 user review. Do not auto-chain.
- Per CLAUDE.md: this is a 2-engine touch (Engine D + Engine E feature panel) — at the boundary of propose-first. **Proposed-first applied for visibility.**

---

## Time budget

Phase 1: ~3 hr (audit + survey + look-ahead verification + audit doc)
Phase 2: ~6-8 hr (2.5-3 hr per data-source integration × 2-3 sources, + tests + smoke + audit doc)

Total: ~9-11 hr across two dispatches, separated by user review of Phase 1.

---

## Open questions for the implementing agent

### Phase 1 questions

1. **What's actually in `data/insider/`?** Symlinked across worktrees, last touched 2026-04. May be a yfinance scrape, a one-time export, or empty placeholder. First action: `ls -la` and `head -3` on each file.

2. **FINRA short interest history depth.** How far back does the free data go? If only 2017+, that constrains backtest windows for any short-interest-using edge. Document.

3. **GDELT BigQuery vs API.** Free API has rate limits + result-size caps. BigQuery public dataset is unrestricted but requires GCP account + billing setup. RECOMMEND: API for v1 (low cost, lower scale); BigQuery if API rate-limits become binding.

4. **GDELT event-code selection.** GDELT has ~300 event codes; aggregating ALL of them produces noisy daily-volume signal. Better: pick a curated subset (economic + crisis-related codes). RECOMMEND a 20-30 code curated list in Phase 1 audit doc.

### Phase 2 questions

5. **Should insider feature be per-ticker or market-aggregate?** Form 4 is filed per-ticker per-officer. Aggregating to ticker-level (e.g., total net buying per ticker over 60d) makes sense for an alpha feature. Aggregating further to market-level (total insider activity across all S&P 500 names) could be a regime signal. RECOMMEND: ticker-level for Engine D Foundry feature; market-level deferred to future regime-analyst dispatch.

6. **GDELT feature lag.** GDELT data has ~15-minute lag from event to indexed record. For daily-bar backtest this is fine; for intraday it would matter. Document.

7. **Curated GDELT event-code list ownership.** Who maintains the list as GDELT's coding evolves? RECOMMEND: in `data/gdelt_curated_event_codes.yml`, user-maintainable, version-tagged. Document.

8. **Smoke validation: cap=3 vs cap=10.** Cap=3 is a fast sanity check; cap=10 is a real first-pass. Phase 2 specifies cap=3 for speed; full cap=30 Discovery is T-042b.

---

## Forward-look (T-042b + T-042c candidates)

After T-042 Phase 2 lands:

- **T-042b**: cap=30 Discovery cycle on substrate-honest with full input-expanded library (~3-5 hr). Tests whether the wider feature surface translates to better candidate generation rate. Requires T-040 (Parquet canon) so canon md5 doesn't shift mid-experiment.
- **T-042c**: HMM input panel rebuild incorporating GDELT regime feature (~6-8 hr, regime-analyst lens). Propose-first per Engine E touch. Per the 2026-05-06 memory entry, HMM input panel rebuild is the unblock condition for re-evaluating regime signal — this is a natural step toward it.
- **T-042d**: Insider feature as market-aggregate regime signal (~3 hr). Smaller scope; could bundle with T-042c.

---

## Director note

This spec is **propose-first** because:
1. Phase 2 touches Engine D Foundry AND adds a feature to Engine E's available panel. Two engines is at the boundary of propose-first.
2. The whole Engine D input library is load-bearing for autonomous Discovery; expanding it materially changes Engine D's search surface, which deserves user visibility.

Recommended sequencing:
1. T-034 + T-035 + T-036 + T-038 (current chains) land.
2. T-040 (Parquet migration) lands. Canon rebaseline established.
3. T-039 (observability relocation) lands. cockpit/ is dashboard-only.
4. T-042 Phase 1 (audit) dispatches. ~3 hr.
5. User reviews Phase 1 audit; decides which sources to build in Phase 2.
6. T-042 Phase 2 (build) dispatches. ~6-8 hr.
7. T-041 (spin-off edge) can run in parallel with Phase 2 (different file surfaces).
