
import sys
import os
from engines.engine_d_research.discovery import DiscoveryEngine

def validate_discovery_vocabulary():
    print("--- Phase 3: Validating Discovery Vocabulary ---")
    disc = DiscoveryEngine()
    
    # Generate 20 candidates to maximize chance of seeing new features
    print("Generating 20 Candidates...")
    candidates = disc.generate_candidates(n_mutations=20)
    
    found_regime = False
    found_rank = False
    found_new_math = False
    
    new_indicators = ["sma_cross", "residual_momentum", "donchian_breakout", "pivot_position"]
    
    for c in candidates:
        # Check composite genomes (params.genes)
        if "genes" in c["params"]:
            genes = c["params"]["genes"]
            for g in genes:
                # Check Regime
                if g.get("type") == "regime":
                    found_regime = True
                    print(f"✅ Found Regime Gene: {g}")
                
                # Check Rank
                op = g.get("operator", "")
                if "percentile" in op:
                    found_rank = True
                    print(f"✅ Found Ranking Logic: {op}")
                    
                # Check New Math
                ind = g.get("indicator")
                if ind in new_indicators:
                    found_new_math = True
                    print(f"✅ Found New Math: {ind}")
                    
    print("\n--- Summary ---")
    print(f"Regime Awareness: {'YES' if found_regime else 'NO'}")
    print(f"Cross-Sectional Ranking: {'YES' if found_rank else 'NO'}")
    print(f"Advanced Math (Residual/SMA/Donchian): {'YES' if found_new_math else 'NO'}")
    
    if found_regime and found_rank and found_new_math:
        print("PHASE 3 DISCOVERY VALIDATED.")
    else:
        print("WARNING: Some features not found (random chance?). Run again.")

if __name__ == "__main__":
    validate_discovery_vocabulary()
