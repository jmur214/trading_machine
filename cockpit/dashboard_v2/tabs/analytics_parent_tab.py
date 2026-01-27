
# cockpit/dashboard_v2/tabs/analytics_parent_tab.py
"""Parent container for Analytics, Governor, and Evolution sub-tabs."""
from __future__ import annotations
from dash import dcc, html

# Reuse design tokens
CARD_STYLE = {
    "background": "rgba(15, 20, 26, 0.85)",
    "backdropFilter": "blur(20px)",
    "border": "1px solid rgba(56, 68, 77, 0.4)",
    "borderRadius": "16px",
    "padding": "16px 24px",
    "boxShadow": "0 4px 12px rgba(0, 0, 0, 0.4)",
    "marginBottom": "24px",
    "display": "flex",
    "alignItems": "center",
    "justifyContent": "space-between"
}

def analytics_parent_layout():
    """Layout containing the sub-navigation dropdown and content area."""
    return html.Div(
        children=[
            # Sub-navigation Bar
            html.Div(
                style=CARD_STYLE,
                children=[
                    html.Div(
                        children=[
                            html.H3("Analytics Hub", style={"margin": "0 0 4px 0", "color": "#f0f6fc", "fontSize": "18px"}),
                            html.P("Select a module to view detailed intelligence.", style={"margin": "0", "color": "#8b949e", "fontSize": "13px"}),
                        ]
                    ),
                    html.Div(
                        style={"width": "250px"},
                        children=[
                            dcc.Dropdown(
                                id="analytics_sub_tab_selector",
                                options=[
                                    {"label": "Performance & Attribution", "value": "performance"},
                                    {"label": "Governor Intelligence", "value": "governor"},
                                    {"label": "Evolutionary Research", "value": "evolution"},
                                ],
                                value="performance",
                                clearable=False,
                                className="dark-dropdown" # Ensure CSS picks this up if defined, or rely on dcc defaults
                            ),
                        ]
                    ),
                ]
            ),
            
            # Content Area
            html.Div(id="analytics_sub_content"),
        ]
    )
