# cockpit/dashboard/tabs/settings_tab.py
"""Settings tab - includes Mode selection and configuration options."""
from __future__ import annotations
from dash import dcc, html

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


def settings_layout():
    """Settings tab with Mode selection and configuration options."""
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Settings & Configuration", style={"margin": "0", "color": "#f0f6fc"}),
                ]
            ),
            
            # Content Grid
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px"},
                children=[
                    # Mode Selection Card
                    html.Div(
                        style={**CARD_STYLE, "position": "relative", "overflow": "hidden"},
                        children=[
                            # Gradient accent line
                            html.Div(style={
                                "position": "absolute",
                                "top": "0",
                                "left": "0",
                                "right": "0",
                                "height": "3px",
                                "background": "linear-gradient(90deg, #58a6ff, #a371f7)",
                            }),
                            
                            html.H4("Trading Mode", style={"margin": "8px 0 8px 0", "color": "#f0f6fc", "fontWeight": "600"}),
                            html.P("Select your trading environment", style={
                                "margin": "0 0 20px 0",
                                "fontSize": "13px",
                                "color": "#6e7681",
                            }),
                            
                            dcc.RadioItems(
                                id="mode_selector_radio",
                                options=[
                                    {"label": "Backtest Mode", "value": "backtest"},
                                    {"label": "Paper Trading", "value": "paper"},
                                ],
                                value="backtest",
                                labelStyle={
                                    "display": "block",
                                    "padding": "14px 18px",
                                    "margin": "8px 0",
                                    "background": "rgba(22, 27, 34, 0.7)",
                                    "border": "1px solid rgba(56, 68, 77, 0.4)",
                                    "borderRadius": "10px",
                                    "cursor": "pointer",
                                    "transition": "all 0.2s ease",
                                    "color": "#8b949e",
                                    "fontWeight": "500",
                                },
                                inputStyle={"marginRight": "12px"},
                            ),
                            
                            html.Div(style={"height": "16px"}),
                            
                            html.Button(
                                "INITIATE LIVE (Coming Soon)",
                                id="go_live_button",
                                n_clicks=0,
                                style={
                                    "width": "100%",
                                    "background": "linear-gradient(135deg, #4d1a1a, #2d0f0f)",
                                    "color": "#f85149",
                                    "padding": "14px 20px",
                                    "border": "1px solid rgba(248, 81, 73, 0.3)",
                                    "borderRadius": "10px",
                                    "cursor": "not-allowed",
                                    "opacity": "0.6",
                                    "fontWeight": "600",
                                    "fontSize": "13px",
                                },
                                disabled=True,
                            ),
                            
                            html.Div(
                                id="mode_status",
                                style={"marginTop": "20px", "fontSize": "14px", "color": "#6e7681"},
                            ),
                        ],
                    ),
                    
                    # Mode Summary/Status Card
                    html.Div(
                        id="mode_summary_box",
                        style={**CARD_STYLE},
                    ),
                ],
            ),
            
            # Additional Settings Section
            html.Div(style={"height": "24px"}),
            
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H4("Dashboard Settings", style={"margin": "0", "color": "#f0f6fc"}),
                ]
            ),
            
            html.Div(
                style={**CARD_STYLE},
                children=[
                    html.P(
                        "Additional dashboard configuration options will be available here in future updates.",
                        style={"margin": "0", "color": "#6e7681", "fontSize": "14px"},
                    ),
                ],
            ),
        ],
    )
