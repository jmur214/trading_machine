"""Path C — synthetic compounder sleeve feasibility backtest.

DESIGN-PHASE FEASIBILITY TEST. Not production code.

Tests the architectural premise of the compounder sleeve from
docs/Audit/path_c_compounder_design_2026_05.md without committing to
a particular Engine C implementation. Standalone — does NOT touch
the production backtester.

Approach
--------
- Universe: liquid mega/large-caps that have continuous price data over
  2010-01 → 2024-12, fetched via yfinance (~50 names, used as a proxy
  for the eventual S&P 500 universe).
- Quasi-quality + value composite from PRICE-DERIVED proxies:
    * Quality proxy:    12-1 momentum percentile rank (return persistence)
    * Defensive proxy:  inverse 252d vol percentile rank (low-vol = defensive)
    * Mean-reversion guard: 1m reversal (avoid hot stocks at rebalance)
    * Drawdown-control:  inverse 252d max-drawdown percentile rank
  The four are equal-weight averaged to a composite percentile, top
  quintile is held equal-weighted for one year.

Why price-derived proxies, not fundamentals?
--------------------------------------------
The repo's fundamentals_static.csv is a 7-row stub. yfinance's
fundamentals are TTM-only (no historical quarterly). A fundamentals-
backed compounder needs Compustat/FactSet/SimFin data. For a feasibility
test, price-derived proxies are an honest stand-in: they preserve the
key compounder properties (annual rebalance, equal-weight top quintile,
long-only, broad universe) while not pretending to academic-grade
factor exposure.

Pass criterion (per task): compounder after-tax CAGR > SPY after-tax
CAGR over 2010-2024 with MDD ≤ -15%. Tax assumption: 15% LT cap gains
on annual rebalance turnover.

Outputs
-------
- Console summary
- JSON results to data/research/path_c_synthetic_backtest.json
- Markdown summary to docs/Audit/path_c_compounder_synthetic_backtest_2026_05.md
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Universe — 50 liquid large-caps with continuous 2010-2024 history
# ----------------------------------------------------------------------
# Curated to be representative across sectors; NOT a survivor-bias-free
# S&P 500 panel. Acceptable for design-phase feasibility test; flagged
# as a limitation in the writeup.

UNIVERSE: List[str] = [
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
# Factor computation — price-derived quasi-quality + defensive composite
# ----------------------------------------------------------------------

def compute_composite_score(
    prices: pd.DataFrame,
    as_of: pd.Timestamp,
    universe: List[str],
) -> pd.Series:
    """Compute the compounder composite percentile score for each ticker.

    Uses 4 price-derived signals, equal-weighted on percentile ranks:
      - mom_12_1: 12-month return excluding most-recent month (Jegadeesh-Titman)
      - inv_vol:  -1 × 252d realized vol (low-vol → high score)
      - rev_1m:   -1 × 1-month return (mean-reversion guard, avoid hot names)
      - inv_mdd:  -1 × 252d max drawdown (drawdown-control → high score)

    Each percentile is in [0, 1]; composite is mean of the four. Returns
    a Series indexed by ticker; tickers without sufficient history get NaN
    and are dropped from the universe at this rebalance.
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
    """
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
            composite = compute_composite_score(prices, dt, universe)
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
        label="compounder_synthetic",
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
# Main
# ----------------------------------------------------------------------

def main() -> int:
    print(f"[run] Path C synthetic compounder backtest")
    print(f"[run] Universe: {len(UNIVERSE)} tickers + SPY + IEF (for 60/40)")
    print(f"[run] Period: {START_DATE} → {END_DATE}")
    print(f"[run] Initial capital: ${INITIAL_CAPITAL:,.0f}")
    print(f"[run] LT cap gains rate: {LT_CAP_GAINS_RATE:.0%}")

    tickers = UNIVERSE + ["IEF"]
    prices = fetch_prices(tickers, START_DATE, END_DATE)
    print(f"[run] price panel shape: {prices.shape}")

    universe_with_data = [t for t in UNIVERSE if t in prices.columns]
    print(f"[run] universe with usable data: {len(universe_with_data)} / {len(UNIVERSE)}")

    print("\n[run] running compounder backtest...")
    compounder_result, compounder_equity, rebal_events = run_compounder_backtest(
        prices, universe_with_data, INITIAL_CAPITAL, LT_CAP_GAINS_RATE
    )

    print("[run] running SPY buy-and-hold benchmark...")
    spy_result = run_spy_buy_and_hold(prices[BENCHMARK_TICKER], INITIAL_CAPITAL, LT_CAP_GAINS_RATE)

    print("[run] running 60/40 benchmark...")
    six_forty_result = run_60_40_benchmark(prices, INITIAL_CAPITAL, LT_CAP_GAINS_RATE)

    # Pass criterion check
    pass_after_tax = compounder_result.cagr_aftertax > spy_result.cagr_aftertax
    pass_mdd = compounder_result.max_drawdown >= -0.15
    overall_pass = pass_after_tax and pass_mdd

    summary = {
        "metadata": {
            "run_at": datetime.now().isoformat(),
            "period": f"{START_DATE} to {END_DATE}",
            "universe_size_attempted": len(UNIVERSE),
            "universe_size_with_data": len(universe_with_data),
            "initial_capital": INITIAL_CAPITAL,
            "lt_cap_gains_rate": LT_CAP_GAINS_RATE,
            "rebalance_cadence": "annual (first trading day of January)",
            "top_quintile_frac": TOP_QUINTILE_FRAC,
            "factor_proxies": [
                "12-1 momentum percentile",
                "inverse 252d vol percentile",
                "1-month reversal percentile",
                "inverse 252d max-drawdown percentile",
            ],
            "data_source": "yfinance auto-adjusted close",
            "limitations": [
                "Universe is 50 curated mega/large-caps, NOT survivor-bias-free S&P 500",
                "Factors are price-derived proxies, NOT fundamentals (no Compustat data)",
                "Wash-sale rule structurally not in play (annual cadence) — modeled as zero violations",
                "Loss carry-forward simplified vs IRS $3K/yr cap",
            ],
        },
        "results": {
            "compounder": asdict(compounder_result),
            "spy_buyhold": asdict(spy_result),
            "60_40_buyhold": asdict(six_forty_result) if six_forty_result else None,
        },
        "pass_criterion": {
            "compounder_aftertax_cagr_gt_spy_aftertax_cagr": pass_after_tax,
            "compounder_mdd_ge_minus_15pct": pass_mdd,
            "overall": overall_pass,
        },
        "rebalance_events": [asdict(r) for r in rebal_events],
    }

    out_path = Path(__file__).resolve().parents[1] / "data" / "research" / "path_c_synthetic_backtest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n{'=' * 60}")
    print("RESULTS")
    print(f"{'=' * 60}")
    print(f"{'Strategy':<25} {'CAGR pre':>10} {'CAGR after':>12} {'Sharpe':>8} {'MDD':>8}")
    print("-" * 65)
    for r in [compounder_result, spy_result, six_forty_result]:
        if r is None:
            continue
        print(
            f"{r.label:<25} {r.cagr_pretax*100:>9.2f}% {r.cagr_aftertax*100:>11.2f}% "
            f"{r.sharpe_pretax:>8.3f} {r.max_drawdown*100:>7.2f}%"
        )

    print(f"\n{'=' * 60}")
    print("PASS CRITERION")
    print(f"{'=' * 60}")
    print(f"Compounder after-tax CAGR > SPY after-tax CAGR: "
          f"{compounder_result.cagr_aftertax*100:.2f}% vs {spy_result.cagr_aftertax*100:.2f}% "
          f"=> {'PASS' if pass_after_tax else 'FAIL'}")
    print(f"Compounder MDD >= -15%: {compounder_result.max_drawdown*100:.2f}% "
          f"=> {'PASS' if pass_mdd else 'FAIL'}")
    print(f"\nOverall: {'PASS' if overall_pass else 'FAIL'}")
    print(f"\nResults JSON: {out_path}")
    return 0 if overall_pass else 1


if __name__ == "__main__":
    sys.exit(main())
