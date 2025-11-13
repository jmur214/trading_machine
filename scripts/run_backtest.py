from dotenv import load_dotenv
load_dotenv()
import os
import sys
import importlib
from pathlib import Path
from utils.config_loader import load_json
from engines.data_manager.data_manager import DataManager

from engines.engine_a_alpha.alpha_engine import AlphaEngine
from engines.engine_b_risk.risk_engine import RiskEngine
from backtester.backtest_controller import BacktestController
from cockpit.logger import CockpitLogger
from cockpit.metrics import PerformanceMetrics

# --- Import EdgeRegistry for dynamic edge loading ---
from engines.engine_a_alpha.edge_registry import EdgeRegistry

# ✅ NEW: import StrategyGovernor
from engines.engine_d_research.governor import StrategyGovernor

import argparse


def main():
    root = Path(__file__).resolve().parents[1]

    parser = argparse.ArgumentParser(description="Run historical backtest.")
    parser.add_argument("--fresh", action="store_true", help="Clear prior trades/snapshots before running.")
    parser.add_argument("--alpha-debug", action="store_true", help="Enable verbose alpha/edge debug output.")
    parser.add_argument("--no-governor", action="store_true", help="Skip governor updates.")
    parser.add_argument("--env", choices=["dev", "prod"], default="prod",
                        help="Use dev or prod configuration set")
    parser.add_argument("--mode", choices=["sandbox", "prod"], default="prod",
                        help="Run mode to separate data paths")
    args = parser.parse_args()
    env = args.env
    mode = args.mode
    if args.alpha_debug:
        os.environ["ALPHA_DEBUG"] = "1"

    # --- Optional: Clear previous trade and snapshot logs if --fresh is used ---
    if args.fresh:
        log_dir = root / "data" / "trade_logs"
        backup_dir = log_dir / "backup"
        backup_dir.mkdir(parents=True, exist_ok=True)
        import shutil, time
        for fn in ["trades.csv", "portfolio_snapshots.csv"]:
            fpath = log_dir / fn
            if fpath.exists() and fpath.stat().st_size > 0:
                ts = int(time.time())
                shutil.copy(fpath, backup_dir / f"{fn}_{ts}.bak")
                fpath.write_text("")
        print("[RUN_BACKTEST] Cleared previous logs (fresh run mode).")

    # --- Load configuration files ---
    cfg_bt = load_json(str(root / "config" / "backtest_settings.json"))
    cfg_risk = load_json(str(root / f"config/risk_settings.{env}.json"))
    cfg_edges = load_json(str(root / "config" / "edge_config.json"))

    tickers = cfg_bt["tickers"]
    start = cfg_bt["start_date"]
    end = cfg_bt["end_date"]
    timeframe = cfg_bt["timeframe"]
    init_cap = float(cfg_bt["initial_capital"])

    # --- Prepare data ---
    print("[DEBUG] Alpaca keys:", os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_BASE_URL"))
    dm = DataManager(cache_dir=str(root / "data" / "processed"),
                     api_key=os.getenv("ALPACA_API_KEY"),
                     secret_key=os.getenv("ALPACA_SECRET_KEY"),
                     base_url=os.getenv("ALPACA_BASE_URL"))
    data_map = dm.ensure_data(tickers, start, end, timeframe=timeframe)

    # --- Load active edges dynamically (holistic system) ---
    from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec

    edges = {}
    edge_weights = cfg_edges.get("edge_weights", {})
    edge_params = cfg_edges.get("edge_params", {})

    # --- Step 1: Load active edges from EdgeRegistry ---
    try:
        reg = EdgeRegistry()
        registry_edges = reg.list_active_modules()
        print(f"[ALPHA] Using EdgeRegistry modules: {registry_edges}")
    except Exception as e:
        print(f"[ALPHA][WARN] Could not read EdgeRegistry: {e}")
        registry_edges = []

    # --- Step 2: Load active edges from config (for backward compatibility) ---
    config_edges = cfg_edges.get("active_edges", [])
    if config_edges:
        print(f"[ALPHA] Including edges from config: {config_edges}")

    # --- Step 3: Merge and deduplicate ---
    active_edges = sorted(list(set(registry_edges + config_edges)))

    # --- Step 4: Import each edge module dynamically ---
    for edge_name in active_edges:
        try:
            mod = importlib.import_module(f"engines.engine_a_alpha.edges.{edge_name}")

            # Check if the module defines a subclassed Edge class with params
            edge_class = None
            for attr in dir(mod):
                if attr.lower().endswith("edge") and attr not in ["BaseEdge"]:
                    edge_class = getattr(mod, attr)
                    break

            params = edge_params.get(edge_name, {})

            if edge_class is not None:
                try:
                    edges[edge_name] = edge_class(params=params)
                except TypeError:
                    # fallback if the class doesn't support params
                    edges[edge_name] = edge_class()
            else:
                edges[edge_name] = mod

            # --- Ensure it’s registered in the EdgeRegistry ---
            try:
                if hasattr(mod, "EDGE_ID") and hasattr(mod, "CATEGORY"):
                    reg.ensure(EdgeSpec(
                        edge_id=getattr(mod, "EDGE_ID", edge_name),
                        category=getattr(mod, "CATEGORY", "other"),
                        module=edge_name,
                        version="1.0.0",
                        params=params,
                        status="active",
                    ))
            except Exception as e:
                print(f"[ALPHA][WARN] Could not update registry for edge '{edge_name}': {e}")

        except Exception as e:
            print(f"[ALPHA][ERROR] Could not import edge '{edge_name}': {e}")

    print(f"[ALPHA] Loaded {len(edges)} edges: {list(edges.keys())}")

    # ✅ NEW: Instantiate the StrategyGovernor
    governor_state_path = root / "data" / "governor"
    if mode == "sandbox":
        governor_state_path = governor_state_path / "sandbox"
    governor_state_path.mkdir(parents=True, exist_ok=True)

    governor = StrategyGovernor(
        config_path=str(root / "config" / "governor_settings.json"),
        state_path=str(governor_state_path / "edge_weights.json"),
    )

    cfg_alpha = load_json(str(root / f"config/alpha_settings.{env}.json"))

    # --- Initialize engines ---
    alpha = AlphaEngine(
        edges=edges,
        edge_weights=edge_weights,
        config=cfg_alpha,
        debug=True,
        governor=governor,  # ✅ pass it in
    )
    risk = RiskEngine(cfg_risk)
    cockpit = CockpitLogger(out_dir=str(root / "data" / "trade_logs"))

    # --- Execution parameters ---
    exec_params = {
        "slippage_bps": float(cfg_bt.get("slippage_bps", 10.0)),
        "commission": float(cfg_bt.get("commission", 0.0)),
    }

    # --- Create the backtest controller ---
    controller = BacktestController(
        data_map=data_map,
        alpha_engine=alpha,
        risk_engine=risk,
        cockpit_logger=cockpit,
        exec_params=exec_params,
        initial_capital=init_cap,
    )

    # --- Run backtest ---
    history = controller.run(start, end)

    # --- Promote to governor if configured ---
    promote_to_governor = cfg_bt.get("promote_to_governor", True)
    if promote_to_governor:
        import shutil
        trades_src = root / "data" / "trade_logs" / "trades.csv"
        snapshots_src = root / "data" / "trade_logs" / "portfolio_snapshots.csv"
        trades_dst = root / "data" / "trade_logs" / "trades.csv"
        snapshots_dst = root / "data" / "trade_logs" / "portfolio_snapshots.csv"
        try:
            # Copy latest trades and snapshots to trade_logs directory
            shutil.copy2(trades_src, trades_dst)
            shutil.copy2(snapshots_src, snapshots_dst)
            print("[PROMOTE] Trades and portfolio snapshots promoted to governor.")
        except Exception as e:
            print(f"[PROMOTE][WARN] Could not promote trades/snapshots: {e}")
    else:
        print("[PROMOTE] Promotion to governor skipped by configuration.")

    # --- Ensure all logs are flushed and closed ---
    controller.logger.flush()
    controller.logger.close()

    # --- Results ---
    print(f"Backtest complete. Snapshots: {len(history)}")
    print("Trade log:", str(root / "data" / "trade_logs" / "trades.csv"))
    print("Portfolio snapshots:", str(root / "data" / "trade_logs" / "portfolio_snapshots.csv"))

    metrics = None

    # ✅ NEW BLOCK: Update governor with fresh trade results
    try:
        metrics = PerformanceMetrics(
            snapshots_path=str(root / "data" / "trade_logs" / "portfolio_snapshots.csv"),
            trades_path=str(root / "data" / "trade_logs" / "trades.csv"),
        )
        if not args.no_governor:
            governor.update_from_trades(metrics.trades, metrics.snapshots)
            governor.save_weights()
            print("[GOVERNOR] Edge weights updated and saved.")
        else:
            print("[GOVERNOR] Skipped by --no-governor.")
    except Exception as e:
        print(f"[GOVERNOR][WARN] Could not update governor or build metrics: {e}")

    if metrics is None:
        try:
            metrics = PerformanceMetrics(
                snapshots_path=str(root / "data" / "trade_logs" / "portfolio_snapshots.csv"),
                trades_path=str(root / "data" / "trade_logs" / "trades.csv"),
            )
        except Exception as e:
            print(f"[PERF][WARN] Could not initialize metrics fallback: {e}")
            metrics = None

    # --- Performance Summary ---
    print("\nCalculating performance metrics...")
    if metrics is not None and hasattr(metrics, "summary"):
        stats = metrics.summary()
    elif metrics is not None and hasattr(metrics, "summary_dict"):
        stats = metrics.summary_dict
    else:
        stats = {}

    print("\nPerformance Summary")
    for k, v in stats.items():
        print(f"{k}: {v}")

    # --- NEW: Export performance summary to JSON for research feedback loop ---
    try:
        import json
        from datetime import datetime
        perf_path = root / "data" / "research" / "performance_summary.json"
        perf_path.parent.mkdir(parents=True, exist_ok=True)
        # Add timestamp before writing stats
        stats["timestamp"] = datetime.utcnow().isoformat() + "Z"
        with open(perf_path, "w") as f:
            json.dump(stats, f, indent=2)
        print(f"[PERF] Performance summary exported to {perf_path}")
    except Exception as e:
        print(f"[PERF][WARN] Could not export performance summary: {e}")

    # --- NEW: Automatic feedback update and saving using governor ---
    try:
        if metrics is not None and not args.no_governor:
            governor.update_from_trades(metrics.trades, metrics.snapshots)
            governor.save_weights()
            print("[GOVERNOR] Feedback: Edge weights updated and saved after performance summary.")
        elif args.no_governor:
            print("[GOVERNOR] Feedback skipped by --no-governor.")
        else:
            print("[GOVERNOR][WARN] Skipped feedback because metrics are unavailable.")
    except Exception as e:
        print(f"[GOVERNOR][WARN] Could not update governor in feedback: {e}")

    # --- NEW: Automatically promote latest backtest run results from the most recent UUID folder ---
    try:
        import shutil

        trade_logs_dir = root / "data" / "trade_logs"
        # List all directories that look like UUIDs (assuming UUID format or any directory)
        candidate_dirs = [d for d in trade_logs_dir.iterdir() if d.is_dir()]
        if not candidate_dirs:
            print("[PROMOTE][WARN] No subdirectories found in data/trade_logs for promotion.")
        else:
            # Sort directories by modification time descending
            candidate_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
            latest_dir = candidate_dirs[0]
            trades_src = latest_dir / "trades.csv"
            snapshots_src = latest_dir / "portfolio_snapshots.csv"
            trades_dst = trade_logs_dir / "trades.csv"
            snapshots_dst = trade_logs_dir / "portfolio_snapshots.csv"
            if trades_src.exists() and snapshots_src.exists():
                shutil.copy2(trades_src, trades_dst)
                shutil.copy2(snapshots_src, snapshots_dst)
                print(f"[PROMOTE] Automatically promoted trades and portfolio snapshots from latest run folder '{latest_dir.name}' to top-level trade_logs directory.")
            else:
                print(f"[PROMOTE][WARN] Missing trades.csv or portfolio_snapshots.csv in latest run folder '{latest_dir.name}'. Promotion skipped.")
    except Exception as e:
        print(f"[PROMOTE][WARN] Automatic promotion of latest backtest results failed: {e}")

    return 0


if __name__ == "__main__":
    code = main()
    sys.exit(0 if code is None else code)