
import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import MagicMock

from backtester.backtest_controller import BacktestController, BacktestParams
from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine
from engines.engine_b_risk.risk_engine import RiskEngine
from engines.engine_a_alpha.alpha_engine import AlphaEngine

from cockpit.logger import CockpitLogger

# Golden Path:
# 1. Buy Ticker A at $100.
# 2. Ticker A goes to $110.
# 3. Ticker A DATA VANISHES (Gap).
# 4. Ticker A comes back at $50 (Crash).
#
# EXPECTED BEHAVIOR (If Fixed):
# - Gap: Position should be closed (Panic Exit) or effectively managed. 
# - Equity: Should reflect the crash or cash out.
#
# ACTUAL BEHAVIOR (Buggy):
# - Bagholder: Position held through gap because AlphaEngine never sees it.
# - Vanity: During gap, Equity stays at $110 (or entry $100) because of avg_price fallback.

@pytest.fixture
def golden_data():
    # Generate 60 days of data (50 days warm up, then the Event)
    dates = pd.date_range("2023-11-01", periods=60, freq="D")
    
    # Base price 100 flat for 50 days
    opens = [100.0] * 50
    highs = [105.0] * 50
    lows = [95.0] * 50
    closes = [100.0] * 50
    
    # Event Sequence (Day 51-60)
    # 51: Buy Signal Trigger ($100)
    # 52: Hold ($110)
    # 53: GAP
    # 54: GAP
    # 55: Crash ($50)
    # ...
    
    opens.extend([100, 110, np.nan, np.nan, 50, 50, 50, 50, 50, 50])
    highs.extend([105, 115, np.nan, np.nan, 55, 55, 55, 55, 55, 55])
    lows.extend([95, 105, np.nan, np.nan, 45, 45, 45, 45, 45, 45])
    closes.extend([100, 110, np.nan, np.nan, 50, 50, 50, 50, 50, 50])
    
    df = pd.DataFrame({
        "Open": opens,
        "High": highs,
        "Low": lows,
        "Close": closes,
        "Volume": [1000] * 60
    }, index=dates)
    
    df_gapped = df.dropna()
    return {"GOLD": df_gapped}

def test_bagholder_and_vanity_bugs(golden_data):
    # Setup Engines
    alpha = MagicMock(spec=AlphaEngine)
    risk = RiskEngine({"min_bars_warmup": 0}) # Disable warmup for short test
    logger = MagicMock(spec=CockpitLogger)
    
    # Force a BUY signal on Day 1 (Index 1)
    # Alpha returns a list of signal dicts
    def mock_alpha_logic(slice_map, ts):
        # Trigger on Day 51 (start of event sequence)
        ts_str = str(ts)
        print(f"DEBUG: Mock Alpha Logic called at {ts_str}")
        if "2023-12-21" in ts_str: 
             print(f"DEBUG: TRIGGERING SIGNAL AT {ts} for GOLD")
             return [{"ticker": "GOLD", "signal": 1.0, "weight": 1.0, "meta": {}}]
        return []
    
    alpha.generate_signals.side_effect = mock_alpha_logic
    # alpha.compute_signals.return_value = [] # Removed invalid line
    
    # Run Backtest
    controller = BacktestController(
        data_map=golden_data,
        alpha_engine=alpha,
        risk_engine=risk,
        cockpit_logger=logger,
        exec_params={"commission": 0.0, "slippage_bps": 0.0},
        initial_capital=10000.0,
        bt_params=BacktestParams(verbose=True) 
    )
    
    start_dt = "2023-11-01"
    end_dt = "2024-01-10"
    
    print("\n--- STARTING GOLDEN PATH TEST ---\n")
    history = controller.run(start_dt, end_dt)
    
    # Check what happened at the end
    portfolio = controller.portfolio
    # Safely get position (if None, implies 0 qty but we need object)
    from engines.engine_c_portfolio.portfolio_engine import Position
    final_pos = portfolio.positions.get("GOLD", Position())
    
    print(f"\nFinal Position Qty: {final_pos.qty}")
    print(f"Final Portfolio Equity: {history[-1]['equity']}")
    
    # --- BUG 1: BAGHOLDER ASSERTION ---
    # If bug exists, we still hold the position because the gap prevented an exit signal
    # If fixed, we should have exited (due to forced check) or ideally Panic Exited.
    # For now, we EXPECT THE BUG to demonstrate it.
    assert final_pos.qty > 0, "Bug not reproduced! System somehow closed the position without data?"
    print("✅ Bagholder Bug Reproduced: Position is still open despite data blackout.")

    # --- BUG 2: VANITY ASSERTION ---
    # Check the snapshots during the gap.
    # Day 2 ($110) -> Equity should be ~10000 + (10 * 10) = 10100 (assuming 1 unit or similar sizing)
    # Day 5 ($50) -> Equity should drop.
    # But wait, without data, what does snapshot say?
    # If Vanity Bug exists, snapshot on gap days uses last known avg_price or simply repeats.
    
    # Let's look at equity curve
    equities = [snap['equity'] for snap in history]
    print(f"Equity Curve: {equities}")
    
    # If Vanity Bug is active, equity won't show the 'real' danger of the gap until price comes back
    # or it might show a straight line.
    
    # This test primarily reproduces the Bagholder state (stuck position).
    # The Vanity probe logs we added will confirm the "Using avg_price" logic in stdout.

if __name__ == "__main__":
    import sys
    sys.exit(pytest.main(["-v", __file__]))
