"""Callbacks for the Feature Foundry audit tab."""
from __future__ import annotations

from dash import Input, Output, html

from ..utils.styles import COLORS


def register_feature_foundry_callbacks(app):
    @app.callback(
        Output("foundry_feature_table", "data"),
        Output("foundry_source_table", "data"),
        Output("foundry_validation_errors", "children"),
        Output("foundry_review_pending", "children"),
        Output("foundry_summary", "children"),
        Input("foundry_refresh", "n_clicks"),
        prevent_initial_call=False,
    )
    def refresh(_):
        # Lazy imports — keep dashboard import path Foundry-agnostic so a
        # cockpit run without Foundry plugins still boots cleanly.
        try:
            # Trigger plugin self-registration
            import core.feature_foundry.sources  # noqa: F401
            import core.feature_foundry.features  # noqa: F401
            from ..utils.feature_foundry_loader import (
                load_foundry_rows,
                load_source_rows,
                load_validation_errors,
                load_review_pending_rows,
            )
        except Exception as exc:
            return (
                [], [],
                html.Div(f"Foundry import failed: {exc}",
                         style={"color": COLORS["accent_red"]}),
                html.Div(""),
                "0 features · 0 sources",
            )

        feature_rows = load_foundry_rows()
        source_rows = load_source_rows()
        errors = load_validation_errors()
        review_pending = load_review_pending_rows()

        if errors:
            error_block = html.Ul(
                [html.Li(e, style={"color": COLORS["accent_red"]}) for e in errors],
                style={"margin": "0", "paddingLeft": "20px"},
            )
        else:
            error_block = html.Div(
                "all model cards valid",
                style={"color": COLORS["accent_green"]},
            )

        if review_pending:
            review_block = html.Ul(
                [
                    html.Li(
                        [
                            html.Span(
                                row["feature_id"],
                                style={
                                    "fontWeight": "600",
                                    "color": COLORS["accent_yellow"],
                                    "fontFamily": "'SF Mono', 'Fira Code', monospace",
                                },
                            ),
                            html.Span(
                                f"  —  {row.get('flagged_reason') or 'flagged'}",
                                style={
                                    "color": COLORS["text_secondary"],
                                    "fontSize": "12px",
                                },
                            ),
                        ],
                        style={"marginBottom": "6px"},
                    )
                    for row in review_pending
                ],
                style={"margin": "0", "paddingLeft": "20px"},
            )
        else:
            review_block = html.Div(
                "no features flagged for review",
                style={"color": COLORS["accent_green"], "fontSize": "12px"},
            )

        summary = (
            f"{len(feature_rows)} features · {len(source_rows)} sources · "
            f"{len(errors)} validation errors · "
            f"{len(review_pending)} review_pending"
        )
        return (
            feature_rows, source_rows, error_block, review_block, summary,
        )
