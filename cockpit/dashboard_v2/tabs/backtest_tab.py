# cockpit/dashboard_v2/tabs/backtest_tab.py
"""Backtest tab — run backtests, configure parameters, view results."""
from __future__ import annotations
from dash import dcc, html

from ..utils.styles import (
    CARD_STYLE, SECTION_HEADER, COLORS, BUTTON_PRIMARY,
    BUTTON_SECONDARY, INPUT_STYLE, TERMINAL_STYLE, status_badge,
)


def backtest_layout():
    """Backtest workspace with config panel and results."""
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Backtesting", style={"margin": "0", "color": COLORS["text_primary"]}),
                    html.Span("Historical Strategy Validation", style={
                        "background": f"rgba(88, 166, 255, 0.15)",
                        "color": COLORS["accent_blue"],
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "4px 12px",
                        "borderRadius": "20px",
                    }),
                ]
            ),

            # Two-column layout
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "380px 1fr",
                    "gap": "24px",
                    "marginBottom": "24px",
                },
                children=[
                    # Left: Config Panel
                    html.Div(
                        style={**CARD_STYLE, "position": "relative", "overflow": "hidden"},
                        children=[
                            # Accent line
                            html.Div(style={
                                "position": "absolute", "top": "0", "left": "0", "right": "0",
                                "height": "3px",
                                "background": f"linear-gradient(90deg, {COLORS['accent_blue']}, {COLORS['accent_purple']})",
                            }),

                            html.H4("Configuration", style={
                                "margin": "8px 0 20px", "color": COLORS["text_primary"], "fontWeight": "600",
                            }),

                            # Parameters
                            html.Div(style={"marginBottom": "16px"}, children=[
                                html.Label("Start Date", style={"fontSize": "12px", "color": COLORS["text_muted"], "marginBottom": "4px", "display": "block"}),
                                dcc.Input(id="bt-start-date", type="text", placeholder="YYYY-MM-DD",
                                          style={**INPUT_STYLE, "marginBottom": "12px"}),
                            ]),
                            html.Div(style={"marginBottom": "16px"}, children=[
                                html.Label("End Date", style={"fontSize": "12px", "color": COLORS["text_muted"], "marginBottom": "4px", "display": "block"}),
                                dcc.Input(id="bt-end-date", type="text", placeholder="YYYY-MM-DD",
                                          style={**INPUT_STYLE, "marginBottom": "12px"}),
                            ]),
                            html.Div(style={"marginBottom": "16px"}, children=[
                                html.Label("Initial Capital", style={"fontSize": "12px", "color": COLORS["text_muted"], "marginBottom": "4px", "display": "block"}),
                                dcc.Input(id="bt-capital", type="number", placeholder="100000",
                                          style={**INPUT_STYLE, "marginBottom": "12px"}),
                            ]),
                            html.Div(style={"marginBottom": "16px"}, children=[
                                html.Label("Environment", style={"fontSize": "12px", "color": COLORS["text_muted"], "marginBottom": "4px", "display": "block"}),
                                dcc.Dropdown(
                                    id="bt-env",
                                    options=[
                                        {"label": "Production", "value": "prod"},
                                        {"label": "Development", "value": "dev"},
                                    ],
                                    value="prod",
                                    clearable=False,
                                    style={"marginBottom": "12px"},
                                ),
                            ]),

                            # Checkboxes
                            dcc.Checklist(
                                id="bt-options",
                                options=[
                                    {"label": "  Fresh run (clear prior logs)", "value": "fresh"},
                                    {"label": "  Discovery mode (post-backtest hunt)", "value": "discover"},
                                ],
                                value=["fresh"],
                                style={"color": COLORS["text_secondary"], "fontSize": "13px", "marginBottom": "20px"},
                                inputStyle={"marginRight": "8px"},
                                labelStyle={"display": "block", "marginBottom": "8px"},
                            ),

                            # Action Buttons
                            html.Div(
                                style={"display": "flex", "gap": "10px", "marginBottom": "16px"},
                                children=[
                                    html.Button("Run Backtest", id="bt-run-btn", n_clicks=0, style=BUTTON_PRIMARY),
                                    html.Button("Run Benchmark", id="bt-bench-btn", n_clicks=0, style=BUTTON_SECONDARY),
                                ],
                            ),

                            html.Div(
                                style={"display": "flex", "alignItems": "center", "gap": "10px"},
                                children=[
                                    html.Button("Stop", id="bt-stop-btn", n_clicks=0,
                                                style={**BUTTON_SECONDARY, "color": COLORS["accent_red"],
                                                       "borderColor": "rgba(248, 81, 73, 0.3)"},
                                                disabled=True),
                                    html.Span(id="bt-status-badge", children="IDLE",
                                              style=status_badge("idle")),
                                    html.Span(id="bt-elapsed", style={
                                        "fontSize": "12px", "color": COLORS["text_dim"],
                                    }),
                                ],
                            ),
                        ],
                    ),

                    # Right: Results / Output Panel
                    html.Div(
                        style={**CARD_STYLE},
                        children=[
                            html.Div(
                                style={**SECTION_HEADER, "marginBottom": "12px"},
                                children=[
                                    html.H4("Output", style={
                                        "margin": "0", "color": COLORS["text_primary"], "fontSize": "14px",
                                    }),
                                ],
                            ),
                            html.Pre(
                                "Ready to run. Configure parameters and click 'Run Backtest' or 'Run Benchmark'.",
                                id="bt-output",
                                style=TERMINAL_STYLE,
                            ),
                        ],
                    ),
                ],
            ),

            # Bottom: Last benchmark report
            html.Div(
                id="bt-last-results",
                style={"marginBottom": "24px"},
            ),

            # Hidden stores and interval
            dcc.Store(id="bt-process-id", data=""),
            dcc.Store(id="bt-output-offset", data=0),
            dcc.Interval(id="bt-poll", interval=1000, disabled=True),
        ],
    )
