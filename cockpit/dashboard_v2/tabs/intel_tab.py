# cockpit/dashboard_v2/tabs/intel_tab.py
"""Intel tab - Market intelligence and news summary."""
from __future__ import annotations
from dash import html, dcc

from ..utils.styles import CARD_STYLE, SECTION_HEADER, COLORS, BUTTON_SECONDARY


def create_intel_layout():
    """Intel tab with market news and intelligence summary.

    NewsSummarizer is loaded lazily in the callback — not at layout time —
    to avoid blocking the UI or erroring on missing dependencies.
    """
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Market Intelligence", style={
                        "margin": "0",
                        "color": COLORS["text_primary"],
                    }),
                    html.Span("AI-Powered News Analysis", style={
                        "background": "rgba(163, 113, 247, 0.15)",
                        "color": COLORS["accent_purple"],
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "4px 12px",
                        "borderRadius": "20px",
                    }),
                ]
            ),

            # Controls
            html.Div(
                style={"marginBottom": "24px"},
                children=[
                    html.Button(
                        "Refresh Intel",
                        id="intel_refresh_button",
                        n_clicks=0,
                        style=BUTTON_SECONDARY,
                    ),
                ],
            ),

            # Intel Summary Card
            html.Div(
                style=CARD_STYLE,
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("News Summary", style={
                            "margin": "0",
                            "color": COLORS["text_primary"],
                            "fontSize": "14px",
                        }),
                    ]),
                    html.Pre(
                        "Click 'Refresh Intel' to load the latest market intelligence.",
                        id="intel_summary_box",
                        style={
                            "whiteSpace": "pre-wrap",
                            "fontSize": "14px",
                            "fontFamily": "'SF Mono', 'Fira Code', 'Consolas', monospace",
                            "padding": "20px",
                            "backgroundColor": "rgba(10, 14, 20, 0.6)",
                            "color": COLORS["text_secondary"],
                            "borderRadius": "10px",
                            "border": f"1px solid {COLORS['border_subtle']}",
                            "lineHeight": "1.6",
                            "maxHeight": "600px",
                            "overflowY": "auto",
                            "margin": "0",
                        },
                    ),
                ],
            ),
        ],
    )
