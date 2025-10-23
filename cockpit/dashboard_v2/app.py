from __future__ import annotations

import os
from pathlib import Path
import dash
from dash import dcc, html
from dotenv import load_dotenv

load_dotenv()

# Load Alpaca keys
ALPACA_API_KEY = os.environ.get("APCA_API_KEY_ID", "")
ALPACA_API_SECRET = os.environ.get("APCA_API_SECRET_KEY", "")

# --- Tabs (layouts) ---
from .tabs.dashboard_tab import dashboard_layout, mode_layout
from .tabs.analytics_tab import analytics_layout
from .tabs.performance_tab import performance_layout
from .tabs.governor_tab import governor_layout
from .tabs.settings_tab import settings_layout
from .tabs.intel_tab import create_intel_layout

# --- Callbacks ---
from .callbacks.shared_callbacks import register_shared_callbacks
from .callbacks.dashboard_callbacks import register_dashboard_callbacks
from .callbacks.analytics_callbacks import register_analytics_callbacks
from .callbacks.performance_callbacks import register_performance_callbacks
from .callbacks.governor_callbacks import register_governor_callbacks
from .callbacks.mode_callbacks import register_mode_callbacks
from .callbacks.intel_callbacks import register_intel_callbacks


def create_dash_app(live: bool = False) -> dash.Dash:
    """Create and configure the Dash app for Cockpit v2."""
    app = dash.Dash(
        __name__,
        suppress_callback_exceptions=True,
        prevent_initial_callbacks="initial_duplicate",
        title="Trading Cockpit v2",
    )
    app.config.suppress_callback_exceptions = True

    # ---------- Global Layout ----------
    app.layout = html.Div(
        style={"backgroundColor": "#12151b", "color": "#EEE", "padding": "18px"},
        children=[
            html.H1("Trading Dashboard v2", style={"textAlign": "center"}),
            dcc.Store(id="mode_state", data="backtest"),
            dcc.Tabs(
                id="tabs",
                value="tab-mode",
                parent_style={"color": "#000"},
                children=[
                    dcc.Tab(label="Mode", value="tab-mode", selected_style={"background": "#222"}),
                    dcc.Tab(label="Dashboard", value="tab-dashboard", selected_style={"background": "#222"}),
                    dcc.Tab(label="Performance", value="tab-performance", selected_style={"background": "#222"}),
                    dcc.Tab(label="Analytics", value="tab-analytics", selected_style={"background": "#222"}),
                    dcc.Tab(label="Governor", value="tab-governor", selected_style={"background": "#222"}),
                    dcc.Tab(label="Intel", value="tab-intel", selected_style={"background": "#222"}),
                    dcc.Tab(label="Settings", value="tab-settings", selected_style={"background": "#222"}),
                ],
            ),
            html.Div(id="tab-content"),
            dcc.Interval(id="pulse", interval=2000, n_intervals=0, disabled=not live),
        ],
    )

    # ---------- Register Callbacks ----------
    register_shared_callbacks(
        app,
        live=live,
        layouts={
            "tab-mode": mode_layout,
            "tab-dashboard": dashboard_layout,
            "tab-performance": performance_layout,
            "tab-analytics": analytics_layout,
            "tab-governor": governor_layout,
            "tab-intel": create_intel_layout,
            "tab-settings": settings_layout,
        },
    )

    register_dashboard_callbacks(app)
    register_performance_callbacks(app)
    register_analytics_callbacks(app, live=live)
    register_governor_callbacks(app)
    register_mode_callbacks(app)
    register_intel_callbacks(app)

    return app


def run_dashboard(live: bool = False, port: int = 8050):
    """Launch the v2 dashboard."""
    app = create_dash_app(live=live)
    app.run(debug=True, host="0.0.0.0", port=port, use_reloader=False)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="Enable interval pulse updates (for paper trading).")
    p.add_argument("--port", type=int, default=8050, help="Port number (default 8050).")
    args = p.parse_args()
    run_dashboard(live=args.live, port=args.port)