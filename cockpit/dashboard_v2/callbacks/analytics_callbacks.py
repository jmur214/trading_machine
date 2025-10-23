from __future__ import annotations

import os
from datetime import datetime, timezone, timedelta
from typing import Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output


from ..utils.datamanager import DataManager


def _normalize_to_100(series: pd.Series) -> pd.Series:
    if series is None or series.empty:
        return series
    base = float(series.iloc[0]) if len(series) else 1.0
    if base == 0:
        base = 1.0
    return 100.0 * (series / base)


def _map_benchmark_symbol(sel: str) -> str:
    # Map UI values to Alpaca symbols / assets
    mapping = {
        "^GSPC": "SPY",     # S&P 500 proxy
        "^NDX": "QQQ",      # NASDAQ-100 proxy
        "BTC-USD": "BTC/USD" # Alpaca crypto symbol format
    }
    return mapping.get(sel, sel)


def _load_benchmark_alpaca(symbol_ui: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """Fetch daily bars from Alpaca for the chosen benchmark. Returns DataFrame with ['timestamp','close'] in UTC.
    Falls back to empty DataFrame if keys/module unavailable.
    """
    try:
        # Lazy import to avoid hard dependency if not installed
        from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except Exception:
        return pd.DataFrame()

    api_key = os.getenv("ALPACA_API_KEY") or os.getenv("APCA_API_KEY_ID")
    api_secret = os.getenv("ALPACA_SECRET_KEY") or os.getenv("APCA_API_SECRET_KEY")
    if not api_key or not api_secret:
        return pd.DataFrame()

    # Ensure naive to UTC datetimes for Alpaca request
    s = pd.Timestamp(start).to_pydatetime()
    e = pd.Timestamp(end).to_pydatetime()
    if s.tzinfo is None:
        s = s.replace(tzinfo=timezone.utc)
    if e.tzinfo is None:
        e = e.replace(tzinfo=timezone.utc)

    sym = _map_benchmark_symbol(symbol_ui)
    is_crypto = "/" in sym

    try:
        if is_crypto:
            client = CryptoHistoricalDataClient(api_key, api_secret)
            req = CryptoBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Day, start=s, end=e)
            bars = client.get_crypto_bars(req).df
        else:
            client = StockHistoricalDataClient(api_key, api_secret)
            req = StockBarsRequest(symbol_or_symbols=sym, timeframe=TimeFrame.Day, start=s, end=e)
            bars = client.get_stock_bars(req).df
    except Exception:
        return pd.DataFrame()

    if bars is None or len(bars) == 0:
        return pd.DataFrame()

    # If multi-index (symbol, timestamp), select first level if needed
    if isinstance(bars.index, pd.MultiIndex):
        try:
            bars = bars.xs(sym, level=0)
        except Exception:
            bars = bars.reset_index()

    bars = bars.reset_index()
    # Normalize column names
    if "timestamp" not in bars.columns:
        # alpaca SDK uses 'timestamp' in newer versions; if not, map 'time' or similar
        for c in ("time", "t", "Timestamp"):
            if c in bars.columns:
                bars.rename(columns={c: "timestamp"}, inplace=True)
                break
    if "close" not in bars.columns:
        for c in ("Close", "c"):  # just in case
            if c in bars.columns:
                bars.rename(columns={c: "close"}, inplace=True)
                break

    if "timestamp" not in bars.columns or "close" not in bars.columns:
        return pd.DataFrame()

    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True, errors="coerce")
    bars = bars.dropna(subset=["timestamp"]).sort_values("timestamp")
    return bars[["timestamp", "close"]]


# --- Helpers ---
def _timeframe_bounds(df: pd.DataFrame, tf: str) -> Tuple[pd.Timestamp, pd.Timestamp]:
    if df.empty:
        now = pd.Timestamp.utcnow().tz_localize("UTC")
        return now - timedelta(days=3650), now
    start = df["timestamp"].min()
    end = df["timestamp"].max()
    if tf == "1y":
        start = end - pd.Timedelta(days=365)
    elif tf == "6m":
        start = end - pd.Timedelta(days=182)
    elif tf == "3m":
        start = end - pd.Timedelta(days=91)
    elif tf == "1m":
        start = end - pd.Timedelta(days=30)
    return start, end


