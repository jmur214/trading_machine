# cockpit/dashboard/callbacks/performance_callbacks.py
from __future__ import annotations
import numpy as np
import pandas as pd
from dash import Input, Output
import plotly.graph_objects as go

from ..utils.datamanager import DataManager


def timeframe_filter(df: pd.DataFrame, tf_value: str) -> pd.DataFrame:
    if df is None or df.empty:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce", utc=True)
    out = out.dropna(subset=["timestamp"]).sort_values("timestamp")
    if tf_value == "all" or out["timestamp"].empty:
        return out
    end_date = out["timestamp"].max()
    offsets = {
        "1y": pd.DateOffset(years=1),
        "6m": pd.DateOffset(months=6),
        "3m": pd.DateOffset(months=3),
        "1m": pd.DateOffset(months=1),
    }
    if tf_value in offsets:
        start = end_date - offsets[tf_value]
        return out[out["timestamp"] >= start]
    return out

dataman = DataManager()

def register_performance_callbacks(app):
    @app.callback(
        Output("rolling_sharpe_chart", "figure"),
        Output("rolling_maxdd_chart", "figure"),
        Output("pnl_decomp_chart", "figure"),
        Output("edge_corr_heatmap", "figure"),
        Output("edge_weight_evolution_chart", "figure"),
        Input("timeframe_performance", "value"),
        Input("mode_state", "data"),
        Input("pulse", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_performance_tab(tf_value, mode_value, _n):
        # Load equity/trades based on mode
        if mode_value == "paper":
            df = dataman.get_equity_curve("paper")
            trades = dataman.get_trades("paper")
        else:
            df = dataman.get_equity_curve("backtest")
            trades = dataman.get_trades("backtest")

        df_tf = timeframe_filter(df, tf_value) if df is not None else pd.DataFrame()
        trades_tf = timeframe_filter(trades, tf_value) if (trades is not None and not trades.empty) else pd.DataFrame()

        # Rolling Sharpe
        sharpe_fig = go.Figure()
        if df_tf is not None and not df_tf.empty:
            rets = df_tf["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
            if not rets.empty:
                win = 21
                roll_mean = rets.rolling(win).mean()
                roll_std = rets.rolling(win).std()
                roll_sharpe = (roll_mean / roll_std) * np.sqrt(252)
                sharpe_fig.add_trace(go.Scatter(x=df_tf["timestamp"], y=roll_sharpe, mode="lines", name="Rolling Sharpe"))
        sharpe_fig.update_layout(title="Rolling Sharpe (≈21d window)", template="plotly_dark", yaxis_title="Sharpe")

        # Rolling Max Drawdown
        maxdd_fig = go.Figure()
        if df_tf is not None and not df_tf.empty:
            roll_max = df_tf["equity"].cummax()
            drawdown = (df_tf["equity"] - roll_max) / roll_max
            maxdd_fig.add_trace(go.Scatter(x=df_tf["timestamp"], y=drawdown.clip(-1, 0), fill="tozeroy", mode="lines", name="Drawdown"))
        maxdd_fig.update_layout(title="Rolling Max Drawdown", template="plotly_dark", yaxis_title="Drawdown", yaxis_tickformat=".0%")

        # PnL decomposition (Realized vs Unrealized from snapshots)
        pnl_fig = go.Figure()
        if df_tf is not None and not df_tf.empty:
            realized = float(df_tf.get("realized_pnl", pd.Series([0])).iloc[-1] - df_tf.get("realized_pnl", pd.Series([0])).iloc[0]) if "realized_pnl" in df_tf.columns else 0.0
            unrealized = float(df_tf.get("unrealized_pnl", pd.Series([0])).iloc[-1]) if "unrealized_pnl" in df_tf.columns else 0.0
            pnl_fig.add_trace(go.Bar(name="Realized", x=["PnL"], y=[realized]))
            pnl_fig.add_trace(go.Bar(name="Unrealized", x=["PnL"], y=[unrealized]))
            pnl_fig.update_layout(barmode="stack", title="PnL Decomposition (Realized vs Unrealized)", template="plotly_dark", yaxis_title="PnL ($)")
        else:
            pnl_fig.update_layout(template="plotly_dark")

        # Edge correlation heatmap (daily PnL by edge)
        corr_fig = go.Figure()
        if trades_tf is not None and not trades_tf.empty and {"edge", "timestamp", "pnl"}.issubset(trades_tf.columns):
            tmp = trades_tf.copy()
            tmp["date"] = pd.to_datetime(tmp["timestamp"], errors="coerce").dt.date
            daily_edge = tmp.groupby(["date", "edge"])["pnl"].sum().unstack().fillna(0.0)
            if daily_edge.shape[1] >= 2:
                corr = daily_edge.corr().fillna(0.0)
                corr_fig.add_trace(go.Heatmap(z=corr.values, x=corr.columns.astype(str), y=corr.index.astype(str), zmin=-1, zmax=1, colorscale="RdBu", colorbar=dict(title="Corr")))
        corr_fig.update_layout(title="Edge Correlation (Daily PnL)", template="plotly_dark")

        # Edge weight evolution (history log optional)
        ew_fig = go.Figure()
        try:
            import json
            from pathlib import Path
            hist = Path("data/governor/edge_weights_history.csv")
            log = Path("data/governor/feedback_history.log")
            dfh = None
            if hist.exists() and hist.stat().st_size > 0:
                dfh = pd.read_csv(hist)
                if "timestamp" in dfh.columns:
                    dfh["timestamp"] = pd.to_datetime(dfh["timestamp"], errors="coerce")
            elif log.exists() and log.stat().st_size > 0:
                rows = []
                for line in log.read_text().splitlines():
                    try:
                        o = json.loads(line)
                        ts = pd.to_datetime(o.get("timestamp") or o.get("time") or pd.Timestamp.utcnow(), errors="coerce")
                        for k, v in (o.get("weights") or o.get("edge_weights") or {}).items():
                            rows.append({"timestamp": ts, "edge": k, "weight": v})
                    except Exception:
                        continue
                if rows:
                    dfh = pd.DataFrame(rows)
            if dfh is not None and not dfh.empty:
                dfh = dfh.dropna(subset=["timestamp", "edge", "weight"]).sort_values("timestamp")
                for edge_name, edf in dfh.groupby("edge"):
                    ew_fig.add_trace(go.Scatter(x=edf["timestamp"], y=edf["weight"], mode="lines", name=str(edge_name)))
        except Exception:
            pass
        ew_fig.update_layout(title="Edge Weight Evolution", xaxis_title="Date", yaxis_title="Weight", template="plotly_dark", legend=dict(x=0, y=1))

        return sharpe_fig, maxdd_fig, pnl_fig, corr_fig, ew_fig