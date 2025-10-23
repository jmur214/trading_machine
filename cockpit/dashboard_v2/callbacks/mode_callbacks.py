

import os
from pathlib import Path
import pandas as pd
import numpy as np
from dash import html
from dash.dependencies import Output, Input

# Import helper functions from v2 or fallback to dashboard.py
try:
    from cockpit.dashboard.utils import safe_read_csv, compute_trade_pnl_fifo, summarize_period, _summary_kpi_cards
except ImportError:
    from cockpit.dashboard.dashboard import safe_read_csv, compute_trade_pnl_fifo, summarize_period, _summary_kpi_cards

try:
    from cockpit.metrics import PerformanceMetrics
except ImportError:
    try:
        from metrics import PerformanceMetrics
    except Exception:
        PerformanceMetrics = None

# Get Alpaca keys from environment
ALPACA_API_KEY = os.environ.get("APCA_API_KEY_ID", "")
ALPACA_API_SECRET = os.environ.get("APCA_API_SECRET_KEY", "")


def register_mode_callbacks(app):
    @app.callback(
        Output("mode_summary_box", "children"),
        Input("mode_state", "data"),
        prevent_initial_call=False,
    )
    def _update_mode_summary(mode_value):
        # --- PAPER MODE ---
        if mode_value == "paper":
            try:
                from alpaca.trading.client import TradingClient
            except Exception:
                TradingClient = None
            if TradingClient is None or not ALPACA_API_KEY or not ALPACA_API_SECRET:
                return html.Div(
                    [
                        html.H3("(Paper) Account Summary", style={"marginTop": 0}),
                        html.Div(
                            "No paper account connected.",
                            style={"color": "#ffb300", "fontSize": "22px", "padding": "18px 0"},
                        ),
                    ],
                    style={
                        "backgroundColor": "#1b1b1b",
                        "padding": "18px 20px",
                        "borderRadius": "8px",
                        "boxShadow": "0 0 8px rgba(0,0,0,0.5)",
                    },
                )
            try:
                client = TradingClient(ALPACA_API_KEY, ALPACA_API_SECRET, paper=True)
                account = client.get_account()
                positions = client.get_all_positions()
                equity = float(getattr(account, "equity", None) or 0)
                buying_power = float(getattr(account, "buying_power", None) or 0)
                cash = float(getattr(account, "cash", None) or 0)
                unrealized_pl = float(getattr(account, "unrealized_pl", None) or 0)
                card_style = {
                    "backgroundColor": "#181c22",
                    "color": "#e0e0e0",
                    "padding": "16px 18px",
                    "borderRadius": "10px",
                    "boxShadow": "0 2px 12px rgba(0,0,0,0.21)",
                    "margin": "0 10px 12px 0",
                    "minWidth": "140px",
                    "textAlign": "center",
                    "display": "inline-block",
                }
                def fmt(val, prefix="$"):
                    try:
                        return f"{prefix}{float(val):,.2f}"
                    except Exception:
                        return "-"
                kpis = [
                    html.Div([html.Div("Equity", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                              html.Div(fmt(equity), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                    html.Div([html.Div("Buying Power", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                              html.Div(fmt(buying_power), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                    html.Div([html.Div("Cash", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                              html.Div(fmt(cash), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                    html.Div([html.Div("Unrealized PnL", style={"fontSize": "15px", "opacity": 0.76, "marginBottom": "6px"}),
                              html.Div(fmt(unrealized_pl), style={"fontSize": "22px", "fontWeight": 600})], style=card_style),
                ]
                pos_list = []
                if positions:
                    for pos in positions:
                        try:
                            symbol = getattr(pos, "symbol", "-")
                            qty = getattr(pos, "qty", "-")
                            unreal = getattr(pos, "unrealized_pl", "-")
                            side = getattr(pos, "side", "-")
                            pos_list.append(f"{symbol} ({side}) | Qty: {qty} | Unr. PnL: ${float(unreal):,.2f}")
                        except Exception:
                            continue
                return html.Div(
                    [
                        html.H3("(Paper) Account Summary", style={"marginTop": 0}),
                        html.Div(
                            kpis,
                            style={"display": "flex", "flexWrap": "wrap", "gap": "0.5rem", "marginBottom": "10px"},
                        ),
                        html.Div(
                            [
                                html.Div("Open Positions:", style={"fontWeight": 600, "fontSize": "16px", "marginBottom": "4px"}),
                                html.Div(
                                    "\n".join(pos_list) if pos_list else "No open positions.",
                                    style={"whiteSpace": "pre-line", "fontSize": "15px"},
                                ),
                            ],
                            style={
                                "backgroundColor": "#181c22",
                                "padding": "10px 12px",
                                "borderRadius": "8px",
                                "marginTop": "8px",
                            },
                        ),
                    ],
                    style={
                        "backgroundColor": "#1b1b1b",
                        "padding": "18px 20px",
                        "borderRadius": "8px",
                        "boxShadow": "0 0 8px rgba(0,0,0,0.5)",
                    },
                )
            except Exception:
                return html.Div(
                    [
                        html.H3("(Paper) Account Summary", style={"marginTop": 0}),
                        html.Div(
                            "No paper account connected.",
                            style={"color": "#ffb300", "fontSize": "22px", "padding": "18px 0"},
                        ),
                    ],
                    style={
                        "backgroundColor": "#1b1b1b",
                        "padding": "18px 20px",
                        "borderRadius": "8px",
                        "boxShadow": "0 0 8px rgba(0,0,0,0.5)",
                    },
                )

        # --- BACKTEST OR OTHER MODES ---
        # Compose file paths
        snapshots_path = f"data/trade_logs/{mode_value}/portfolio_snapshots.csv"
        trades_path = f"data/trade_logs/{mode_value}/trades.csv"
        default_snapshots = "data/trade_logs/portfolio_snapshots.csv"
        default_trades = "data/trade_logs/trades.csv"
        def file_exists(path):
            return Path(path).exists() and Path(path).stat().st_size > 0
        if not file_exists(snapshots_path):
            snapshots_path = default_snapshots
        if not file_exists(trades_path):
            trades_path = default_trades
        # Load snapshots/trades using metrics if possible, else CSV fallback
        if PerformanceMetrics is not None:
            try:
                m = PerformanceMetrics(snapshots_path=snapshots_path, trades_path=trades_path)
                df_snap = m.snapshots.copy()
                df_tr = m.trades.copy() if m.trades is not None else pd.DataFrame()
            except Exception:
                df_snap = safe_read_csv(snapshots_path)
                df_tr = safe_read_csv(trades_path)
        else:
            df_snap = safe_read_csv(snapshots_path)
            df_tr = safe_read_csv(trades_path)
        # Ensure trade PnL exists for win rate
        if df_tr is not None and not df_tr.empty:
            if ("pnl" not in df_tr.columns) or (df_tr["pnl"].isna().all()):
                df_tr = compute_trade_pnl_fifo(df_tr)
        summary = summarize_period(df_snap, df_tr)
        return html.Div(
            [
                html.H3(f"({mode_value.capitalize()}) Performance Summary", style={"marginTop": 0}),
                html.Div(_summary_kpi_cards(summary)),
            ],
            style={
                "backgroundColor": "#1b1b1b",
                "padding": "18px 20px",
                "borderRadius": "8px",
                "boxShadow": "0 0 8px rgba(0,0,0,0.5)",
            },
        )