import numpy as np
import pandas as pd
import random
from typing import Dict, List, Tuple

class SyntheticMarketGenerator:
    """
    Generates realistic synthetic market data using Regime-Switching Geometric Brownian Motion.
    Simulates:
      1. Bull Market: Positive Drift, Low Volatility
      2. Bear Market: Negative Drift, High Volatility
      3. Sideways/Choppy: Zero Drift, Medium Volatility
    """
    
    REGIMES = {
        "bull": {"mu": 0.0005, "sigma": 0.010},    # ~12% annualized return, 16% vol
        "bear": {"mu": -0.001, "sigma": 0.025},    # ~-25% annualized, 40% vol
        "sideways": {"mu": 0.0, "sigma": 0.015}    # 0% return, 24% vol
    }
    
    TRANSITION_MATRIX = {
        # Current -> {Next: Prob}
        "bull": {"bull": 0.98, "sideways": 0.015, "bear": 0.005},
        "bear": {"bear": 0.95, "sideways": 0.04, "bull": 0.01},
        "sideways": {"sideways": 0.95, "bull": 0.025, "bear": 0.025}
    }

    def __init__(self, seed=None):
        if seed:
            np.random.seed(seed)
            random.seed(seed)

    def generate_price_history(self, days: int = 252, start_price: float = 100.0, start_date: str = "2020-01-01") -> pd.DataFrame:
        """
        Generates OHLCV Data.
        """
        dates = pd.date_range(start=start_date, periods=days, freq="D") # Use provided start date
        
        prices = [start_price]
        regimes = ["bull"] # Start in bull
        
        current_price = start_price
        current_regime = "bull"
        
        data = []
        
        for i in range(1, days):
            # 1. Determine Regime (Markov Chain)
            probs = self.TRANSITION_MATRIX[current_regime]
            next_regime = np.random.choice(list(probs.keys()), p=list(probs.values()))
            current_regime = next_regime
            
            # 2. Get Parameters
            params = self.REGIMES[current_regime]
            mu, sigma = params["mu"], params["sigma"]
            
            # 3. Simulate Daily Return (GBM)
            # r = mu + sigma * Z
            daily_ret = np.random.normal(mu, sigma)
            
            # 4. Update Price
            current_price = current_price * (1 + daily_ret)
            prices.append(current_price)
            regimes.append(current_regime)
            
            # 5. Generate OHLC (Simple approximations)
            # Open is close to prev close
            # High/Low based on today's volatility
            open_p = prices[-2] if i > 0 else start_price
            high_p = max(open_p, current_price) * (1 + abs(np.random.normal(0, sigma/2)))
            low_p = min(open_p, current_price) * (1 - abs(np.random.normal(0, sigma/2)))
            
            # Ensure logic
            high_p = max(high_p, current_price, open_p)
            low_p = min(low_p, current_price, open_p)
            
            vol = int(np.random.lognormal(15, 0.5)) # Random volume
            
            data.append({
                "Date": dates[i],
                "Open": open_p,
                "High": high_p,
                "Low": low_p,
                "Close": current_price,
                "Volume": vol,
                "Regime": current_regime
            })
            
        df = pd.DataFrame(data)
        if not df.empty:
            df.set_index("Date", inplace=True)
            
        return df

    def generate_fundamentals(self, price_df: pd.DataFrame) -> pd.DataFrame:
        """
        Generates consistent P/E, P/S data for the simulated price.
        Logic:
           - Earnings (EPS) grow smoothly-ish (with noise).
           - Price jumps (Regimes) cause P/E to expand/contract.
           - Allows testing 'Value Trap' logic (Price drops but EPS stays stable -> Low PE).
        """
        if price_df.empty:
            return pd.DataFrame()
            
        days = len(price_df)
        
        # Simulate EPS Trajectory (Independent of Price, mostly)
        # EPS Drift ~ 8% annualized
        eps_start = price_df["Close"].iloc[0] / 20.0 # Start at PE 20
        eps_drift = 0.08 / 252
        eps_vol = 0.005 # Earnings are smoother than price
        
        eps_series = [eps_start]
        for _ in range(days-1):
            change = np.random.normal(eps_drift, eps_vol)
            eps_series.append(eps_series[-1] * (1 + change))
            
        # Add quarterly "Jumps" (Earnings Surprise)
        # Every ~63 days
        for i in range(0, days, 63):
             shock = np.random.normal(0, 0.10) # +/- 10% surprise
             if i < len(eps_series):
                 eps_series[i] = eps_series[i] * (1 + shock)
                 # Propagate shock fwd
                 for j in range(i+1, days):
                     eps_series[j] = eps_series[j] * (1 + shock)
                     
        price_df["EPS_TTM"] = eps_series
        price_df["PE_Ratio"] = price_df["Close"] / price_df["EPS_TTM"]
        
        # Generate other metrics relatively
        price_df["Market_Cap"] = price_df["Close"] * 1000000 # Dummy shares
        price_df["PS_Ratio"] = price_df["PE_Ratio"] / 4.0 # Dummy margin logic
        price_df["Debt_to_Equity"] = 1.0 + np.random.normal(0, 0.1, days).cumsum() # Random walk debt
        
        return price_df[["PE_Ratio", "EPS_TTM", "Market_Cap", "PS_Ratio", "Debt_to_Equity"]]

if __name__ == "__main__":
    gen = SyntheticMarketGenerator()
    df = gen.generate_price_history(days=365)
    funds = gen.generate_fundamentals(df)
    
    print(f"Generated {len(df)} days.")
    print("Regimes:", df["Regime"].value_counts())
    print(funds.tail())
