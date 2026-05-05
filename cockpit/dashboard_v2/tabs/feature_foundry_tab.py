"""Feature Foundry audit tab.

F6 of the Feature Foundry. Single view onto the substrate's state:
  - per-feature row: name, tier, source, last revalidation, ablation
    contribution, twin presence, color-coded health flag
  - per-source row: license, freshness, point-in-time discipline
  - validator panel: any model card / registry mismatches

This tab is read-only. The cron-driven ablation runner + freshness
refresher live elsewhere; this view surfaces their output.
"""
from __future__ import annotations

from dash import dcc, html, dash_table

from ..utils.styles import CARD_STYLE, SECTION_HEADER, COLORS


def feature_foundry_layout():
    return html.Div(
        style={"minHeight": "70vh"},
        children=[
            # Header
            html.Div(
                style=SECTION_HEADER,
                children=[
                    html.H3("Feature Foundry", style={
                        "margin": "0", "color": COLORS["text_primary"],
                    }),
                    html.Span("Substrate audit", style={
                        "background": "rgba(88, 166, 255, 0.15)",
                        "color": COLORS["accent_blue"],
                        "fontSize": "11px",
                        "fontWeight": "600",
                        "padding": "4px 12px",
                        "borderRadius": "20px",
                    }),
                ],
            ),

            # Refresh control
            html.Div(
                style={
                    **CARD_STYLE, "padding": "12px 24px", "marginBottom": "24px",
                    "display": "flex", "alignItems": "center", "gap": "16px",
                },
                children=[
                    html.Button(
                        "Refresh", id="foundry_refresh", n_clicks=0,
                        style={
                            "background": COLORS["bg_input"],
                            "color": COLORS["text_secondary"],
                            "border": f"1px solid {COLORS['border']}",
                            "borderRadius": "8px",
                            "padding": "6px 16px",
                            "fontSize": "13px",
                            "cursor": "pointer",
                        },
                    ),
                    html.Span(id="foundry_summary", style={
                        "color": COLORS["text_muted"], "fontSize": "12px",
                    }),
                ],
            ),

            # Validation errors panel
            html.Div(
                style={**CARD_STYLE, "marginBottom": "24px"},
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("Model card validation", style={
                            "margin": "0", "color": COLORS["text_primary"],
                            "fontSize": "14px",
                        }),
                        html.Span("Hard CI gate; empty = clean", style={
                            "color": COLORS["text_muted"], "fontSize": "11px",
                            "marginLeft": "12px",
                        }),
                    ]),
                    html.Div(id="foundry_validation_errors", style={
                        "color": COLORS["text_secondary"], "fontSize": "12px",
                        "fontFamily": "'SF Mono', 'Fira Code', monospace",
                    }),
                ],
            ),

            # Review Pending panel — surfaces features the 90-day archive
            # auditor has flagged. Empty under healthy conditions; populated
            # rows demand human triage. Per CLAUDE.md, the auditor never
            # deletes — it just surfaces here.
            html.Div(
                style={**CARD_STYLE, "marginBottom": "24px"},
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("Review Pending", style={
                            "margin": "0", "color": COLORS["text_primary"],
                            "fontSize": "14px",
                        }),
                        html.Span(
                            "90-day archive auditor flags. Human-triage required: "
                            "archive (status='archived'), un-flag, or investigate.",
                            style={
                                "color": COLORS["text_muted"], "fontSize": "11px",
                                "marginLeft": "12px",
                            },
                        ),
                    ]),
                    html.Div(id="foundry_review_pending", style={
                        "color": COLORS["text_secondary"], "fontSize": "12px",
                    }),
                ],
            ),

            # Per-feature audit table
            html.Div(
                style={**CARD_STYLE, "marginBottom": "24px"},
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("Features", style={
                            "margin": "0", "color": COLORS["text_primary"],
                            "fontSize": "14px",
                        }),
                        html.Span(
                            "Health: green = ok, yellow = warn (stale / no twin), "
                            "red = fail (no card / negative ablation).",
                            style={
                                "color": COLORS["text_muted"],
                                "fontSize": "11px", "marginLeft": "12px",
                            },
                        ),
                    ]),
                    dash_table.DataTable(
                        id="foundry_feature_table",
                        data=[],
                        columns=[
                            {"name": "Feature ID", "id": "feature_id"},
                            {"name": "Tier", "id": "tier"},
                            {"name": "Source", "id": "source"},
                            {"name": "Horizon (d)", "id": "horizon", "type": "numeric"},
                            {"name": "License", "id": "license"},
                            {"name": "Card", "id": "has_model_card"},
                            {"name": "Last Revalidated", "id": "last_revalidation"},
                            {"name": "Ablation Δ Sharpe", "id": "ablation_contribution"},
                            {"name": "Twin", "id": "twin_present"},
                            {"name": "Twin ID", "id": "twin_id"},
                            {"name": "Health", "id": "health"},
                            {"name": "Reason", "id": "health_reason"},
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
                            "fontFamily": "'SF Mono', 'Fira Code', monospace",
                            "textAlign": "left",
                        },
                        style_data_conditional=[
                            {"if": {"row_index": "odd"},
                             "backgroundColor": "rgba(22, 27, 34, 0.4)"},
                            {"if": {"filter_query": "{health} = ok"},
                             "color": COLORS["accent_green"]},
                            {"if": {"filter_query": "{health} = warn"},
                             "color": COLORS["accent_yellow"]},
                            {"if": {"filter_query": "{health} = fail"},
                             "color": COLORS["accent_red"], "fontWeight": "600"},
                        ],
                    ),
                ],
            ),

            # Per-source audit table
            html.Div(
                style={**CARD_STYLE, "marginBottom": "24px"},
                children=[
                    html.Div(style=SECTION_HEADER, children=[
                        html.H4("Data sources", style={
                            "margin": "0", "color": COLORS["text_primary"],
                            "fontSize": "14px",
                        }),
                        html.Span(
                            "Stale freshness flips the row to warn. "
                            "point_in_time_safe=NO blocks production use.",
                            style={
                                "color": COLORS["text_muted"],
                                "fontSize": "11px", "marginLeft": "12px",
                            },
                        ),
                    ]),
                    dash_table.DataTable(
                        id="foundry_source_table",
                        data=[],
                        columns=[
                            {"name": "Source", "id": "name"},
                            {"name": "License", "id": "license"},
                            {"name": "Point-in-time safe", "id": "point_in_time_safe"},
                            {"name": "Latency", "id": "latency"},
                            {"name": "Freshness", "id": "freshness"},
                            {"name": "Health", "id": "health"},
                        ],
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
                            "fontFamily": "'SF Mono', 'Fira Code', monospace",
                            "textAlign": "left",
                        },
                        style_data_conditional=[
                            {"if": {"row_index": "odd"},
                             "backgroundColor": "rgba(22, 27, 34, 0.4)"},
                            {"if": {"filter_query": "{health} = ok"},
                             "color": COLORS["accent_green"]},
                            {"if": {"filter_query": "{health} = warn"},
                             "color": COLORS["accent_yellow"]},
                        ],
                    ),
                ],
            ),
        ],
    )
