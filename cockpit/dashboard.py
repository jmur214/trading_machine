# cockpit/dashboard.py

import pandas as pd
import numpy as np
import dash
from dash import dcc, html, Input, Output
import plotly.graph_objects as go
from cockpit.metrics import PerformanceMetrics


def compute_trade_pnl(trades: pd.DataFrame) -> pd.DataFrame:
    """
    Estimate realized PnL by pairing entries/exits per ticker.
    Realizes PnL when side flips (long <-> short) or when side == 'exit'.
    Leaves PnL NaN for open legs.
    """
    if trades is None or trades.empty:
        return trades

    trades = trades.copy()
    trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce")
    trades.sort_values(["ticker", "timestamp"], inplace=True)
    if "pnl" not in trades.columns:
        trades["pnl"] = np.nan

    for tkr, tdf in trades.groupby("ticker", sort=False):
        prev_row = None
        for idx, row in tdf.iterrows():
            if prev_row is not None:
                side_now = str(row["side"]).lower()
                side_prev = str(prev_row["side"]).lower()

                flipped = (side_now in ("long", "short")) and (side_prev in ("long", "short")) and (side_now != side_prev)
                explicit_exit = (side_now == "exit")

                if flipped or explicit_exit:
                    qty_closed = min(abs(int(prev_row["qty"])), abs(int(row["qty"])))
                    direction = 1 if side_prev == "long" else -1
                    realized = (float(row["fill_price"]) - float(prev_row["fill_price"])) * qty_closed * direction
                    trades.loc[idx, "pnl"] = round(realized, 2)
            prev_row = row
    return trades


def timeframe_filter(df: pd.DataFrame, tf_value: str) -> pd.DataFrame:
    """Filter dataframe by timeframe code."""
    if df is None or df.empty:
        return df
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
    if tf_value == "all":
        return df
    if df["timestamp"].empty:
        return df

    end_date = df["timestamp"].max()
    offsets = {
        "1y": pd.DateOffset(years=1),
        "6m": pd.DateOffset(months=6),
        "3m": pd.DateOffset(months=3),
        "1m": pd.DateOffset(months=1),
    }
    if tf_value in offsets:
        start = end_date - offsets[tf_value]
        return df[df["timestamp"] >= start]
    return df


