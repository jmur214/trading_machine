
import sys
import os
import pandas as pd
import numpy as np
from pathlib import Path

# Add project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.data_manager.data_manager import DataManager
from engines.engine_a_alpha.learning.signal_gate import SignalGate

def train_gate():
    root = Path(__file__).resolve().parents[1]
    trades_path = root / "data" / "trade_logs" / "trades.csv"
    
    if not trades_path.exists():
        print("[TRAIN] No trade history found. Run a backtest first.")
        return

    print(f"[TRAIN] Loading trade history from {trades_path}...")
    trades = pd.read_csv(trades_path)
    
    # Filter for closed trades or trades with realized PnL
    # If trades.csv logs fills, we need to reconstruct round-trips.
    # Assuming trades.csv contains 'pnl' column for exit rows or we derive it?
    # Actually, current metrics system outputs a 'trades.csv' that is likely a list of fills.
    # Let's check format. Standard 'PerformanceMetrics' output usually has 'pnl' on EXT fills.
    
    # However, easy way: Look for lines with 'realized_pnl' != 0
    # But better: Use the 'PerformanceMetrics' parser to get round-trip trades.
    from cockpit.metrics import PerformanceMetrics
    snapshots_path = root / "data" / "trade_logs" / "portfolio_snapshots.csv"
    metrics = PerformanceMetrics(trades_path=str(trades_path), snapshots_path=str(snapshots_path))
    completed_trades = metrics.trades # This is a DataFrame of round-trip trades
    
    if completed_trades.empty:
        print("[TRAIN] No completed trades to learn from.")
        return

    print(f"[TRAIN] Found {len(completed_trades)} completed trades.")
    
    dm = DataManager(cache_dir=str(root / "data" / "processed"))
    gate = SignalGate()
    
    # Sort trades by timestamp to ensure we can look back
    if 'timestamp' in completed_trades.columns:
        completed_trades['timestamp'] = pd.to_datetime(completed_trades['timestamp'])
        completed_trades = completed_trades.sort_values("timestamp")

    X = []
    y = []
    
    # Track open positions to pair entries with exits
    # Simple heuristic: for each PnL row (exit), find most recent entry
    
    valid_count = 0
    for idx, row in completed_trades.iterrows():
        # Only look at rows with Realized PnL (Exits)
        pnl = row.get('pnl')
        if pd.isna(pnl):
            continue
            
        exit_time = row['timestamp']
        ticker = row['ticker']
        
        # Find matching entry (most recent fill for this ticker before exit)
        # We assume 1-position-at-a-time (no hedging/scaling in simple mode)
        # Filter for same ticker, time < exit_time
        mask = (completed_trades['ticker'] == ticker) & (completed_trades['timestamp'] < exit_time)
        prev_trades = completed_trades[mask]
        
        if prev_trades.empty:
            continue
            
        # The entry is likely the last one
        entry_row = prev_trades.iloc[-1]
        entry_time = entry_row['timestamp']
        
        # Load market data
        df = dm.load_cached(ticker, "1d")
        if df is None or df.empty:
            continue
            
        # Slicing: Data UP TO entry_time
        slice_idx = df.index.searchsorted(entry_time)
        if slice_idx == 0: continue
        
        # This is the data available BEFORE the trade
        hist_df = df.iloc[:slice_idx] 
        
        if len(hist_df) < 50: continue
        
        # Mock signal dict as Gate expects it
        sig = {"ticker": ticker}
        
        features = gate.extract_features(ticker, hist_df, sig)
        if features is None: continue
        
        # Flatten (1, N) -> (N,)
        X.append(features[0])
        
        # Target: Did we make money?
        target = 1 if pnl > 0 else 0
        y.append(target)
        valid_count += 1
        
    if not X:
        print("[TRAIN] Could not extract features for any trades.")
        return
        
    print(f"[TRAIN] Extracted features for {valid_count} trades.")
    
    X_arr = np.array(X)
    y_arr = np.array(y)
    
    # Split
    split = int(len(X_arr) * 0.8)
    X_train, y_train = X_arr[:split], y_arr[:split]
    X_test, y_test = X_arr[split:], y_arr[split:]
    
    # Train
    # We use the Gate's internal train method if exposed, or just fit explicit clf
    # gate.train() only takes X, y.
    if gate.train(X_train, y_train):
        # Validate
        if len(X_test) > 0:
            preds = gate.model.predict(X_test)
            acc = np.mean(preds == y_test)
            print(f"[TRAIN] Calibration Accuracy (Holdout): {acc:.2%}")
            
            # Feature Importance
            try:
                imps = gate.model.feature_importances_
                print(f"[TRAIN] Feature Importances: {imps}")
            except: pass
            
        print("[TRAIN] Brain Upgrade Complete.")

if __name__ == "__main__":
    train_gate()
