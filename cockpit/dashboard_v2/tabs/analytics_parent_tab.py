
# cockpit/dashboard_v2/tabs/analytics_parent_tab.py
"""Parent container for Analytics, Governor, and Evolution sub-tabs."""
from __future__ import annotations
from dash import dcc, html

from ..utils.styles import CARD_STYLE, COLORS, SUB_TAB_STYLE, SUB_TAB_SELECTED_STYLE


def analytics_parent_layout():
    """Layout containing sub-tab navigation and content area."""
    nav_bar_style = {
        **CARD_STYLE,
        "padding": "16px 24px",
        "marginBottom": "24px",
        "display": "flex",
        "alignItems": "center",
        "justifyContent": "space-between",
    }

    return html.Div(
        children=[
            # Sub-navigation Bar
            html.Div(
                style=nav_bar_style,
                children=[
                    html.Div(
                        children=[
                            html.H3("Analytics Hub", style={
                                "margin": "0 0 4px 0",
                                "color": COLORS["text_primary"],
                                "fontSize": "18px",
                            }),
                            html.P("Deep performance analysis and system intelligence.", style={
                                "margin": "0",
                                "color": COLORS["text_muted"],
                                "fontSize": "13px",
                            }),
                        ]
                    ),
                    html.Div(
                        children=[
                            dcc.Tabs(
                                id="analytics-sub-tabs",
                                value="performance",
                                children=[
                                    dcc.Tab(
                                        label="Performance & Attribution",
                                        value="performance",
                                        style=SUB_TAB_STYLE,
                                        selected_style=SUB_TAB_SELECTED_STYLE,
                                    ),
                                    dcc.Tab(
                                        label="Governor Intelligence",
                                        value="governor",
                                        style=SUB_TAB_STYLE,
                                        selected_style=SUB_TAB_SELECTED_STYLE,
                                    ),
                                    dcc.Tab(
                                        label="Evolutionary Research",
                                        value="evolution",
                                        style=SUB_TAB_STYLE,
                                        selected_style=SUB_TAB_SELECTED_STYLE,
                                    ),
                                ],
                                className="analytics-sub-tabs",
                            ),
                        ],
                    ),
                ]
            ),

            # Content Area
            html.Div(id="analytics_sub_content"),
        ]
    )
