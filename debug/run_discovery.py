
from engines.engine_d_research.discovery import DiscoveryEngine
print("Running Discovery Engine...")
disc = DiscoveryEngine()
cands = disc.generate_candidates(n_mutations=3)
disc.save_candidates(cands)
