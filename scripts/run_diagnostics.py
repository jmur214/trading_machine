import os, sys, subprocess, json, time
import glob

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
os.chdir(PROJECT_ROOT)

results = []

def run(cmd, step_name=None):
    print(f"\n[RUNNING] {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        status = "✅"
        print(f"{status} SUCCESS: {cmd}")
    else:
        status = "❌"
        print(f"{status} FAIL: {cmd}")
    print(result.stdout)
    if result.stderr:
        print(result.stderr)
    if step_name:
        results.append({"step": step_name, "status": status})
    return result

def check_file(path, desc):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        status = "✅"
        print(f"{status} {desc} found: {path}")
    else:
        status = "⚠️"
        print(f"{status} Missing or empty {desc}: {path}")
    results.append({"step": desc, "status": status})

print("=== Trading Machine System Diagnostic ===\n")

# 1. Edge tests
run("pytest -q tests/test_edge_outputs_extended.py", step_name="Edge tests")

# 2. Alpha pipeline & collector integration
for test in ["tests/test_alpha_pipeline.py", "tests/test_collector_integration.py"]:
    if os.path.exists(test):
        run(f"pytest -q {test}", step_name=f"Test: {os.path.basename(test)}")
    else:
        status = "⚠️"
        print(f"{status} Skipping missing test: {test}")
        results.append({"step": f"Test: {os.path.basename(test)}", "status": status})

# 3. Portfolio / Backtest Controller
for test in ["tests/test_portfolio.py", "tests/test_backtest_controller.py"]:
    if os.path.exists(test):
        run(f"pytest -q {test}", step_name=f"Test: {os.path.basename(test)}")

# 4. Backtest dry run
print("\n[STEP] Running debug backtest...")
run("python -m scripts.run_backtest --fresh", step_name="Backtest dry run")

# 5. Check output artifacts

# Check all trades.csv under data/trade_logs subfolders
trade_log_paths = glob.glob("data/trade_logs/*/trades.csv")
non_empty_trade_logs = 0
for path in trade_log_paths:
    if os.path.exists(path) and os.path.getsize(path) > 0:
        status = "✅"
        print(f"{status} Trade log found: {path}")
        non_empty_trade_logs += 1
    else:
        status = "⚠️"
        print(f"{status} Missing or empty Trade log: {path}")
    results.append({"step": f"Trade log: {path}", "status": status})

# Check portfolio snapshots and performance summary as before
check_file("data/trade_logs/portfolio_snapshots.csv", "Portfolio snapshots")
check_file("data/research/performance_summary.json", "Performance summary")

# Add summary entry for trading activity
if non_empty_trade_logs > 0:
    status = "✅"
    print(f"{status} Trading Activity detected with {non_empty_trade_logs} non-empty trade log(s).")
else:
    status = "⚠️"
    print(f"{status} No non-empty trade logs detected in any subfolder.")
results.append({"step": "Trading Activity", "status": status})

# 6. Governor feedback
print("\n[STEP] Running Governor feedback...")
run("python -m analytics.edge_feedback", step_name="Governor feedback")

# 7. Print final summary
print("\n=== Diagnostics complete ===")
print("If trades.csv is empty or metrics missing, focus on RiskEngine → Execution → Governor chain.")

# Summary aggregation and printout
print("\n=== Summary ===")
print(f"{'Step':40} Status")
pass_count = 0
for r in results:
    print(f"{r['step'][:40]:40} {r['status']}")
    if r['status'] == "✅":
        pass_count += 1
total = len(results)
score = (pass_count / total * 100) if total > 0 else 0
print(f"\nOverall system health: {score:.1f}% ({pass_count}/{total} steps passed)")