"""Capital-Allocation Diagnostic tab.

Surfaces the rivalry pathology that `docs/Audit/oos_2025_decomposition_2026_04.md`
had to assemble in pandas after the fact: three views of the trade log that
make capital starvation visible at a glance during any backtest run.

Panels:
  1. Per-edge fill-share table — fill count, share, PnL, share, mean PnL/fill,
     status; rivalry-pattern rows highlighted in red.
  2. Fill-share vs PnL-contribution scatter — diagonal y=x is "neutral"; any
     edge below the diagonal earned less than its fill share would justify.
  3. Rolling fill-share over time — per-edge series with the cap line drawn;
     when a series sits at the cap, the capper is binding.
"""
from __future__ import annotations

from dash import dcc, html, dash_table

from ..utils.styles import CARD_STYLE, SECTION_HEADER, COLORS
from ..utils.capital_allocation_loader import (
    DEFAULT_FILL_SHARE_CAP,
    ROLLING_WINDOW_DAYS,
    list_run_uuids,
)


def _run_options():
    """Build run-uuid dropdown options. Newest-mtime first; truncated UUIDs."""
    runs = list_run_uuids(limit=40)
    opts = []
    for r in runs:
        if r.n_fills == 0:
            continue
        label = f"{r.run_uuid[:8]}…  ({r.start_date[:10] if r.start_date else '?'} → {r.end_date[:10] if r.end_date else '?'}, {r.n_fills:,} fills, {r.n_edges} edges)"
        opts.append({"label": label, "value": r.run_uuid})
    return opts


