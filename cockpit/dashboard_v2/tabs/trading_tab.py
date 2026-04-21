# cockpit/dashboard_v2/tabs/trading_tab.py
"""Trading tab — Paper/Live account monitoring, positions, real-time status."""
from __future__ import annotations
from dash import dcc, html, dash_table

from ..utils.styles import CARD_STYLE, SECTION_HEADER, COLORS, KPI_CARD_STYLE


def trading_layout():
    """Trading workspace with account overview, positions, and recent fills."""
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Trading", style={"margin": "0", "color": COLORS["text_primary"]}),
                    html.Span(id="trading-connection-badge"),
                ]
            ),

            # Account Overview KPIs
            html.Div(
                id="trading-account-kpis",
                style={"marginBottom": "24px"},
            ),

            # Two-column: Positions + Recent Fills
            html.Div(
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(2, minmax(0, 1fr))",
                    "gap": "24px",
                    "marginBottom": "24px",
                },
                children=[
                    # Open Positions
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Open Positions", style={
                                    "margin": "0", "color": COLORS["text_primary"], "fontSize": "14px",
                                }),
                            ]),
                            dash_table.DataTable(
                                id="trading-positions-table",
                                data=[],
                                columns=[
                                    {"name": "Ticker", "id": "symbol"},
                                    {"name": "Side", "id": "side"},
                                    {"name": "Qty", "id": "qty"},
                                    {"name": "Avg Entry", "id": "avg_entry"},
                                    {"name": "Current", "id": "current_price"},
                                    {"name": "Unr. PnL", "id": "unrealized_pl"},
                                ],
                                page_size=10,
                                sort_action="native",
                                style_table={"overflowX": "auto"},
                                style_header={
                                    "backgroundColor": COLORS["bg_elevated"],
                                    "color": COLORS["text_secondary"],
                                    "fontWeight": "600",
                                    "fontSize": "11px",
                                    "textTransform": "uppercase",
                                    "letterSpacing": "0.05em",
                                    "border": "none",
                                    "borderBottom": f"1px solid {COLORS['border']}",
                                    "padding": "12px 14px",
                                },
                                style_cell={
                                    "backgroundColor": "transparent",
                                    "color": COLORS["text_secondary"],
                                    "fontSize": "12px",
                                    "border": "none",
                                    "borderBottom": f"1px solid {COLORS['border_subtle']}",
                                    "padding": "10px 14px",
                                    "fontFamily": "'SF Mono', 'Fira Code', monospace",
                                    "textAlign": "left",
                                },
                                style_data_conditional=[
                                    {"if": {"row_index": "odd"}, "backgroundColor": "rgba(22, 27, 34, 0.4)"},
                                    {
                                        "if": {"filter_query": "{unrealized_pl} contains '-'", "column_id": "unrealized_pl"},
                                        "color": COLORS["accent_red"], "fontWeight": "600",
                                    },
                                ],
                            ),
                        ],
                    ),

                    # Recent Fills
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Recent Fills", style={
                                    "margin": "0", "color": COLORS["text_primary"], "fontSize": "14px",
                                }),
                            ]),
                            dash_table.DataTable(
                                id="trading-fills-table",
                                data=[],
                                columns=[
                                    {"name": "Time", "id": "timestamp"},
                                    {"name": "Ticker", "id": "ticker"},
                                    {"name": "Side", "id": "side"},
                                    {"name": "Qty", "id": "qty"},
                                    {"name": "Price", "id": "fill_price"},
                                    {"name": "PnL", "id": "pnl"},
                                ],
                                page_size=10,
                                sort_action="native",
                                style_table={"overflowX": "auto"},
                                style_header={
                                    "backgroundColor": COLORS["bg_elevated"],
                                    "color": COLORS["text_secondary"],
                                    "fontWeight": "600",
                                    "fontSize": "11px",
                                    "textTransform": "uppercase",
                                    "letterSpacing": "0.05em",
                                    "border": "none",
                                    "borderBottom": f"1px solid {COLORS['border']}",
                                    "padding": "12px 14px",
                                },
                                style_cell={
                                    "backgroundColor": "transparent",
                                    "color": COLORS["text_secondary"],
                                    "fontSize": "12px",
                                    "border": "none",
                                    "borderBottom": f"1px solid {COLORS['border_subtle']}",
                                    "padding": "10px 14px",
                                    "fontFamily": "'SF Mono', 'Fira Code', monospace",
                                    "textAlign": "left",
                                },
                                style_data_conditional=[
                                    {"if": {"row_index": "odd"}, "backgroundColor": "rgba(22, 27, 34, 0.4)"},
                                    {
                                        "if": {"filter_query": "{pnl} > 0", "column_id": "pnl"},
                                        "color": COLORS["accent_green"], "fontWeight": "600",
                                    },
                                    {
                                        "if": {"filter_query": "{pnl} < 0", "column_id": "pnl"},
                                        "color": COLORS["accent_red"], "fontWeight": "600",
                                    },
                                ],
                            ),
                        ],
                    ),
                ],
            ),

            # Equity curve for paper account
            html.Div(
                style=CARD_STYLE,
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("Paper Equity Curve", style={
                            "margin": "0", "color": COLORS["text_primary"], "fontSize": "14px",
                        }),
                    ]),
                    dcc.Graph(id="trading-equity-chart", style={"height": "300px"}, config={"displayModeBar": False}),
                ],
            ),

            # Polling interval for live updates
            dcc.Interval(id="trading-poll", interval=5000, disabled=True),
        ],
    )
