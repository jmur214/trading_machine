---
description: Run the Autonomous Evolution Cycle (Discovery + GA + Validation)
---

This workflow triggers Engine D's discovery pipeline to hunt for new edges, evolve composite genomes, and validate candidates through the 4-gate pipeline.

Steps:
1. **Regime Detection**: Engine E detects current market regime (trend, volatility, correlation).
2. **Feature Engineering**: Computes 40+ features across 7 categories (technical, fundamental, calendar, microstructure, inter-market, regime, cross-sectional).
3. **Pattern Hunting**: Two-stage ML pipeline — LightGBM screens for important features, shallow decision tree extracts interpretable rules.
4. **Genetic Evolution**: GA cycle on CompositeEdge population — tournament selection, crossover, mutation, elitism. Population persists in `data/governor/ga_population.yml`.
5. **4-Gate Validation**:
   - **Gate 1 — Backtest**: Sharpe > 0 (cheap filter).
   - **Gate 2 — PBO Robustness**: 50 synthetic paths, survival rate > 0.7.
   - **Gate 3 — WFO Degradation**: OOS Sharpe >= 60% of IS Sharpe.
   - **Gate 4 — Significance**: Monte Carlo permutation test p-value < 0.05.
6. **Promotion**: Candidates passing ALL gates are promoted to `active` in `data/governor/edges.yml`.

**How to Run**:
```bash
# Full discovery cycle (post-backtest)
python -m scripts.run_backtest --discover

# With fresh logs
python -m scripts.run_backtest --fresh --discover

# Generate candidates only (no validation)
python -m engines.engine_d_discovery.discovery
```

**Outcome**:
- Check `data/governor/edges.yml` for newly promoted edges (status: active).
- Check `data/governor/ga_population.yml` for GA population state and generation count.
- Check `data/research/discovery_log.jsonl` for full audit trail of the discovery cycle.
