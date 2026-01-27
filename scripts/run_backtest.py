import os
import sys
import importlib
from pathlib import Path
import pandas as pd
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




def run_backtest_logic(
    env="prod",
    mode="prod",
    fresh=False,
    no_governor=False,
    alpha_debug=False,
    override_start=None,
    override_end=None,
    override_params=None,  # Dict for injecting optimizer params e.g. {"lookback": 20}
    exact_edge_ids=None    # List of edge_ids to load exclusively (Isolation Mode)
):
    """
    Programmatic entry point for running a backtest.
    Allows overrides for optimization loops.
    """
    root = Path(__file__).resolve().parents[1]
    if alpha_debug:
        os.environ["ALPHA_DEBUG"] = "1"

    # --- Optional: Clear previous trade and snapshot logs if --fresh is used ---
    if fresh:
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
    # --- Load Configuration ---
    cfg_bt = load_json(str(root / "config" / "backtest_settings.json"))
    cfg_risk = load_json(str(root / f"config/risk_settings.{env}.json"))

    # allow overrides
    if override_start: cfg_bt["start_date"] = override_start
    if override_end: cfg_bt["end_date"] = override_end
    
    start = cfg_bt.get("start_date", "2024-01-01")
    end = cfg_bt.get("end_date", "2024-01-01")
    tickers = cfg_bt.get("tickers", ["AAPL"])
    timeframe = cfg_bt["timeframe"] # Keep existing timeframe
    init_cap = float(cfg_bt.get("initial_capital", 100000.0))

    # --- Setup Components ---
    from datetime import datetime, timedelta
    import pandas as pd # pandas is needed for pd.to_datetime
    
    # Parse simulation start for warmup calculation
    try:
        sim_start_dt = pd.to_datetime(start)
    except:
        sim_start_dt = pd.to_datetime("2024-01-01")
        
    # Fetch 365 days extra for warmup (indicators like SMA200 need history)
    # limit check: don't go before 2015 maybe? but providers handle it.
    fetch_start_dt = sim_start_dt - timedelta(days=365)
    fetch_start_str = fetch_start_dt.strftime("%Y-%m-%d")
    
    print(f"[RUN_BACKTEST] Warmup: Fetching data from {fetch_start_str} to enable indicators.")
    
    # We load data from fetch_start, but simulation runs from 'start'
    dm = DataManager(cache_dir=str(root / "data" / "processed"),
                     api_key=os.getenv("ALPACA_API_KEY"),
                     secret_key=os.getenv("ALPACA_SECRET_KEY"),
                     base_url=os.getenv("ALPACA_BASE_URL"))
    # 'data_map' loads explicitly from the warmup date
    data_map = dm.ensure_data(tickers, fetch_start_str, end, timeframe=timeframe)
    
    # 🌟 EDGE LOADING 🌟
    # If explicit 'target_status' is provided, load those. Default to 'active'.
    # If 'params' are overridden for a specific module, inject them.
    
    registry = EdgeRegistry()
    target_status = "active" # Default
    if alpha_debug: 
        # In alpha debug, maybe we want to see all? Or still just active.
        pass
    
    # Logic to handle "candidate" vs "active" loading will be controlled 
    # via the registry queries below.
    
    # Instantiate AlphaEngine
    # alpha = AlphaEngine() # This is moved down after edges are loaded
    
    # Load edges from registry
    # We allow the caller to specify which *set* of edges to run via kwarg, or default to active
    # For now, let's expose 'target_status' as an argument to run_backtest_logic if needed,
    # or just iterate manually if we are the optimizer.
    
    # But wait! The optimizer usually passes 'override_params'.
    # If we are running a standard backtest, we load "active".
    
    # Let's see what edges are requested.
    # For this refactor, we'll stick to 'active' by default, but logging which ones load.
    active_specs = registry.list(status="active")
    
    # If override_params contains keys that match candidate edges, we should try to load them too!
    # This is a bit tricky. The optimizer generally runs ONE specific configuration.
    
    # SIMPLIFICATION:
    # 🌟 EDGE LOADING 🌟
    registry = EdgeRegistry()
    loaded_edges = {}
    specs_to_load = {}

    if exact_edge_ids and len(exact_edge_ids) > 0:
        print(f"[RUN_BACKTEST] Isolation Mode: Loading exact edges {exact_edge_ids}")
        for eid in exact_edge_ids:
            spec = registry.get(eid) # registry.get handles lookup by ID
            if spec:
                specs_to_load[eid] = spec
            else:
                print(f"[RUN_BACKTEST] Edge ID {eid} not found in registry.")
    else:
        # Default Mode: Load Active
        active_specs = registry.list(status="active")
        for spec in active_specs:
            specs_to_load[spec.edge_id] = spec

        # 2. ALSO load any edge implied by `override_params` keys, even if candidate.
        if override_params:
            for edge_id_or_module_name in override_params.keys():
                 # Avoid trying to load "alpha" or config keys as edges
                 if edge_id_or_module_name in ["alpha", "risk", "portfolio"]:
                     continue
                     
                 spec = registry.get(edge_id_or_module_name)
                 if not spec:
                     # Try to find by module name matching
                     for s in registry.get_all_specs():
                         if s.module == edge_id_or_module_name:
                             spec = s
                             break
                 
                 if spec and spec.edge_id not in specs_to_load:
                     print(f"[RUN_BACKTEST] Injecting candidate/override edge {spec.edge_id} for testing.")
                     specs_to_load[spec.edge_id] = spec

    print(f"[RUN_BACKTEST] Loading {len(specs_to_load)} edges: {list(specs_to_load.keys())}")

    # Import and register
    for edge_id, spec in specs_to_load.items():
        mod_name = spec.module
        params = spec.params.copy() if spec.params else {}

        # INJECT OPTIMIZATION PARAMS
        if override_params:
            if edge_id in override_params:
                if isinstance(override_params[edge_id], dict):
                    params.update(override_params[edge_id])
                    if alpha_debug:
                        print(f"[RUN_BACKTEST] Overriding {edge_id} params: {override_params[edge_id]}")
            # Fallback for module-level overrides if needed
            elif mod_name in override_params and isinstance(override_params[mod_name], dict):
                params.update(override_params[mod_name])
        
        try:
            if "." in mod_name:
                mod = importlib.import_module(mod_name)
            else:
                mod = importlib.import_module(f"engines.engine_a_alpha.edges.{mod_name}")

            # Check if the module defines a subclassed Edge class with params
            edge_class = None
            for attr in dir(mod):
                if attr.lower().endswith("edge") and attr not in ["BaseEdge"]:
                     # Avoid importing imported classes like EdgeBase
                     val = getattr(mod, attr)
                     if hasattr(val, "__module__") and val.__module__ == mod.__name__:
                        edge_class = val
                        break
            
            # Fallback check if strict module match failed
            if edge_class is None:
                for attr in dir(mod):
                    if attr.lower().endswith("edge") and attr not in ["BaseEdge"]:
                        edge_class = getattr(mod, attr)
                        break

            if edge_class is not None:
                try:
                    loaded_edges[edge_id] = edge_class(params=params)
                except TypeError:
                    loaded_edges[edge_id] = edge_class()
            else:
                # Fallback if no specific Edge class is found, assume module itself is the edge
                loaded_edges[edge_id] = mod
            
            print(f"[ALPHA] Loaded edge '{edge_id}' with params: {params}")

        except Exception as e:
            print(f"[ALPHA][ERROR] Could not import edge module '{mod_name}': {e}")

    # Instantiate StrategyGovernor
    governor_state_path = root / "data" / "governor"
    if mode == "sandbox":
        governor_state_path = governor_state_path / "sandbox"
    governor_state_path.mkdir(parents=True, exist_ok=True)

    governor = StrategyGovernor(
        config_path=str(root / "config" / "governor_settings.json"),
        state_path=str(governor_state_path / "edge_weights.json"),
    )

    cfg_alpha = load_json(str(root / f"config/alpha_settings.{env}.json"))
    
    # Inject Alpha Config Overrides (e.g. thresholds) from override_params
    if override_params and "alpha" in override_params:
        for k, v in override_params["alpha"].items():
            cfg_alpha[k] = v
        print(f"[OPTIMIZER] Injected Alpha Config: {override_params['alpha']}")

    # --- Initialize engines ---
    edge_weights = {} # Initialize default weights
    alpha = AlphaEngine(
        edges=loaded_edges,
        edge_weights=edge_weights,
        config=cfg_alpha,
        debug=True,
        governor=governor,
    )
    risk = RiskEngine(cfg_risk)
    
    # Use a separate log dir for optimization runs to avoid polluting main logs?
    # For now, keep standard but maybe we should silence stdout if running in loop.
    cockpit = CockpitLogger(out_dir=str(root / "data" / "trade_logs"))

    exec_params = {
        "slippage_bps": float(cfg_bt.get("slippage_bps", 10.0)),
        "commission": float(cfg_bt.get("commission", 0.0)),
    }

    controller = BacktestController(
        data_map=data_map,
        alpha_engine=alpha,
        risk_engine=risk,
        cockpit_logger=cockpit,
        exec_params=exec_params,
        initial_capital=init_cap,
    )

    history = controller.run(start, end)
    
    # Flush Logger
    controller.logger.flush()
    controller.logger.close()
    
    # Calculate Metrics
    metrics = None
    try:
        metrics = PerformanceMetrics(
            snapshots_path=str(root / "data" / "trade_logs" / "portfolio_snapshots.csv"),
            trades_path=str(root / "data" / "trade_logs" / "trades.csv"),
        )
        if not no_governor:
            governor.update_from_trades(metrics.trades, metrics.snapshots)
            governor.save_weights()
    except Exception as e:
        print(f"[GOVERNOR][WARN] Could not update governor: {e}")

    # Return summary stats for the optimizer to use
    summary = {}
    if metrics:
        summary = metrics.summary_dict if hasattr(metrics, "summary_dict") else metrics.summary()
    
    # ALSO persist to file as usual for the main run usage
    try:
        import json
        from datetime import datetime
        perf_path = root / "data" / "research" / "performance_summary.json"
        perf_path.parent.mkdir(parents=True, exist_ok=True)
        summary["timestamp"] = datetime.utcnow().isoformat() + "Z"
        with open(perf_path, "w") as f:
            json.dump(summary, f, indent=2)
    except Exception:
        pass
        
    return summary

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

    # Call the logic function
    stats = run_backtest_logic(
        env=args.env,
        mode=args.mode,
        fresh=args.fresh,
        no_governor=args.no_governor,
        alpha_debug=args.alpha_debug
    )
    
    print("\nPerformance Summary")
    for k, v in stats.items():
        print(f"{k}: {v}")

    return 0



if __name__ == "__main__":
    code = main()
    sys.exit(0 if code is None else code)