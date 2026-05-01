"""Capital-allocation diagnostics — pure-pandas loaders for the dashboard tab.

Reads trade logs at `data/trade_logs/<run_uuid>/trades.csv` and the live edge
registry at `data/governor/edges.yml`. Computes the three views the rivalry
audit (`docs/Audit/oos_2025_decomposition_2026_04.md`) had to assemble by hand.

No engine imports — only pandas + standard lib + PyYAML — so this module is
safe to call from a Dash callback path.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

import pandas as pd
import yaml

DATA_DIR = Path("data")
TRADE_LOGS_DIR = DATA_DIR / "trade_logs"
EDGES_YML = DATA_DIR / "governor" / "edges.yml"

DEFAULT_FILL_SHARE_CAP = 0.20
ROLLING_WINDOW_DAYS = 20


# ---------- run-uuid discovery ----------

@dataclass(frozen=True)
class RunSummary:
    run_uuid: str
    start_date: Optional[str]
    end_date: Optional[str]
    n_fills: int
    n_edges: int
    mtime: float


def list_run_uuids(limit: int = 60) -> list[RunSummary]:
    """List trade-log run UUIDs sorted by mtime (newest first)."""
    if not TRADE_LOGS_DIR.exists():
        return []
    rows: list[RunSummary] = []
    for child in TRADE_LOGS_DIR.iterdir():
        if not child.is_dir():
            continue
        trades_path = child / "trades.csv"
        if not trades_path.exists() or trades_path.stat().st_size == 0:
            continue
        try:
            head = pd.read_csv(trades_path, usecols=["timestamp", "edge"], nrows=1)
            tail_iter = pd.read_csv(
                trades_path,
                usecols=["timestamp", "edge"],
                chunksize=2048,
            )
            last = None
            edges: set[str] = set()
            n = 0
            for chunk in tail_iter:
                last = chunk.tail(1)
                edges.update(chunk["edge"].dropna().unique())
                n += len(chunk)
            start = str(head["timestamp"].iloc[0]) if not head.empty else None
            end = str(last["timestamp"].iloc[0]) if last is not None and not last.empty else None
        except Exception:
            continue
        rows.append(RunSummary(
            run_uuid=child.name,
            start_date=start,
            end_date=end,
            n_fills=n,
            n_edges=len(edges),
            mtime=trades_path.stat().st_mtime,
        ))
    rows.sort(key=lambda r: r.mtime, reverse=True)
    return rows[:limit]


# ---------- raw trade-log loader ----------

@lru_cache(maxsize=8)
def load_trades(run_uuid: str) -> pd.DataFrame:
    """Load trades for a run UUID. Cached because callbacks re-fire on every input change."""
    path = TRADE_LOGS_DIR / run_uuid / "trades.csv"
    if not path.exists() or path.stat().st_size == 0:
        return pd.DataFrame()
    df = pd.read_csv(
        path,
        usecols=[
            "timestamp", "ticker", "side", "qty", "fill_price", "pnl",
            "edge", "edge_id", "edge_category", "trigger", "regime_label",
        ],
    )
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    df["date"] = df["timestamp"].dt.date
    return df


# ---------- edges.yml status loader ----------

@lru_cache(maxsize=2)
def load_edge_status() -> dict[str, dict]:
    """Map edge_id -> {status, tier, category} from edges.yml. Empty dict if file missing."""
    if not EDGES_YML.exists():
        return {}
    try:
        raw = yaml.safe_load(EDGES_YML.read_text())
    except Exception:
        return {}
    out: dict[str, dict] = {}
    for spec in raw.get("edges", []) or []:
        eid = spec.get("edge_id")
        if not eid:
            continue
        out[eid] = {
            "status": spec.get("status", "unknown"),
            "tier": spec.get("tier", "unknown"),
            "category": spec.get("category", "unknown"),
        }
    return out


# ---------- per-edge fill-share + PnL summary ----------

def compute_edge_summary(trades: pd.DataFrame) -> pd.DataFrame:
    """Per-edge: fill count, fill %, sum PnL, PnL %, mean PnL/fill, status, tier.

    Fill = any row in the trade log (entries + exits + stops + take_profits).
    PnL is non-null only on exit rows; we sum across all rows so an edge's
    PnL contribution rolls up to whichever entry-edge opened the position.
    """
    if trades.empty:
        return pd.DataFrame(columns=[
            "edge", "fill_count", "fill_pct", "total_pnl", "pnl_pct",
            "mean_pnl_per_fill", "n_pnl_rows", "status", "tier", "category",
        ])

    grp = trades.groupby("edge")
    summary = pd.DataFrame({
        "fill_count": grp.size(),
        "total_pnl": grp["pnl"].sum(min_count=1).fillna(0.0),
        "n_pnl_rows": grp["pnl"].apply(lambda s: s.notna().sum()),
    }).reset_index()

    total_fills = summary["fill_count"].sum()
    total_pnl_abs = summary["total_pnl"].abs().sum()
    summary["fill_pct"] = summary["fill_count"] / total_fills if total_fills else 0.0
    summary["pnl_pct"] = (
        summary["total_pnl"] / total_pnl_abs if total_pnl_abs else 0.0
    )
    # mean PnL per fill is divided by fill_count (not by n_pnl_rows) so that
    # high-frequency edges that don't realise often look correctly small.
    summary["mean_pnl_per_fill"] = summary["total_pnl"] / summary["fill_count"]

    statuses = load_edge_status()
    summary["status"] = summary["edge"].map(lambda e: statuses.get(e, {}).get("status", "unknown"))
    summary["tier"] = summary["edge"].map(lambda e: statuses.get(e, {}).get("tier", "unknown"))
    summary["category"] = summary["edge"].map(lambda e: statuses.get(e, {}).get("category", "unknown"))

    summary = summary.sort_values("fill_count", ascending=False).reset_index(drop=True)
    return summary


# ---------- rivalry flag (high fill-share + low/negative PnL) ----------

def flag_rivalry(summary: pd.DataFrame, fill_pct_thresh: float = 0.10) -> pd.DataFrame:
    """Add a `rivalry_flag` column.

    True iff fill-share >= threshold AND PnL contribution is negative OR
    PnL contribution share is below half the fill share. The pattern this
    catches is "edge consumes capital but doesn't earn its share back."
    """
    if summary.empty:
        return summary.assign(rivalry_flag=[])
    out = summary.copy()
    high_share = out["fill_pct"] >= fill_pct_thresh
    pnl_neg = out["total_pnl"] < 0
    pnl_below_share = out["pnl_pct"] < (out["fill_pct"] * 0.5)
    out["rivalry_flag"] = high_share & (pnl_neg | pnl_below_share)
    return out


# ---------- per-day rolling fill-share for cap-binding diagnostic ----------

def compute_rolling_fill_share(
    trades: pd.DataFrame,
    window_days: int = ROLLING_WINDOW_DAYS,
    entries_only: bool = True,
) -> pd.DataFrame:
    """Per-day rolling fill share per edge over a trailing window.

    Returns a DataFrame indexed by date with one column per edge (share of
    that edge's fills in the trailing `window_days`). This is the closest
    proxy to what `signal_processor`'s `fill_share_capper` actually sees,
    because the live capper computes share over a rolling lookback and
    scales an edge's signal strength when its share exceeds `cap`.

    When a series sits at the cap line, the cap is binding for that edge.
    """
    if trades.empty:
        return pd.DataFrame()
    df = trades[trades["trigger"] == "entry"] if entries_only else trades
    if df.empty:
        return pd.DataFrame()
    daily = df.groupby(["date", "edge"]).size().unstack(fill_value=0).sort_index()
    if len(daily) < 2:
        return daily.div(daily.sum(axis=1), axis=0).fillna(0.0)
    rolling_counts = daily.rolling(window=window_days, min_periods=1).sum()
    rolling_total = rolling_counts.sum(axis=1).replace(0, pd.NA)
    rolling_share = rolling_counts.div(rolling_total, axis=0).fillna(0.0)
    return rolling_share


def cap_binding_summary(
    rolling_share: pd.DataFrame,
    cap: float = DEFAULT_FILL_SHARE_CAP,
    slack: float = 0.005,
) -> pd.DataFrame:
    """Per-day summary of cap-binding state.

    Columns:
      - max_share: that day's max rolling share across edges
      - max_edge: the edge holding max_share
      - binding: bool — max_share >= (cap - slack), the cap is biting
      - over_cap_count: # edges over (cap - slack) that day

    `slack` allows for the cap-and-renormalise rounding that the live
    capper performs.
    """
    if rolling_share.empty:
        return pd.DataFrame()
    max_share = rolling_share.max(axis=1)
    max_edge = rolling_share.idxmax(axis=1)
    over = (rolling_share >= (cap - slack)).sum(axis=1)
    out = pd.DataFrame({
        "max_share": max_share,
        "max_edge": max_edge,
        "over_cap_count": over,
        "binding": max_share >= (cap - slack),
    })
    return out


# ---------- regime-conditional view (optional bonus) ----------

def compute_regime_breakdown(trades: pd.DataFrame) -> pd.DataFrame:
    """Per-edge per-regime fill-count + PnL. Empty if no regime_label column."""
    if trades.empty or "regime_label" not in trades.columns:
        return pd.DataFrame()
    grp = trades.groupby(["edge", "regime_label"])
    out = pd.DataFrame({
        "fill_count": grp.size(),
        "total_pnl": grp["pnl"].sum(min_count=1).fillna(0.0),
    }).reset_index()
    return out
