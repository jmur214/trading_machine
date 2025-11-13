import argparse
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone

try:
    from scripts.run_diagnostics import run_full_diagnostics
except ImportError:
    run_full_diagnostics = None

def print_timestamped(msg, debug):
    if debug:
        now = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        print(f"[{now}] {msg}")
    else:
        print(msg)

def run_pytest(debug):
    print_timestamped("[STEP] Running Pytest...", debug)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-q",
                "--disable-warnings",
                "--tb=short",
                "-k",
                "edge or alpha or collector",
            ],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if debug:
            print(result.stdout)
            if result.stderr.strip():
                print(result.stderr)
        passed = "failed" not in result.stdout.lower()
        return passed
    except Exception as e:
        print(f"❌ Pytest run failed: {e}")
        return False

def check_latest_backtest(debug):
    print_timestamped("[STEP] Checking Trade Logs...", debug)
    backtest_dir = os.path.expanduser("data/trade_logs")
    if not os.path.isdir(backtest_dir):
        print("❌ Trade logs directory not found")
        return False, False
    try:
        runs = sorted(
            [
                d
                for d in os.listdir(backtest_dir)
                if os.path.isdir(os.path.join(backtest_dir, d))
            ],
            reverse=True,
        )
        if not runs:
            print("❌ No trade log runs found")
            return False, False
        latest = os.path.join(backtest_dir, runs[0])
        trades_file = os.path.join(latest, "trades.csv")
        portfolio_file = os.path.join(latest, "portfolio_snapshots.csv")
        trades_exist = os.path.isfile(trades_file)
        portfolio_exist = os.path.isfile(portfolio_file)
        if trades_exist:
            print(f"✅ Trades found: {trades_file}")
        else:
            print("⚠️  Trades file missing")
        if portfolio_exist:
            print(f"✅ Portfolio snapshots found: {portfolio_file}")
        else:
            print("⚠️  Portfolio snapshots missing")
        return trades_exist, portfolio_exist
    except Exception as e:
        print(f"❌ Error checking trade log files: {e}")
        return False, False

def check_governor_health(debug):
    print_timestamped("[STEP] Governor Metrics...", debug)
    base_path = os.path.expanduser("data/governor")
    sandbox_path = os.path.join(base_path, "sandbox")
    weights_file = os.path.join(sandbox_path, "edge_weights.json")
    metrics_file = os.path.join(sandbox_path, "edge_metrics.json")

    weights_ok = False
    metrics_ok = False

    if os.path.isfile(weights_file):
        weights_ok = True
        print(f"✅ Edge Weights found (sandbox): {weights_file}")
    else:
        fallback_weights = os.path.join(base_path, "edge_weights.json")
        if os.path.isfile(fallback_weights):
            weights_ok = True
            print(f"✅ Edge Weights found: {fallback_weights}")
        else:
            print("⚠️ Edge Weights missing")

    if os.path.isfile(metrics_file):
        metrics_ok = True
        print(f"✅ Edge Metrics found (sandbox): {metrics_file}")
    else:
        fallback_metrics = os.path.join(base_path, "edge_metrics.json")
        if os.path.isfile(fallback_metrics):
            metrics_ok = True
            print(f"✅ Edge Metrics found: {fallback_metrics}")
        else:
            print("⚠️ Edge Metrics missing")

    return weights_ok, metrics_ok

def calculate_health_score(pytest_ok, trades_ok, portfolio_ok, weights_ok, metrics_ok):
    checks = [pytest_ok, trades_ok, portfolio_ok, weights_ok, metrics_ok]
    score = sum(1 for c in checks if c) / len(checks) * 100
    return int(score)

def signal_handler(sig, frame):
    print("\nTermination requested, exiting gracefully...")
    sys.exit(0)

def main():
    parser = argparse.ArgumentParser(description="Continuous machine health validation")
    parser.add_argument(
        "--interval",
        type=int,
        default=60,
        help="Minutes between checks (default: 60)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one time and exit",
    )
    parser.add_argument(
        "--no-tests",
        action="store_true",
        help="Skip pytest suite",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Verbose output with live timestamps",
    )
    args = parser.parse_args()

    signal.signal(signal.SIGINT, signal_handler)

    while True:
        now_str = datetime.now(timezone.utc).strftime("%H:%M UTC")
        print(f"\n=== Continuous Validation Run ({now_str}) ===")

        if run_full_diagnostics is not None and not args.no_tests:
            print_timestamped("[STEP] Running full diagnostics from run_diagnostics.py...", args.debug)
            try:
                run_full_diagnostics(debug=args.debug)
            except Exception as e:
                print(f"❌ Error running full diagnostics: {e}")

        pytest_ok = True
        if not args.no_tests:
            pytest_ok = run_pytest(args.debug)

        trades_ok, portfolio_ok = check_latest_backtest(args.debug)
        weights_ok, metrics_ok = check_governor_health(args.debug)

        health_score = calculate_health_score(pytest_ok, trades_ok, portfolio_ok, weights_ok, metrics_ok)

        if health_score == 100:
            summary_icon = "✅"
        elif health_score >= 70:
            summary_icon = "⚠️"
        else:
            summary_icon = "❌"

        print(f"=== Health Summary: {summary_icon} {health_score}% OK ===")

        if args.once:
            break

        print(f"Next run in {args.interval} minutes...")
        try:
            time.sleep(args.interval * 60)
        except KeyboardInterrupt:
            print("\nTermination requested, exiting gracefully...")
            break

if __name__ == "__main__":
    main()
