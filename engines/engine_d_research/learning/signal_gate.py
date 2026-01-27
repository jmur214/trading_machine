import pandas as pd
import numpy as np
import joblib
from pathlib import Path

class SignalGate:
    """
    AI Component that 'gates' or filters trading signals based on 
    learned market regimes. Uses a scikit-learn model.
    """
    def __init__(self, model_path="data/brain/signal_gate.joblib"):
        self.model_path = Path(model_path)
        self.model = None
        self.loaded = False
        
    def load(self):
        """Load the trained model from disk."""
        if self.model_path.exists():
            try:
                self.model = joblib.load(self.model_path)
                self.loaded = True
                print(f"[AI] SignalGate loaded from {self.model_path}")
            except Exception as e:
                print(f"[AI] Failed to load model: {e}")
        else:
            print(f"[AI] No model found at {self.model_path}. Gate allows all.")

    def extract_features(self, ticker, data, signal_details):
        """
        Convert current market state into a feature vector.
        Features must match training time exactly.
        
        Args:
            ticker (str): Symbol
            data (pd.DataFrame): Historical data up to T (Open, High, Low, Close)
            signal_details (dict): Metadata about the signal (e.g. edge_id)
            
        Returns:
            np.array: Feature vector (1, N_features)
        """
        # --- Feature Engineering ---
        # 1. Volatility (ATR-like)
        # 2. Trend (SMA-distance)
        # 3. Momentum (RSI)
        
        if len(data) < 50:
            return None
            
        close = data["Close"]
        
        # Volatility: StdDev of last 20 returns
        returns = close.pct_change()
        vol_20 = returns.rolling(20).std().iloc[-1]
        
        # Trend: Distance from SMA50
        sma_50 = close.rolling(50).mean().iloc[-1]
        trend_dist = (close.iloc[-1] / (sma_50 + 1e-9)) - 1.0
        
        # Momentum: Simple ROC 14
        mom_14 = (close.iloc[-1] / (close.iloc[-14] + 1e-9)) - 1.0
        
        return np.array([[vol_20, trend_dist, mom_14]]) # Shape (1, 3)

    def predict(self, signals, data_map):
        """
        Filter a list of signals.
        
        Args:
            signals (list): List of signal dicts from AlphaEngine
            data_map (dict): Current market data snapshot
            
        Returns:
            list: Filtered/Modified signals
        """
        if not self.loaded:
            return signals # Pass-through if no model
            
        approved_signals = []
        for sig in signals:
            ticker = sig["ticker"]
            if ticker not in data_map:
                continue
                
            features = self.extract_features(ticker, data_map[ticker], sig)
            if features is None or features.shape[1] != 3: # Safety check
                approved_signals.append(sig)
                continue
                
            try:
                # Predict Probability of Success (Class 1)
                prob_success = self.model.predict_proba(features)[0][1]
                
                # Thresholding logic
                # If model is < 50% confident, kill the signal
                if prob_success > 0.5:
                    # Optional: boost confidence if model is very sure
                    approved_signals.append(sig)
                else:
                    # GATED
                    # print(f"[AI] Rejected {ticker} signal (Prob: {prob_success:.2f})")
                    pass
            except Exception as e:
                # Fallback
                approved_signals.append(sig)
                
        return approved_signals

    def train(self, X, y):
        """
        Train a new model.
        Args:
            X (np.array): Feature matrix
            y (np.array): Target vector (1=Profit, 0=Loss)
        """
        try:
            from sklearn.ensemble import RandomForestClassifier
            clf = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
            clf.fit(X, y)
            self.model = clf
            self.loaded = True
            
            # Save
            self.model_path.parent.mkdir(parents=True, exist_ok=True)
            joblib.dump(clf, self.model_path)
            print(f"[AI] Trained and saved model to {self.model_path}")
            return True
        except ImportError:
            print("[AI][ERROR] scikit-learn not installed. Cannot train.")
            return False
