# cockpit/dashboard/tabs/dashboard_tab.py
from __future__ import annotations
from dash import dcc, html

def mode_layout():
    return html.Div(
        style={
            "minHeight": "78vh",
            "background": "linear-gradient(180deg,#121212,#101010,#0c0c0c)",
            "borderRadius": "12px",
            "padding": "28px 28px 40px 28px",
            "boxShadow": "0 0 12px rgba(0,0,0,0.55)",
        },
        children=[
            html.Div(
                style={
                    "display": "flex",
                    "justifyContent": "space-between",
                    "alignItems": "flex-start",
                    "gap": "24px",
                    "flexWrap": "wrap",
                },
                children=[
                    html.Div(
                        style={
                            "flex": "0 0 320px",
                            "backgroundColor": "#171717",
                            "border": "1px solid #2a2a2a",
                            "borderRadius": "10px",
                            "padding": "18px 20px",
                        },
                        children=[
                            html.H3("Select Trading Mode", style={"marginTop": 0}),
                            dcc.RadioItems(
                                id="mode_selector_radio",
                                options=[
                                    {"label": "Backtest", "value": "backtest"},
                                    {"label": "Paper Trading", "value": "paper"},
                                ],
                                value="backtest",
                                labelStyle={"display": "block", "margin": "10px 0"},
                                style={"fontSize": "16px"},
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
                                    "marginTop": "10px",
                                },
                                disabled=True,
                            ),
                            html.Div(id="mode_status", style={"marginTop": "12px", "fontSize": "16px"}),
                        ],
                    ),
                    html.Div(
                        id="mode_summary_box",
                        style={
                            "flex": "1 1 480px",
                            "minWidth": "420px",
                            "backgroundColor": "#171717",
                            "border": "1px solid #2a2a2a",
                            "borderRadius": "10px",
                            "padding": "18px 22px",
                        },
                    ),
                ],
            ),
        ],
    )

def dashboard_layout():
    return html.Div(
        style={"backgroundColor": "#161b22", "padding": "16px 18px", "borderRadius": "12px"},
        children=[
            html.Div(
                [
                    html.H4(id="mode_label", style={"margin": "0 0 6px 0"}),
                    html.Div(
                        id="mode_top_indicator",
                        style={"fontSize": "18px", "fontWeight": "bold", "marginLeft": "10px", "display": "inline-block"},
                    ),
                ],
                style={
                    "margin": "0 0 10px 0",
                    "padding": "8px 12px",
                    "background": "#171717",
                    "border": "1px solid #222",
                    "borderRadius": "8px",
                    "display": "flex",
                    "alignItems": "center",
                },
            ),
            html.Div(
                [
                    html.Div(
                        [
                            html.H4("Performance Summary"),
                            html.Div(id="summary_box"),
                            html.Br(),
                            html.Div(
                                style={"display": "flex", "alignItems": "center", "gap": "10px"},
                                children=[
                                    html.Label("Timeframe", style={"marginBottom": 0}),
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
                                        style={"width": 120, "color": "#000", "marginRight": "10px"},
                                    ),
                                    html.Button(
                                        "Refresh Data",
                                        id="refresh_button",
                                        n_clicks=0,
                                        style={
                                            "backgroundColor": "#2d8cff",
                                            "color": "#fff",
                                            "padding": "5px 18px",
                                            "border": "none",
                                            "borderRadius": "5px",
                                            "fontSize": "15px",
                                            "fontWeight": "bold",
                                            "boxShadow": "0 1px 4px #0003",
                                            "cursor": "pointer",
                                        },
                                    ),
                                ],
                            ),
                        ],
                        style={
                            "width": "32%",
                            "display": "inline-block",
                            "verticalAlign": "top",
                            "backgroundColor": "#1b1b1b",
                            "borderRadius": "10px",
                            "border": "1px solid #232323",
                            "padding": "18px 18px 10px 18px",
                            "boxShadow": "0 0 8px #0004",
                            "minHeight": "320px",
                        },
                    ),
                    html.Div(
                        [dcc.Graph(id="equity_chart")],
                        style={
                            "width": "66%",
                            "display": "inline-block",
                            "backgroundColor": "#1b1b1b",
                            "borderRadius": "10px",
                            "border": "1px solid #232323",
                            "padding": "12px 8px 10px 8px",
                            "boxShadow": "0 0 8px #0004",
                            "minHeight": "320px",
                            "verticalAlign": "top",
                        },
                    ),
                ],
                style={"margin": "12px 0", "display": "flex", "gap": "18px"},
            ),
            html.Div(
                [dcc.Graph(id="drawdown_chart")],
                style={"margin": "12px 0", "backgroundColor": "#1b1b1b", "borderRadius": "10px", "padding": "10px 8px", "boxShadow": "0 0 8px #0004"},
            ),
            html.H4("Profit / Loss by Edge"),
            html.Div(
                [dcc.Graph(id="edge_pnl_chart")],
                style={"margin": "12px 0", "backgroundColor": "#1b1b1b", "borderRadius": "10px", "padding": "10px 8px", "boxShadow": "0 0 8px #0004"},
            ),
            html.H4("Recent Trades"),
            html.Pre(
                id="recent_trades_box",
                style={"backgroundColor": "#181818", "borderRadius": "8px", "padding": "12px", "fontSize": "14px", "color": "#e0e0e0", "border": "1px solid #232323"},
            ),
        ],
    )
