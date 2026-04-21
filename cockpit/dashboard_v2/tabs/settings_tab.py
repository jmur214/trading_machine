# cockpit/dashboard_v2/tabs/settings_tab.py
"""Settings tab - includes Mode selection and configuration options."""
from __future__ import annotations
from dash import dcc, html

from ..utils.styles import CARD_STYLE, SECTION_HEADER, COLORS


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
            
            # Mode Selection Card
            html.Div(
                style={**CARD_STYLE, "position": "relative", "overflow": "hidden", "maxWidth": "480px", "marginBottom": "24px"},
                children=[
                    html.Div(style={
                        "position": "absolute", "top": "0", "left": "0", "right": "0",
                        "height": "3px",
                        "background": f"linear-gradient(90deg, {COLORS['accent_blue']}, {COLORS['accent_purple']})",
                    }),

                    html.H4("Trading Mode", style={
                        "margin": "8px 0 8px 0", "color": COLORS["text_primary"], "fontWeight": "600",
                    }),
                    html.P("Select your trading environment", style={
                        "margin": "0 0 20px 0", "fontSize": "13px", "color": COLORS["text_dim"],
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
                            "background": COLORS["bg_input"],
                            "border": f"1px solid {COLORS['border']}",
                            "borderRadius": "10px",
                            "cursor": "pointer",
                            "transition": "all 0.2s ease",
                            "color": COLORS["text_muted"],
                            "fontWeight": "500",
                        },
                        inputStyle={"marginRight": "12px"},
                    ),

                    html.Div(
                        id="mode_status",
                        style={"marginTop": "20px", "fontSize": "14px", "color": COLORS["text_dim"]},
                    ),

                    # Hidden placeholder — mode_summary_box is expected by mode_callbacks
                    html.Div(id="mode_summary_box", style={"display": "none"}),
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
