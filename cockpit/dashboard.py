# cockpit/dashboard.py

import pandas as pd
import dash
from dash import dcc, html
import plotly.graph_objects as go
from cockpit.metrics import PerformanceMetrics


def compute_trade_pnl(trades: pd.DataFrame):
    """Estimate simple PnL by pairing consecutive trades per ticker."""
    if trades is None or trades.empty:
        return trades

    trades = trades.copy()
    trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce")

    trades.sort_values(["ticker", "timestamp"], inplace=True)

    trades["pnl"] = 0.0
    for tkr, tdf in trades.groupby("ticker"):
        tdf = tdf.sort_values("timestamp")
        prev = None
        for idx, row in tdf.iterrows():
            if prev is not None:
                if row["side"] == "long":
                    pnl = (row["fill_price"] - prev["fill_price"]) * prev["qty"]
                else:
                    pnl = (prev["fill_price"] - row["fill_price"]) * prev["qty"]
                trades.loc[idx, "pnl"] = pnl
            prev = row
    return trades


def run_dashboard():
    # Load performance data
    metrics = PerformanceMetrics(
        snapshots_path="data/trade_logs/portfolio_snapshots.csv",
        trades_path="data/trade_logs/trades.csv",
    )

    df = metrics.snapshots
    trades = metrics.trades

    # Compute synthetic PnL if not logged yet
    if trades is not None and "pnl" not in trades.columns:
        trades = compute_trade_pnl(trades)

    # Initialize Dash app
    app = dash.Dash(__name__)
    app.title = "Trading Cockpit"

    # --- Equity Curve Figure ---
    equity_fig = go.Figure()

    # Base equity curve
    equity_fig.add_trace(go.Scatter(
        x=df["timestamp"],
        y=df["equity"],
        mode="lines",
        name="Equity",
        line=dict(color="deepskyblue", width=2)
    ))

    # Add PnL markers if available
    if trades is not None and "pnl" in trades.columns:
        trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce")

        wins = trades[trades["pnl"] > 0]
        losses = trades[trades["pnl"] <= 0]

        equity_fig.add_trace(go.Scatter(
            x=wins["timestamp"],
            y=wins["fill_price"],
            mode="markers",
            name="Winning Trades",
            marker=dict(color="limegreen", size=10, symbol="circle"),
            hovertext=[
                f"{r.ticker} | {r.side} | Qty: {r.qty} | Price: {r.fill_price:.2f} | Est. PnL: {r.pnl:.2f}"
                for _, r in wins.iterrows()
            ],
            hoverinfo="text"
        ))

        equity_fig.add_trace(go.Scatter(
            x=losses["timestamp"],
            y=losses["fill_price"],
            mode="markers",
            name="Losing Trades",
            marker=dict(color="red", size=10, symbol="x"),
            hovertext=[
                f"{r.ticker} | {r.side} | Qty: {r.qty} | Price: {r.fill_price:.2f} | Est. PnL: {r.pnl:.2f}"
                for _, r in losses.iterrows()
            ],
            hoverinfo="text"
        ))

    equity_fig.update_layout(
        title="Portfolio Equity Curve (with Trade PnL Markers)",
        xaxis_title="Date",
        yaxis_title="Equity / Price ($)",
        hovermode="x unified",
        template="plotly_dark",
        legend=dict(x=0, y=1)
    )

    # --- Drawdown Figure ---
    roll_max = df["equity"].cummax()
    drawdown = (df["equity"] - roll_max) / roll_max
    drawdown_fig = go.Figure()
    drawdown_fig.add_trace(go.Scatter(
        x=df["timestamp"],
        y=drawdown,
        fill="tozeroy",
        mode="lines",
        name="Drawdown",
        line=dict(color="firebrick")
    ))
    drawdown_fig.update_layout(
        title="Drawdown Over Time",
        xaxis_title="Date",
        yaxis_title="Drawdown (%)",
        template="plotly_dark",
    )

    # --- Dashboard Layout ---
    app.layout = html.Div([
        html.H1("Trading Cockpit Dashboard", style={"textAlign": "center"}),

        html.Div([
            html.Div([
                html.H4("Performance Summary"),
                html.Ul([
                    html.Li(f"{k}: {v}") for k, v in metrics.summary().items()
                ])
            ], style={"width": "30%", "display": "inline-block", "verticalAlign": "top"}),

            html.Div([
                dcc.Graph(figure=equity_fig)
            ], style={"width": "65%", "display": "inline-block"})
        ], style={"margin": "20px"}),

        html.Div([
            dcc.Graph(figure=drawdown_fig)
        ], style={"margin": "20px"}),

        html.H4("Recent Trades"),
        html.Pre(trades.tail(10).to_string(index=False) if trades is not None else "No trades found.")
    ])

    app.run(debug=True)


if __name__ == "__main__":
    run_dashboard()