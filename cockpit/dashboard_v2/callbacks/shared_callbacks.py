# cockpit/dashboard/callbacks/shared_callbacks.py
"""Shared callbacks for tab routing and mode state management."""
from __future__ import annotations
from dash import Input, Output, html
import plotly.graph_objects as go


def register_shared_callbacks(app, live: bool, layouts: dict[str, callable]):
    """Register shared callbacks for tab navigation and mode state."""
    
    @app.callback(Output("tab-content", "children"), Input("tabs", "value"))
    def _render_tab(tab_value):
        """Render the appropriate tab content based on selection."""
        if tab_value in layouts:
            return layouts[tab_value]()
        return layouts["tab-settings"]()

    @app.callback(Output("mode_state", "data"), Input("mode_selector_radio", "value"), prevent_initial_call=False)
    def _set_mode_state(selected_mode):
        """Update mode state when selection changes."""
        return selected_mode

    @app.callback(Output("mode_status", "children"), Input("mode_state", "data"), prevent_initial_call=False)
    def _mode_status(mode_value):
        """Display current mode status in settings."""
        return f"Active Mode: {mode_value.capitalize()}"

    @app.callback(Output("mode_label", "children"), Input("mode_state", "data"), prevent_initial_call=False)
    def _mode_label(mode_value):
        """Display mode label in header."""
        label = "Backtest" if mode_value == "backtest" else ("Paper" if mode_value == "paper" else "Live")
        return f"Active Mode: {label}"

    @app.callback(Output("mode_top_indicator", "children"), Input("mode_state", "data"), Input("pulse", "n_intervals"), prevent_initial_call=False)
    def _mode_indicator(mode_value, _n):
        """Display mode indicator badge (no emojis)."""
        if mode_value == "paper":
            return html.Span("PAPER MODE — Auto-refreshing", style={
                "color": "#3fb950",
                "background": "rgba(63, 185, 80, 0.15)",
                "padding": "4px 12px",
                "borderRadius": "20px",
                "fontSize": "12px",
                "fontWeight": "600",
            })
        elif mode_value == "live":
            return html.Span("LIVE MODE (Coming Soon)", style={
                "color": "#d29922",
                "background": "rgba(210, 153, 34, 0.15)",
                "padding": "4px 12px",
                "borderRadius": "20px",
                "fontSize": "12px",
                "fontWeight": "600",
            })
        else:
            return html.Span("BACKTEST MODE", style={
                "color": "#a371f7",
                "background": "rgba(163, 113, 247, 0.15)",
                "padding": "4px 12px",
                "borderRadius": "20px",
                "fontSize": "12px",
                "fontWeight": "600",
            })