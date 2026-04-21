# cockpit/dashboard_v2/tabs/governor_tab.py
"""Governor tab - Strategy weights and recommendations visualization."""
from __future__ import annotations
from dash import dcc, html

from ..utils.styles import CARD_STYLE, SECTION_HEADER, COLORS


def governor_layout():
    """Governor intelligence tab with strategy weights and recommendations."""
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Governor Intelligence", style={"margin": "0", "color": "#f0f6fc"}),
                    html.Span("Strategy Weight Allocation & Recommendations", style={
                        "background": "rgba(88, 166, 255, 0.15)",
                        "color": "#58a6ff",
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "4px 12px",
                        "borderRadius": "20px",
                    }),
                ]
            ),
            
            # Charts Grid - 2x2
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px", "marginBottom": "24px"},
                children=[
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Current Weight Allocation", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="gov_weight_chart", style={"height": "300px"}, config={"displayModeBar": False}),
                        ],
                    ),
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Sharpe Ratio vs Weight", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="gov_sr_weight_scatter", style={"height": "300px"}, config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),
            
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px"},
                children=[
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Strategy Recommendations", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="gov_recommendation_chart", style={"height": "300px"}, config={"displayModeBar": False}),
                        ],
                    ),
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Weight Evolution Over Time", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="gov_weight_evolution", style={"height": "300px"}, config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),
        ],
    )
