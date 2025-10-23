"""
Launcher for Trading Machine Cockpit v2.
Usage:
    python cockpit_dashboard_v2.py
or:
    python cockpit_dashboard_v2.py --live
"""
from cockpit.dashboard_v2.app import run_dashboard

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--live", action="store_true", help="Enable auto-refresh updates (Paper Mode).")
    p.add_argument("--port", type=int, default=8050, help="Port number (default 8050).")
    args = p.parse_args()
    run_dashboard(live=args.live, port=args.port)