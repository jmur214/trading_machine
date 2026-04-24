import pandas as pd
import numpy as np
import joblib
import time
from pathlib import Path

# Model older than this is considered stale; confidence is neutralized so
# downstream position sizing doesn't propagate out-of-distribution predictions.
STALENESS_SECONDS = 30 * 24 * 3600
NEUTRAL_CONFIDENCE = 0.65

class SignalGate:
    """
    AI Component that 'gates' or filters trading signals based on
    learned market regimes. Uses a scikit-learn model.
    """
    def __init__(self, model_path="data/brain/signal_gate.joblib"):
        self.model_path = Path(model_path)
        self.model = None
        self.loaded = False
        self.stale = False
        self.model_age_days = None

    def load(self):
        """Load the trained model from disk."""
        if self.model_path.exists():
            try:
                self.model = joblib.load(self.model_path)
                self.loaded = True
                age_s = time.time() - self.model_path.stat().st_mtime
                self.model_age_days = age_s / 86400.0
                self.stale = age_s > STALENESS_SECONDS
                stale_tag = " [STALE — confidence will be neutralized]" if self.stale else ""
                print(f"[AI] SignalGate loaded from {self.model_path} (age={self.model_age_days:.1f}d){stale_tag}")
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
        
        # Volume: Ratio of current volume to 20-day average
        if "Volume" in data.columns:
            vol_curr = data["Volume"].iloc[-1]
            vol_avg = data["Volume"].rolling(20).mean().iloc[-1]
            vol_ratio = vol_curr / (vol_avg + 1e-9)
        else:
            vol_ratio = 1.0
            
        return np.array([[vol_20, trend_dist, mom_14, vol_ratio]]) # Shape (1, 4)

    def predict(self, signals, data_map):
        """
        Advisory scorer. Attaches 'gate_confidence' (0.0 to 1.0) to every
        signal and returns them all — Risk Engine handles sizing based on
        confidence. When the model is stale or features don't extract, a
        neutral confidence is attached so downstream sizing isn't biased.
        """
        if not self.loaded:
            return signals  # Pass-through if no model

        for sig in signals:
            ticker = sig.get("ticker")
            if ticker is None or ticker not in data_map:
                sig["gate_confidence"] = NEUTRAL_CONFIDENCE
                continue

            features = self.extract_features(ticker, data_map[ticker], sig)
            if features is None:
                sig["gate_confidence"] = NEUTRAL_CONFIDENCE
                continue

            if self.model and hasattr(self.model, "n_features_in_"):
                if features.shape[1] != self.model.n_features_in_:
                    # Feature schema drift — don't let stale model score this.
                    sig["gate_confidence"] = NEUTRAL_CONFIDENCE
                    continue

            try:
                prob_success = float(self.model.predict_proba(features)[0][1])
                if self.stale:
                    # Model is out-of-distribution; fall back to neutral.
                    sig["gate_confidence"] = NEUTRAL_CONFIDENCE
                    sig.setdefault("meta", {})["gate_stale_raw"] = prob_success
                else:
                    sig["gate_confidence"] = prob_success
            except Exception:
                sig["gate_confidence"] = NEUTRAL_CONFIDENCE

        return signals

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
