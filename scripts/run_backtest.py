"""
scripts/run_backtest.py
=======================
Thin CLI wrapper around ModeController.run_backtest().

All orchestration logic lives in orchestration/mode_controller.py.
This script only parses CLI args and delegates.

run_backtest_logic() is kept as a backward-compatible entry point used by
scripts/run_benchmark.py, scripts/optimize.py, and scripts/harvest_data.py.
"""

import sys
import argparse
from pathlib import Path

from orchestration.mode_controller import ModeController


def run_backtest_logic(
    env="prod",
    mode="prod",
    fresh=False,
    no_governor=False,
    alpha_debug=False,
    override_start=None,
    override_end=None,
    override_params=None,
    exact_edge_ids=None,
    discover=False,
    override_capital=None,
):
    """
    Backward-compatible programmatic entry point for running a backtest.
    Delegates to ModeController.run_backtest().
    """
    root = Path(__file__).resolve().parents[1]
    mc = ModeController(root, env=env)
    return mc.run_backtest(
        mode=mode,
        fresh=fresh,
        no_governor=no_governor,
        alpha_debug=alpha_debug,
        override_start=override_start,
        override_end=override_end,
        override_params=override_params,
        exact_edge_ids=exact_edge_ids,
        discover=discover,
        override_capital=override_capital,
    )


def main():
    parser = argparse.ArgumentParser(description="Run historical backtest.")
    parser.add_argument("--fresh", action="store_true", help="Clear prior trades/snapshots before running.")
    parser.add_argument("--alpha-debug", action="store_true", help="Enable verbose alpha/edge debug output.")
    parser.add_argument("--no-governor", action="store_true", help="Skip governor updates.")
    parser.add_argument("--env", choices=["dev", "prod"], default="prod",
                        help="Use dev or prod configuration set")
    parser.add_argument("--mode", choices=["sandbox", "prod"], default="prod",
                        help="Run mode to separate data paths")
    parser.add_argument("--capital", type=float, default=None,
                        help="Override initial capital (e.g. 5000)")
    parser.add_argument("--discover", action="store_true",
                        help="Run post-backtest discovery cycle (hunt + validate + promote)")
    args = parser.parse_args()

    stats = run_backtest_logic(
        env=args.env,
        mode=args.mode,
        fresh=args.fresh,
        no_governor=args.no_governor,
        alpha_debug=args.alpha_debug,
        override_capital=args.capital,
        discover=args.discover,
    )

    print("\nPerformance Summary")
    for k, v in stats.items():
        print(f"{k}: {v}")

    return 0


if __name__ == "__main__":
    code = main()
    sys.exit(0 if code is None else code)
