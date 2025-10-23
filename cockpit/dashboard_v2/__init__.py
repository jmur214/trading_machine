"""
Trading Machine Cockpit v2 — modular Dash app.

Run it via:
    python -m cockpit.dashboard_v2.app
or:
    python cockpit_dashboard_v2.py

Note: This version is isolated from cockpit/dashboard.py
so you can switch between v1 and v2 without conflicts.
"""
from .app import run_dashboard, create_dash_app