# cockpit/dashboard/callbacks/shared_callbacks.py
from __future__ import annotations
from dash import Input, Output, html
import plotly.graph_objects as go

def register_shared_callbacks(app, live: bool, layouts: dict[str, callable]):
    @app.callback(Output("tab-content", "children"), Input("tabs", "value"))
    def _render_tab(tab_value):
        if tab_value == "tab-mode":
            return layouts["tab-mode"]()
        if tab_value == "tab-dashboard":
            return layouts["tab-dashboard"]()
        if tab_value == "tab-performance":
            return layouts["tab-performance"]()
        if tab_value == "tab-analytics":
            return layouts["tab-analytics"]()
        if tab_value == "tab-governor":
            return layouts["tab-governor"]()
        if tab_value == "tab-intel":
            return layouts["tab-intel"]()
        return layouts["tab-settings"]()
    

    @app.callback(Output("mode_state", "data"), Input("mode_selector_radio", "value"), prevent_initial_call=False)
    def _set_mode_state(selected_mode):
        return selected_mode

    @app.callback(Output("mode_status", "children"), Input("mode_state", "data"), prevent_initial_call=False)
    def _mode_status(mode_value):
        return f"Active Mode: {mode_value.capitalize()}"

    @app.callback(Output("mode_label", "children"), Input("mode_state", "data"), prevent_initial_call=False)
    def _mode_label(mode_value):
        label = "Backtest" if mode_value == "backtest" else ("Paper" if mode_value == "paper" else "Live")
        return f"Active Mode: {label}"

    @app.callback(Output("mode_top_indicator", "children"), Input("mode_state", "data"), Input("pulse", "n_intervals"), prevent_initial_call=False)
    def _mode_indicator(mode_value, _n):
        if mode_value == "paper":
            return html.Span("🟢 PAPER MODE — Auto-refreshing", style={"color": "#12ff8c"})
        elif mode_value == "live":
            return html.Span("⚪ LIVE MODE (Coming Soon)", style={"color": "#ffb300"})
        else:
            return html.Span("🟣 BACKTEST MODE", style={"color": "#8c6bff"})