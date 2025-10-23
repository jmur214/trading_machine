from __future__ import annotations
from dash import dcc, html
from dash import dash_table

def analytics_layout():
    return html.Div(
        children=[
            html.Div(
                [
                    html.Label("Timeframe", style={"fontWeight": "600"}),
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
                    html.Label("Benchmark", style={"fontWeight": "600"}),
                    dcc.Dropdown(
                        id="benchmark_selector",
                        options=[
                            {"label": "S&P 500 (SPY)", "value": "^GSPC"},
                            {"label": "NASDAQ 100 (QQQ)", "value": "^NDX"},
                            {"label": "Bitcoin (BTC/USD)", "value": "BTC-USD"},
                        ],
                        value="^GSPC",
                        clearable=False,
                        style={"width": 260, "color": "#000"},
                    ),
                ],
                style={"margin": "6px 0"},
            ),
            html.Div("Cumulative PnL by edge (realized) and normalized equity vs selected benchmark.", style={"opacity": 0.8, "marginBottom": "8px"}),
            html.Div([dcc.Graph(id="edge_cum_pnl_chart")], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="equity_vs_bench_chart")], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="rolling_outperformance_chart")], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="pnl_heatmap_chart")], style={"margin": "12px 0"}),
            html.Div(
                [
                    html.H4("Trades Table"),
                    dash_table.DataTable(
                        id="trades_table",
                        data=[], columns=[], page_size=15,
                        sort_action="native", filter_action="native", row_deletable=False,
                        style_table={"overflowX": "auto", "border": "1px solid #333"},
                        style_cell={
                            "backgroundColor": "#0f1116", "color": "#e0e0e0",
                            "border": "1px solid #222", "fontFamily": "Menlo, Consolas, monospace",
                            "fontSize": "12px", "padding": "6px",
                        },
                        style_header={
                            "backgroundColor": "#11161c", "fontWeight": "bold",
                            "border": "1px solid #333", "color": "#f5f5f5"
                        },
                        style_data_conditional=[
                            {"if": {"row_index": "odd"}, "backgroundColor": "#11141a"},
                            {"if": {"filter_query": "{pnl} > 0"}, "backgroundColor": "#0f1b12", "color": "#a8ff9e"},
                            {"if": {"filter_query": "{pnl} < 0"}, "backgroundColor": "#231214", "color": "#ff9ea8"},
                        ],
                    ),
                ],
                style={"margin": "12px 0"},
            ),
        ],
        style={"padding": "16px", "backgroundColor": "#161b22", "borderRadius": "12px"},
    )
