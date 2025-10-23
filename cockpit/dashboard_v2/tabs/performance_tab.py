# cockpit/dashboard/tabs/performance_tab.py
from __future__ import annotations
from dash import dcc, html

def performance_layout():
    return html.Div(
        style={"backgroundColor": "#161b22", "padding": "20px", "borderRadius": "12px"},
        children=[
            html.H3("Performance Overview", style={"marginTop": 0, "color": "#e0e0e0"}),
            html.Div(
                [
                    html.Label("Timeframe", style={"color": "#ddd", "marginRight": "8px"}),
                    dcc.Dropdown(
                        id="timeframe_performance",
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
                style={"marginBottom": "14px"},
            ),
            html.Div([dcc.Graph(id="rolling_sharpe_chart", style={"height": "320px"})], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="rolling_maxdd_chart", style={"height": "320px"})], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="pnl_decomp_chart", style={"height": "320px"})], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="edge_corr_heatmap", style={"height": "320px"})], style={"margin": "12px 0"}),
            html.Div([dcc.Graph(id="edge_weight_evolution_chart", style={"height": "320px"})], style={"margin": "12px 0"}),
        ],
    )
