
from __future__ import annotations
import pandas as pd
import numpy as np
import json
import os
import logging
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from engines.engine_a_alpha.edge_base import EdgeBase
from engines.engine_a_alpha.edge_template import EdgeTemplate

# Setup Logger
logger = logging.getLogger("NEWS_EDGE")

class NewsSentimentEdge(EdgeBase, EdgeTemplate):
    """
    Advanced News Sentiment Edge (Phase 15).
    
    Features:
    1. Local Sentiment: VADER score of ticker-specific news.
    2. Macro Impact: Systemic news (War, Fed) mapped to Sector impact.
    3. Velocity: High news volume = High Volatility (Signal Damping).
    4. Momentum: Change in sentiment (Leading Indicator).
    
    Data Source:
    - data/intel/history/news_history_{tickers}_{date}.csv (Backtest)
    - Live feed (NewsCollector interaction - Future)
    """
    
    EDGE_ID = "news_sentiment_v2"
    EDGE_GROUP = "fundamental" # Or 'alternative'
    EDGE_CATEGORY = "sentiment"

    @classmethod
    def get_hyperparameter_space(cls):
        return {
            "lookback_window": {"type": "int", "min": 1, "max": 7}, # Days to look back for sentiment
            "min_velocity": {"type": "int", "min": 1, "max": 5}, # Min articles to trigger signal
            "macro_weight": {"type": "float", "min": 0.2, "max": 0.8}, # Weight of Macro vs Local
        }

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.data_cache = {} # (ticker, date_str) -> sentiment_score
        self.macro_cache = {} # (date_str) -> {sector: impact_score}
        self.velocity_cache = {} # (ticker, date_str) -> article_count
        
        self.sector_map = self._load_sector_map()
        self.macro_config = self._load_macro_config()
        self.history_loaded = False
        
        # Paths
        self.history_dir = Path("data/intel/history")
    
    def _load_sector_map(self) -> Dict[str, str]:
        try:
            with open("config/sector_map.json", "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load sector_map: {e}")
            return {}

    def _load_macro_config(self) -> Dict:
        try:
            with open("config/macro_impact.json", "r") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load macro_impact: {e}")
            return {}

    def _load_history_lazy(self):
        """
        Loads all CSVs in data/intel/history/ into memory structures.
        Optimized for backtesting (pre-loading).
        """
        if self.history_loaded:
            return

        csv_files = list(self.history_dir.glob("news_history_*.csv"))
        if not csv_files:
            return

        all_news = []
        for f in csv_files:
            try:
                df = pd.read_csv(f)
                if 'published' in df.columns:
                    df['date'] = pd.to_datetime(df['published']).dt.date
                    all_news.append(df)
            except Exception as e:
                logger.error(f"Error reading {f}: {e}")
        
        if not all_news:
            self.history_loaded = True
            return

        full_df = pd.concat(all_news, ignore_index=True)
        
        # --- PRE-COMPUTE: Macro Impact per Day ---
        dates = full_df['date'].unique()
        for d in dates:
            d_str = str(d)
            daily_news = full_df[full_df['date'] == d]
            sector_scores = {}
            
            for _, row in daily_news.iterrows():
                txt = (str(row.get('title', '')) + " " + str(row.get('summary', ''))).lower()
                for category, rules in self.macro_config.items():
                    keywords = rules.get("keywords", [])
                    impacts = rules.get("impact", {})
                    if any(kw in txt for kw in keywords):
                        for sec, imp in impacts.items():
                            sector_scores[sec] = sector_scores.get(sec, 0.0) + imp
            self.macro_cache[d_str] = sector_scores

        # --- PRE-COMPUTE: Local Ticker Sentiment ---
        # Expanded matching for common names
        name_map = {
            "AAPL": ["APPLE", "IPHONE", "MAC"],
            "MSFT": ["MICROSOFT", "AZURE", "WINDOWS"],
            "GOOGL": ["GOOGLE", "ALPHABET"],
            "AMZN": ["AMAZON", "AWS"],
            "TSLA": ["TESLA", "MUSK", "CYBERTRUCK"],
            "META": ["FACEBOOK", "INSTAGRAM"],
            "NFLX": ["NETFLIX"],
            "NVDA": ["NVIDIA"],
            "BA": ["BOEING"],
        }

        for _, row in full_df.iterrows():
            d_str = str(row['date'])
            txt_upper = (str(row.get('title', '')) + " " + str(row.get('summary', ''))).upper()
            score = float(row.get('sentiment', 0.0))
            if pd.isna(score): continue
            
            candidates = str(row.get('tickers', '')).split(',')
            
            for cand in candidates:
                cand = cand.strip().upper()
                if not cand: continue
                
                # Check Ticker OR Aliases
                aliases = [cand] + name_map.get(cand, [])
                is_match = False
                
                # If only 1 ticker in the row, assume it matches (implicit attribution)
                if len(candidates) == 1:
                    is_match = True
                else:
                    for a in aliases:
                        if a in txt_upper:
                           is_match = True
                           break
                
                if is_match:
                    key = (cand, d_str)
                    if key not in self.data_cache:
                        self.data_cache[key] = []
                    self.data_cache[key].append(score)
                    self.velocity_cache[key] = self.velocity_cache.get(key, 0) + 1

        self.history_loaded = True
        logger.info(f"Loaded {len(full_df)} news items. Cache keys: {len(self.data_cache)}")

    def compute_signals(self, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp) -> Dict[str, float]:
        """
        Compute normalized signal (-1.0 to 1.0) for each ticker.
        """
        self._load_history_lazy()
        
        scores = {}
        date_str = str(now.date())
        
        # Hyperparams
        lookback = self.params.get("lookback_window", 3)
        macro_wt = self.params.get("macro_weight", 0.5)
        local_wt = 1.0 - macro_wt
        min_vel = self.params.get("min_velocity", 1)

        # Pre-fetch Macro Impact for today
        today_macro = self.macro_cache.get(date_str, {})
        
        for ticker in data_map.keys():
            sector = self.sector_map.get(ticker, "Unknown")
            
            # 1. Macro Score
            # Sum of impacts for this sector today
            # We might want to lookback here too? For now, spot impact.
            macro_raw = today_macro.get(sector, 0.0)
            macro_score = np.clip(macro_raw, -1.0, 1.0) # Normalize
            
            # 2. Local Score (Lookback Avg)
            local_scores = []
            velocity_sum = 0
            
            # Scan lookback window
            for i in range(lookback):
                d = (now - timedelta(days=i)).date()
                d_s = str(d)
                
                # key
                k = (ticker, d_s)
                
                # Sentiment
                if k in self.data_cache:
                   local_scores.extend(self.data_cache[k])
                
                # Velocity
                velocity_sum += self.velocity_cache.get(k, 0)

            if not local_scores and macro_raw == 0.0:
                # No news, neutral
                scores[ticker] = 0.0
                continue
                
            local_avg = np.mean(local_scores) if local_scores else 0.0
            
            # 3. Momentum (Current Day vs Lookback Avg)
            # If today's score > avg of past N days
            # Simplified: Local Avg already captures 'current state'.
            # Momentum would require splitting Today vs Past. 
            # For MVP V2, let's stick to the weighted score.
            
            # 4. Velocity Impact
            # If velocity is HUGE -> High Vol -> Dampen signal? Or amplify?
            # User said: "High Volatility Regime". Use it as a risk signal?
            # Here we are outputting Directional Alpha.
            # If sentiment is -0.8 and Velocity is HIGH -> Confidence should be HIGH (Strong Crash).
            # If sentiment is 0.0 and Velocity is HIGH -> Ambiguity (Risk).
            
            velocity_mult = 1.0
            if velocity_sum > (min_vel * 3): # Spike
                velocity_mult = 1.2 # Boost conviction on high volume news
            elif velocity_sum < min_vel and not local_scores:
                velocity_mult = 0.0 # Ignore if noise
            
            # 5. Final Blend
            # If no local news, rely purely on macro? 
            # Or dampen macro if no specific news? 
            # Let's allow Macro to drive if it's strong.
            
            final_raw = (local_avg * local_wt) + (macro_score * macro_wt)
            final_score = np.clip(final_raw * velocity_mult, -1.0, 1.0)
            
            # Clean tiny values
            if abs(final_score) < 0.1:
                final_score = 0.0
                
            scores[ticker] = float(final_score)
            
        return scores

    def generate_signals(self, data_map, as_of):
        # Standard wrapper
        scores = self.compute_signals(data_map, as_of)
        signals = []
        for t, s in scores.items():
            if s == 0.0: continue
            
            side = "long" if s > 0 else "short"
            signals.append({
                "ticker": t,
                "side": side,
                "strength": abs(s),
                "edge_id": self.EDGE_ID,
                "edge_group": self.EDGE_GROUP,
                "edge_category": self.EDGE_CATEGORY,
                "meta": {
                    "explain": f"News Sentiment: {s:.2f} (Macro+Local)",
                    "raw_score": s
                }
            })
        return signals
