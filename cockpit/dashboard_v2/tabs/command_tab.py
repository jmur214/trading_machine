# cockpit/dashboard_v2/tabs/command_tab.py
"""Command Center tab — general-purpose terminal for running any system command."""
from __future__ import annotations
from dash import dcc, html

from ..utils.styles import (
    CARD_STYLE, SECTION_HEADER, COLORS, BUTTON_PRIMARY,
    BUTTON_SECONDARY, TERMINAL_STYLE, status_badge,
)
from ..utils.command_runner import COMMANDS


def command_layout():
    """Command Center with command selector, parameters, and terminal output."""
    cmd_options = [
        {"label": spec["label"], "value": key}
        for key, spec in COMMANDS.items()
    ]

    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Command Center", style={"margin": "0", "color": COLORS["text_primary"]}),
                    html.Span("System Operations Terminal", style={
                        "background": "rgba(63, 185, 80, 0.15)",
                        "color": COLORS["accent_green"],
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "4px 12px",
                        "borderRadius": "20px",
                    }),
                ]
            ),

            # Command Bar
            html.Div(
                style={
                    **CARD_STYLE,
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "16px",
                    "padding": "16px 24px",
                    "marginBottom": "24px",
                },
                children=[
                    # Command Selector
                    html.Div(
                        style={"flex": "1", "maxWidth": "300px"},
                        children=[
                            html.Label("Command", style={
                                "fontSize": "11px", "color": COLORS["text_muted"],
                                "textTransform": "uppercase", "letterSpacing": "0.05em",
                                "marginBottom": "4px", "display": "block",
                            }),
                            dcc.Dropdown(
                                id="cmd-selector",
                                options=cmd_options,
                                value="backtest",
                                clearable=False,
                            ),
                        ],
                    ),

                    # Description
                    html.Div(
                        id="cmd-description",
                        style={
                            "flex": "2",
                            "color": COLORS["text_dim"],
                            "fontSize": "13px",
                            "padding": "0 16px",
                        },
                    ),

                    # Buttons
                    html.Button("Run", id="cmd-run-btn", n_clicks=0, style=BUTTON_PRIMARY),
                    html.Button("Stop", id="cmd-stop-btn", n_clicks=0, disabled=True,
                                style={**BUTTON_SECONDARY, "color": COLORS["accent_red"],
                                       "borderColor": "rgba(248, 81, 73, 0.3)"}),

                    # Status
                    html.Span(id="cmd-status-badge", children="IDLE", style=status_badge("idle")),
                    html.Span(id="cmd-elapsed", style={
                        "fontSize": "12px", "color": COLORS["text_dim"], "minWidth": "60px",
                    }),
                ],
            ),

            # Parameters Panel (hidden inputs — all always in DOM)
            html.Div(
                id="cmd-params-panel",
                style={**CARD_STYLE, "marginBottom": "24px", "display": "none"},
                children=[
                    html.H4("Parameters", style={
                        "margin": "0 0 16px", "color": COLORS["text_primary"],
                        "fontSize": "14px", "fontWeight": "600",
                    }),

                    # Backtest/Benchmark params (shown/hidden by callback)
                    html.Div(id="cmd-params-dates", style={"display": "none"}, children=[
                        html.Div(style={"display": "flex", "gap": "16px", "marginBottom": "12px"}, children=[
                            html.Div(style={"flex": "1"}, children=[
                                html.Label("Start Date", style={"fontSize": "12px", "color": COLORS["text_muted"], "display": "block", "marginBottom": "4px"}),
                                dcc.Input(id="cmd-param-start", type="text", placeholder="YYYY-MM-DD",
                                          style={"width": "100%"}),
                            ]),
                            html.Div(style={"flex": "1"}, children=[
                                html.Label("End Date", style={"fontSize": "12px", "color": COLORS["text_muted"], "display": "block", "marginBottom": "4px"}),
                                dcc.Input(id="cmd-param-end", type="text", placeholder="YYYY-MM-DD",
                                          style={"width": "100%"}),
                            ]),
                            html.Div(style={"flex": "1"}, children=[
                                html.Label("Capital", style={"fontSize": "12px", "color": COLORS["text_muted"], "display": "block", "marginBottom": "4px"}),
                                dcc.Input(id="cmd-param-capital", type="number", placeholder="100000",
                                          style={"width": "100%"}),
                            ]),
                        ]),
                    ]),

                    html.Div(id="cmd-params-backtest-opts", style={"display": "none"}, children=[
                        dcc.Checklist(
                            id="cmd-param-bt-opts",
                            options=[
                                {"label": "  Fresh run", "value": "fresh"},
                                {"label": "  Discovery mode", "value": "discover"},
                            ],
                            value=["fresh"],
                            style={"color": COLORS["text_secondary"], "fontSize": "13px"},
                            inputStyle={"marginRight": "8px"},
                            labelStyle={"display": "inline-block", "marginRight": "20px"},
                        ),
                    ]),

                    # Custom args input (always available)
                    html.Div(style={"marginTop": "12px"}, children=[
                        html.Label("Additional Arguments", style={
                            "fontSize": "12px", "color": COLORS["text_muted"],
                            "display": "block", "marginBottom": "4px",
                        }),
                        dcc.Input(id="cmd-param-extra", type="text", placeholder="e.g. --verbose --skip-tests",
                                  style={"width": "100%"}),
                    ]),
                ],
            ),

            # Terminal Output
            html.Div(
                style=CARD_STYLE,
                children=[
                    html.Div(
                        style={**SECTION_HEADER, "marginBottom": "12px"},
                        children=[
                            html.H4("Terminal", style={
                                "margin": "0", "color": COLORS["text_primary"], "fontSize": "14px",
                            }),
                        ],
                    ),
                    html.Pre(
                        "Select a command and click 'Run' to execute.",
                        id="cmd-output",
                        style={**TERMINAL_STYLE, "maxHeight": "600px"},
                    ),
                ],
            ),

            # Hidden stores and polling interval
            dcc.Store(id="cmd-process-id", data=""),
            dcc.Store(id="cmd-output-offset", data=0),
            dcc.Interval(id="cmd-poll", interval=1000, disabled=True),
        ],
    )
