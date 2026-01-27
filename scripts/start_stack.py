
import subprocess
import time

def run_background(cmd, log_file):
    print(f"Starting: {cmd} (log: {log_file})")
    with open(log_file, "w") as f:
        subprocess.Popen(cmd.split(), stdout=f, stderr=subprocess.STDOUT)

def main():
    print("==================================================")
    print("   SPINNING UP PAPER TRADING STACK")
    print("==================================================")
    
    # 1. Kill old instances
    print("[1/4] Cleaning up old processes...")
    try:
        subprocess.run(["pkill", "-f", "run_paper_loop"], check=False)
        subprocess.run(["pkill", "-f", "cockpit_dashboard_v2"], check=False)
        subprocess.run(["pkill", "-f", "update_data"], check=False)
    except Exception:
        pass
    time.sleep(1)
    
    # 2. Update Data (Blocking, to ensure we have a base)
    print("[2/4] Verifying data freshness...")
    subprocess.run(["python", "scripts/update_data.py"], check=False)
    
    # 3. Start Paper Loop
    print("[3/4] Starting Paper Trading Engine (Background)...")
    run_background("python scripts/run_paper_loop.py", "logs/paper_engine.log")
    
    # 4. Start Dashboard
    print("[4/4] Starting Cockpit Dashboard (Background)...")
    run_background("python cockpit_dashboard_v2.py --live --port 8050", "logs/dashboard.log")
    
    print("--------------------------------------------------")
    print("✅ Stack is ALIVE!")
    print("   -> Dashboard: http://localhost:8050")
    print("   -> Engine Logs: logs/paper_engine.log")
    print("   -> Trade Logs: data/trade_logs/trades.csv")
    print("--------------------------------------------------")

if __name__ == "__main__":
    main()
