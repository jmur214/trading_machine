import sys
import os
import pandas as pd
import glob
import yaml
from pathlib import Path
from typing import Dict, Any

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from brokers.shadow_broker import ShadowBroker
from engines.engine_d_research.feature_engineering import FeatureEngineer
from engines.engine_d_research.discovery import DiscoveryEngine
from engines.engine_a_alpha.edges.rule_based_edge import RuleBasedEdge
from engines.data_manager.fundamentals.loader import FundamentalLoader

def load_candidates(registry_path: str = "data/governor/edges.yml") -> Dict[str, RuleBasedEdge]:
    """
    Load 'Candidate' edges from the registry.
    """
    p = Path(registry_path)
    if not p.exists(): return {}
    
    try:
        data = yaml.safe_load(p.read_text())
        edges = data.get("edges", [])
        loaded = {}
        for count, spec in enumerate(edges):
            if spec.get("class") == "RuleBasedEdge":
                edge = RuleBasedEdge()
                edge.set_params(spec.get("params", {}))
                loaded[spec["edge_id"]] = edge
        return loaded
    except Exception as e:
        print(f"Error loading candidates: {e}")
        return {}

def run_shadow_session():
    print("--- 🌑 Starting Shadow Trading Session ---")
    
    # 1. Initialize
    broker = ShadowBroker(initial_capital=100000.0)
    discovery = DiscoveryEngine()
    fe = FeatureEngineer()
    fund_loader = FundamentalLoader()
    
    # 2. Load Data (Raw)
    data_dir = Path("data/raw")
    files = list(data_dir.glob("*_1d.csv"))
    
    if not files:
        print("No data files found in data/raw.")
        return

    # Map for current prices and DF storage
    current_prices = {}
    data_map = {}
    
    print(f"Loading {len(files)} tickers...")
    
    for f in files:
        sym = f.name.split("_")[0]
        try:
            df = pd.read_csv(f)
            
            # Normalize
            rename_map = {
                "timestamp": "Date", "open": "Open", "high": "High", 
                "low": "Low", "close": "Close", "volume": "Volume"
            }
            df = df.rename(columns=rename_map)
            if "Date" not in df.columns: continue
            
            df["Date"] = pd.to_datetime(df["Date"])
            df.set_index("Date", inplace=True)
            df = df.sort_index()
            
            # Compute Features ONCE
            # Ensure we have enough data
            if len(df) < 50: continue
            
            # Fundamentals
            fund_df = fund_loader.generate_point_in_time(sym, df)
            
            df = fe.compute_all_features(df, fund_df=fund_df)
            
            if df.empty: continue
            
            data_map[sym] = df
            current_prices[sym] = df.iloc[-1]["Close"]
            
        except Exception as e:
            pass # Silent fail for speed listing
            
    print(f"Data Loaded: {len(data_map)} valid tickers.")
    
    # 3. The Hunt (Discovery Phase)
    # in Prod, this might run weekly. Here we check if we need to hunt.
    # For now, ALWAYS hunt to demonstrate the loop.
    print("🔎 Running Discovery Scan (The Hunter)...")
    candidates_specs = discovery.hunt(data_map)
    
    if candidates_specs:
        print(f"Captured {len(candidates_specs)} new candidate rules!")
        discovery.save_candidates(candidates_specs)
    else:
        print("No new patterns found this session.")
        
    # 4. Load Candidates (Execution Phase)
    # We load ALL candidates from the registry to trade them.
    active_candidates = load_candidates()
    print(f"Loaded {len(active_candidates)} active candidate strategies for Shadow Trading.")
    
    if not active_candidates:
        print("No candidates to trade. Exiting.")
        return

    # 5. Execution Loop
    hits = 0
    
    for sym, df in data_map.items():
        # Check every candidate against every ticker
        # (Inefficient O(N*M), but fine for <100 strategies and <1000 tickers for now)
        
        for edge_id, edge in active_candidates.items():
            signal = edge.check_signal(df)
            
            if signal:
                direction = signal["signal"] # long/short
                conf = signal["confidence"]
                
                # In Shadow, we take the trade!
                # Simple Size: $5k per trade
                price = current_prices[sym]
                qty = 5000 // price
                
                if qty > 0:
                    print(f"[{sym}] 🎯 SIGNAL ({edge_id}): {signal['context']}")
                    broker.place_order(sym, "buy" if direction == "long" else "sell", qty, price=price)
                    hits += 1

    # 6. End of Session
    print(f"\nScanning Complete. Executed {hits} shadow trades.")
    
    # Mark to Market
    final_eq = broker.update_prices(current_prices)
    
    print("--- Session Summary ---")
    print(f"Total Equity: ${final_eq:.2f}")
    print(f"Cash:         ${broker.cash:.2f}")
    print("Positions:")
    for sym, qty in broker.get_positions().items():
        print(f"  - {sym}: {qty}")
        
    print("-----------------------")


if __name__ == "__main__":
    run_shadow_session()
