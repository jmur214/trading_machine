# cockpit/dashboard_v2/tabs/evolution_tab.py
"""Evolution tab - WFO results visualization and genome registry."""
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


def evolution_layout():
    """Evolution & Validation tab showing WFO results and genome registry."""
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Evolutionary Intelligence", style={"margin": "0", "color": "#f0f6fc"}),
                    html.Span("Walk-Forward Validation & Genome Discovery", style={
                        "background": "rgba(163, 113, 247, 0.15)",
                        "color": "#a371f7",
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "4px 12px",
                        "borderRadius": "20px",
                    }),
                ]
            ),
            
            # Stats Row
            html.Div(
                id="evo_stats_row",
                style={"display": "grid", "gridTemplateColumns": "repeat(4, minmax(0, 1fr))", "gap": "16px", "marginBottom": "24px"},
            ),
            
            # Charts Grid
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px", "marginBottom": "24px"},
                children=[
                    # WFO Heatmap
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Validation Stability Matrix", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                                html.Span("Sharpe by Strategy x Walk-Forward Step", style={
                                    "color": "#6e7681", "fontSize": "11px", "marginLeft": "auto"
                                }),
                            ]),
                            dcc.Graph(id="evo_wfo_heatmap", style={"height": "350px"}, config={"displayModeBar": False}),
                        ],
                    ),
                    
                    # Performance Distribution
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Strategy Performance Distribution", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                            ]),
                            dcc.Graph(id="evo_performance_dist", style={"height": "350px"}, config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),
            
            # Genome Registry Table
            html.Div(
                style=CARD_STYLE,
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("Generated Genome Registry", style={"margin": "0", "color": "#f0f6fc", "fontSize": "14px"}),
                        html.Span("Auto-discovered strategy configurations", style={
                            "color": "#6e7681", "fontSize": "11px", "marginLeft": "auto"
                        }),
                    ]),
                    html.Div(
                        id="evo_registry_container",
                        style={"marginTop": "8px"},
                    ),
                ],
            ),
        ],
    )


def _stat_card(label: str, value: str, color: str):
    """Create a mini stat card (used by callbacks)."""
    return html.Div(
        style={
            **CARD_STYLE,
            "padding": "20px",
            "textAlign": "center",
            "position": "relative",
            "overflow": "hidden",
        },
        children=[
            # Gradient accent
            html.Div(style={
                "position": "absolute",
                "top": "0",
                "left": "0",
                "right": "0",
                "height": "3px",
                "background": f"linear-gradient(90deg, {color}, transparent)",
            }),
            html.Div(label, style={
                "fontSize": "11px",
                "fontWeight": "500",
                "color": "#6e7681",
                "textTransform": "uppercase",
                "letterSpacing": "0.05em",
                "marginBottom": "8px",
            }),
            html.Div(value, style={
                "fontSize": "24px",
                "fontWeight": "700",
                "color": color,
                "letterSpacing": "-0.02em",
            }),
        ],
    )
