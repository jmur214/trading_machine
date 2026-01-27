
# cockpit/dashboard_v2/callbacks/analytics_navigation_callbacks.py
from dash import Input, Output, html
from ..tabs.performance_tab import performance_layout
from ..tabs.governor_tab import governor_layout
from ..tabs.evolution_tab import evolution_layout

def register_analytics_navigation_callbacks(app):
    @app.callback(
        Output("analytics_sub_content", "children"),
        Input("analytics_sub_tab_selector", "value"),
        prevent_initial_call=False  # Fire on load to show default
    )
    def render_analytics_sub_content(selected_tab):
        if selected_tab == "performance":
            return performance_layout()
        elif selected_tab == "governor":
            return governor_layout()
        elif selected_tab == "evolution":
            return evolution_layout()
        return html.Div("Select a module.")
