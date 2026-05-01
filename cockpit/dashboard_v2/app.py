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
from .tabs.dashboard_tab import dashboard_layout
from .tabs.analytics_parent_tab import analytics_parent_layout
from .tabs.settings_tab import settings_layout
from .tabs.intel_tab import create_intel_layout
from .tabs.backtest_tab import backtest_layout
from .tabs.trading_tab import trading_layout
from .tabs.command_tab import command_layout

# --- Sub-Tabs Imports ---
from .tabs.performance_tab import performance_layout
from .tabs.governor_tab import governor_layout
from .tabs.evolution_tab import evolution_layout

# --- Shared styles ---
from .utils.styles import TAB_STYLE, TAB_SELECTED_STYLE

# --- Callbacks ---
from .callbacks.shared_callbacks import register_shared_callbacks
from .callbacks.analytics_navigation_callbacks import register_analytics_navigation_callbacks
from .callbacks.dashboard_callbacks import register_dashboard_callbacks
from .callbacks.performance_callbacks import register_performance_callbacks
from .callbacks.governor_callbacks import register_governor_callbacks
from .callbacks.mode_callbacks import register_mode_callbacks
from .callbacks.intel_callbacks import register_intel_callbacks
from .callbacks.evolution_callbacks import register_evolution_callbacks
from .callbacks.backtest_callbacks import register_backtest_callbacks
from .callbacks.trading_callbacks import register_trading_callbacks
from .callbacks.command_callbacks import register_command_callbacks
from .callbacks.capital_allocation_callbacks import register_capital_allocation_callbacks


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
    tab_style = TAB_STYLE
    selected_tab_style = TAB_SELECTED_STYLE

    app.layout = html.Div(
        style={
            "minHeight": "100vh",
            "padding": "0",
        },
        children=[
            # Header Section
            html.Div(
                style={
                    "padding": "24px 32px 16px",
                    "borderBottom": "1px solid rgba(56, 68, 77, 0.3)",
                    "marginBottom": "24px",
                },
                children=[
                    html.H1(
                        "Trading Cockpit",
                        style={
                            "textAlign": "center",
                            "margin": "0 0 8px 0",
                            "fontSize": "1.75rem",
                            "fontWeight": "700",
                            "letterSpacing": "-0.03em",
                            "background": "linear-gradient(90deg, #58a6ff, #a371f7)",
                            "WebkitBackgroundClip": "text",
                            "WebkitTextFillColor": "transparent",
                            "backgroundClip": "text",
                        }
                    ),
                    html.P(
                        "Autonomous Research & Trading Laboratory",
                        style={
                            "textAlign": "center",
                            "margin": "0",
                            "color": "#6e7681",
                            "fontSize": "13px",
                            "fontWeight": "400",
                        }
                    ),
                ]
            ),
            
            # Mode State Store
            dcc.Store(id="mode_state", data="backtest"),
            
            # Navigation Tabs (condensed)
            html.Div(
                style={"padding": "0 32px", "marginBottom": "24px"},
                children=[
                    dcc.Tabs(
                        id="tabs",
                        value="tab-dashboard",
                        className="custom-tabs",
                        children=[
                            dcc.Tab(label="Dashboard", value="tab-dashboard", style=tab_style, selected_style=selected_tab_style),
                            dcc.Tab(label="Backtest", value="tab-backtest", style=tab_style, selected_style=selected_tab_style),
                            dcc.Tab(label="Trading", value="tab-trading", style=tab_style, selected_style=selected_tab_style),
                            dcc.Tab(label="Analytics", value="tab-analytics-parent", style=tab_style, selected_style=selected_tab_style),
                            dcc.Tab(label="Command Center", value="tab-command", style=tab_style, selected_style=selected_tab_style),
                            dcc.Tab(label="Intel", value="tab-intel", style=tab_style, selected_style=selected_tab_style),
                            dcc.Tab(label="Settings", value="tab-settings", style=tab_style, selected_style=selected_tab_style),
                        ],
                    ),
                ]
            ),
            
            # Tab Content Area
            html.Div(
                id="tab-content",
                style={"padding": "0 32px 32px"},
            ),
            
            # Interval for live updates
            dcc.Interval(id="pulse", interval=2000, n_intervals=0, disabled=not live),
        ],
    )

    # ---------- Register Callbacks ----------
    register_shared_callbacks(
        app,
        live=live,
        layouts={
            "tab-dashboard": dashboard_layout,
            "tab-backtest": backtest_layout,
            "tab-trading": trading_layout,
            "tab-analytics-parent": analytics_parent_layout,
            "tab-command": command_layout,
            "tab-intel": create_intel_layout,
            "tab-settings": settings_layout,
        },
    )

    # Register sub-nav handler
    register_analytics_navigation_callbacks(app)

    # Register functional callbacks
    register_dashboard_callbacks(app)
    register_performance_callbacks(app)
    register_governor_callbacks(app)
    register_mode_callbacks(app)
    register_intel_callbacks(app)
    register_evolution_callbacks(app)
    register_backtest_callbacks(app)
    register_trading_callbacks(app)
    register_command_callbacks(app)
    register_capital_allocation_callbacks(app)

    return app


def run_dashboard(live: bool = False, port: int = 8050):
    """Launch the v2 dashboard."""
    app = create_dash_app(live=live)
    # Default to localhost for security (prevents LAN access)
    app.run(debug=True, host="127.0.0.1", port=port, use_reloader=False)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="Enable interval pulse updates (for paper trading).")
    p.add_argument("--port", type=int, default=8050, help="Port number (default 8050).")
    args = p.parse_args()
    run_dashboard(live=args.live, port=args.port)