def capital_allocation_layout():
    options = _run_options()
    default_value = options[0]["value"] if options else None

    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Capital Allocation Diagnostic", style={"margin": "0", "color": COLORS["text_primary"]}),
                    html.Span("Rivalry & Cap-Binding Surveillance", style={
                        "background": "rgba(248, 81, 73, 0.15)",
                        "color": COLORS["accent_red"],
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "4px 12px",
                        "borderRadius": "20px",
                    }),
                ],
            ),

            # Run selector + cap input
            html.Div(
                style={
                    **CARD_STYLE,
                    "display": "flex",
                    "alignItems": "center",
                    "gap": "24px",
                    "padding": "16px 24px",
                    "marginBottom": "24px",
                    "flexWrap": "wrap",
                },
                children=[
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "12px", "flex": "1 1 480px"},
                        children=[
                            html.Label("Run UUID:", style={"color": COLORS["text_muted"], "fontSize": "13px"}),
                            dcc.Dropdown(
                                id="capalloc_run_uuid",
                                options=options,
                                value=default_value,
                                clearable=False,
                                style={"flex": "1 1 auto", "minWidth": "320px", "color": "#000"},
                            ),
                        ],
                    ),
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "8px"},
                        children=[
                            html.Label("Fill-share cap:", style={"color": COLORS["text_muted"], "fontSize": "13px"}),
                            dcc.Input(
                                id="capalloc_cap",
                                type="number",
                                min=0.05,
                                max=1.0,
                                step=0.01,
                                value=DEFAULT_FILL_SHARE_CAP,
                                style={
                                    "width": "80px",
                                    "background": COLORS["bg_input"],
                                    "color": COLORS["text_secondary"],
                                    "border": f"1px solid {COLORS['border']}",
                                    "borderRadius": "8px",
                                    "padding": "6px 10px",
                                    "fontSize": "13px",
                                },
                            ),
                        ],
                    ),
                    html.Div(
                        style={"display": "flex", "alignItems": "center", "gap": "8px"},
                        children=[
                            html.Label("Rolling window (days):", style={"color": COLORS["text_muted"], "fontSize": "13px"}),
                            dcc.Input(
                                id="capalloc_window",
                                type="number",
                                min=5,
                                max=120,
                                step=5,
                                value=ROLLING_WINDOW_DAYS,
                                style={
                                    "width": "80px",
                                    "background": COLORS["bg_input"],
                                    "color": COLORS["text_secondary"],
                                    "border": f"1px solid {COLORS['border']}",
                                    "borderRadius": "8px",
                                    "padding": "6px 10px",
                                    "fontSize": "13px",
                                },
                            ),
                        ],
                    ),
                ],
            ),

            # Headline KPI strip
            html.Div(id="capalloc_headline", style={"marginBottom": "24px"}),

            # Panel 1: Per-edge fill-share table
            html.Div(
                style={**CARD_STYLE, "marginBottom": "24px"},
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("1. Per-edge fill share vs PnL contribution", style={"margin": "0", "color": COLORS["text_primary"], "fontSize": "14px"}),
                        html.Span("Rivalry rows highlighted (high fill-share + negative or starved PnL)", style={
                            "color": COLORS["text_muted"], "fontSize": "11px", "marginLeft": "12px",
                        }),
                    ]),
                    dash_table.DataTable(
                        id="capalloc_table",
                        data=[],
                        columns=[
                            {"name": "Edge", "id": "edge"},
                            {"name": "Status", "id": "status"},
                            {"name": "Fills", "id": "fill_count", "type": "numeric"},
                            {"name": "Fill %", "id": "fill_pct_disp"},
                            {"name": "Total PnL ($)", "id": "total_pnl_disp"},
                            {"name": "PnL %", "id": "pnl_pct_disp"},
                            {"name": "Mean PnL/Fill ($)", "id": "mean_pnl_disp"},
                            {"name": "Tier", "id": "tier"},
                        ],
                        sort_action="native",
                        style_table={"overflowX": "auto"},
                        style_header={
                            "backgroundColor": "rgba(22, 27, 34, 0.9)",
                            "color": COLORS["text_secondary"],
                            "fontWeight": "600",
                            "fontSize": "11px",
                            "textTransform": "uppercase",
                            "letterSpacing": "0.05em",
                            "border": "none",
                            "borderBottom": f"1px solid {COLORS['border']}",
                            "padding": "12px 16px",
                        },
                        style_cell={
                            "backgroundColor": "transparent",
                            "color": COLORS["text_secondary"],
                            "fontSize": "12px",
                            "border": "none",
                            "borderBottom": "1px solid rgba(56, 68, 77, 0.3)",
                            "padding": "10px 14px",
                            "fontFamily": "'SF Mono', 'Fira Code', 'Consolas', monospace",
                            "textAlign": "left",
                        },
                        style_data_conditional=[
                            {"if": {"row_index": "odd"}, "backgroundColor": "rgba(22, 27, 34, 0.4)"},
                            {
                                "if": {"filter_query": "{rivalry_flag} = true"},
                                "backgroundColor": "rgba(248, 81, 73, 0.10)",
                                "borderLeft": f"3px solid {COLORS['accent_red']}",
                            },
                            {
                                "if": {"filter_query": "{status} = active"},
                                "color": COLORS["accent_green"],
                                "fontWeight": "600",
                            },
                            {
                                "if": {"filter_query": "{status} = retired"},
                                "color": COLORS["text_dim"],
                                "fontStyle": "italic",
                            },
                        ],
                    ),
                ],
            ),

            # Panel 2: Scatter
            html.Div(
                style={"display": "grid", "gridTemplateColumns": "repeat(2, minmax(0, 1fr))", "gap": "24px", "marginBottom": "24px"},
                children=[
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("2. Fill-share vs PnL-contribution", style={"margin": "0", "color": COLORS["text_primary"], "fontSize": "14px"}),
                                html.Span("Diagonal y = x is neutral. Below = rivalry-net-negative.", style={
                                    "color": COLORS["text_muted"], "fontSize": "11px", "marginLeft": "12px",
                                }),
                            ]),
                            dcc.Graph(id="capalloc_scatter", style={"height": "380px"}, config={"displayModeBar": False}),
                        ],
                    ),
                    # Panel 4 (regime breakdown) — bonus if data available
                    html.Div(
                        style=CARD_STYLE,
                        children=[
                            html.Div(style=SECTION_HEADER, children=[
                                html.H4("Per-regime PnL by edge (bonus)", style={"margin": "0", "color": COLORS["text_primary"], "fontSize": "14px"}),
                                html.Span("Crisis vs benign — does rivalry pattern persist?", style={
                                    "color": COLORS["text_muted"], "fontSize": "11px", "marginLeft": "12px",
                                }),
                            ]),
                            dcc.Graph(id="capalloc_regime", style={"height": "380px"}, config={"displayModeBar": False}),
                        ],
                    ),
                ],
            ),

            # Panel 3: Cap-binding time series
            html.Div(
                style={**CARD_STYLE, "marginBottom": "24px"},
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("3. Cap-binding diagnostic — rolling fill share per edge", style={"margin": "0", "color": COLORS["text_primary"], "fontSize": "14px"}),
                        html.Span(
                            f"Rolling fill share over a trailing window (default {ROLLING_WINDOW_DAYS} days). Series sitting at the red cap line indicates fill_share_capper biting on that edge.",
                            style={"color": COLORS["text_muted"], "fontSize": "11px", "marginLeft": "12px"},
                        ),
                    ]),
                    dcc.Graph(id="capalloc_binding_chart", style={"height": "440px"}, config={"displayModeBar": False}),
                    html.Div(id="capalloc_binding_summary", style={
                        "color": COLORS["text_muted"], "fontSize": "12px",
                        "marginTop": "12px", "fontFamily": "'SF Mono', 'Fira Code', 'Consolas', monospace",
                    }),
                ],
            ),
        ],
    )
