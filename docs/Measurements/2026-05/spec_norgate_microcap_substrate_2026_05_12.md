# Spec — T-2026-05-12-056: Norgate microcap substrate integration

**Date drafted:** 2026-05-12 LATE (director-side, post-research-synthesis)
**Status:** SPEC for queue. **Blocked on USER ACTION: Norgate Data subscription ($80/mo). User has approved the spend.**
**Will be executed by:** Agent A or B once Norgate credentials are in `.env` (~12-16 hr).
**Sequencing:** independent of T-054, T-055; can dispatch in parallel once data access ready.
**Output:** new substrate adapter + microcap universe ($50M-$500M cap, ~1500 tickers) + cost model + smoke validation + audit doc.

---

## Why this is the project's biggest substrate move

Per the 2026-05-16 alpha research dive's #1 recommendation:

> "The biggest strategic miss is substrate, not strategy. Microcap ($50M-$500M cap) is structurally where retail alpha lives. The team has never tested its architecture on the substrate where retail alpha is structurally available."

Mechanism: institutional capital is mandate-blocked from microcaps (S&P 500 needs >$22.7B market cap; Russell 1000 floor ~$3B; most pension/insurance mandates exclude below $200M-$500M). Hou-Xue-Zhang's "trading frictions" anomalies that fail at NYSE breakpoints **succeed in microcaps** because the binding factor is capital constraint, not signal degradation. McLean-Pontiff's 58% post-publication decay is weaker in microcaps because institutional arbitrage capital is structurally absent.

Our 0/11 factor-α verdict on S&P 500 substrate-honest universe is **academically validated** by the dive's literature review — that result is EXPECTED on liquid US large-cap. The substrate × strategy combination targets the empty quadrant of retail alpha space.

**The microcap substrate experiment is the structural fix the empirical findings argue for.**

---

## Prerequisites (USER ACTION before dispatch)

1. **Norgate Data subscription** at $80/mo: https://norgatedata.com/
   - "Stock Histories: US Indices" includes survivorship-bias-free history back to ~1990 for delisted + active names
   - Required for any microcap work (yfinance silently inflates microcap backtests by 2-5% annualized per the dive)
2. **Credentials added to `.env`** (or wherever the project loads API keys) under `NORGATE_API_KEY`
3. **Confirm coverage**: Norgate provides daily OHLCV + delisting flags + corporate actions for US equities. Sample a few known-delisted microcaps (e.g., late-2010s biotech failures) to confirm history is complete.

---

## What

### Phase 1 — Substrate adapter (~4-5 hr)

`engines/data_manager/norgate_adapter.py` (NEW):

```python
class NorgateAdapter:
    """
    Survivorship-bias-free historical US equity adapter for microcap work.

    Loads daily OHLCV for the requested universe + date range, including
    delisted tickers with proper delisting returns (-30% to -100% on failures
    per CRSP convention).

    Capacity: this is the substrate where retail alpha lives per
    Hou-Xue-Zhang / McLean-Pontiff / Cusatis-Miles-Woolridge convergence.
    """

    def load_universe(self, market_cap_range: Tuple[float, float],
                      asof_date: pd.Timestamp) -> List[str]:
        """Return tickers in [low_cap, high_cap] at point-in-time asof_date."""

    def load_bars(self, ticker: str, start: date, end: date) -> pd.DataFrame:
        """Load OHLCV; INCLUDES delisting returns for tickers that died in window."""
```

### Phase 2 — Microcap universe build (~2 hr)

`scripts/build_microcap_universe_t056.py`:

- Universe definition: tickers with market cap ∈ [$50M, $500M] at point-in-time
- Window: 2010-2024 (15 years; deeper than current substrate-honest 5yr per MBL constraints)
- Output: `data/universes/microcap_50m_500m_pit.parquet` with (ticker, date_first_in_universe, date_last_in_universe) — point-in-time membership tracking

Universe stats expected:
- ~1500 unique tickers entering/exiting over 15 years
- ~600-900 tickers in universe at any given point
- ~30-40% delisting rate over 15 years (high baseline for microcaps)

### Phase 3 — Microcap-specific cost model (~2-3 hr)

`engines/engine_b_risk/cost_model_microcap.py` (NEW; do NOT modify the existing equity cost model):

```python
class MicrocapCostModel:
    """
    Cost model calibrated for $50M-$500M cap names.

    Per the research dive: "Rule of thumb: if your backtest shows SR > 2
    and depends on round-trip cost <10 bps, redo at 25 bps before believing
    it. For microcaps, assume 50-100 bps round-trip minimum."

    Components:
    - Bid-ask half-spread: 25-50 bps (vs 1-5 bps for mega-cap)
    - Market impact: square-root law ΔP/P ≈ Y·σ·√(Q/V), Y ≈ 0.5-1.0
    - ADV-based position cap: ≤2% of 20-day ADV per name (non-negotiable)
    - Slippage: stochastic 20-50% of half-spread on top of mid-price fill
    """
```

### Phase 4 — Smoke validation: re-test existing edges on microcap substrate (~4-5 hr)

Run TWO edges from the existing inventory on the new microcap substrate:

1. **`insider_cluster_v1`** — per the dive: "20+ years of mining; HFTs front-run filings within minutes; SEC's December 2022 10b5-1 reform shortened plan cooling-off periods. Move insider_cluster_v1 to a microcap universe and re-test." Cohen-Malloy-Pomorski (2012) showed EW long-short generated 180 bps/month (~21.6% annualized, t=6.07) on opportunistic insider trades.

2. **Mean-reversion variant** (RSI(2) or similar) — per dive: "Microcap mean-reversion with regime filter is the cleanest standalone retail alpha. Quantitativo's 2024 RSI(2) replication: Sharpe 1.14, CAGR 25.7% vs NDX 17.6% (2010-2024)."

