
# cockpit/dashboard_v2/tabs/performance_tab.py
"""Performance & Analysis tab - Merges Performance, Analytics, and Governor."""
from __future__ import annotations
from dash import dcc, html, dash_table

# ============================================
# DESIGN TOKENS
# ============================================
CARD_STYLE = {
    "background": "rgba(15, 20, 26, 0.85)",
    "backdropFilter": "blur(20px)",
    "border": "1px solid rgba(56, 68, 77, 0.4)",
    "borderRadius": "16px",
    "padding": "24px",
    "boxShadow": "0 4px 12px rgba(0, 0, 0, 0.4)",
    "minWidth": "0",
    "maxWidth": "100%",
}

SECTION_HEADER = {
    "display": "flex",
    "alignItems": "center",
    "gap": "12px",
    "marginBottom": "16px",
    "paddingBottom": "12px",
    "borderBottom": "1px solid rgba(56, 68, 77, 0.4)",
}

def performance_layout():
    """Combined Performance, Analytics, and Governor layout."""
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Performance & Analysis", style={"margin": "0", "color": "#f0f6fc"}),
                    html.Span("Strategic Attribution & Deep Dive", style={
                        "background": "rgba(88, 166, 255, 0.15)",
                        "color": "#58a6ff",
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "4px 12px",
                        "borderRadius": "20px",
                    }),
                ]
            ),
            
            # Filter Bar
            html.Div(
                style={
                    **CARD_STYLE,
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "24px",
                    "padding": "16px 24px",
                    "marginBottom": "24px",
                },
                children=[
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "12px"},
                        children=[
                            html.Label("Timeframe:", style={"color": "#8b949e", "fontSize": "13px", "marginBottom": "0"}),
                            dcc.Dropdown(
                                id="timeframe_performance",
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
                        ],
                    ),
                    # Benchmark selector moved here from analytics
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "12px"},
                        children=[
                            html.Label("Benchmark:", style={"color": "#8b949e", "fontSize": "13px", "marginBottom": "0"}),
                            dcc.Dropdown(
                                id="benchmark_selector",
                                options=[
                                    {"label": "S&P 500 (SPY)", "value": "^GSPC"},
                                    {"label": "NASDAQ 100 (QQQ)", "value": "^NDX"},
                                    {"label": "Bitcoin (BTC)", "value": "BTC-USD"},
                                ],
                                value="^GSPC",
                                clearable=False,
                                style={"width": "160px"},
                            ),
                        ],
                    ),
                ],
            ),
            
            # 1. Allocation & Attribution Grid
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px", "marginBottom": "24px"},
                children=[
                    # Current Allocation (from Gov)
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Current Allocation", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="perf_allocation_chart", style={"height": "300px"}, config={"displayModeBar": False}),
                        ],
                    ),
                    # PnL Attribution (By Edge)
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Attribution by Strategy", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="pnl_decomp_chart", style={"height": "300px"}, config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),
            
            # 2. Performance Metrics Grid (Rolling)
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px", "marginBottom": "24px"},
                children=[
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Rolling Sharpe Ratio", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="rolling_sharpe_chart", style={"height": "280px"}, config={"displayModeBar": False}),
                        ],
                    ),
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Rolling Max Drawdown", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="rolling_maxdd_chart", style={"height": "280px"}, config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),
            
            # 3. Benchmark Analysis
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px", "marginBottom": "24px"},
                children=[
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Equity vs Benchmark", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="equity_vs_bench_chart", style={"height": "280px"}, config={"displayModeBar": False}),
                        ],
                    ),
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Heatmap & Correlation", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="edge_corr_heatmap", style={"height": "280px"}, config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),
            
            # 4. Detailed Trades Table
            html.Div(
                style=CARD_STYLE,
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("Trade History", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                    ]),
                    dash_table.DataTable(
                        id="analytics_trades_table",
                        data=[],
                        columns=[
                            {"name": "Date", "id": "timestamp"},
                            {"name": "Ticker", "id": "ticker"},
                            {"name": "Strategy", "id": "edge"},
                            {"name": "Side", "id": "side"},
                            {"name": "Qty", "id": "qty"},
                            {"name": "Price", "id": "fill_price"},
                            {"name": "PnL", "id": "pnl"},
                        ],
                        page_size=15,
                        sort_action="native",
                        filter_action="native",
                        style_table={"overflowX": "auto"},
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
                        ],
                    ),
                ],
            ),
        ],
    )
