"""Callbacks for the Feature Foundry audit tab."""
from __future__ import annotations

from dash import Input, Output, html

from ..utils.styles import COLORS


def register_feature_foundry_callbacks(app):
    @app.callback(
        Output("foundry_feature_table", "data"),
        Output("foundry_source_table", "data"),
        Output("foundry_validation_errors", "children"),
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
            )
        except Exception as exc:
            return (
                [], [],
                html.Div(f"Foundry import failed: {exc}",
                         style={"color": COLORS["accent_red"]}),
                "0 features · 0 sources",
            )

        feature_rows = load_foundry_rows()
        source_rows = load_source_rows()
        errors = load_validation_errors()

        if errors:
            error_block = html.Ul(
                [html.Li(e, style={"color": COLORS["accent_red"]}) for e in errors],
                style={"margin": "0", "paddingLeft": "20px"},
            )
        else:
            error_block = html.Div(
                "✓ all model cards valid",
                style={"color": COLORS["accent_green"]},
            )

        summary = (
            f"{len(feature_rows)} features · {len(source_rows)} sources · "
            f"{len(errors)} validation errors"
        )
        return feature_rows, source_rows, error_block, summary