def summarize_period(df_snap: pd.DataFrame, df_trades: pd.DataFrame) -> dict:
    """Compute realistic summary for the filtered period (caps drawdown >= -100%)."""
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

    # Total return
    if start_eq <= 0:
        total_ret = np.nan
    else:
        total_ret = (end_eq - start_eq) / start_eq

    # Period length for CAGR
    days = (df_snap["timestamp"].iloc[-1] - df_snap["timestamp"].iloc[0]).days
    if (not np.isnan(total_ret)) and days > 0:
        cagr = (1 + total_ret) ** (365.0 / days) - 1
    else:
        cagr = np.nan

    # Drawdown (cap at -100%)
    roll_max = df_snap["equity"].cummax()
    dd = (df_snap["equity"] - roll_max) / roll_max
    dd = dd.clip(lower=-1, upper=0)
    max_dd = dd.min() * 100.0  # percent

    # Returns stats
    rets = df_snap["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    vol = rets.std() * np.sqrt(252) * 100.0 if not rets.empty else np.nan
    sharpe = (rets.mean() / rets.std()) * np.sqrt(252) if not rets.empty and rets.std() > 0 else np.nan

    # Win rate from realized PnL
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


def run_dashboard():
    # Load via PerformanceMetrics (robust csv handling)
    metrics = PerformanceMetrics(
        snapshots_path="data/trade_logs/portfolio_snapshots.csv",
        trades_path="data/trade_logs/trades.csv",
    )
    df = metrics.snapshots.copy()
    trades = metrics.trades.copy() if metrics.trades is not None else pd.DataFrame()

    # Backfill PnL if missing or all NaN
    if trades is not None and not trades.empty:
        if ("pnl" not in trades.columns) or (trades["pnl"].isna().all()):
            trades = compute_trade_pnl(trades)
        # ensure numeric types
        for col in ("qty", "fill_price", "pnl"):
            if col in trades.columns:
                trades[col] = pd.to_numeric(trades[col], errors="coerce")
        trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce")
        trades = trades.dropna(subset=["timestamp"])

    app = dash.Dash(__name__)
    app.title = "Trading Cockpit"

    # Layout (keeps your original visuals; summary becomes dynamic)
    app.layout = html.Div(
        style={"backgroundColor": "#111", "color": "#EEE", "padding": "18px"},
        children=[
            html.H1("Trading Dashboard", style={"textAlign": "center"}),

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
                        [
                            dcc.Graph(id="equity_chart"),
                        ],
                        style={"width": "70%", "display": "inline-block"},
                    ),
                ],
                style={"margin": "12px 0"},
            ),

            html.Div(
                [dcc.Graph(id="drawdown_chart")],
                style={"margin": "12px 0"},
            ),

            html.H4("Recent Trades"),
            html.Pre(id="recent_trades_box"),
        ],
    )

    @app.callback(
        Output("equity_chart", "figure"),
        Output("drawdown_chart", "figure"),
        Output("summary_box", "children"),
        Output("recent_trades_box", "children"),
        Input("timeframe", "value"),
    )
    def update_all(tf_value):
        # Filter snapshots and trades by timeframe
        df_tf = timeframe_filter(df, tf_value)
        trades_tf = timeframe_filter(trades, tf_value) if trades is not None and not trades.empty else pd.DataFrame()

        # --- Summary (dynamic) ---
        summary = summarize_period(df_tf, trades_tf)
        summary_list = html.Ul([html.Li(f"{k}: {v}") for k, v in summary.items()])

        # --- Equity figure ---
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

        # Plot winning/losing trade markers ON the equity curve (your original style)
        if not df_tf.empty and not trades_tf.empty and "pnl" in trades_tf.columns:
            wins = trades_tf[trades_tf["pnl"] > 0]
            losses = trades_tf[trades_tf["pnl"] <= 0]

            # Align trade markers with nearest prior equity value for Y axis
            eq_series = df_tf.set_index("timestamp")["equity"]

            def equity_at(ts):
                try:
                    return float(eq_series.loc[:ts].iloc[-1])
                except Exception:
                    return np.nan

            if not wins.empty:
                y_wins = [equity_at(ts) for ts in wins["timestamp"]]
                eq_fig.add_trace(
                    go.Scatter(
                        x=wins["timestamp"],
                        y=y_wins,
                        mode="markers",
                        name="Winning Trades",
                        marker=dict(color="limegreen", size=9, symbol="circle"),
                        hovertext=[
                            f"{r.ticker} | {r.side} | Qty: {int(r.qty)} | Px: {float(r.fill_price):.2f} | PnL: {float(r.pnl) if pd.notna(r.pnl) else 0:.2f}"
                            for _, r in wins.iterrows()
                        ],
                        hoverinfo="text",
                    )
                )

            if not losses.empty:
                y_losses = [equity_at(ts) for ts in losses["timestamp"]]
                eq_fig.add_trace(
                    go.Scatter(
                        x=losses["timestamp"],
                        y=y_losses,
                        mode="markers",
                        name="Losing Trades",
                        marker=dict(color="red", size=9, symbol="x"),
                        hovertext=[
                            f"{r.ticker} | {r.side} | Qty: {int(r.qty)} | Px: {float(r.fill_price):.2f} | PnL: {float(r.pnl) if pd.notna(r.pnl) else 0:.2f}"
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

        # --- Drawdown figure (capped >= -100%) ---
        dd_fig = go.Figure()
        if not df_tf.empty:
            roll_max = df_tf["equity"].cummax()
            drawdown = (df_tf["equity"] - roll_max) / roll_max
            drawdown = drawdown.clip(lower=-1, upper=0)  # cap at -100% for realism
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
            yaxis_tickformat=".0%",  # show as percent
            template="plotly_dark",
        )

        recent_txt = (
            trades_tf.tail(10).to_string(index=False)
            if not trades_tf.empty
            else "No trades found."
        )

        return eq_fig, dd_fig, summary_list, recent_txt

    app.run(debug=True)


if __name__ == "__main__":
    run_dashboard()