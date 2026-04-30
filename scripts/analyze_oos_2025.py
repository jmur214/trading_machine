"""
scripts/analyze_oos_2025.py
===========================
Edge-by-edge, month-by-month decomposition of the 2025 OOS Q1 anchor
run vs the lifecycle-counterfactual run. Pure pandas — no backtests.

Reads:
  data/trade_logs/72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34/  (Q1 anchor)
  data/trade_logs/a8c335a3-a014-4434-989b-1fda70f44481/  (counterfactual)

Output: stdout tables suitable for paste into the audit doc.

Run: python -m scripts.analyze_oos_2025
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TRADES_DIR = ROOT / "data" / "trade_logs"
SPY_CSV = ROOT / "data" / "processed" / "SPY_1d.csv"

Q1_RUN = "72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34"
CF_RUN = "a8c335a3-a014-4434-989b-1fda70f44481"


def load_trades(run_id: str) -> pd.DataFrame:
    p = TRADES_DIR / run_id / f"trades_{run_id}.csv"
    df = pd.read_csv(p, parse_dates=["timestamp"])
    df["month"] = df["timestamp"].dt.to_period("M").astype(str)
    return df


def pivot_pnl(df: pd.DataFrame) -> pd.DataFrame:
    out = df.pivot_table(index="edge", columns="month", values="pnl",
                         aggfunc="sum", fill_value=0.0)
    out["TOTAL"] = out.sum(axis=1)
    return out.sort_values("TOTAL", ascending=False)


def pivot_fills(df: pd.DataFrame) -> pd.DataFrame:
    out = df.pivot_table(index="edge", columns="month", values="pnl",
                         aggfunc="size", fill_value=0)
    out["TOTAL"] = out.sum(axis=1)
    return out.sort_values("TOTAL", ascending=False)


def regime_pnl_crosstab(df: pd.DataFrame) -> pd.DataFrame:
    out = df.pivot_table(index="edge", columns="regime_label", values="pnl",
                         aggfunc="sum", fill_value=0.0)
    out["TOTAL"] = out.sum(axis=1)
    return out.sort_values("TOTAL", ascending=False)


def regime_fill_crosstab(df: pd.DataFrame) -> pd.DataFrame:
    out = df.pivot_table(index="edge", columns="regime_label", values="pnl",
                         aggfunc="size", fill_value=0)
    out["TOTAL"] = out.sum(axis=1)
    return out.sort_values("TOTAL", ascending=False)


def regime_by_month(df: pd.DataFrame) -> pd.DataFrame:
    return df.pivot_table(index="month", columns="regime_label", values="pnl",
                          aggfunc="size", fill_value=0)


def cumulative_top_bottom(df: pd.DataFrame, n: int = 5) -> pd.DataFrame:
    totals = df.groupby("edge")["pnl"].sum().sort_values()
    keep = totals.head(n).index.tolist() + totals.tail(n).index.tolist()
    mp = df[df["edge"].isin(keep)].pivot_table(
        index="month", columns="edge", values="pnl",
        aggfunc="sum", fill_value=0.0,
    ).cumsum()
    return mp[keep]


def spy_monthly_return() -> pd.Series:
    spy = pd.read_csv(SPY_CSV, parse_dates=[0])
    spy.columns = ["date", "open", "high", "low", "close", "vol",
                   "atr_pct", "prev_close"][:len(spy.columns)]
    spy = spy[(spy["date"] >= "2025-01-01") & (spy["date"] <= "2025-12-31")].copy()
    spy["month"] = spy["date"].dt.to_period("M").astype(str)
    mo_close = spy.groupby("month")["close"].last()
    mo_open = spy.groupby("month")["close"].first()
    return ((mo_close / mo_open - 1.0) * 100).round(2)


def rivalry_probe(q1: pd.DataFrame, cf: pd.DataFrame, edges) -> pd.DataFrame:
    rows = []
    for edge in edges:
        a = q1[q1["edge"] == edge]
        b = cf[cf["edge"] == edge]
        rows.append({
            "edge": edge,
            "Q1 fills": len(a),
            "Q1 PnL": round(a["pnl"].sum(), 2),
            "Q1 avg/fill": round(a["pnl"].sum() / max(len(a), 1), 2),
            "CF fills": len(b),
            "CF PnL": round(b["pnl"].sum(), 2),
            "CF avg/fill": round(b["pnl"].sum() / max(len(b), 1), 2),
        })
    return pd.DataFrame(rows).set_index("edge")


def main() -> int:
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 250)
    pd.set_option("display.float_format", lambda x: f"{x:8.1f}")

    q1 = load_trades(Q1_RUN)
    cf = load_trades(CF_RUN)

    sections = [
        ("Q1 ANCHOR — Per-edge per-month REALIZED PnL", pivot_pnl(q1)),
        ("Q1 ANCHOR — Per-edge per-month FILL COUNT", pivot_fills(q1)),
        ("CF — Per-edge per-month REALIZED PnL", pivot_pnl(cf)),
        ("CF — Per-edge per-month FILL COUNT", pivot_fills(cf)),
        ("REGIME × EDGE PnL — Q1 ANCHOR", regime_pnl_crosstab(q1)),
        ("REGIME × EDGE FILLS — Q1 ANCHOR", regime_fill_crosstab(q1)),
        ("REGIME LABEL → MONTH", regime_by_month(q1)),
        ("Q1 — MONTHLY CUMULATIVE PNL (top 5 + bottom 5)", cumulative_top_bottom(q1)),
        ("RIVALRY PROBE — volume_anomaly_v1 + herding_v1",
         rivalry_probe(q1, cf, ["volume_anomaly_v1", "herding_v1"])),
        ("SPY MONTHLY RETURN %", spy_monthly_return().to_frame("ret_%")),
    ]
    for title, table in sections:
        print(f"\n{'=' * 80}\n{title}\n{'=' * 80}")
        print(table.to_string())

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
