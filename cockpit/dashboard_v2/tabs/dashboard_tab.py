# cockpit/dashboard_v2/tabs/dashboard_tab.py
"""Main dashboard tab with KPIs and charts."""
from __future__ import annotations
from dash import dcc, html, dash_table

from ..utils.styles import CARD_STYLE, CHART_CONTAINER, SECTION_HEADER, COLORS


def dashboard_layout():
    """Main dashboard tab with professional KPIs and charts."""
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Mode Indicator Bar
            html.Div(
                style={
                    **CARD_STYLE,
                    "display": "flex",
                    "alignItems": "center",
                    "justifyContent": "space-between",
                    "padding": "16px 24px",
                    "marginBottom": "24px",
                },
                children=[
                    html.Div(
                        children=[
                            html.Span(id="mode_label", style={"fontSize": "14px", "color": "#8b949e", "marginRight": "12px"}),
                            html.Span(id="mode_top_indicator"),
                        ],
                    ),
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "16px"},
                        children=[
                            html.Label("Timeframe:", style={"color": "#8b949e", "fontSize": "13px", "marginBottom": "0"}),
                            dcc.Dropdown(
                                id="timeframe",
                                options=[
                                    {"label": "All Time", "value": "all"},
                                    {"label": "1 Year", "value": "1y"},
                                    {"label": "6 Months", "value": "6m"},
                                    {"label": "3 Months", "value": "3m"},
                                    {"label": "1 Month", "value": "1m"},
                                ],
                                value="all",
                                clearable=False,
                                style={"width": "140px"},
                            ),
                            html.Button(
                                "Refresh",
                                id="refresh_button",
                                n_clicks=0,
                            ),
                        ],
                    ),
                ],
            ),
            
            # KPI Summary Section
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Performance Overview", style={"margin": "0", "color": "#f0f6fc"}),
                ]
            ),
            html.Div(
                id="summary_box",
                style={"marginBottom": "32px"},
            ),
            
            # Charts Grid
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px", "marginBottom": "24px"},
                children=[
                    html.Div(
                        style=CHART_CONTAINER,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Equity Curve", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="equity_chart", style={"height": "300px"}, config={"displayModeBar": False}),
                        ],
                    ),
                    html.Div(
                        style=CHART_CONTAINER,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Drawdown", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="drawdown_chart", style={"height": "300px"}, config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),
            
            # Bottom Grid: Strategy PnL & Activity
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px", "marginBottom": "24px"},
                children=[
                    # Strategy PnL
                    html.Div(
                        style=CHART_CONTAINER,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Profit/Loss by Strategy", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="edge_pnl_chart", style={"height": "300px"}, config={"displayModeBar": False}),
                        ],
                    ),
                    
                    # Recent Activity
                    html.Div(
                        style=CHART_CONTAINER,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Recent Activity", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dash_table.DataTable(
                                id="recent_trades_table",
                                data=[],
                                columns=[
                                    {"name": "Date", "id": "timestamp"},
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Side", "id": "side"},
                                    {"name": "Qty", "id": "qty"},
                                    {"name": "Price", "id": "fill_price"},
                                    {"name": "PnL", "id": "pnl"},
                                ],
                                page_size=8,
                                sort_action="native",
                                filter_action="native",
                                style_table={"overflowX": "auto", "height": "290px", "overflowY": "auto"},
                                style_header={
                                    "backgroundColor": "rgba(22, 27, 34, 0.9)",
                                    "color": "#c9d1d9",
                                    "fontWeight": "600",
                                    "fontSize": "11px",
                                    "textTransform": "uppercase",
                                    "letterSpacing": "0.05em",
                                    "border": "none",
                                    "borderBottom": "1px solid rgba(56, 68, 77, 0.6)",
                                    "padding": "12px 16px",
                                    "position": "sticky", "top": 0, "zIndex": 1
                                },
                                style_cell={
                                    "backgroundColor": "transparent",
                                    "color": "#c9d1d9",
                                    "fontSize": "12px",
                                    "border": "none",
                                    "borderBottom": "1px solid rgba(56, 68, 77, 0.3)",
                                    "padding": "10px 14px",
                                    "fontFamily": "'SF Mono', 'Fira Code', 'Consolas', monospace",
                                    "textAlign": "left",
                                },
                                style_data_conditional=[
                                    {"if": {"row_index": "odd"}, "backgroundColor": "rgba(22, 27, 34, 0.4)"},
                                    {
                                        "if": {"filter_query": "{pnl} > 0", "column_id": "pnl"},
                                        "color": "#3fb950",
                                        "fontWeight": "600"
                                    },
                                    {
                                        "if": {"filter_query": "{pnl} < 0", "column_id": "pnl"},
                                        "color": "#f85149",
                                        "fontWeight": "600"
                                    },
                                    {
                                        "if": {"filter_query": "{side} = 'buy'", "column_id": "side"},
                                        "color": "#58a6ff"
                                    },
                                    {
                                        "if": {"filter_query": "{side} = 'sell'", "column_id": "side"},
                                        "color": "#a371f7"
                                    },
                                ],
                            ),
                        ],
                    ),
                ],
            ),
        ],
    )
