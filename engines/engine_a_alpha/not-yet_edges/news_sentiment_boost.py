# engines/engine_a_alpha/edges/news_sentiment_boost.py
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta
from typing import Dict, List
from debug_config import is_debug_enabled

EDGE_NAME = "news_sentiment_boost"
EDGE_GROUP = "news"

# Optional mapping for sector-level boosts
SECTOR_MAP = {
    "energy": ["XLE"],
    "defense": ["ITA"],
    "technology": ["XLK"],
    "finance": ["XLF"],
}

def load_news_snapshot(path: str | Path = "data/news_snapshot.json") -> List[dict]:
    """Load latest normalized news snapshot file (if exists)."""
    path = Path(path)
    if not path.exists():
        return []
    try:
        with open(path, "r") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception as e:
        if is_debug_enabled("NEWS_EDGE"):
            print(f"[NEWS_EDGE][DEBUG] Failed to load snapshot: {e}")
        return []


def generate_signals(df_map: Dict[str, pd.DataFrame],
                     now: pd.Timestamp,
                     cfg: Dict[str, float] | None = None) -> List[dict]:
    """
    Emit sentiment boost signals for tickers with positive recent news.

    cfg options:
      - min_sentiment: float, threshold to trigger boost (default 0.3)
      - lookback_hours: how far back to look (default 12)
      - decay_hours: how long before strength decays to 0 (default 12)
    """
    cfg = cfg or {}
    min_sent = cfg.get("min_sentiment", 0.3)
    lookback_h = cfg.get("lookback_hours", 12)
    decay_h = cfg.get("decay_hours", 12)

    now_dt = pd.Timestamp(now).to_pydatetime()
    cutoff = now_dt - timedelta(hours=lookback_h)
    news = load_news_snapshot()

    if not news:
        if is_debug_enabled("NEWS_EDGE"):
            print(f"[NEWS_EDGE][DEBUG] No news snapshot found or empty at {now}")
        return []

    signals = []
    for item in news:
        try:
            ts = datetime.fromisoformat(item.get("timestamp"))
            if ts < cutoff:
                continue

            tickers = item.get("tickers", [])
            headline = item.get("headline", "").lower()
            sentiment = float(item.get("sentiment", 0.0))
            if abs(sentiment) < min_sent:
                continue

            # Sector keyword mapping (optional)
            for sector, etfs in SECTOR_MAP.items():
                if sector in headline:
                    tickers.extend(etfs)

            # Remove duplicates
            tickers = list(set(tickers))

            # Decay with time
            age_h = (now_dt - ts).total_seconds() / 3600.0
            decay_factor = max(0.0, 1.0 - age_h / decay_h)
            strength = float(np.clip(abs(sentiment) * decay_factor, 0, 1))

            for t in tickers:
                sig = {
                    "ticker": t,
                    "side": "long" if sentiment > 0 else "short",
                    "strength": strength,
                    "edge": EDGE_NAME,
                    "edge_group": EDGE_GROUP,
                    "meta": {
                        "sentiment": sentiment,
                        "age_hours": round(age_h, 2),
                        "decay_factor": round(decay_factor, 3),
                        "source": item.get("source", "unknown"),
                        "headline": item.get("headline", "")[:120],
                    },
                }
                signals.append(sig)

                if is_debug_enabled("NEWS_EDGE"):
                    print(f"[NEWS_EDGE][DEBUG] {t} sentiment={sentiment:.2f} "
                          f"age={age_h:.1f}h decay_factor={decay_factor:.2f} "
                          f"strength={strength:.2f}")

        except Exception as e:
            if is_debug_enabled("NEWS_EDGE"):
                print(f"[NEWS_EDGE][DEBUG] Skipped invalid item: {e}")
            continue

    if not signals and is_debug_enabled("NEWS_EDGE"):
        print(f"[NEWS_EDGE][DEBUG] No signals emitted at {now}")

    return signals