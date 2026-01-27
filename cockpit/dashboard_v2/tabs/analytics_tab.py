# cockpit/dashboard/tabs/analytics_tab.py
"""Analytics tab - Benchmark comparison and detailed trade analysis."""
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
}

SECTION_HEADER = {
    "display": "flex",
    "alignItems": "center",
    "gap": "12px",
    "marginBottom": "16px",
    "paddingBottom": "12px",
    "borderBottom": "1px solid rgba(56, 68, 77, 0.4)",
}


def analytics_layout():
    """Analytics tab with benchmark comparison and trade analysis."""
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Deep Analytics", style={"margin": "0", "color": "#f0f6fc"}),
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
                                id="timeframe_analytics",
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
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "12px"},
                        children=[
                            html.Label("Benchmark:", style={"color": "#8b949e", "fontSize": "13px", "marginBottom": "0"}),
                            dcc.Dropdown(
                                id="benchmark_selector",
                                options=[
                                    {"label": "S&P 500 (SPY)", "value": "^GSPC"},
                                    {"label": "NASDAQ 100 (QQQ)", "value": "^NDX"},
                                    {"label": "Bitcoin (BTC/USD)", "value": "BTC-USD"},
                                ],
                                value="^GSPC",
                                clearable=False,
                                style={"width": "180px"},
                            ),
                        ],
                    ),
                ],
            ),
            
            # Description
            html.P(
                "Cumulative P&L by edge (realized) and normalized equity vs selected benchmark.",
                style={"color": "#6e7681", "fontSize": "13px", "marginBottom": "24px"},
            ),
            
            # Cumulative P&L Chart
            html.Div(
                style={**CARD_STYLE, "marginBottom": "24px"},
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("Cumulative P&L by Strategy", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                    ]),
                    dcc.Graph(id="edge_cum_pnl_chart", style={"height": "320px"}),
                ],
            ),
            
            # Benchmark Comparison Charts
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px", "marginBottom": "24px"},
                children=[
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Equity vs Benchmark", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="equity_vs_bench_chart", style={"height": "280px"}),
                        ],
                    ),
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Rolling Outperformance", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="rolling_outperformance_chart", style={"height": "280px"}),
                        ],
                    ),
                ],
            ),
            
            # P&L Heatmap
            html.Div(
                style={**CARD_STYLE, "marginBottom": "24px"},
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("P&L Calendar Heatmap", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                    ]),
                    dcc.Graph(id="pnl_heatmap_chart", style={"height": "300px"}),
                ],
            ),
            
            # Trades Table
            html.Div(
                style=CARD_STYLE,
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("Trades Table", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                    ]),
                    dash_table.DataTable(
                        id="trades_table",
                        data=[],
                        columns=[],
                        page_size=15,
                        sort_action="native",
                        filter_action="native",
                        row_deletable=False,
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
                        },
                        style_data_conditional=[
                            {"if": {"row_index": "odd"}, "backgroundColor": "rgba(22, 27, 34, 0.4)"},
                            {"if": {"filter_query": "{pnl} > 0"}, "backgroundColor": "rgba(63, 185, 80, 0.1)", "color": "#3fb950"},
                            {"if": {"filter_query": "{pnl} < 0"}, "backgroundColor": "rgba(248, 81, 73, 0.1)", "color": "#f85149"},
                        ],
                    ),
                ],
            ),
        ],
    )
