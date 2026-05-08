# Trend-Following Phase 0 — Wider-Universe Verdict (722 tickers)

**Date:** 2026-05-08
**Companion to:** `docs/Measurements/2026-05/trend_phase0_verdict_2026-05-07.md` (the original 115-ticker mega-cap verdict)
**Hypothesis tested:** the prior verdict diagnosed trend as "beta-amplified on S&P mega-caps, not asymmetric upside" and recommended retesting on a more dispersion-rich universe. This run tests that hypothesis on the full 722-ticker pool available in `data/processed/` (mega-caps + mid-caps + small-caps + delisted-but-cached).

## Headline

**Hypothesis REFUTED.** Wider-universe trend is materially WORSE than mega-cap trend on every metric except skewness (which is unchanged). MDD kill threshold trips.

| metric | mega-cap (115) | wider (722) | delta |
|---|---:|---:|---:|
| Sortino | +1.467 | +0.456 | **−1.011** |
| Skewness | −0.153 | −0.133 | +0.020 (~flat) |
| Tail ratio | 0.997 | 0.979 | −0.018 (~flat) |
| Upside capture | 1.082 | 0.963 | −0.119 |
| Sharpe (xref) | +1.013 | +0.340 | −0.673 |
| Max drawdown | −23.30% | **−43.14%** | **−19.84pp worse** |
| Bootstrap Sortino 95% CI | [+0.189, +2.913] | **[−0.580, +1.519]** | CI now spans zero |
| Bootstrap P(>0) | 0.98 | 0.83 | weakened |

Wider-universe trend FAILs the gauntlet (1/4 criteria met) AND triggers the |MDD|>25% kill. Mega-cap trend FAILed (2/4) but didn't kill.

## Why the hypothesis was wrong

The mega-cap diagnosis correctly identified trend as beta-amplified — the symmetric tail ratio + flat skew was the tell. The leap to "wider universe gives upside skew" assumed that long-tail names would produce more momentum-driven big winners (the asymmetric-upside property). What actually happens:

1. **Idiosyncratic vol on small/mid caps drawdown harder.** When trend picks a mega-cap that reverses, position sizing already dampens the loss. When it picks a small-cap that reverses, the same position size translates to a much larger drawdown because the underlying is more volatile per unit weight.
2. **Inverse-vol weighting can't fully compensate.** It scales each position by 1/realized_vol, which equalizes ex-ante exposure. But realized vol is a backward-looking estimate; the actual forward path can blow well past the estimate, especially on small-caps with regime-shift risk.
3. **The long tail has more delisted / regime-changed names.** Some of the 722 are catch-up downloads of names that lost institutional coverage / structural prospects in the measured window. Trend latches onto recent winners and gets caught by these reversals.
4. **Skewness STILL didn't improve.** Even with 722 names (>6× the universe size), the skew sits at −0.133 (vs −0.153 on mega-caps). The asymmetric-upside property requires either: (a) a structurally convex strategy (LEAPS / call options), (b) a strategy whose loss is bounded but win is unbounded (e.g. event-driven on binary catalysts), or (c) a strategy that explicitly cuts losers (e.g. stop-loss + ride-winners disciplined trail). 12-month momentum + inverse-vol weighting doesn't have any of these properties on its own.

## What this finding tells us about the trend sleeve concept

The trend sleeve as currently designed (`engines/engine_c_portfolio/sleeves/trend_following_sleeve.py`):
- Long-only top-N momentum filter (252-day lookback)
- Inverse-vol weighting
- Monthly cadence

is **not** an asymmetric-upside vehicle. It's a Sharpe vehicle on mega-caps and a stretched-Sharpe-with-bigger-MDD vehicle on a wider universe. Both run as expected for what they are; neither passes the moonshot-style gauntlet because the gauntlet measures a different property.

Three honest paths forward (NOT pursued in this session — diagnostic stops here):

1. **Reframe the trend sleeve as a Sharpe vehicle, not a moonshot vehicle.** Use a different sleeve gauntlet (Sharpe + DSR + max-drawdown) that matches what trend actually delivers. Rename to `momentum_sharpe_sleeve` or similar; ship at lower capital_pct.
2. **Bolt on a stop-loss / trailing-stop mechanism.** Make the strategy structurally asymmetric by capping losses at, say, −15% from peak. This breaks symmetry of the return distribution by construction. Would need a real backtest harness with the cost layer, not the phantom measurement used here.
3. **Drop the trend sleeve entirely.** If we already have a Sharpe-vehicle in the core book, a second Sharpe-vehicle in a sleeve is redundant. The Moonshot sleeve still needs Phase 1 work (real OPRA + real catalysts) to be evaluated honestly.

## Methodology notes

- 722 tickers loaded from `data/processed/*_1d.csv`. Includes delisted names cached for substrate-honesty work.
- Same `TrendFollowingSleeve` config: `top_n=10`, `lookback_days=252`, `vol_window_days=63`, `max_position_weight=0.20`, monthly cadence, long-only.
- Same gauntlet criteria as the mega-cap run (`SleeveCriteria` for trend: Sortino≥1.2, Skew≥0.0, Tail-ratio≥1.2, Upside-capture≥0.7; MDD kill at 25%).
- Same window: 2021-01-01 → 2025-12-31.
- Phantom allocation — sleeve not wired into PortfolioEngine.allocate. No cost layer applied.

## Caveats

- The 722-ticker universe has data-quality variance: some tickers have shorter histories, some have post-delisting / corporate-action gaps. The trend filter requires ≥253 bars of history, which excludes the very newest IPOs but admits everything else.
- Inverse-vol weighting doesn't account for tracking-error vs benchmark; the strategy ends up with a different effective leverage profile on the wider universe than on the mega-cap subset. A leverage-matched comparison would be cleaner but is significantly more work.
- The MDD kill threshold (25%) was chosen for a moonshot-style gauntlet. Trend strategies historically tolerate 25-30% MDDs in their bad years. A trend-specific gauntlet would loosen this threshold.
- The kill-trigger here is informative even with the loose-fit threshold: a 43% MDD on a long-only-momentum strategy is bigger than what trend should produce. Suggests the strategy is taking on more idiosyncratic risk than designed.

## Bottom line

Two trend universes tested. Both FAIL the asymmetric-upside gauntlet. The mega-cap version is a respectable Sharpe vehicle (1.013) with bounded drawdown; the wider version is a noisier Sharpe vehicle (0.340) with severe drawdown. Neither delivers the property the gauntlet measures.

The trend sleeve, as designed, is not a moonshot vehicle on either universe. The next sensible step is either reframing the sleeve's purpose (Sharpe vehicle) or adding structural asymmetry (stop-losses, trailing trail). Both are out of scope for this session.
