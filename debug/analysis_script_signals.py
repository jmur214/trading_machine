# analysis_script_signals.py
import pandas as pd
import sys

print("--- Analysis: Signal Silence Probe ---")

# Load Trades
try:
    trades = pd.read_csv("data/trade_logs/trades.csv")
    trades['timestamp'] = pd.to_datetime(trades['timestamp'])
except FileNotFoundError:
    print("No trades found.")
    sys.exit(0)

print(f"Total Trades: {len(trades)}")

# Filter for AAPL
aapl_trades = trades[trades['ticker'] == 'AAPL'].sort_values('timestamp')
print(f"\nAAPL Trades ({len(aapl_trades)}):")
print(aapl_trades[['timestamp', 'side', 'qty', 'fill_price', 'edge']])

# Calculate net position
net_pos = 0
for _, row in aapl_trades.iterrows():
    if row['side'] == 'short':
        net_pos -= row['qty']
    elif row['side'] in ['cover', 'exit', 'buy']:
         # Assuming 'exit' or 'buy' closes short for this simplified view, 
         # but rigorous logic depends on if it was opening a long or closing short. 
         # 'risk_engine' uses 'exit' to close.
         if net_pos < 0: # covering
             net_pos += row['qty']
         else: # going long
             net_pos += row['qty']

print(f"\nNet AAPL Position according to Trades log: {net_pos}")

# If net pos is not zero, analyze snapshots to see if it persisted
if net_pos != 0:
    print("\nChecking Portfolio Snapshots for persistence...")
    try:
        snap = pd.read_csv("data/trade_logs/portfolio_snapshots.csv")
        snap['timestamp'] = pd.to_datetime(snap['timestamp'])
        
        # Check last few snapshots for 'positions' count or specific metadata if available
        # (CSV snapshot schema is limited, but we can verify equity drag)
        last_snaps = snap.tail(5)
        print("Last 5 Snapshots:")
        print(last_snaps[['timestamp', 'equity', 'market_value', 'positions']])
        
        if last_snaps['market_value'].iloc[-1] != 0:
             print("ALERT: Non-zero Market Value at end of backtest confirms position was held.")
    except Exception as e:
        print(f"Snapshot analysis failed: {e}")