def register_analytics_callbacks(app, live: bool = False):
    dm = DataManager()

    @app.callback(
        Output("edge_cum_pnl_chart", "figure"),
        Output("equity_vs_bench_chart", "figure"),
        Output("rolling_outperformance_chart", "figure"),
        Output("pnl_heatmap_chart", "figure"),
        Output("trades_table", "data"),
        Output("trades_table", "columns"),
        Input("timeframe_analytics", "value"),
        Input("benchmark_selector", "value"),
        Input("pulse", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_analytics(tf: str, _bench: str, _n):  # noqa: ANN001
        # Load trades & snapshots
        trades, snaps = dm.get_trades_and_snapshots()
        trades = trades.copy()
        snaps = snaps.copy()

        # Ensure UTC timestamps
        for df in (trades, snaps):
            if not df.empty and "timestamp" in df.columns:
                df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
                df.dropna(subset=["timestamp"], inplace=True)
                df.sort_values("timestamp", inplace=True)

        # Filter timeframe on snapshots
        start, end = _timeframe_bounds(snaps, tf)
        eq = snaps[(snaps["timestamp"] >= start) & (snaps["timestamp"] <= end)] if not snaps.empty else pd.DataFrame()

        # 1) Edge cumulative PnL chart
        cum_fig = go.Figure()
        if not trades.empty:
            t = trades.copy()
            # compute cumulative PnL per edge (realized only)
            if "pnl" in t.columns:
                t = t.dropna(subset=["pnl"])  # ignore open legs
                if not t.empty:
                    for edge, g in t.groupby(t.get("edge", pd.Series(["Unknown"] * len(t)))):
                        g = g.sort_values("timestamp")
                        cum = g["pnl"].cumsum()
                        cum_fig.add_trace(go.Scatter(x=g["timestamp"], y=cum, mode="lines", name=str(edge)))
        cum_fig.update_layout(title="Edge Cumulative Realized PnL", template="plotly_dark", xaxis_title="Time", yaxis_title="PnL")

        # 2) Equity vs Benchmark chart (with Alpaca benchmark if available)
        eq_fig = go.Figure()
        title_suffix = ""
        if not eq.empty and "equity" in eq.columns:
            eq_norm = _normalize_to_100(eq["equity"]) if len(eq) > 0 else pd.Series(dtype=float)
            eq_fig.add_trace(go.Scatter(x=eq["timestamp"], y=eq_norm, mode="lines", name="Equity (idx=100)"))

        bm = _load_benchmark_alpaca(_bench, start, end)
        if not bm.empty:
            bm_norm = _normalize_to_100(bm["close"]) if len(bm) > 0 else pd.Series(dtype=float)
            eq_fig.add_trace(go.Scatter(x=bm["timestamp"], y=bm_norm, mode="lines", name=f"Benchmark {_bench} (idx=100)", opacity=0.7))
            title_suffix = f" vs {_bench}"

        eq_fig.update_layout(
            title=f"Equity{title_suffix}", template="plotly_dark",
            xaxis_title="Time", yaxis_title="Indexed Level (100 = start)",
            paper_bgcolor="#0d1117", plot_bgcolor="#0d1117",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        # 3) Rolling Outperformance (placeholder vs zero baseline)
        roll_fig = go.Figure()
        if not eq.empty and "equity" in eq.columns:
            idx = 100.0 * (eq["equity"] / float(eq["equity"].iloc[0])) if len(eq) > 0 else pd.Series(dtype=float)
            out = idx.pct_change(30)
            roll_fig.add_trace(go.Scatter(x=eq["timestamp"], y=out, mode="lines", name="Rolling 30d Return"))
        roll_fig.update_layout(title="Rolling Outperformance (vs baseline)", template="plotly_dark", xaxis_title="Time", yaxis_title="Return")

        # 4) PnL Heatmap by month/day (diverging colors, recent first)
        heat_fig = go.Figure()
        if not trades.empty and "pnl" in trades.columns:
            tt = trades.dropna(subset=["pnl"]).copy()
            if not tt.empty:
                tt["date"] = tt["timestamp"].dt.date
                daily = tt.groupby("date")["pnl"].sum().reset_index()
                daily["date"] = pd.to_datetime(daily["date"], utc=True)
                if not daily.empty:
                    daily["month"] = daily["date"].dt.tz_convert(None).dt.to_period("M").dt.to_timestamp()
                    daily["day"] = daily["date"].dt.day
                    pivot = daily.pivot_table(index="month", columns="day", values="pnl", aggfunc="sum").fillna(0.0)
                    pivot = pivot.sort_index(ascending=False)  # recent months first
                    colorscale = [[0, "#8B0000"], [0.5, "#222"], [1, "#0B6E3D"]]
                    heat_fig = go.Figure(
                        data=go.Heatmap(
                            z=pivot.values,
                            x=list(pivot.columns),
                            y=[d.strftime("%Y-%m") for d in pivot.index],
                            colorscale=colorscale,
                            colorbar=dict(title="PnL"),
                            hovertemplate="%{y} / Day %{x}<br>PnL: %{z:.2f}<extra></extra>",
                        )
                    )
                    heat_fig.update_layout(
                        template="plotly_dark", title="PnL Heatmap (Daily by Month)",
                        paper_bgcolor="#0d1117", plot_bgcolor="#0d1117"
                    )

        # Trades table (cleaned for readability)
        tdf = trades.copy()
        # Drop irrelevant metadata or verbose fields
        drop_cols = [c for c in tdf.columns if c.lower() in {"trigger", "meta", "edge_group", "edge_group_id", "order_id", "exec_id"}]
        tdf.drop(columns=drop_cols, inplace=True, errors="ignore")
        # Select and reorder important columns if they exist
        preferred_order = ["timestamp", "ticker", "side", "qty", "fill_price", "commission", "pnl", "edge"]
        existing_cols = [c for c in preferred_order if c in tdf.columns]
        tdf = tdf[existing_cols + [c for c in tdf.columns if c not in existing_cols]]
        # Format columns
        for col in ("qty", "fill_price", "commission", "pnl"):
            if col in tdf.columns:
                tdf[col] = pd.to_numeric(tdf[col], errors="coerce")
        if "fill_price" in tdf.columns:
            tdf["fill_price"] = tdf["fill_price"].round(4)
        if "pnl" in tdf.columns:
            tdf["pnl"] = tdf["pnl"].round(2)
        if "timestamp" in tdf.columns:
            tdf["timestamp"] = pd.to_datetime(tdf["timestamp"], errors="coerce", utc=True).dt.strftime("%Y-%m-%d %H:%M")
        cols = [{"name": c, "id": c} for c in tdf.columns]
        data = tdf.to_dict("records")
        return cum_fig, eq_fig, roll_fig, heat_fig, data, cols