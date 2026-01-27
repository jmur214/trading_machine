
import sys
import os
from pathlib import Path

# Add project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from orchestration.mode_controller import ModeController

def main():
    root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    print(f"[TEST] Initializing ModeController from {root}...")
    
    try:
        mc = ModeController(project_root=root)
        
        # Check Portfolio Config on Main Controller
        print(f"[TEST] ModeController.portfolio_cfg: {mc.portfolio_cfg}")
        print(f"[TEST] ModeController.portfolio_cfg.mode: {mc.portfolio_cfg.mode}")
        
        if mc.portfolio_cfg.mode == "mean_variance":
             print("[PASS] Portfolio Config Mode is 'mean_variance'")
        else:
             print(f"[FAIL] Portfolio Config Mode is '{mc.portfolio_cfg.mode}', expected 'mean_variance'")
             
        # Mock initialization of Paper Controller to verify pass-through
        # (We don't need to actually run it, just check the portfolio obj it creates)
        from orchestration.mode_controller import PaperTradeController, PaperParams
        
        print("[TEST] Initializing PaperTradeController...")
        paper = PaperTradeController(
            data_map={}, # Empty map is fine for init
            alpha_engine=mc.alpha,
            risk_engine=mc.risk,
            cockpit_logger=mc.cockpit,
            initial_capital=mc.init_cap,
            exec_params=mc.exec_params,
            paper_params=PaperParams(),
            portfolio_cfg=mc.portfolio_cfg
        )
        
        p_mode = paper.portfolio.policy.cfg.mode
        print(f"[TEST] PaperTradeController.portfolio.policy.cfg.mode: {p_mode}")
        
        if p_mode == "mean_variance":
            print("[PASS] PaperTradeController wired correctly!")
        else:
            print(f"[FAIL] PaperTradeController has mode '{p_mode}'")
            
    except Exception as e:
        print(f"[ERROR] {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
