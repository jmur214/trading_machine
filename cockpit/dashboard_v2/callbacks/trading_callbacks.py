# cockpit/dashboard_v2/callbacks/trading_callbacks.py
"""Callbacks for the Trading tab — account overview, positions, fills, equity curve."""
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
from dash import Input, Output, html, no_update
import plotly.graph_objects as go

from ..utils.styles import CARD_STYLE, COLORS, KPI_CARD_STYLE, accent_line, status_badge
from ..utils.chart_helpers import get_chart_layout, empty_chart


def register_trading_callbacks(app):

    # ---- Connection badge ----
    @app.callback(
        Output("trading-connection-badge", "children"),
        Output("trading-connection-badge", "style"),
        Input("trading-poll", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_connection_badge(_n):
        api_key = os.environ.get("APCA_API_KEY_ID", "")
        if api_key:
            return "PAPER CONNECTED", status_badge("complete")
        return "NOT CONFIGURED", status_badge("idle")

    # ---- Account KPIs ----
    @app.callback(
        Output("trading-account-kpis", "children"),
        Input("trading-poll", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_account_kpis(_n):
        snapshot_path = Path("data/snapshots/portfolio_snapshot.csv")
        if not snapshot_path.exists():
            return html.Div(
                style={**CARD_STYLE, "textAlign": "center", "padding": "40px"},
                children=[
                    html.P("No portfolio data available.", style={
                        "color": COLORS["text_dim"], "fontSize": "14px", "margin": "0 0 8px",
                    }),
                    html.P("Run a backtest or connect a paper trading account to see account data.", style={
                        "color": COLORS["text_dim"], "fontSize": "12px", "margin": "0",
                    }),
                ],
            )

        try:
            df = pd.read_csv(snapshot_path)
        except Exception:
            return html.Div()

        if df.empty:
            return html.Div()

        latest = df.iloc[-1]
        kpi_items = []

        # Build KPIs from available columns
        col_map = [
            ("equity", "Equity", COLORS["accent_blue"]),
            ("cash", "Cash", COLORS["accent_green"]),
            ("buying_power", "Buying Power", COLORS["accent_purple"]),
            ("total_pnl", "Total PnL", COLORS["accent_green"]),
            ("unrealized_pnl", "Unrealized PnL", COLORS["accent_yellow"]),
        ]

        for col, label, color in col_map:
            if col in latest.index:
                val = latest[col]
                if pd.notna(val):
                    formatted = f"${val:,.2f}" if isinstance(val, (int, float)) else str(val)
                    kpi_items.append((label, formatted, color))

        if not kpi_items:
            return html.Div()

        cards = []
        for label, val, color in kpi_items:
            cards.append(
                html.Div(
                    style={**KPI_CARD_STYLE, "position": "relative", "overflow": "hidden"},
                    children=[
                        html.Div(style=accent_line(color)),
                        html.Div(label, style={
                            "fontSize": "11px", "fontWeight": "500", "color": COLORS["text_dim"],
                            "textTransform": "uppercase", "letterSpacing": "0.05em", "marginBottom": "6px",
                        }),
                        html.Div(str(val), style={
                            "fontSize": "18px", "fontWeight": "700", "color": COLORS["text_secondary"],
                        }),
                    ],
                )
            )

        return html.Div(cards, style={
            "display": "grid",
            "gridTemplateColumns": "repeat(auto-fit, minmax(160px, 1fr))",
            "gap": "16px",
        })

    # ---- Positions table ----
    @app.callback(
        Output("trading-positions-table", "data"),
        Input("trading-poll", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_positions(_n):
        positions_path = Path("data/snapshots/positions.csv")
        if not positions_path.exists():
            return []
        try:
            df = pd.read_csv(positions_path)
            return df.to_dict("records")
        except Exception:
            return []

    # ---- Fills table ----
    @app.callback(
        Output("trading-fills-table", "data"),
        Input("trading-poll", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_fills(_n):
        fills_path = Path("data/trades/fill_log.csv")
        if not fills_path.exists():
            return []
        try:
            df = pd.read_csv(fills_path)
            if "timestamp" in df.columns:
                df = df.sort_values("timestamp", ascending=False)
            return df.head(20).to_dict("records")
        except Exception:
            return []

    # ---- Equity curve chart ----
    @app.callback(
        Output("trading-equity-chart", "figure"),
        Input("trading-poll", "n_intervals"),
        prevent_initial_call=False,
    )
    def update_equity_chart(_n):
        snapshot_path = Path("data/snapshots/portfolio_snapshot.csv")
        if not snapshot_path.exists():
            return empty_chart("No equity data available")

        try:
            df = pd.read_csv(snapshot_path)
        except Exception:
            return empty_chart("Error loading equity data")

        if df.empty or "equity" not in df.columns:
            return empty_chart("No equity column found")

        date_col = None
        for col in ("date", "timestamp", "Date"):
            if col in df.columns:
                date_col = col
                break

        x_vals = df[date_col] if date_col else list(range(len(df)))

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=x_vals,
            y=df["equity"],
            mode="lines",
            line={"color": COLORS["accent_blue"], "width": 2},
            fill="tozeroy",
            fillcolor="rgba(88, 166, 255, 0.08)",
            name="Equity",
        ))
        fig.update_layout(get_chart_layout("Paper Account Equity"))
        return fig
