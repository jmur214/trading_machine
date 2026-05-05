"""SimFin → fundamentals panel adapter.

Converts SimFin's three quarterly bulk datasets (income / balance / cashflow)
into a single PIT-aware panel keyed on (ticker, publish_date) and computes
the six Value / Quality / Accruals factors specified in
docs/Core/Ideas_Pipeline/path_c_unblock_plan.md.

PIT discipline: we use SimFin's `Publish Date` (not `Restated Date`) as the
join key. SimFin's docs state the figures themselves are latest-restated;
filtering on Publish Date gives us a defensible PIT approximation. Documented
restatement bias for accruals factors — see ws_f_fundamentals_data_scoping.md.

Free tier covers ~3,985 US tickers, ~5 years (2020-mid → present).
"""
from __future__ import annotations

import os
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

import simfin as sf

REPO_ROOT = Path(__file__).resolve().parents[3]
SIMFIN_RAW_DIR = REPO_ROOT / "data" / "raw" / "simfin"
PROCESSED_PATH = REPO_ROOT / "data" / "processed" / "fundamentals_simfin.parquet"


# ---------------------------------------------------------------------------
# Loaders (cached on disk by simfin package)
# ---------------------------------------------------------------------------

def _ensure_simfin_configured() -> None:
    api_key = os.environ.get("SIMFIN_API_KEY")
    if not api_key:
        raise RuntimeError(
            "SIMFIN_API_KEY not set in environment. Source .env first."
        )
    sf.set_api_key(api_key)
    SIMFIN_RAW_DIR.mkdir(parents=True, exist_ok=True)
    sf.set_data_dir(str(SIMFIN_RAW_DIR))


