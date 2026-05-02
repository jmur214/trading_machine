
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Any
import copy
import logging

from engines.engine_d_discovery.discovery import DiscoveryEngine
from backtester.backtest_controller import BacktestController
from engines.engine_a_alpha.alpha_engine import AlphaEngine
from engines.engine_b_risk.risk_engine import RiskEngine
from cockpit.logger import CockpitLogger

class WalkForwardOptimizer:
    """
    Tier 1 Research Feature: Walk-Forward Optimization (WFO).
    
    Purpose:
    --------
    To solve the "Consistency" problem. Strategies tuned on 2020 fail in 2021.
    WFO continuously re-tunes strategies on a sliding window.
    
    Process:
    --------
    | Train (12M) | Test (3M) | -> Roll forward 3M -> | Train (12M) | Test (3M) |
    
    This simulates "Adaptive Learning" over time.
    """
    
    def __init__(self, data_map: Dict[str, pd.DataFrame]):
        self.data_map = data_map
        self.logger = logging.getLogger("WFO")
        
    def run_optimization(self, strategy_spec: Dict[str, Any], 
                         start_date: str, 
                         train_months: int = 12, 
                         test_months: int = 3) -> Dict[str, Any]:
        """
        optimize parameters over rolling windows.
        """
        # Define Timeline
        full_timeline = pd.to_datetime(list(self.data_map.values())[0].index)
        start_dt = pd.to_datetime(start_date)
        
        # Align start — find closest index.  pandas 2.0 removed the
        # `method='nearest'` kwarg from Index.get_loc; use get_indexer instead.
        try:
            indexer = full_timeline.get_indexer([start_dt], method="nearest")
            start_idx = int(indexer[0]) if len(indexer) and indexer[0] != -1 else 0
        except Exception:
            start_idx = 0
             
        current_idx = start_idx

        # Results container.
        # `oos_returns` accumulates per-day RETURNS across windows, not raw
        # equity values. Stitching equity values across independent test
        # windows (each starting at $100k) produces phantom −4.76% returns
        # at every window boundary because pct_change() applied to the
        # concatenated equity sequence sees a step from window-N's last
        # equity (≈$105k) to window-(N+1)'s first equity ($100k). Phase 5
        # of the gauntlet architectural fix (2026-05-02) stitches returns
        # instead, which is the well-known WFO-trap fix.
        oos_returns: list = []
        param_history = []
        
        # Instantiate Edge Class only once to check params
        from importlib import import_module
        mod = import_module(strategy_spec["module"])
        cls_ = getattr(mod, strategy_spec["class"])
        base_edge = cls_()
        param_space = getattr(base_edge, "get_hyperparameter_space", lambda: {})()
        
        if not param_space:
            self.logger.warning("No hyperparams to optimize.")
            return {}

        total_steps = (len(full_timeline) - start_idx) // (test_months * 21) # approx
        
        print(f"[WFO] Starting Walk-Forward Optimization from {start_date}...")
        
        # Rolling Loop
        while True:
            # Define Windows
            train_end_idx = current_idx + (train_months * 21) # approx 21 trading days/mo
            test_end_idx = train_end_idx + (test_months * 21)
            
            if test_end_idx >= len(full_timeline):
                break
                
            train_start = full_timeline[current_idx]
            train_end = full_timeline[train_end_idx]
            test_start = full_timeline[train_end_idx] # gapless
            test_end = full_timeline[test_end_idx]
            
            print(f"  > Train: {train_start.date()} to {train_end.date()} | Test: {test_start.date()} to {test_end.date()}")
            
            # 1. OPTIMIZE (In-Sample)
            best_sharpe = -999
            best_params = {}
            
            # Simple Grid Search / Random Search (Mocked for speed in this MVP)
            # In production, use optuna. Here we sample 5 random configs.
            for i in range(5):
                # Sample params
                trial_params = base_edge.sample_params()
                
                # Run Backtest on Train Window
                res = self._quick_backtest(strategy_spec, trial_params, train_start, train_end)
                if res["sharpe"] > best_sharpe:
                    best_sharpe = res["sharpe"]
                    best_params = trial_params
            
            param_history.append({"date": test_start, "params": best_params, "is_sharpe": best_sharpe})
            
            # 2. VALIDATE (Out-of-Sample)
            # Run the winner on the Test window
            test_res = self._quick_backtest(strategy_spec, best_params, test_start, test_end)
            test_equity = test_res.get("equity_curve") or []
            if len(test_equity) >= 2:
                # Stitch RETURNS across windows, not equity values. Each
                # window's backtest starts fresh at $100k; appending equity
                # across windows would create phantom drawdowns at every
                # window boundary (window-N ends at e.g. $105k, window-(N+1)
                # starts at $100k → phantom −4.76% return). Returns are
                # window-internal so this concat is safe.
                window_returns = pd.Series(test_equity).pct_change().dropna().tolist()
                oos_returns.extend(window_returns)

            # Roll Forward
            current_idx += (test_months * 21)
            
        print("[WFO] Optimization Complete.")
        
        # Analyze Consistency
        # Did OOS Sharpe match In-Sample Sharpe?
        # Degradation Ratio
        if not param_history: 
            return {}
            
        avg_is_sharpe = np.mean([p["is_sharpe"] for p in param_history])

        # Calc OOS Sharpe from the stitched per-day return series.
        if len(oos_returns) > 1:
            ret = pd.Series(oos_returns).dropna()
            if ret.std() == 0:
                oos_sharpe = 0
            else:
                oos_sharpe = ret.mean() / ret.std() * np.sqrt(252)
        else:
            oos_sharpe = 0
            
        return {
            "is_sharpe_avg": avg_is_sharpe,
            "oos_sharpe": oos_sharpe,
            "degradation": oos_sharpe / avg_is_sharpe if avg_is_sharpe > 0 else 0,
            "param_stability": param_history
        }

    def _quick_backtest(self, spec, params, start, end):
        # Instantiate
        from importlib import import_module
        mod = import_module(spec["module"])
        cls_ = getattr(mod, spec["class"])
        edge = cls_()
        edge.set_params(params)
        
        alpha = AlphaEngine(edges={spec["edge_id"]: edge}, debug=False)
        risk = RiskEngine({"risk_per_trade_pct": 0.01}) # fixed
        
        # Filter Data Map for Speed? 
        # For MVP, pass full map, controller handles slicing via start/end strings
        
        logger = CockpitLogger(out_dir="/tmp/wfo", flush_each_fill=False)
        
        controller = BacktestController(
            data_map=self.data_map, 
            alpha_engine=alpha, 
            risk_engine=risk, 
            cockpit_logger=logger, 
            initial_capital=100_000,
            batch_flush_interval=99999
        )
        
        hist = controller.run(str(start.date()), str(end.date()))
        
        equity = [h["equity"] for h in hist]
        
        if len(equity) < 2: return {"sharpe": 0, "equity_curve": []}
        
        ret = pd.Series(equity).pct_change().dropna()
        if ret.std() == 0: return {"sharpe": 0, "equity_curve": equity}
        
        sharpe = ret.mean() / ret.std() * np.sqrt(252)
        return {"sharpe": sharpe, "equity_curve": equity}
