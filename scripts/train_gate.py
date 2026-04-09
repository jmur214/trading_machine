
import pandas as pd
import numpy as np
import sys
import os
from pathlib import Path

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engines.engine_d_research.learning.signal_gate import SignalGate

def train_gate_model():
    """
    Train the SignalGate model using harvested data.
    """
    print("[TRAIN_GATE] Starting Model Training...")
    
    data_path = Path("data/brain/training_data.csv")
    if not data_path.exists():
        print("[TRAIN_GATE] No training data found. Please run harvest_data.py first.")
        return
        
    try:
        df = pd.read_csv(data_path)
        if df.empty:
            print("[TRAIN_GATE] Training data is empty.")
            return
            
        print(f"[TRAIN_GATE] Loaded {len(df)} samples.")
        
        # Prepare X, y
        target_col = "target"
        feature_cols = [c for c in df.columns if c != target_col]
        
        X = df[feature_cols].values
        y = df[target_col].values
        
        # Train
        gate = SignalGate()
        success = gate.train(X, y)
        
        if success:
            print("[TRAIN_GATE] Model successfully trained and saved.")
        else:
            print("[TRAIN_GATE] Training failed.")
            
    except Exception as e:
        print(f"[TRAIN_GATE] Error: {e}")

if __name__ == "__main__":
    train_gate_model()