A/B per substrate: S&P 500 substrate vs microcap substrate. Same edge, same window, different universe + different cost model.

**Per CLAUDE.md 6th non-negotiable**: bootstrap CI on every Sharpe.

### Phase 5 — Audit doc + state updates (~1-2 hr)

`docs/Audit/microcap_substrate_smoke_2026_05_12.md`:
- Universe build statistics (ticker count, delisting rate, market-cap distribution)
- Per-edge Sharpe S&P 500 vs Microcap substrate, with bootstrap CI
- Cost model calibration evidence
- Forward-look: which other existing edges deserve microcap re-test in T-056b

---

## Acceptance

1. **`engines/data_manager/norgate_adapter.py`** with universe + bar loaders + delisting handling
2. **`scripts/build_microcap_universe_t056.py`** produces `data/universes/microcap_50m_500m_pit.parquet`
3. **`engines/engine_b_risk/cost_model_microcap.py`** with MicrocapCostModel; does NOT modify existing equity cost model
4. **A/B smoke**: `insider_cluster_v1` + RSI(2) variant on S&P 500 vs microcap substrate
5. **Output table**:
   | Edge | S&P 500 Sharpe (ci_low) | Microcap Sharpe (ci_low) | Δ |
   |---|---|---|---|
   | `insider_cluster_v1` | ? | ? | ? |
   | `rsi_2_microcap_mean_reversion_v1` | ? | ? | ? |
6. **Determinism**: 3-rep bitwise canon md5 per cell
7. **Tests** in `tests/test_norgate_adapter.py` + `tests/test_microcap_cost_model.py`:
   - Adapter loads known historical universe correctly
   - Delisting returns applied to known failures (e.g., bankruptcies in 2015-2024)
   - Cost model: 50-100 bps round-trip on synthetic microcap trades
   - Cost model: ADV cap rejects oversized trades
8. **Audit doc** at `docs/Audit/microcap_substrate_smoke_2026_05_12.md`
9. **State doc updates**: forward_plan + health_check + lessons_learned
10. **Branch:** `feature/norgate-microcap-substrate`. Push only; director merges.

---

## Hard constraints

- DO NOT modify the existing S&P 500 substrate or cost model. The microcap substrate is PARALLEL infrastructure.
- DO NOT mix S&P 500 and microcap trade logs in the same backtest. Separate run, separate substrate.
- DO NOT use yfinance for microcap history. Norgate is required for survivorship-bias-free data.
- Per microcap-specific: ≤2% of 20-day ADV per name. Non-negotiable.
- Per CLAUDE.md: this is a NEW external dependency (Norgate API). **User has approved the spend 2026-05-12.**
- Per CLAUDE.md 6th non-negotiable: bootstrap CI on every Sharpe headline.

---

## Time budget

- Phase 1 (adapter): 4-5 hr
- Phase 2 (universe build): 2 hr
- Phase 3 (cost model): 2-3 hr
- Phase 4 (smoke A/B): 4-5 hr (60 backtests at vectorized speed: 30 cells × 2 substrates)
- Phase 5 (audit doc): 1-2 hr
- **Total: 12-16 hr**

---

## Open questions for implementing agent (surface in audit doc)

1. **Norgate API rate limits?** Their docs should specify; respect them. If batch downloads are required, document.

2. **Historical depth: 2010-2024 or 1990-2024?** Per the MBL math (T-050 candidate), deeper history is structurally valuable. Recommend start with 2010-2024 for v1 (matches existing S&P 500 substrate window for direct A/B), then extend in T-056b if results are promising.

3. **Market-cap cutoffs: strict 50M-500M or 50M-1B?** Strict 50M-500M per the dive's recommendation; below ~$200M coverage thins; below ~$100M most mandates exclude. The 500M ceiling separates from the existing S&P 500 substrate cleanly.

4. **Should the cost model also include borrow rates?** Yes for any future short-side test, but Phase 4's smoke is long-only — defer borrow modeling to T-056b.

5. **Should we include both NYSE + NASDAQ microcaps?** Yes — universe is "tradable US microcap." Pink sheets / OTC explicitly excluded (capacity + execution issues at retail).

---

## Forward-look (after T-056 lands)

If smoke shows microcap substrate produces materially higher edge Sharpes than S&P 500 substrate for the same edges:
- T-056b: extend to all currently-paused edges (PEAD variants, momentum_6_1, low_vol_factor, etc.) on microcap substrate
- T-056c: build microcap-native edges (RSI(2) variant, OS-cluster + insider, post-bankruptcy reversion)
- T-050: extend microcap substrate back to 1990 (multi-decade extension addresses the MBL gap)
- Reframe project: microcap becomes the canonical alpha substrate; S&P 500 becomes factor-replication baseline

If smoke shows microcap substrate is similar to or worse than S&P 500 substrate for the same edges:
- Diagnose: is the cost model too aggressive? Are the edges genuinely substrate-independent (= factor-bound)?
- This would significantly weaken the alpha-research dive's substrate-is-the-issue framing — falsification is informative

---

## Director note + user approval gate

User has explicitly approved the Norgate $80/mo spend 2026-05-12 ("maybe everything outside LLM"). User action required before dispatch: subscribe to Norgate + add credentials to `.env`. Director will surface a 1-line check ("Norgate credentials in place?") before dispatching to an agent.

This task is the project's first DELIBERATE substrate pivot. Per the research dive: "The team has been searching honestly in the wrong place. That's a much better diagnosis than 'the strategies don't work' — because it implies a specific actionable fix: change the substrate, not the strategies."