def load_raw_panels() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load the 3 quarterly bulk datasets from SimFin (cached after first call)."""
    _ensure_simfin_configured()
    inc = sf.load_income(variant="quarterly", market="us")
    bal = sf.load_balance(variant="quarterly", market="us")
    cf = sf.load_cashflow(variant="quarterly", market="us")
    return inc, bal, cf


# ---------------------------------------------------------------------------
# Panel construction — join + canonical column names
# ---------------------------------------------------------------------------

# Income statement columns we keep (renamed to snake_case canonical)
_INC_KEEP = {
    "Publish Date": "publish_date",
    "Restated Date": "restated_date",
    "Fiscal Year": "fiscal_year",
    "Fiscal Period": "fiscal_period",
    "Shares (Diluted)": "shares_diluted",
    "Revenue": "revenue",
    "Gross Profit": "gross_profit",
    "Operating Income (Loss)": "operating_income",
    "Net Income (Common)": "net_income",
}

# Balance sheet columns
_BAL_KEEP = {
    "Cash, Cash Equivalents & Short Term Investments": "cash_and_st_investments",
    "Accounts & Notes Receivable": "accounts_receivable",
    "Inventories": "inventories",
    "Total Current Assets": "total_current_assets",
    "Total Assets": "total_assets",
    "Short Term Debt": "short_term_debt",
    "Total Current Liabilities": "total_current_liabilities",
    "Long Term Debt": "long_term_debt",
    "Total Liabilities": "total_liabilities",
    "Total Equity": "total_equity",
}

# Cashflow columns (used for accruals + capex)
_CF_KEEP = {
    "Net Cash from Operating Activities": "operating_cash_flow",
    "Change in Working Capital": "change_in_working_capital",
    "Change in Fixed Assets & Intangibles": "capex_change",
}


def _select_and_rename(df: pd.DataFrame, mapping: dict[str, str]) -> pd.DataFrame:
    available = {src: dst for src, dst in mapping.items() if src in df.columns}
    return df[list(available.keys())].rename(columns=available)


def build_panel(
    income: Optional[pd.DataFrame] = None,
    balance: Optional[pd.DataFrame] = None,
    cashflow: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """Join the 3 statements into a single ticker × report_date panel.

    Returns a DataFrame indexed by (Ticker, Report Date) with canonical
    snake_case columns covering all fields needed for V/Q/A factors.
    """
    if income is None or balance is None or cashflow is None:
        income, balance, cashflow = load_raw_panels()

    inc = _select_and_rename(income, _INC_KEEP)
    bal = _select_and_rename(balance, _BAL_KEEP)
    cf = _select_and_rename(cashflow, _CF_KEEP)

    # Income carries the Publish Date / fiscal-period metadata; the other
    # two statements are joined on the same (Ticker, Report Date) index.
    panel = inc.join(bal, how="outer", rsuffix="_bal")
    panel = panel.join(cf, how="outer", rsuffix="_cf")

    panel = panel.sort_index()
    panel["publish_date"] = pd.to_datetime(panel["publish_date"])
    return panel


# ---------------------------------------------------------------------------
# Factor computation — six V/Q/A primitives
# ---------------------------------------------------------------------------

def compute_factors(panel: pd.DataFrame) -> pd.DataFrame:
    """Compute the six V/Q/A factors specified in path_c_unblock_plan.md.

    Note: P/E and P/B require market price; we expose the BOOK-side primitives
    that don't need price. Price-relative ratios are computed at backtest time
    when daily prices are available.

    Returns the input panel with new columns appended:
      - earnings_yield_book = net_income / total_equity   (book-relative E/P proxy)
      - book_to_assets       = total_equity / total_assets (B/P proxy without price)
      - roe                  = net_income / total_equity
      - roa                  = net_income / total_assets
      - gross_margin         = gross_profit / revenue
      - gross_profitability  = gross_profit / total_assets   (Novy-Marx)
      - sloan_accruals       = (net_income - operating_cash_flow) / total_assets
      - asset_growth         = ΔTotal Assets / lagged Total Assets (per-ticker)
    """
    df = panel.copy()

    safe_div = lambda num, den: np.where(
        (den != 0) & den.notna() & num.notna(),
        num / den,
        np.nan,
    )

    df["earnings_yield_book"] = safe_div(df["net_income"], df["total_equity"])
    df["book_to_assets"] = safe_div(df["total_equity"], df["total_assets"])
    df["roe"] = safe_div(df["net_income"], df["total_equity"])
    df["roa"] = safe_div(df["net_income"], df["total_assets"])
    df["gross_margin"] = safe_div(df["gross_profit"], df["revenue"])
    df["gross_profitability"] = safe_div(df["gross_profit"], df["total_assets"])

    # Sloan accruals = NI - OCF (scaled by assets)
    df["sloan_accruals"] = safe_div(
        df["net_income"] - df["operating_cash_flow"],
        df["total_assets"],
    )

    # Per-ticker year-over-year asset growth
    df["_assets_lag4"] = df.groupby(level="Ticker")["total_assets"].shift(4)
    df["asset_growth"] = safe_div(
        df["total_assets"] - df["_assets_lag4"],
        df["_assets_lag4"],
    )
    df = df.drop(columns=["_assets_lag4"])

    return df


# ---------------------------------------------------------------------------
# Cache + public API
# ---------------------------------------------------------------------------

def build_and_cache(force: bool = False) -> Path:
    """Build the full panel + factors and cache to data/processed/.

    Idempotent: skips rebuild if the parquet exists and is newer than the
    raw simfin caches, unless force=True.
    """
    PROCESSED_PATH.parent.mkdir(parents=True, exist_ok=True)

    if PROCESSED_PATH.exists() and not force:
        # Cheap freshness check — if processed is newer than the income raw,
        # assume nothing changed
        raw_income = SIMFIN_RAW_DIR / "us-income-quarterly.csv"
        if not raw_income.exists() or PROCESSED_PATH.stat().st_mtime >= raw_income.stat().st_mtime:
            return PROCESSED_PATH

    panel = build_panel()
    panel = compute_factors(panel)
    panel.to_parquet(PROCESSED_PATH)
    return PROCESSED_PATH


def load_panel(force_rebuild: bool = False) -> pd.DataFrame:
    """Load the cached PIT panel (build it if missing)."""
    path = build_and_cache(force=force_rebuild)
    return pd.read_parquet(path)


def load_fundamentals(
    ticker: str,
    asof_date: date,
    panel: Optional[pd.DataFrame] = None,
) -> Optional[dict]:
    """Return the most recent fundamentals known to the public as of asof_date.

    Uses Publish Date (not Report Date) for PIT correctness. Returns None if
    no filings have been published for this ticker as of that date.
    """
    if panel is None:
        panel = load_panel()

    asof_ts = pd.Timestamp(asof_date)
    try:
        ticker_slice = panel.xs(ticker, level="Ticker")
    except KeyError:
        return None

    eligible = ticker_slice[ticker_slice["publish_date"] <= asof_ts]
    if eligible.empty:
        return None

    latest = eligible.sort_values("publish_date").iloc[-1]
    return latest.to_dict()
