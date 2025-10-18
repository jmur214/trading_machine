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

# ✅ NEW: import StrategyGovernor
from engines.engine_d_research.governor import StrategyGovernor


def main():
    root = Path(__file__).resolve().parents[1]

    # --- Load configuration files ---
    cfg_bt = load_json(str(root / "config" / "backtest_settings.json"))
    cfg_risk = load_json(str(root / "config" / "risk_settings.json"))
    cfg_edges = load_json(str(root / "config" / "edge_config.json"))

    tickers = cfg_bt["tickers"]
    start = cfg_bt["start_date"]
    end = cfg_bt["end_date"]
    timeframe = cfg_bt["timeframe"]
    init_cap = float(cfg_bt["initial_capital"])

    # --- Prepare data ---
    dm = DataManager(cache_dir=str(root / "data" / "processed"))
    data_map = dm.ensure_data(tickers, start, end, timeframe=timeframe)

    # --- Load active edges dynamically ---
    edges = {}
    edge_weights = cfg_edges.get("edge_weights", {})
    active_edges = cfg_edges.get("active_edges", [])

    for edge_name in active_edges:
        try:
            mod = importlib.import_module(f"engines.engine_a_alpha.edges.{edge_name}")
            edges[edge_name] = mod
        except Exception as e:
            print(f"[ALPHA][ERROR] Could not import edge '{edge_name}': {e}")

    print(f"[ALPHA] Loaded {len(edges)} edges: {list(edges.keys())}")

    # ✅ NEW: Instantiate the StrategyGovernor
    governor = StrategyGovernor(
        config_path=str(root / "config" / "governor_settings.json"),
        state_path=str(root / "data" / "governor" / "edge_weights.json"),
    )

    # --- Initialize engines ---
    alpha = AlphaEngine(
        edges=edges,
        edge_weights=edge_weights,
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

    # --- Results ---
    print(f"Backtest complete. Snapshots: {len(history)}")
    print("Trade log:", str(root / "data" / "trade_logs" / "trades.csv"))
    print("Portfolio snapshots:", str(root / "data" / "trade_logs" / "portfolio_snapshots.csv"))

    # ✅ NEW BLOCK: Update governor with fresh trade results
    try:
        metrics = PerformanceMetrics(
            snapshots_path=str(root / "data" / "trade_logs" / "portfolio_snapshots.csv"),
            trades_path=str(root / "data" / "trade_logs" / "trades.csv"),
        )
        governor.update_from_trades(metrics.trades, metrics.snapshots)
        governor.save_weights()
        print("[GOVERNOR] Edge weights updated and saved.")
    except Exception as e:
        print(f"[GOVERNOR][WARN] Could not update governor: {e}")

    # --- Performance Summary ---
    print("\nCalculating performance metrics...")
    if hasattr(metrics, "summary"):
        stats = metrics.summary()
    elif hasattr(metrics, "summary_dict"):
        stats = metrics.summary_dict
    else:
        stats = {}

    print("\nPerformance Summary")
    for k, v in stats.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    sys.exit(main())