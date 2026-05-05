"""Path C — compounder sleeve feasibility backtest.

DESIGN-PHASE FEASIBILITY TEST. Not production code.

Tests the architectural premise of the compounder sleeve from
docs/Measurements/2026-05/path_c_compounder_design_2026_05.md without committing to
a particular Engine C implementation. Standalone — does NOT touch
the production backtester.

History (2026-05-02 → 2026-05-05)
---------------------------------
The original synthetic version used 4 PRICE-DERIVED factor proxies
(mom_12_1, inv_vol, rev_1m, inv_mdd) on a 51-name curated universe.
That version FAILED (CAGR 12.03% vs SPY 13.69%, MDD -25.19%) — see
``project_compounder_synthetic_failed_2026_05_02``. Hypothesis: (a) 51
names too small for cross-sectional factor work, (b) price-derived
proxies aren't orthogonal to SPY without real fundamentals.

This version (2026-05-05) wires up the SimFin FREE adapter shipped
today and replaces the synthetic factors with real V/Q/A fundamentals
on a 350+ name S&P 500 ex-financials universe. Both code paths are
preserved:

    compute_composite_score_synthetic   — original 4 price-derived
                                            factors (Cell C of harness)
    compute_composite_score_real         — 6 V/Q/A fundamentals factors
                                            (Cell D of harness)

The script does NOT auto-run the harness. Pass ``--run`` to execute.

Real-fundamentals factors (Cell D)
----------------------------------
Per ``docs/Core/Ideas_Pipeline/path_c_unblock_plan.md`` §3, six factors
across three families:

  Value (HIGH = cheaper):
    1. earnings_yield_market = TTM_NetIncome / market_cap
    2. book_to_market        = total_equity   / market_cap

  Quality (HIGH = better):
    3. roic_proxy            = TTM_OperatingIncome*(1-0.21) / (equity+LT_debt)
                                (SimFin doesn't expose effective tax rate)
    4. gross_profitability   = TTM_GrossProfit / total_assets   (Novy-Marx)

  Accruals (HIGH = lower accruals = better quality earnings):
    5. inv_sloan_accruals    = -sloan_accruals
    6. inv_asset_growth      = -asset_growth

Each ranked cross-sectionally, equal-weight composite percentile.

Universe
--------
S&P 500 current-constituents ∩ NOT-financials ∩ SimFin coverage. The
financials exclusion is REQUIRED on the SimFin FREE tier (most banks
are missing). Approx 350-450 names depending on day's coverage.

Pass criterion (per task spec): compounder after-tax CAGR > SPY
after-tax CAGR over the run window with MDD >= -15%. Tax assumption:
15% LT cap gains on annual rebalance turnover.

Outputs (only when --run is passed)
-----------------------------------
- Console summary
- JSON results to data/research/path_c_synthetic_backtest.json
- Markdown summary to docs/Measurements/2026-05/path_c_compounder_synthetic_backtest_2026_05.md
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Repo-root on path so `engines.*` imports work when this script is
# run directly (the cross-script convention used by fetch_universe.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Synthetic-baseline universe — 50 liquid large-caps used by the
# original (failed) synthetic test. Preserved so Cell C of the eventual
# harness remains reproducible.
# ----------------------------------------------------------------------
# Curated to be representative across sectors; NOT a survivor-bias-free
# S&P 500 panel.

UNIVERSE_SYNTHETIC: List[str] = [
    # Tech
    "AAPL", "MSFT", "GOOGL", "META", "ORCL", "CSCO", "IBM", "ADBE", "INTC", "TXN",
    # Healthcare
    "JNJ", "PFE", "UNH", "MRK", "ABT", "LLY", "TMO", "BMY",
    # Financials
    "JPM", "BAC", "WFC", "C", "GS", "MS", "BLK",
    # Consumer
    "WMT", "HD", "PG", "KO", "PEP", "MCD", "NKE", "COST", "TGT",
    # Industrials
    "CAT", "BA", "HON", "GE", "MMM", "UPS", "LMT",
    # Energy
    "XOM", "CVX", "COP",
    # Materials/Utilities
    "LIN", "DD", "DUK", "SO", "NEE",
    # Telecom
    "VZ", "T",
]

# Backwards-compatible alias for the synthetic harness path.
UNIVERSE = UNIVERSE_SYNTHETIC

# Hard exclude list of financial-sector tickers. SimFin FREE tier does
# not cover most banks/insurers, and the compounder thesis (V/Q/A
# factors) doesn't translate cleanly to financial-sector accounting
# anyway (book-to-market on banks behaves differently from non-financials).
# This is a belt-and-suspenders alongside the GICS-sector filter in
# build_universe(): even if a financial leaks into the SimFin panel
# (e.g. BLK, V, MA which ARE present), we keep them out of the candidate
# universe.
FINANCIALS_HARD_EXCLUDE = {
    # Big banks
    "JPM", "BAC", "C", "WFC", "USB", "PNC", "TFC", "BK",
    # Investment banks / brokers
    "GS", "MS", "SCHW", "RJF", "LPLA",
    # Insurance
    "BRK.B", "BRK.A", "AIG", "MET", "PRU", "TRV", "ALL", "HIG", "PFG",
    "AFL", "AON", "MMC", "AJG", "WTW", "BRO", "CB", "CINF", "GL",
    "L", "PGR", "RE", "RGA", "WRB", "AIZ",
    # Asset managers
    "BLK", "BX", "KKR", "APO", "ARES", "AMP", "BEN", "IVZ", "TROW",
    "STT", "NTRS",
    # Card networks / payments (debatable; card networks behave more
    # like tech, but they're GICS Financials and we err conservative)
    "V", "MA", "AXP", "FI", "FIS", "PYPL", "GPN", "DFS", "COF", "SYF",
    # Exchanges / data
    "ICE", "CME", "NDAQ", "MKTX", "CBOE", "MCO", "SPGI", "MSCI",
    # Other financials
    "ACGL", "EVRG", "FITB", "HBAN", "KEY", "MTB", "RF", "ZION",
    "CFG", "FRC", "WAL", "PB", "WBS", "CMA",
    "ARES", "OWL", "WAB",
}


# ----------------------------------------------------------------------
# SimFin-aware universe construction (replaces the hardcoded list)
# ----------------------------------------------------------------------

def build_universe(
    panel: Optional[pd.DataFrame] = None,
    membership_cache_dir: Optional[Path] = None,
) -> List[str]:
    """S&P 500 current-constituents ∩ ex-financials ∩ SimFin coverage.

    Why ex-financials: SimFin FREE tier excludes most banks (JPM, BAC,
    C, WFC, GS, MS, USB, PNC, TFC, SCHW are confirmed missing as of
    2026-05-05). Also, V/Q/A factor accounting on financials behaves
    differently from non-financials (book-to-market on a bank is not
    the same construct as on a manufacturer), so excluding the sector
    is methodologically defensible regardless of data coverage.

    Order of operations:
      1. Pull current S&P 500 constituents from the cached membership
         loader (Wikipedia-scraped, refreshed weekly).
      2. Drop GICS Financials sector tickers.
      3. Drop the hard-exclude list (FINANCIALS_HARD_EXCLUDE) for
         belt-and-suspenders coverage of edge cases.
      4. Intersect with SimFin panel ticker coverage.

    Parameters
    ----------
    panel
        Pre-loaded SimFin fundamentals panel (avoids re-loading in
        tests). If None, loads via simfin_adapter.load_panel().
    membership_cache_dir
        Override for the SP500 membership parquet cache. Tests can
        point this at a fixture directory.

    Returns
    -------
    Sorted list of tickers, ~350-430 names depending on overlap.
    """
    # Lazy imports — keep the module importable when running the
    # synthetic-only path without SimFin credentials configured.
    from engines.data_manager.universe import SP500MembershipLoader

    candidate_dirs: List[Path] = []
    if membership_cache_dir is not None:
        candidate_dirs.append(Path(membership_cache_dir))
    else:
        # First try the worktree-local cache, then fall back to the
        # main repo's data/universe/ cache. Worktrees often share data
        # caches with their parent repo.
        candidate_dirs.append(
            Path(__file__).resolve().parents[1] / "data" / "universe"
        )
        # Walk up to find a non-worktree repo root with a populated cache.
        # Worktrees live under .claude/worktrees/<name>/; the parent repo
        # is up two levels from the worktree root.
        worktree_marker = Path(__file__).resolve().parents[1]
        if ".claude" in worktree_marker.parts and "worktrees" in worktree_marker.parts:
            idx = worktree_marker.parts.index(".claude")
            parent_repo = Path(*worktree_marker.parts[:idx])
            candidate_dirs.append(parent_repo / "data" / "universe")

    membership = None
    for cand in candidate_dirs:
        if not cand.exists():
            continue
        loader = SP500MembershipLoader(cache_dir=cand)
        df = loader.load_cached()
        if not df.empty:
            membership = df
            break

    if membership is None or membership.empty:
        raise RuntimeError(
            f"S&P 500 membership cache is empty at all of {candidate_dirs}. "
            f"Run: python -c 'from engines.data_manager.universe import "
            f"SP500MembershipLoader; SP500MembershipLoader().fetch_membership(force=True)'"
        )

    # Current constituents = rows with included_until NaT
    current = membership[membership["included_until"].isna()]

    # Drop financials by GICS sector
    sector_mask = ~current["sector"].astype(str).str.contains(
        "Financ", na=False, case=False
    )
    current_non_fin = current[sector_mask]
    sp500_ex_fin = set(current_non_fin["ticker"].unique())

    # Belt-and-suspenders hard exclude
    sp500_ex_fin = sp500_ex_fin - FINANCIALS_HARD_EXCLUDE

    # Intersect with SimFin coverage
    if panel is None:
        from engines.data_manager.fundamentals.simfin_adapter import load_panel
        panel = load_panel()

    simfin_tickers = set(panel.index.get_level_values("Ticker").unique())
    final = sorted(sp500_ex_fin & simfin_tickers)
    return final

BENCHMARK_TICKER = "SPY"
START_DATE = "2010-01-01"
END_DATE = "2024-12-31"
INITIAL_CAPITAL = 10_000.0
LT_CAP_GAINS_RATE = 0.15  # long-term federal rate (compounder annual rebal hits this)
ST_CAP_GAINS_RATE = 0.30  # for SPY 60-40 reference comparison if needed
ANNUAL_REBALANCE_MONTH = 1
ANNUAL_REBALANCE_DAY_NOMINAL = 5  # first ~trading day of January (5th to dodge holidays)
TOP_QUINTILE_FRAC = 0.20

DATA_CACHE = Path(__file__).resolve().parents[1] / "data" / "research" / "path_c_cache"
DATA_CACHE.mkdir(parents=True, exist_ok=True)


# ----------------------------------------------------------------------
# Data fetch
# ----------------------------------------------------------------------

def fetch_prices(tickers: List[str], start: str, end: str) -> pd.DataFrame:
    """Fetch adjusted close prices via yfinance, with parquet caching.

    Returns a DataFrame indexed by date, columns = tickers.
    """
    cache_path = DATA_CACHE / f"prices_{start}_{end}.parquet"
    if cache_path.exists():
        df = pd.read_parquet(cache_path)
        missing = [t for t in tickers if t not in df.columns]
        if not missing:
            return df.loc[start:end, tickers].copy()
        print(f"[fetch] cache exists but missing {len(missing)} tickers; refetching")

    try:
        import yfinance as yf
    except ImportError:
        print("[fetch] yfinance not installed; aborting", file=sys.stderr)
        sys.exit(1)

    print(f"[fetch] downloading {len(tickers)} tickers from yfinance...")
    raw = yf.download(
        tickers + [BENCHMARK_TICKER],
        start=start,
        end=end,
        auto_adjust=True,
        progress=False,
        threads=True,
    )
    if raw.empty:
        print("[fetch] yfinance returned empty frame", file=sys.stderr)
        sys.exit(1)

    if isinstance(raw.columns, pd.MultiIndex):
        prices = raw["Close"].copy()
    else:
        prices = raw[["Close"]].copy()
        prices.columns = tickers + [BENCHMARK_TICKER]

    prices.index = pd.to_datetime(prices.index).tz_localize(None)
    prices = prices.dropna(how="all")

    prices.to_parquet(cache_path)
    print(f"[fetch] cached {prices.shape} to {cache_path.name}")
    return prices


# ----------------------------------------------------------------------
# Factor computation — synthetic baseline (Cell C of harness)
# ----------------------------------------------------------------------

def compute_composite_score_synthetic(
    prices: pd.DataFrame,
    as_of: pd.Timestamp,
    universe: List[str],
) -> pd.Series:
    """SYNTHETIC (price-derived) composite — preserved as Cell C baseline.

    Uses 4 price-derived signals, equal-weighted on percentile ranks:
      - mom_12_1: 12-month return excluding most-recent month (Jegadeesh-Titman)
      - inv_vol:  -1 × 252d realized vol (low-vol → high score)
      - rev_1m:   -1 × 1-month return (mean-reversion guard, avoid hot names)
      - inv_mdd:  -1 × 252d max drawdown (drawdown-control → high score)

    Each percentile is in [0, 1]; composite is mean of the four. Returns
    a Series indexed by ticker; tickers without sufficient history get NaN
    and are dropped from the universe at this rebalance.

    This was the version that FAILED on the 51-name curated universe on
    2026-05-02 (CAGR 12.03% vs SPY 13.69%). Retained for harness
    reproducibility — the eventual 4-cell harness will compare this
    against real-fundamentals (Cell D) on the same wider universe.
    """
    end = as_of
    start_lookback = end - pd.DateOffset(years=2)

    window = prices.loc[start_lookback:end].copy()
    if window.empty:
        return pd.Series(dtype=float)

    available = [t for t in universe if t in window.columns]
    window = window[available]

    # 1) 12-1 momentum: return from t-12mo to t-1mo
    end_minus_1m = end - pd.DateOffset(months=1)
    end_minus_12m = end - pd.DateOffset(months=12)

    def _value_at(df: pd.DataFrame, dt: pd.Timestamp) -> pd.Series:
        sub = df.loc[:dt]
        if sub.empty:
            return pd.Series(dtype=float)
        return sub.iloc[-1]

    p_1m = _value_at(window, end_minus_1m)
    p_12m = _value_at(window, end_minus_12m)
    mom_12_1 = (p_1m / p_12m) - 1.0

    # 2) Inverse 252d vol
    daily_returns = window.pct_change().dropna(how="all")
    last_252 = daily_returns.tail(252)
    vol_252 = last_252.std() * np.sqrt(252)
    inv_vol = -vol_252

    # 3) Inverse 1-month return (mean-reversion guard)
    p_now = _value_at(window, end)
    rev_1m = -((p_now / p_1m) - 1.0)

    # 4) Inverse 252d max drawdown
    last_252_prices = window.tail(252)
    rolling_max = last_252_prices.cummax()
    drawdowns = (last_252_prices / rolling_max) - 1.0
    max_dd = drawdowns.min()  # most negative
    inv_mdd = -max_dd  # less negative DD = higher score

    factors = pd.DataFrame({
        "mom_12_1": mom_12_1,
        "inv_vol": inv_vol,
        "rev_1m": rev_1m,
        "inv_mdd": inv_mdd,
    })

    factors = factors.dropna(how="any")
    if factors.empty:
        return pd.Series(dtype=float)

    pct = factors.rank(pct=True)
    composite = pct.mean(axis=1)
    return composite.sort_values(ascending=False)


# Backwards-compatible alias — preserves any external callers that
# imported `compute_composite_score`. The synthetic path is the default
# only because it has no external-data prerequisite; the real path
# requires the SimFin panel.
compute_composite_score = compute_composite_score_synthetic


# ----------------------------------------------------------------------
# Factor computation — REAL fundamentals composite (Cell D of harness)
# ----------------------------------------------------------------------

# Effective tax rate proxy used in ROIC. SimFin doesn't expose a clean
# effective tax rate field; the federal statutory rate is a defensible
# proxy. Using a constant (vs ticker-specific) means ROIC is a *quality
# rank*, not an absolute return measure — which is fine for cross-sectional
# percentile composition.
_ROIC_TAX_RATE = 0.21


def _ttm_sum(
    panel: pd.DataFrame,
    ticker: str,
    asof_ts: pd.Timestamp,
    column: str,
    n_quarters: int = 4,
) -> Optional[float]:
    """Trailing-N-quarter sum of a flow item, PIT-correct via publish_date.

    SimFin stores QUARTERLY flow values (net_income, gross_profit, etc.).
    A TTM (trailing twelve months) figure requires summing the most
    recent 4 quarterly publishes that are <= asof_ts.

    Returns None if fewer than n_quarters of history are available.
    """
    try:
        ticker_slice = panel.xs(ticker, level="Ticker")
    except KeyError:
        return None

    eligible = ticker_slice[ticker_slice["publish_date"] <= asof_ts]
    if len(eligible) < n_quarters:
        return None

    # Most-recent N quarterly publishes
    recent = eligible.sort_values("publish_date").tail(n_quarters)
    vals = recent[column]
    if vals.isna().any():
        return None
    return float(vals.sum())


def _latest_balance_sheet_value(
    panel: pd.DataFrame,
    ticker: str,
    asof_ts: pd.Timestamp,
    column: str,
) -> Optional[float]:
    """Most-recently-published balance-sheet item known as of asof_ts.

    Balance sheet items are stocks (point-in-time), not flows — we want
    the latest snapshot, not a TTM sum.
    """
    try:
        ticker_slice = panel.xs(ticker, level="Ticker")
    except KeyError:
        return None
    eligible = ticker_slice[ticker_slice["publish_date"] <= asof_ts]
    if eligible.empty:
        return None
    latest = eligible.sort_values("publish_date").iloc[-1]
    val = latest.get(column)
    if val is None or pd.isna(val):
        return None
    return float(val)


def _latest_panel_value(
    panel: pd.DataFrame,
    ticker: str,
    asof_ts: pd.Timestamp,
    column: str,
) -> Optional[float]:
    """Most-recently-published value of any column, including precomputed factors.

    Used for sloan_accruals and asset_growth which the SimFin adapter
    already computed at panel-build time.
    """
    return _latest_balance_sheet_value(panel, ticker, asof_ts, column)


def compute_composite_score_real(
    prices: pd.DataFrame,
    as_of: pd.Timestamp,
    universe: List[str],
    panel: pd.DataFrame,
) -> pd.Series:
    """REAL-fundamentals composite — 6 V/Q/A factors via SimFin panel.

    Per ``docs/Core/Ideas_Pipeline/path_c_unblock_plan.md`` §3:

      Value (HIGH = cheaper):
        1. earnings_yield_market = TTM_NetIncome / market_cap
        2. book_to_market        = total_equity   / market_cap

      Quality (HIGH = better):
        3. roic_proxy            = TTM_OperatingIncome*(1-0.21) / (equity+LT_debt)
        4. gross_profitability   = TTM_GrossProfit / total_assets   (Novy-Marx)

      Accruals (HIGH = lower accruals = better quality earnings):
        5. inv_sloan_accruals    = -sloan_accruals
        6. inv_asset_growth      = -asset_growth

    Each factor cross-sectionally rank-percentiled; equal-weight composite.
    Tickers without sufficient PIT data (TTM requires ≥4 published quarters)
    are dropped from this rebalance.

    PIT discipline: all fundamentals are filtered on ``publish_date <=
    as_of``. Market cap uses the ``as_of`` price × the most-recent
    diluted-share-count published before as_of. No look-ahead.

    Parameters
    ----------
    prices
        Price panel (date × ticker), used only for market_cap on as_of.
    as_of
        Rebalance date.
    universe
        Candidate ticker list (already filtered to S&P 500 ex-financials
        ∩ SimFin coverage by ``build_universe()``).
    panel
        SimFin fundamentals panel from ``simfin_adapter.load_panel()``.

    Returns
    -------
    Composite percentile series indexed by ticker, sorted descending.
    """
    asof_ts = pd.Timestamp(as_of)

    # Snap as_of to a price-panel-available date if needed
    if asof_ts not in prices.index:
        sub = prices.loc[:asof_ts]
        if sub.empty:
            return pd.Series(dtype=float)
        asof_ts_price = sub.index[-1]
    else:
        asof_ts_price = asof_ts

    rows = []
    for ticker in universe:
        # Need a tradeable price on as_of
        if ticker not in prices.columns:
            continue
        px = prices.at[asof_ts_price, ticker]
        if pd.isna(px) or px <= 0:
            continue

        # TTM flow items (require 4 published quarters of history)
        ttm_ni = _ttm_sum(panel, ticker, asof_ts, "net_income")
        ttm_oi = _ttm_sum(panel, ticker, asof_ts, "operating_income")
        ttm_gp = _ttm_sum(panel, ticker, asof_ts, "gross_profit")

        # Stock items (latest published snapshot)
        equity = _latest_balance_sheet_value(panel, ticker, asof_ts, "total_equity")
        assets = _latest_balance_sheet_value(panel, ticker, asof_ts, "total_assets")
        lt_debt = _latest_balance_sheet_value(panel, ticker, asof_ts, "long_term_debt")
        shares = _latest_balance_sheet_value(panel, ticker, asof_ts, "shares_diluted")

        # Pre-computed factors from the adapter
        sloan = _latest_panel_value(panel, ticker, asof_ts, "sloan_accruals")
        ag = _latest_panel_value(panel, ticker, asof_ts, "asset_growth")

        # Skip if any required input is missing — keeps the cross-section clean.
        if any(x is None for x in (
            ttm_ni, ttm_oi, ttm_gp, equity, assets, shares, sloan, ag
        )):
            continue
        if shares <= 0 or assets <= 0:
            continue

        market_cap = px * shares
        if market_cap <= 0:
            continue

        # Defensive denominators — equity can be negative for highly
        # levered names; treat negative-equity book/market as missing
        # rather than producing a misleading sign.
        if equity is None or equity <= 0:
            book_to_market = np.nan
        else:
            book_to_market = equity / market_cap

        earnings_yield = ttm_ni / market_cap

        # ROIC denominator: use total invested capital ≈ equity + LT debt
        # (SimFin doesn't expose Cash-and-Equivalents-net cleanly across
        # all tickers; equity + LT-debt is the academic-friendly proxy).
        invested_capital = (equity if equity and equity > 0 else 0.0) + \
                           (lt_debt if lt_debt and lt_debt > 0 else 0.0)
        if invested_capital <= 0:
            roic = np.nan
        else:
            roic = (ttm_oi * (1.0 - _ROIC_TAX_RATE)) / invested_capital

        gross_profitability = ttm_gp / assets
        inv_sloan_accruals = -sloan
        inv_asset_growth = -ag

        rows.append({
            "ticker": ticker,
            "earnings_yield_market": earnings_yield,
            "book_to_market": book_to_market,
            "roic_proxy": roic,
            "gross_profitability": gross_profitability,
            "inv_sloan_accruals": inv_sloan_accruals,
            "inv_asset_growth": inv_asset_growth,
        })

    if not rows:
        return pd.Series(dtype=float)

    factors = pd.DataFrame(rows).set_index("ticker")

    # Drop rows with all-NaN factor values; for partial-NaN, rank=pct
    # naturally handles missing values (NaN excluded from rank).
    factors = factors.dropna(how="all")
    if factors.empty:
        return pd.Series(dtype=float)

    pct = factors.rank(pct=True)
    # mean across factors, skipping NaN — a ticker with 5/6 factors
    # available still gets a valid composite score, weighted by what
    # it has.
    composite = pct.mean(axis=1, skipna=True)
    composite = composite.dropna()
    return composite.sort_values(ascending=False)


# ----------------------------------------------------------------------
# Compounder backtest
# ----------------------------------------------------------------------

@dataclass
class RebalanceEvent:
    date: str
    n_held: int
    long_basket: List[str]
    pre_rebalance_value: float


@dataclass
class BacktestResult:
    label: str
    cagr_pretax: float
    cagr_aftertax: float
    sharpe_pretax: float
    max_drawdown: float
    final_equity_pretax: float
    final_equity_aftertax: float
    annual_returns: Dict[str, float]
    n_rebalances: int
    avg_holding_period_days: float


def get_first_trading_day_of_january(prices: pd.DataFrame, year: int) -> Optional[pd.Timestamp]:
    """Find the first available trading day in January of `year`."""
    jan = prices.loc[f"{year}-01-01":f"{year}-01-31"]
    if jan.empty:
        return None
    return jan.index[0]


def run_compounder_backtest(
    prices: pd.DataFrame,
    universe: List[str],
    initial_capital: float,
    lt_tax_rate: float,
    panel: Optional[pd.DataFrame] = None,
    use_real_fundamentals: bool = False,
    label: str = "compounder_synthetic",
) -> Tuple[BacktestResult, pd.Series, List[RebalanceEvent]]:
    """Long-only annual-rebalance equal-weighted top-quintile compounder.

    Tax model: at each annual rebalance, all positions sold are deemed
    long-term (>= 365d held by construction). Realized gains are taxed at
    `lt_tax_rate`; tax is paid out of cash before the new basket is bought.
    Realized losses offset gains within the same tax year up to the gains
    amount; excess losses are carried forward (capped at $3K/yr per IRS,
    but for the equity simulation we apply full carry-forward to keep math
    simple — the conservatism point is that our after-tax CAGR figure
    *under-reports* the after-tax benefit of LT vs ST).

    Parameters
    ----------
    use_real_fundamentals
        If True, dispatches to ``compute_composite_score_real`` (requires
        ``panel``). If False (default), uses the legacy synthetic
        price-derived composite — preserved for Cell C of the harness.
    panel
        SimFin fundamentals panel. Required when use_real_fundamentals=True.
    label
        Tag attached to the BacktestResult.
    """
    if use_real_fundamentals and panel is None:
        raise ValueError(
            "panel must be provided when use_real_fundamentals=True"
        )
    daily_index = prices.index
    cash = initial_capital
    holdings: Dict[str, float] = {}  # ticker -> shares
    cost_basis: Dict[str, float] = {}  # ticker -> avg buy price
    equity_pretax = pd.Series(index=daily_index, dtype=float)
    equity_aftertax = pd.Series(index=daily_index, dtype=float)
    aftertax_cash = initial_capital
    realized_pnl_pretax = 0.0
    realized_pnl_aftertax = 0.0
    cumulative_tax_paid = 0.0
    loss_carry_forward = 0.0

    rebalance_dates: List[pd.Timestamp] = []
    rebalance_events: List[RebalanceEvent] = []

    years = sorted(set(daily_index.year))
    for yr in years:
        rd = get_first_trading_day_of_january(prices, yr)
        if rd is None:
            continue
        rebalance_dates.append(rd)

    holding_period_days_log: List[int] = []
    last_buy_date_per_ticker: Dict[str, pd.Timestamp] = {}

    for i, dt in enumerate(daily_index):
        # Mark-to-market for equity tracking
        mv = sum(
            shares * prices.at[dt, t]
            for t, shares in holdings.items()
            if t in prices.columns and not np.isnan(prices.at[dt, t])
        )
        equity_pretax.iat[i] = cash + mv
        # After-tax tracking: same MV but separate cash bucket reflecting
        # taxes already paid in prior rebalances
        equity_aftertax.iat[i] = aftertax_cash + mv

        # Rebalance check
        if dt in rebalance_dates:
            if use_real_fundamentals:
                composite = compute_composite_score_real(
                    prices, dt, universe, panel
                )
            else:
                composite = compute_composite_score_synthetic(
                    prices, dt, universe
                )
            if composite.empty:
                continue

            n_top = max(1, int(len(composite) * TOP_QUINTILE_FRAC))
            new_basket = list(composite.head(n_top).index)

            # Sell everything not in new basket (and rebalance everything for equal-weight)
            sell_targets = list(holdings.keys())
            cycle_realized_pretax = 0.0

            for t in sell_targets:
                if t not in prices.columns:
                    continue
                px = prices.at[dt, t]
                if np.isnan(px):
                    continue
                shares = holdings[t]
                proceeds = shares * px
                gain = proceeds - shares * cost_basis[t]
                cycle_realized_pretax += gain

                if t in last_buy_date_per_ticker:
                    holding_period_days_log.append(
                        (dt - last_buy_date_per_ticker[t]).days
                    )
                cash += proceeds
                aftertax_cash += proceeds
                holdings.pop(t)
                cost_basis.pop(t)
                last_buy_date_per_ticker.pop(t, None)

            # Tax on net realized gains (LT rate applied; losses carried fwd)
            taxable_gain = cycle_realized_pretax - loss_carry_forward
            if taxable_gain > 0:
                tax_owed = taxable_gain * lt_tax_rate
                aftertax_cash -= tax_owed
                cumulative_tax_paid += tax_owed
                loss_carry_forward = 0.0
            else:
                # Net loss: add to carry-forward
                loss_carry_forward += abs(min(0.0, cycle_realized_pretax))

            realized_pnl_pretax += cycle_realized_pretax

            # Buy new basket equal-weighted from cash
            mv_post_sell = 0.0  # all positions liquidated
            buying_power_pretax = cash
            buying_power_aftertax = aftertax_cash
            target_per_name = buying_power_pretax / max(1, len(new_basket))
            target_per_name_aftertax = buying_power_aftertax / max(1, len(new_basket))

            for t in new_basket:
                if t not in prices.columns:
                    continue
                px = prices.at[dt, t]
                if np.isnan(px) or px <= 0:
                    continue
                shares = target_per_name / px
                holdings[t] = shares
                cost_basis[t] = px
                last_buy_date_per_ticker[t] = dt
                cash -= shares * px

            # Re-sync after-tax cash post-buy: (aftertax_cash already had
            # tax debited; the same shares are bought against it)
            aftertax_cash -= sum(holdings[t] * cost_basis[t] for t in holdings)

            rebalance_events.append(RebalanceEvent(
                date=dt.strftime("%Y-%m-%d"),
                n_held=len(holdings),
                long_basket=new_basket,
                pre_rebalance_value=equity_pretax.iat[i],
            ))

    # End-of-backtest: liquidate everything for honest final-equity
    last_dt = daily_index[-1]
    final_realized_pretax = 0.0
    for t in list(holdings.keys()):
        if t not in prices.columns:
            continue
        px = prices.at[last_dt, t]
        if np.isnan(px):
            # find last available price
            last_valid = prices[t].dropna()
            if last_valid.empty:
                continue
            px = last_valid.iloc[-1]
        shares = holdings[t]
        proceeds = shares * px
        gain = proceeds - shares * cost_basis[t]
        final_realized_pretax += gain
        cash += proceeds
        aftertax_cash += proceeds
        holdings.pop(t)

    final_taxable = final_realized_pretax - loss_carry_forward
    if final_taxable > 0:
        final_tax = final_taxable * lt_tax_rate
        aftertax_cash -= final_tax
        cumulative_tax_paid += final_tax

    final_equity_pretax = cash
    final_equity_aftertax = aftertax_cash

    n_years = (last_dt - daily_index[0]).days / 365.25
    cagr_pretax = (final_equity_pretax / initial_capital) ** (1 / n_years) - 1
    cagr_aftertax = (final_equity_aftertax / initial_capital) ** (1 / n_years) - 1

    daily_returns = equity_pretax.pct_change().dropna()
    sharpe_pretax = (
        np.sqrt(252) * daily_returns.mean() / daily_returns.std()
        if daily_returns.std() > 0 else 0.0
    )

    rolling_max = equity_pretax.cummax()
    drawdowns = (equity_pretax / rolling_max) - 1
    max_drawdown = drawdowns.min()

    annual_returns = {}
    for yr in sorted(set(daily_index.year)):
        yr_eq = equity_pretax[equity_pretax.index.year == yr]
        if len(yr_eq) < 2:
            continue
        annual_returns[str(yr)] = float(yr_eq.iloc[-1] / yr_eq.iloc[0] - 1)

    avg_holding = (
        np.mean(holding_period_days_log) if holding_period_days_log else 0.0
    )

    result = BacktestResult(
        label=label,
        cagr_pretax=float(cagr_pretax),
        cagr_aftertax=float(cagr_aftertax),
        sharpe_pretax=float(sharpe_pretax),
        max_drawdown=float(max_drawdown),
        final_equity_pretax=float(final_equity_pretax),
        final_equity_aftertax=float(final_equity_aftertax),
        annual_returns=annual_returns,
        n_rebalances=len(rebalance_events),
        avg_holding_period_days=float(avg_holding),
    )
    return result, equity_pretax, rebalance_events


# ----------------------------------------------------------------------
# SPY benchmark — buy & hold (effectively zero tax until terminal sale)
# ----------------------------------------------------------------------

def run_spy_buy_and_hold(
    prices: pd.Series,
    initial_capital: float,
    lt_tax_rate: float,
) -> BacktestResult:
    """Pure buy-and-hold of SPY. Tax applies only at terminal sale (LT)."""
    spy_clean = prices.dropna()
    p0 = spy_clean.iloc[0]
    p_end = spy_clean.iloc[-1]
    shares = initial_capital / p0
    final_pretax = shares * p_end
    gain = final_pretax - initial_capital
    tax = max(0.0, gain) * lt_tax_rate
    final_aftertax = final_pretax - tax

    n_years = (spy_clean.index[-1] - spy_clean.index[0]).days / 365.25
    cagr_pretax = (final_pretax / initial_capital) ** (1 / n_years) - 1
    cagr_aftertax = (final_aftertax / initial_capital) ** (1 / n_years) - 1

    equity = shares * spy_clean
    daily_returns = equity.pct_change().dropna()
    sharpe = (
        np.sqrt(252) * daily_returns.mean() / daily_returns.std()
        if daily_returns.std() > 0 else 0.0
    )
    rolling_max = equity.cummax()
    drawdowns = (equity / rolling_max) - 1
    max_dd = drawdowns.min()

    annual_returns = {}
    for yr in sorted(set(spy_clean.index.year)):
        yr_eq = equity[equity.index.year == yr]
        if len(yr_eq) < 2:
            continue
        annual_returns[str(yr)] = float(yr_eq.iloc[-1] / yr_eq.iloc[0] - 1)

    return BacktestResult(
        label="spy_buyhold",
        cagr_pretax=float(cagr_pretax),
        cagr_aftertax=float(cagr_aftertax),
        sharpe_pretax=float(sharpe),
        max_drawdown=float(max_dd),
        final_equity_pretax=float(final_pretax),
        final_equity_aftertax=float(final_aftertax),
        annual_returns=annual_returns,
        n_rebalances=0,
        avg_holding_period_days=float(n_years * 365.25),
    )


# ----------------------------------------------------------------------
# 60/40 reference (SPY/IEF) — annual rebalance with LT tax
# ----------------------------------------------------------------------

def run_60_40_benchmark(
    prices: pd.DataFrame,
    initial_capital: float,
    lt_tax_rate: float,
) -> Optional[BacktestResult]:
    if "IEF" not in prices.columns:
        return None
    daily_index = prices.index
    cash = initial_capital
    aftertax_cash = initial_capital
    holdings: Dict[str, float] = {}
    cost_basis: Dict[str, float] = {}
    equity_pretax = pd.Series(index=daily_index, dtype=float)
    realized_pretax_total = 0.0
    cumulative_tax_paid = 0.0

    target = {"SPY": 0.60, "IEF": 0.40}
    years = sorted(set(daily_index.year))
    rebalance_dates = [
        d for d in (get_first_trading_day_of_january(prices, y) for y in years)
        if d is not None
    ]

    for i, dt in enumerate(daily_index):
        mv = sum(
            shares * prices.at[dt, t]
            for t, shares in holdings.items()
            if t in prices.columns and not np.isnan(prices.at[dt, t])
        )
        equity_pretax.iat[i] = cash + mv

        if dt in rebalance_dates:
            cycle_realized = 0.0
            for t in list(holdings.keys()):
                px = prices.at[dt, t]
                if np.isnan(px):
                    continue
                proceeds = holdings[t] * px
                gain = proceeds - holdings[t] * cost_basis[t]
                cycle_realized += gain
                cash += proceeds
                aftertax_cash += proceeds
                holdings.pop(t)
                cost_basis.pop(t)

            if cycle_realized > 0:
                tax = cycle_realized * lt_tax_rate
                aftertax_cash -= tax
                cumulative_tax_paid += tax
            realized_pretax_total += cycle_realized

            for t, w in target.items():
                if t not in prices.columns:
                    continue
                px = prices.at[dt, t]
                if np.isnan(px) or px <= 0:
                    continue
                target_dollars = cash * w
                shares = target_dollars / px
                holdings[t] = shares
                cost_basis[t] = px
                cash -= shares * px
            aftertax_cash -= sum(holdings[t] * cost_basis[t] for t in holdings)

    last_dt = daily_index[-1]
    for t in list(holdings.keys()):
        px = prices.at[last_dt, t]
        if np.isnan(px):
            px = prices[t].dropna().iloc[-1]
        proceeds = holdings[t] * px
        gain = proceeds - holdings[t] * cost_basis[t]
        if gain > 0:
            tax = gain * lt_tax_rate
            aftertax_cash -= tax
            cumulative_tax_paid += tax
        cash += proceeds
        aftertax_cash += proceeds
        holdings.pop(t)

    n_years = (last_dt - daily_index[0]).days / 365.25
    cagr_pretax = (cash / initial_capital) ** (1 / n_years) - 1
    cagr_aftertax = (aftertax_cash / initial_capital) ** (1 / n_years) - 1
    daily_returns = equity_pretax.pct_change().dropna()
    sharpe = (
        np.sqrt(252) * daily_returns.mean() / daily_returns.std()
        if daily_returns.std() > 0 else 0.0
    )
    rolling_max = equity_pretax.cummax()
    drawdowns = (equity_pretax / rolling_max) - 1
    max_dd = drawdowns.min()

    annual_returns = {}
    for yr in years:
        yr_eq = equity_pretax[equity_pretax.index.year == yr]
        if len(yr_eq) < 2:
            continue
        annual_returns[str(yr)] = float(yr_eq.iloc[-1] / yr_eq.iloc[0] - 1)

    return BacktestResult(
        label="60_40_buyhold",
        cagr_pretax=float(cagr_pretax),
        cagr_aftertax=float(cagr_aftertax),
        sharpe_pretax=float(sharpe),
        max_drawdown=float(max_dd),
        final_equity_pretax=float(cash),
        final_equity_aftertax=float(aftertax_cash),
        annual_returns=annual_returns,
        n_rebalances=len(rebalance_dates),
        avg_holding_period_days=365.25,
    )


# ----------------------------------------------------------------------
# Main — 4-cell harness (real-fundamentals, synthetic, SPY, 60/40)
# ----------------------------------------------------------------------

def main() -> int:
    """Run the 4-cell harness comparing real-fundamentals vs synthetic.

    Cells:
        D — compounder with REAL V/Q/A fundamentals composite
        C — compounder with SYNTHETIC price-derived composite (negative control)
        A — SPY buy-and-hold
        B — 60/40 SPY/IEF
    """
    from engines.data_manager.fundamentals.simfin_adapter import load_panel

    print(f"[run] Path C compounder — 4-cell harness")
    print(f"[run] Period: {START_DATE} → {END_DATE}")
    print(f"[run] Initial capital: ${INITIAL_CAPITAL:,.0f}")
    print(f"[run] LT cap gains rate: {LT_CAP_GAINS_RATE:.0%}")

    print("[run] loading SimFin fundamentals panel...")
    panel = load_panel()
    print(f"[run] panel: {panel.shape[0]} rows, "
          f"{panel.index.get_level_values('Ticker').nunique()} tickers")

    print("[run] building S&P 500 ex-financials universe...")
    real_universe = build_universe(panel=panel)
    print(f"[run] real-fundamentals universe: {len(real_universe)} tickers")

    tickers_to_fetch = sorted(set(real_universe + UNIVERSE_SYNTHETIC + ["IEF"]))
    prices = fetch_prices(tickers_to_fetch, START_DATE, END_DATE)
    print(f"[run] price panel shape: {prices.shape}")

    real_universe_with_data = [t for t in real_universe if t in prices.columns]
    synthetic_universe_with_data = [t for t in UNIVERSE_SYNTHETIC if t in prices.columns]

    print(f"[run] real universe with price data: {len(real_universe_with_data)}")
    print(f"[run] synthetic universe with price data: {len(synthetic_universe_with_data)}")

    print("\n[run] Cell D — REAL fundamentals compounder...")
    real_result, _, real_events = run_compounder_backtest(
        prices, real_universe_with_data, INITIAL_CAPITAL, LT_CAP_GAINS_RATE,
        panel=panel, use_real_fundamentals=True,
        label="compounder_real_fundamentals",
    )

    print("[run] Cell C — SYNTHETIC compounder (negative control)...")
    synthetic_result, _, synthetic_events = run_compounder_backtest(
        prices, synthetic_universe_with_data, INITIAL_CAPITAL, LT_CAP_GAINS_RATE,
        use_real_fundamentals=False,
        label="compounder_synthetic",
    )

    print("[run] Cell A — SPY buy-and-hold...")
    spy_result = run_spy_buy_and_hold(prices[BENCHMARK_TICKER], INITIAL_CAPITAL, LT_CAP_GAINS_RATE)

    print("[run] Cell B — 60/40 SPY/IEF...")
    six_forty_result = run_60_40_benchmark(prices, INITIAL_CAPITAL, LT_CAP_GAINS_RATE)

    # Pass criterion is keyed off REAL compounder
    pass_after_tax = real_result.cagr_aftertax > spy_result.cagr_aftertax
    pass_mdd = real_result.max_drawdown >= -0.15
    overall_pass = pass_after_tax and pass_mdd

    summary = {
        "metadata": {
            "run_at": datetime.now().isoformat(),
            "period": f"{START_DATE} to {END_DATE}",
            "real_universe_size": len(real_universe_with_data),
            "synthetic_universe_size": len(synthetic_universe_with_data),
            "initial_capital": INITIAL_CAPITAL,
            "lt_cap_gains_rate": LT_CAP_GAINS_RATE,
            "rebalance_cadence": "annual (first trading day of January)",
            "top_quintile_frac": TOP_QUINTILE_FRAC,
            "real_fundamentals_factors": [
                "earnings_yield_market = TTM_NetIncome / market_cap",
                "book_to_market = total_equity / market_cap",
                "roic_proxy = TTM_OperatingIncome*(1-0.21) / (equity+LT_debt)",
                "gross_profitability = TTM_GrossProfit / total_assets",
                "inv_sloan_accruals = -sloan_accruals (precomputed by adapter)",
                "inv_asset_growth = -asset_growth (precomputed by adapter)",
            ],
            "synthetic_factors": [
                "12-1 momentum percentile",
                "inverse 252d vol percentile",
                "1-month reversal percentile",
                "inverse 252d max-drawdown percentile",
            ],
            "data_sources": [
                "yfinance auto-adjusted close (prices)",
                "SimFin FREE quarterly bulk (fundamentals, 2020-06-30 → 2025-04-30)",
                "Wikipedia S&P 500 historical membership (universe)",
            ],
            "limitations": [
                "Universe is current S&P 500 ex-financials (no PIT membership tracking)",
                "Financials sector dropped — SimFin FREE doesn't cover most banks",
                "SimFin restatement bias on accruals factors — see ws_f_fundamentals_data_scoping.md",
                "ROIC tax rate is constant 21% (statutory federal) — not effective rate",
                "Wash-sale rule structurally not in play (annual cadence) — modeled as zero violations",
                "Loss carry-forward simplified vs IRS $3K/yr cap",
            ],
        },
        "results": {
            "compounder_real": asdict(real_result),
            "compounder_synthetic": asdict(synthetic_result),
            "spy_buyhold": asdict(spy_result),
            "60_40_buyhold": asdict(six_forty_result) if six_forty_result else None,
        },
        "pass_criterion": {
            "real_compounder_aftertax_cagr_gt_spy": pass_after_tax,
            "real_compounder_mdd_ge_minus_15pct": pass_mdd,
            "overall": overall_pass,
        },
        "rebalance_events_real": [asdict(r) for r in real_events],
        "rebalance_events_synthetic": [asdict(r) for r in synthetic_events],
    }

    out_path = Path(__file__).resolve().parents[1] / "data" / "research" / "path_c_synthetic_backtest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n{'=' * 65}")
    print("RESULTS — 4-CELL HARNESS")
    print(f"{'=' * 65}")
    print(f"{'Strategy':<32} {'CAGR pre':>10} {'CAGR after':>12} {'Sharpe':>8} {'MDD':>8}")
    print("-" * 75)
    for r in [real_result, synthetic_result, spy_result, six_forty_result]:
        if r is None:
            continue
        print(
            f"{r.label:<32} {r.cagr_pretax*100:>9.2f}% {r.cagr_aftertax*100:>11.2f}% "
            f"{r.sharpe_pretax:>8.3f} {r.max_drawdown*100:>7.2f}%"
        )

    print(f"\n{'=' * 65}")
    print("PASS CRITERION (real-fundamentals compounder)")
    print(f"{'=' * 65}")
    print(f"After-tax CAGR > SPY: "
          f"{real_result.cagr_aftertax*100:.2f}% vs {spy_result.cagr_aftertax*100:.2f}% "
          f"=> {'PASS' if pass_after_tax else 'FAIL'}")
    print(f"MDD >= -15%: {real_result.max_drawdown*100:.2f}% "
          f"=> {'PASS' if pass_mdd else 'FAIL'}")
    print(f"\nOverall: {'PASS' if overall_pass else 'FAIL'}")
    print(f"\nResults JSON: {out_path}")
    return 0 if overall_pass else 1


def _print_wired_summary() -> None:
    """No-arg invocation: print wiring summary, do NOT run the harness."""
    print("Path C compounder rewired with real SimFin fundamentals (2026-05-05).")
    print()
    try:
        from engines.data_manager.fundamentals.simfin_adapter import load_panel
        panel = load_panel()
        universe = build_universe(panel=panel)
        print(f"  Universe: {len(universe)} tickers (S&P 500 ex-financials ∩ SimFin)")
        if universe:
            print(f"  Sample: {', '.join(universe[:5])}, ..., {', '.join(universe[-3:])}")
        print(f"  Panel: {panel.shape[0]} rows × {panel.shape[1]} cols, "
              f"{panel.index.get_level_values('Ticker').nunique()} tickers")
    except Exception as exc:
        print(f"  [warn] could not preview universe ({exc!s}); the script is "
              f"still importable but SimFin/Wikipedia caches may be missing.")
    print()
    print("Composite functions available:")
    print("  compute_composite_score_synthetic — 4 price-derived factors (Cell C)")
    print("  compute_composite_score_real      — 6 V/Q/A real fundamentals (Cell D)")
    print()
    print("To run the 4-cell harness:")
    print("  python scripts/path_c_synthetic_compounder.py --run")
    print()
    print("(Director directive 2026-05-05: do NOT auto-run; stop here.)")


if __name__ == "__main__":
    if "--run" in sys.argv:
        sys.exit(main())
    _print_wired_summary()
    sys.exit(0)
