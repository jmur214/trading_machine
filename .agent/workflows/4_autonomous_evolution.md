---
description: Run the Autonomous Evolution Cycle (Machine Learning Loop)
---

This workflow triggers the "Brain" of the system to proactively learn and upgrade itself.

Steps:
1. **Initialize the Research Environment**: Loads historical data and Discovery Engine.
2. **Generate Mutations**: Uses Genetic Algorithms to spawn 10-50 new strategy variations (Mutants).
3. **Survivor Validation**:
   - Runs **Backtest** (Profit Check).
   - Runs **Robustness Check** (Parallel Universe PBO Check).
   - Runs **Sortino Check** (Upside "Skyrocket" Potential).
4. **Consistency Verification**:
   - Runs **Walk-Forward Optimization** to ensure the strategy didn't just get lucky.
5. **Promotion**:
   - If a mutant survives all checks, it is PROMOTED to `config/edge_config.json`.
   - The next time you run `Live` or `Paper`, this new strategy will be active.

**How to Run**:
```bash
# Run a small batch (fast)
python scripts/run_evolution_cycle.py

# To run a large batch, edit the script to n_candidates=50
```

**Outcome**:
Check `config/edge_config.json` after the run. You should see new, evolved strategies (e.g., `rsi_long_mut_a1b2`) added with optimized weights.
