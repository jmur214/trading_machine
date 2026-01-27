
# seed_governor_data.py
import json
import random
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

GOV_DIR = Path("data/governor")
GOV_DIR.mkdir(parents=True, exist_ok=True)

def run():
    print("Seeding Governor Data...")
    
    # 1. Load existing edge weights if available to keep consistency
    weights_path = GOV_DIR / "edge_weights.json"
    if weights_path.exists():
        with open(weights_path) as f:
            w_data = json.load(f)
            weights = w_data.get("weights", {})
    else:
        # Fallback seeded weights
        weights = {
            "rsi_bounce_v1": 0.25,
            "trend_follow_v1": 0.20,
            "mean_reversion_v1": 0.15,
            "volatility_breakout_v1": 0.10,
            "momentum_alpha": 0.30
        }

    # Filter out near-zero weights for cleaner appearance
    active_weights = {k: v for k, v in weights.items() if v > 0.001}
    # Normalize to 1.0
    total = sum(active_weights.values())
    if total > 0:
        active_weights = {k: v/total for k, v in active_weights.items()}
    
    # 2. Generate Metrics
    metrics = {}
    for edge in active_weights:
        # Synthetic SR correlated with weight (governor logic often allocates more to high SR)
        # Add some noise
        base_sr = 1.0 + (active_weights[edge] * 2.0) # Higher weight ~ higher SR
        sr = max(0.2, np.random.normal(base_sr, 0.3))
        
        metrics[edge] = {
            "sr": round(sr, 2),
            "win_rate": round(random.uniform(0.45, 0.65), 2),
            "trade_count": random.randint(50, 500),
            "mdd": round(random.uniform(-0.25, -0.05), 3),
            "last_trade": datetime.now(timezone.utc).isoformat()
        }

    # 3. Generate Recommendations
    recommendations = {}
    for edge in active_weights:
        # Suggest slight changes
        current = active_weights[edge]
        change = random.uniform(-0.05, 0.05)
        suggested = max(0.01, current + change)
        recommendations[edge] = {
            "current": round(current, 3),
            "suggested": round(suggested, 3),
            "reason": "Improved Sharpe" if change > 0 else "Volatility Penalty"
        }

    # 4. Construct System State
    system_state = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "total_strategies": len(active_weights),
            "active_strategies": len(active_weights),
            "portfolio_sharpe": 1.45, # Synthetic
        },
        "weights": active_weights,
        "metrics": metrics,
        "recommendations": recommendations 
    }

    # Write files
    (GOV_DIR / "system_state.json").write_text(json.dumps(system_state, indent=2))
    
    # Also update allocation.json for legacy if needed (though we switched to sector)
    (GOV_DIR / "allocation.json").write_text(json.dumps(active_weights, indent=2))

    print(f"Seeded system_state.json with {len(active_weights)} strategies.")

if __name__ == "__main__":
    run()
