# cockpit/dashboard.py

from __future__ import annotations
import argparse
from pathlib import Path
from functools import lru_cache

import pandas as pd
import numpy as np
import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go

# Prefer central metrics loader; fallback to direct CSVs if unavailable
try:
    from cockpit.metrics import PerformanceMetrics  # repo-local
except Exception:  # pragma: no cover
    try:
        from metrics import PerformanceMetrics  # project root fallback
    except Exception:
        PerformanceMetrics = None  # dashboard will use CSV fallback

# Optional benchmark fetch (graceful if unavailable/offline)
try:
    import yfinance as yf
except Exception:  # pragma: no cover
    yf = None


# ---------------------------- Utilities ---------------------------- #

def safe_read_csv(path: str | Path, parse_ts: bool = True) -> pd.DataFrame:
    """
    Load CSV if present; return empty DataFrame on any issue.
    Ensures timestamp column is parsed and sorted if present.
    """
    try:
        p = Path(path)
        if not p.exists() or p.stat().st_size == 0:
            return pd.DataFrame()
        df = pd.read_csv(p)
        if parse_ts and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df
    except Exception:
        return pd.DataFrame()


def compute_trade_pnl_fifo(trades: pd.DataFrame) -> pd.DataFrame:
    """
    FIFO realized PnL matcher supporting long/short, exits, and flips.
    Leaves open legs with NaN PnL. Commission is not netted here (to keep parity
    with logger snapshots); can be added later if desired.
    """
    if trades is None or trades.empty:
        return pd.DataFrame(columns=["timestamp", "ticker", "side", "qty", "fill_price", "commission", "pnl", "edge"])

    df = trades.copy()

    # Normalize core types
    for col in ("qty", "fill_price", "commission"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "commission" not in df.columns:
        df["commission"] = 0.0

    # Ensure edge column for attribution charts
    if "edge" not in df.columns:
        df["edge"] = "Unknown"

    # Ensure timestamp order per ticker
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values(["ticker", "timestamp"])
    if "pnl" not in df.columns:
        df["pnl"] = np.nan

    stacks: dict[str, list[dict]] = {}

    def sign_for(side: str) -> int:
        s = str(side).lower()
        return +1 if s == "long" else (-1 if s == "short" else 0)

    def closes_position(prev_sign: int, now_side: str) -> bool:
        s = str(now_side).lower()
        if s in ("exit", "cover"):
            return True
        now_sign = sign_for(s)
        return prev_sign != 0 and now_sign != 0 and np.sign(prev_sign) != np.sign(now_sign)

    for tkr, tdf in df.groupby("ticker", sort=False):
        stack = stacks.setdefault(tkr, [])  # elements: {"sign": +1/-1, "price": float, "qty": int}

        def current_net_sign() -> int:
            if not stack:
                return 0
            net = sum(leg["sign"] * leg["qty"] for leg in stack)
            return int(np.sign(net)) if net != 0 else 0

        prev_net_sign = 0
        for idx, row in tdf.iterrows():
            side = str(row.get("side", "")).lower()
            qty = int(row.get("qty", 0))
            px = float(row.get("fill_price", np.nan))
            if qty <= 0 or not np.isfinite(px):
                continue

            if side in ("long", "short"):
                now_sign = sign_for(side)
                if prev_net_sign == 0 or prev_net_sign == now_sign:
                    stack.append({"sign": now_sign, "price": px, "qty": qty})
                else:
                    # flip: close FIFO then open remainder
                    remaining = qty
                    realized = 0.0
                    while remaining > 0 and stack and np.sign(stack[0]["sign"]) != np.sign(now_sign):
                        leg = stack[0]
                        m = min(remaining, leg["qty"])
                        direction = leg["sign"]
                        realized += (px - leg["price"]) * (m * direction)
                        leg["qty"] -= m
                        remaining -= m
                        if leg["qty"] == 0:
                            stack.pop(0)
                    if remaining > 0:
                        stack.append({"sign": now_sign, "price": px, "qty": remaining})
                    df.loc[idx, "pnl"] = round(realized, 2)

            elif closes_position(prev_net_sign, side):
                # exit or cover: close against FIFO until qty is consumed
                remaining = qty
                realized = 0.0
                while remaining > 0 and stack:
                    leg = stack[0]
                    m = min(remaining, leg["qty"])
                    direction = leg["sign"]
                    realized += (px - leg["price"]) * (m * direction)
                    leg["qty"] -= m
                    remaining -= m
                    if leg["qty"] == 0:
                        stack.pop(0)
                df.loc[idx, "pnl"] = round(realized, 2)

            prev_net_sign = current_net_sign()

    return df


def timeframe_filter(df: pd.DataFrame, tf_value: str) -> pd.DataFrame:
    """Filter dataframe by timeframe code ('all', '1y', '6m', '3m', '1m')."""
    if df is None or df.empty:
        return df
    out = df.copy()
    out["timestamp"] = pd.to_datetime(out["timestamp"], errors="coerce")
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


def summarize_period(df_snap: pd.DataFrame, df_trades: pd.DataFrame) -> dict:
    """
    Summary with sane caps and NaN-aware calculations.
    Max Drawdown is capped to [-100%, 0%]; Win Rate computed only on realized rows.
    """
    if df_snap is None or df_snap.empty:
        return {
            "Starting Equity": "-",
            "Ending Equity": "-",
            "Net Profit": "-",
            "Total Return (%)": "-",
            "CAGR (%)": "-",
            "Max Drawdown (%)": "-",
            "Sharpe Ratio": "-",
            "Volatility (%)": "-",
            "Win Rate (%)": "-",
        }

    start_eq = float(df_snap["equity"].iloc[0])
    end_eq = float(df_snap["equity"].iloc[-1])

    total_ret = np.nan if start_eq <= 0 else (end_eq - start_eq) / start_eq
    days = (df_snap["timestamp"].iloc[-1] - df_snap["timestamp"].iloc[0]).days
    cagr = (1 + total_ret) ** (365.0 / days) - 1 if (days > 0 and not np.isnan(total_ret)) else np.nan

    roll_max = df_snap["equity"].cummax()
    dd = (df_snap["equity"] - roll_max) / roll_max
    dd = dd.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=-1, upper=0)
    max_dd = dd.min() * 100.0

    rets = (
        df_snap["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        if "equity" in df_snap.columns else pd.Series(dtype=float)
    )
    vol = rets.std() * np.sqrt(252) * 100.0 if not rets.empty else np.nan
    sharpe = (rets.mean() / rets.std()) * np.sqrt(252) if (not rets.empty and rets.std() > 0) else np.nan

    win_rate = np.nan
    if df_trades is not None and not df_trades.empty and "pnl" in df_trades.columns:
        realized = df_trades.dropna(subset=["pnl"])
        if not realized.empty:
            win_rate = 100.0 * (realized["pnl"] > 0).sum() / len(realized)

    return {
        "Starting Equity": round(start_eq, 2),
        "Ending Equity": round(end_eq, 2),
        "Net Profit": round(end_eq - start_eq, 2),
        "Total Return (%)": None if np.isnan(total_ret) else round(total_ret * 100.0, 2),
        "CAGR (%)": None if np.isnan(cagr) else round(cagr * 100.0, 2),
        "Max Drawdown (%)": None if np.isnan(max_dd) else round(max_dd, 2),
        "Sharpe Ratio": None if np.isnan(sharpe) else round(sharpe, 3),
        "Volatility (%)": None if np.isnan(vol) else round(vol, 2),
        "Win Rate (%)": None if np.isnan(win_rate) else round(win_rate, 2),
    }


# ------- Benchmark loader (cached) ------- #

@lru_cache(maxsize=8)
def load_benchmark(symbol: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    """
    Download benchmark (e.g., ^GSPC or SPY) between start/end.
    Returns empty DF on any failure or if yfinance missing.
    """
    if yf is None:
        return pd.DataFrame()
    try:
        df = yf.download(symbol, start=start.date(), end=end.date(), interval="1d", progress=False)
        if df is None or df.empty:
            return pd.DataFrame()
        df = df.rename(columns={c: c.strip().title() for c in df.columns})
        df = df.reset_index().rename(columns={"Date": "timestamp"})
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        px = pd.to_numeric(df["Close"], errors="coerce")
        if px.isna().all():
            return pd.DataFrame()
        df["index"] = 100.0 * (px / px.iloc[0])
        return df[["timestamp", "index"]]
    except Exception:
        return pd.DataFrame()


# ---------------------------- App Runner ---------------------------- #

def run_dashboard(live: bool = False,
                  snapshots_csv: str = "data/trade_logs/portfolio_snapshots.csv",
                  trades_csv: str = "data/trade_logs/trades.csv"):

    # Prefer PerformanceMetrics loader; fall back to direct CSVs
    use_metrics_loader = PerformanceMetrics is not None
    if use_metrics_loader:
        try:
            metrics = PerformanceMetrics(snapshots_path=snapshots_csv, trades_path=trades_csv)
            base_snapshots = metrics.snapshots.copy()
            base_trades = metrics.trades.copy() if metrics.trades is not None else pd.DataFrame()
        except Exception as e:
            print(f"[DASH] Falling back to direct CSV load: {e}")
            use_metrics_loader = False
            base_snapshots = safe_read_csv(snapshots_csv)
            base_trades = safe_read_csv(trades_csv)
    else:
        base_snapshots = safe_read_csv(snapshots_csv)
        base_trades = safe_read_csv(trades_csv)

    def reload_frames():
        """Reload frames from disk (for live mode)."""
        if use_metrics_loader:
            try:
                m = PerformanceMetrics(snapshots_path=snapshots_csv, trades_path=trades_csv)
                snaps = m.snapshots.copy()
                trs = m.trades.copy() if m.trades is not None else pd.DataFrame()
                return snaps, trs
            except Exception:
                pass
        return safe_read_csv(snapshots_csv), safe_read_csv(trades_csv)

    app = dash.Dash(
        __name__,
        suppress_callback_exceptions=True,
        prevent_initial_callbacks="initial_duplicate",  # optional safeguard
    )
    app.config.suppress_callback_exceptions = True
    app.title = "Trading Cockpit"

    # ---------------------------- Layout ---------------------------- #
    app.layout = html.Div(
        style={"backgroundColor": "#111", "color": "#EEE", "padding": "18px"},
        children=[
            html.H1("Trading Dashboard", style={"textAlign": "center"}),

            dcc.Tabs(
                id="tabs",
                value="tab-mode",
                parent_style={"color": "#000"},
                children=[
                    dcc.Tab(label="Mode", value="tab-mode", selected_style={"background": "#222"}),
                    dcc.Tab(label="Summary", value="tab-summary", selected_style={"background": "#222"}),
                    dcc.Tab(label="Dashboard", value="tab-dashboard", selected_style={"background": "#222"}),
                    dcc.Tab(label="Analytics", value="tab-analytics", selected_style={"background": "#222"}),
                    dcc.Tab(label="Settings", value="tab-settings", selected_style={"background": "#222"}),
                ],
            ),

            html.Div(id="tab-content"),

            dcc.Interval(id="pulse", interval=2000, n_intervals=0, disabled=not live),
        ],
    )

    # ---------------------------- Tab Content ---------------------------- #
    @app.callback(
        Output("tab-content", "children"),
        Input("tabs", "value"),
    )
    def render_tab(tab_value):
        if tab_value == "tab-mode":
            return _mode_layout()
        elif tab_value == "tab-summary":
            return _summary_layout()
        elif tab_value == "tab-dashboard":
            return _dashboard_layout()
        elif tab_value == "tab-analytics":
            return _analytics_layout()
        else:
            return _settings_layout()
        # ---------- Mode tab ---------- #
    def _mode_layout():
        return html.Div(
            style={"padding": "20px"},
            children=[
                html.H3("Select Trading Mode"),
                dcc.RadioItems(
                    id="mode_selector",
                    options=[
                        {"label": "Backtest", "value": "backtest"},
                        {"label": "Paper Trading", "value": "paper"},
                    ],
                    value="backtest",
                    labelStyle={"display": "block"},
                    style={"marginBottom": "15px"},
                ),
                html.Button(
                    "INITIATE LIVE",
                    id="go_live_button",
                    n_clicks=0,
                    style={
                        "backgroundColor": "red",
                        "color": "white",
                        "padding": "10px 20px",
                        "border": "none",
                        "cursor": "not-allowed",
                        "opacity": 0.6,
                    },
                    disabled=True,
                ),
                html.Br(),
                html.Div(id="mode_status", style={"marginTop": "20px", "fontSize": "18px"}),
            ],
        )

    # ---------- Summary tab ---------- #
    def _summary_layout():
        summary = summarize_period(base_snapshots, base_trades)
        summary_list = html.Ul([html.Li(f"{k}: {v}") for k, v in summary.items()])
        return html.Div(
            style={"padding": "20px"},
            children=[
                html.H3("(Backtest) Performance Summary"),
                summary_list,
            ],
        )

    # ---------- Mode selector callback ---------- #
    @app.callback(
        Output("mode_status", "children"),
        Input("mode_selector", "value"),
    )
    def update_mode(mode_value):
        snapshots_path = f"data/trade_logs/{mode_value}/portfolio_snapshots.csv"
        trades_path = f"data/trade_logs/{mode_value}/trades.csv"
        return f"Active Mode: {mode_value.capitalize()}"

    # ---------- Dashboard tab components ---------- #
    def _dashboard_layout():
        return html.Div(
            children=[
                # --- ADD THIS: Mode Controls row (lightweight, safe placeholder) ---
                html.Div(
                    [
                        html.H4("Mode Controls (placeholder)"),
                        dcc.RadioItems(
                            id="mode_selector",
                            options=[
                                {"label": "Backtest", "value": "backtest"},
                                {"label": "Paper", "value": "paper"},
                                {"label": "Live (placeholder)", "value": "live"},
                            ],
                            value="backtest",
                            labelStyle={"display": "inline-block", "marginRight": "16px"},
                            inputStyle={"marginRight": "6px"},
                            style={"color": "#EEE"},
                        ),
                        html.Div(id="mode_label", style={"marginTop": "6px", "opacity": 0.85}),
                    ],
                    style={"margin": "6px 0 18px 0", "padding": "8px 12px", "border": "1px solid #333", "borderRadius": "8px"},
                ),
                # --- existing Dashboard rows continue below ---
                html.Div(
                    [
                        html.Div(
                            [
                                html.H4("Performance Summary"),
                                html.Div(id="summary_box"),
                                html.Br(),
                                html.Label("Timeframe"),
                                dcc.Dropdown(
                                    id="timeframe",
                                    options=[
                                        {"label": "All", "value": "all"},
                                        {"label": "1Y", "value": "1y"},
                                        {"label": "6M", "value": "6m"},
                                        {"label": "3M", "value": "3m"},
                                        {"label": "1M", "value": "1m"},
                                    ],
                                    value="all",
                                    clearable=False,
                                    style={"width": 220, "color": "#000"},
                                ),
                            ],
                            style={"width": "28%", "display": "inline-block", "verticalAlign": "top"},
                        ),
                        html.Div(
                            [dcc.Graph(id="equity_chart")],
                            style={"width": "70%", "display": "inline-block"},
                        ),
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div([dcc.Graph(id="drawdown_chart")], style={"margin": "12px 0"}),
                html.H4("Profit / Loss by Edge"),
                html.Div([dcc.Graph(id="edge_pnl_chart")], style={"margin": "12px 0"}),
                html.H4("Recent Trades"),
                html.Pre(id="recent_trades_box"),
            ]
        )

    # ---------- Analytics tab components ---------- #
    def _analytics_layout():
        return html.Div(
            children=[
                html.Div(
                    [
                        html.Label("Timeframe"),
                        dcc.Dropdown(
                            id="timeframe_analytics",
                            options=[
                                {"label": "All", "value": "all"},
                                {"label": "1Y", "value": "1y"},
                                {"label": "6M", "value": "6m"},
                                {"label": "3M", "value": "3m"},
                                {"label": "1M", "value": "1m"},
                            ],
                            value="all",
                            clearable=False,
                            style={"width": 220, "color": "#000"},
                        ),
                        html.Br(),
                        html.Label("Benchmark"),
                        dcc.Dropdown(
                            id="benchmark_selector",
                            options=[
                                {"label": "S&P 500 (^GSPC)", "value": "^GSPC"},
                                {"label": "NASDAQ 100 (^NDX)", "value": "^NDX"},
                                {"label": "Bitcoin (BTC-USD)", "value": "BTC-USD"},
                            ],
                            value="^GSPC",
                            clearable=False,
                            style={"width": 240, "color": "#000"},
                        ),
                    ],
                    style={"margin": "6px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="edge_cum_pnl_chart"),     # Cumulative PnL by Edge Over Time
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="equity_vs_bench_chart"),  # Equity vs SPY / S&P
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="rolling_outperformance_chart"),  # Rolling Outperformance vs Benchmark
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        dcc.Graph(id="pnl_heatmap_chart"),  # Daily PnL Heatmap
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        html.H4("Interactive Playback (coming soon)"),
                        html.Div("A timeline slider to step through trades & equity."),
                    ],
                    style={"margin": "12px 0"},
                ),
                html.Div(
                    [
                        html.H4("Trades Table (coming soon)"),
                        html.Div("Sortable/filterable DataTable by ticker, edge, side, PnL."),
                    ],
                    style={"margin": "12px 0"},
                ),
            ]
        )

    # ---------- Settings tab (placeholder) ---------- #
    def _settings_layout():
        return html.Div(
            children=[
                html.H3("Settings"),
                html.P("Strategy and dashboard settings will appear here."),
            ]
        )

    # ---------------------------- Dashboard Callbacks ---------------------------- #

    @app.callback(
        Output("equity_chart", "figure"),
        Output("drawdown_chart", "figure"),
        Output("edge_pnl_chart", "figure"),
        Output("summary_box", "children"),
        Output("recent_trades_box", "children"),
        Input("timeframe", "value"),
        Input("pulse", "n_intervals"),
        Input("mode_selector", "value"),  # 👈 new input
        prevent_initial_call=False,
    )
    def update_dashboard(tf_value, _n, mode_value):
        # Select mode-dependent CSVs
        snapshots_path = f"data/trade_logs/{mode_value}/portfolio_snapshots.csv"
        trades_path = f"data/trade_logs/{mode_value}/trades.csv"

        # Reload frames from those CSVs
        if use_metrics_loader:
            try:
                m = PerformanceMetrics(snapshots_path=snapshots_path, trades_path=trades_path)
                df = m.snapshots.copy()
                trades = m.trades.copy() if m.trades is not None else pd.DataFrame()
            except Exception:
                df = safe_read_csv(snapshots_path)
                trades = safe_read_csv(trades_path)
        else:
            df = safe_read_csv(snapshots_path)
            trades = safe_read_csv(trades_path)

        # Ensure PnL attribution and types
        if trades is not None and not trades.empty:
            if ("pnl" not in trades.columns) or (trades["pnl"].isna().all()):
                trades = compute_trade_pnl_fifo(trades)
            # Guarantee 'edge' exists for charts
            if "edge" not in trades.columns:
                trades["edge"] = "Unknown"
            for col in ("qty", "fill_price", "pnl"):
                if col in trades.columns:
                    trades[col] = pd.to_numeric(trades[col], errors="coerce")
            trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce")
            trades = trades.dropna(subset=["timestamp"]).sort_values("timestamp")

        df_tf = timeframe_filter(df, tf_value)
        trades_tf = timeframe_filter(trades, tf_value) if (trades is not None and not trades.empty) else pd.DataFrame()

        # --- Summary ---
        summary = summarize_period(df_tf, trades_tf)
        summary_list = html.Ul([html.Li(f"{k}: {v}") for k, v in summary.items()])

        # --- Equity Chart ---
        eq_fig = go.Figure()
        if not df_tf.empty:
            eq_fig.add_trace(
                go.Scatter(
                    x=df_tf["timestamp"],
                    y=df_tf["equity"],
                    mode="lines",
                    name="Equity",
                    line=dict(color="deepskyblue", width=2),
                )
            )

        # Win/Loss markers aligned to last known equity before each trade
        if not df_tf.empty and not trades_tf.empty and "pnl" in trades_tf.columns:
            wins = trades_tf[trades_tf["pnl"] > 0]
            losses = trades_tf[trades_tf["pnl"] <= 0]
            eq_series = df_tf.set_index("timestamp")["equity"]

            def equity_at(ts):
                try:
                    return float(eq_series.loc[:ts].iloc[-1])
                except Exception:
                    return np.nan

            if not wins.empty:
                eq_fig.add_trace(
                    go.Scatter(
                        x=wins["timestamp"],
                        y=[equity_at(ts) for ts in wins["timestamp"]],
                        mode="markers",
                        name="Winning Trades",
                        marker=dict(color="limegreen", size=9, symbol="circle"),
                        hovertext=[
                            f"{r.ticker} | {getattr(r, 'edge', 'Unknown')} | {r.side} | PnL:{float(r.pnl) if pd.notna(r.pnl) else 0:.2f}"
                            for _, r in wins.iterrows()
                        ],
                        hoverinfo="text",
                    )
                )

            if not losses.empty:
                eq_fig.add_trace(
                    go.Scatter(
                        x=losses["timestamp"],
                        y=[equity_at(ts) for ts in losses["timestamp"]],
                        mode="markers",
                        name="Losing Trades",
                        marker=dict(color="red", size=9, symbol="x"),
                        hovertext=[
                            f"{r.ticker} | {getattr(r, 'edge', 'Unknown')} | {r.side} | PnL:{float(r.pnl) if pd.notna(r.pnl) else 0:.2f}"
                            for _, r in losses.iterrows()
                        ],
                        hoverinfo="text",
                    )
                )

        eq_fig.update_layout(
            title="Equity Curve",
            xaxis_title="Date",
            yaxis_title="Equity ($)",
            hovermode="x unified",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )

        # --- Drawdown Chart (capped to [-100%, 0%]) ---
        dd_fig = go.Figure()
        if not df_tf.empty:
            roll_max = df_tf["equity"].cummax()
            drawdown = (df_tf["equity"] - roll_max) / roll_max
            drawdown = drawdown.replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=-1, upper=0)
            dd_fig.add_trace(
                go.Scatter(
                    x=df_tf["timestamp"],
                    y=drawdown,
                    fill="tozeroy",
                    mode="lines",
                    name="Drawdown",
                    line=dict(color="firebrick"),
                )
            )
        dd_fig.update_layout(
            title="Drawdown Over Time",
            xaxis_title="Date",
            yaxis_title="Drawdown",
            yaxis_tickformat=".0%",
            template="plotly_dark",
        )

        # --- PnL by Edge (bar) ---
        edge_fig = go.Figure()
        if trades_tf is not None and not trades_tf.empty and {"edge", "pnl"}.issubset(set(trades_tf.columns)):
            pnl_by_edge = (
                trades_tf.groupby("edge", dropna=False)["pnl"]
                .sum()
                .sort_values(ascending=False)
                .reset_index()
            )
            if not pnl_by_edge.empty:
                colors = ["limegreen" if v >= 0 else "firebrick" for v in pnl_by_edge["pnl"]]
                edge_fig.add_trace(
                    go.Bar(
                        x=pnl_by_edge["edge"].astype(str),
                        y=pnl_by_edge["pnl"],
                        marker_color=colors,
                        text=[f"${v:,.2f}" for v in pnl_by_edge["pnl"]],
                        textposition="auto",
                        name="PnL",
                    )
                )
        edge_fig.update_layout(
            title="Profit / Loss by Edge",
            xaxis_title="Edge",
            yaxis_title="PnL ($)",
            template="plotly_dark",
        )

        # Recent trades text block
        recent_txt = (
            trades_tf.tail(10).to_string(index=False)
            if not trades_tf.empty
            else "No trades found."
        )

        return eq_fig, dd_fig, edge_fig, summary_list, recent_txt
    # ---------- Mode Label Callback (new, lightweight) ----------
    @app.callback(
        Output("mode_label", "children"),
        Input("mode_selector", "value"),
        prevent_initial_call=False,
    )
    def _show_mode_label(mode_value):
        label = "Backtest" if mode_value == "backtest" else ("Paper" if mode_value == "paper" else "Live")
        return f"Active Mode: {label}"
    
    # ---------------------------- Analytics Callbacks ---------------------------- #

    @app.callback(
        Output("edge_cum_pnl_chart", "figure"),
        Output("equity_vs_bench_chart", "figure"),
        Output("pnl_heatmap_chart", "figure"),
        Output("rolling_outperformance_chart", "figure"),
        Input("timeframe_analytics", "value"),
        Input("timeframe_analytics", "value"),
        Input("pulse", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_analytics(tf_value, benchmark_symbol, _n):
        df, trades = base_snapshots, base_trades
        if live:
            df, trades = reload_frames()

        if trades is not None and not trades.empty:
            if ("pnl" not in trades.columns) or (trades["pnl"].isna().all()):
                trades = compute_trade_pnl_fifo(trades)
            if "edge" not in trades.columns:
                trades["edge"] = "Unknown"
            trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce")
            trades = trades.dropna(subset=["timestamp"]).sort_values("timestamp")

        df_tf = timeframe_filter(df, tf_value)
        trades_tf = timeframe_filter(trades, tf_value) if (trades is not None and not trades.empty) else pd.DataFrame()

        # --- Cumulative PnL by Edge Over Time (monthly) ---
        edge_cum_fig = go.Figure()
        if not trades_tf.empty and {"edge", "pnl", "timestamp"}.issubset(set(trades_tf.columns)):
            tmp = trades_tf.copy()
            tmp["month"] = tmp["timestamp"].dt.to_period("M").dt.to_timestamp()
            monthly = tmp.groupby(["edge", "month"], dropna=False)["pnl"].sum().reset_index()
            monthly = monthly.sort_values("month")
            wide = monthly.pivot(index="month", columns="edge", values="pnl").fillna(0.0)
            cum = wide.cumsum()
            if not cum.empty:
                for col in cum.columns:
                    edge_cum_fig.add_trace(
                        go.Scatter(
                            x=cum.index,
                            y=cum[col],
                            mode="lines",
                            name=str(col),
                        )
                    )
        edge_cum_fig.update_layout(
            title="Cumulative PnL by Edge Over Time (Monthly)",
            xaxis_title="Month",
            yaxis_title="Cumulative PnL ($)",
            hovermode="x unified",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )

        # --- Equity vs Benchmark (S&P 500) ---
        eq_vs_fig = go.Figure()
        if not df_tf.empty:
            eq_series = df_tf[["timestamp", "equity"]].copy()
            eq_series = eq_series.dropna()
            if not eq_series.empty:
                eq_series["index"] = 100.0 * (eq_series["equity"] / eq_series["equity"].iloc[0])
                eq_vs_fig.add_trace(
                    go.Scatter(
                        x=eq_series["timestamp"],
                        y=eq_series["index"],
                        mode="lines",
                        name="Strategy",
                    )
                )
                # benchmark
                start = pd.to_datetime(eq_series["timestamp"].min())
                end = pd.to_datetime(eq_series["timestamp"].max())
                bench = load_benchmark(benchmark_symbol, start, end) if yf is not None else pd.DataFrame()
                if bench.empty and yf is not None:  # fallback to SPY if ^GSPC fails
                    bench = load_benchmark("SPY", start, end)
                if not bench.empty:
                    bench = bench[(bench["timestamp"] >= start) & (bench["timestamp"] <= end)]
                    eq_vs_fig.add_trace(
                        go.Scatter(
                            x=bench["timestamp"],
                            y=bench["index"],
                            mode="lines",
                            name="S&P 500",
                        )
                    )
                else:
                    eq_vs_fig.add_annotation(
                        text="Benchmark download failed (offline?). Showing strategy only.",
                        xref="paper", yref="paper", x=0.01, y=0.95, showarrow=False, font=dict(color="orange")
                    )

        eq_vs_fig.update_layout(
            title=f"Equity (Indexed) vs. {benchmark_symbol}",
            xaxis_title="Date",
            yaxis_title="Index (100 = start)",
            hovermode="x unified",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )
                # --- Daily PnL Heatmap ---
        heatmap_fig = go.Figure()
        if not trades_tf.empty and "pnl" in trades_tf.columns:
            tmp = trades_tf.copy()
            tmp["date"] = tmp["timestamp"].dt.date
            daily = tmp.groupby("date")["pnl"].sum().reset_index()
            daily["month"] = pd.to_datetime(daily["date"]).dt.to_period("M").astype(str)
            daily["day"] = pd.to_datetime(daily["date"]).dt.day

            # Pivot to month/day grid
            pivot = daily.pivot(index="day", columns="month", values="pnl").fillna(0.0)
            heatmap_fig.add_trace(
                go.Heatmap(
                    z=pivot.values,
                    x=pivot.columns,
                    y=pivot.index,
                    colorscale=[
                        [0, "rgb(178,34,34)"],   # deep red for losses
                        [0.5, "rgb(64,64,64)"],  # neutral grey
                        [1, "rgb(0,255,128)"],   # bright green for profits
                    ],
                    colorbar=dict(title="PnL ($)"),
                    hoverongaps=False,
                )
            )

        heatmap_fig.update_layout(
            title="PnL Heatmap by Day",
            xaxis_title="Month",
            yaxis_title="Day of Month",
            template="plotly_dark",
            yaxis_autorange="reversed",
        )
                # --- Rolling Outperformance vs Benchmark (30-day) ---
        outperf_fig = go.Figure()
        if not df_tf.empty:
            eq_series = df_tf[["timestamp", "equity"]].dropna().copy()
            eq_series["return"] = eq_series["equity"].pct_change().fillna(0.0)

            # Benchmark alignment
            start = pd.to_datetime(eq_series["timestamp"].min())
            end = pd.to_datetime(eq_series["timestamp"].max())
            bench = load_benchmark(benchmark_symbol, start, end) if yf is not None else pd.DataFrame()
            if bench.empty and yf is not None:
                bench = load_benchmark("SPY", start, end)
            if not bench.empty:
                bench["return"] = bench["index"].pct_change().fillna(0.0)
                merged = pd.merge_asof(
                    eq_series.sort_values("timestamp"),
                    bench.sort_values("timestamp")[["timestamp", "return"]],
                    on="timestamp",
                    direction="backward",
                    suffixes=("_strategy", "_benchmark"),
                )

                merged["diff"] = merged["return_strategy"] - merged["return_benchmark"]
                merged["rolling_diff"] = merged["diff"].rolling(window=30).mean() * 100.0

                outperf_fig.add_trace(
                    go.Scatter(
                        x=merged["timestamp"],
                        y=merged["rolling_diff"],
                        mode="lines",
                        name="Rolling Outperformance (30D, %)",
                        line=dict(color="limegreen"),
                    )
                )

                # Highlight underperformance (negative rolling diff)
                under = merged[merged["rolling_diff"] < 0]
                if not under.empty:
                    outperf_fig.add_trace(
                        go.Scatter(
                            x=under["timestamp"],
                            y=under["rolling_diff"],
                            mode="lines",
                            name="Underperformance",
                            line=dict(color="firebrick", width=1),
                        )
                    )
            else:
                outperf_fig.add_annotation(
                    text="Benchmark data unavailable (offline?).",
                    xref="paper", yref="paper", x=0.01, y=0.95, showarrow=False, font=dict(color="orange")
                )

        outperf_fig.update_layout(
            title=f"Rolling Outperformance vs {benchmark_symbol} (30-Day Average)",
            xaxis_title="Date",
            yaxis_title="Excess Return (%)",
            hovermode="x unified",
            template="plotly_dark",
            legend=dict(x=0, y=1),
        )

        return edge_cum_fig, eq_vs_fig, heatmap_fig, outperf_fig

    app.run(debug=True)


# ---------------------------- CLI Entry ---------------------------- #

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run trading cockpit dashboard.")
    parser.add_argument("--live", action="store_true", help="Auto-refresh from CSVs every 2s.")
    parser.add_argument("--snapshots", default="data/trade_logs/portfolio_snapshots.csv")
    parser.add_argument("--trades", default="data/trade_logs/trades.csv")
    args = parser.parse_args()

    run_dashboard(live=args.live, snapshots_csv=args.snapshots, trades_csv=args.trades)