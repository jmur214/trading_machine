# Autonomous discovery beyond LLMs

There's a whole universe of non-LLM autonomous methods. Many are *better* than LLMs for parts of the discovery loop because they're cheaper, more rigorous, and not subject to hallucination. The right system uses both.

## 1. **Symbolic regression — find formulas, not parameters**

PySR / gplearn search the space of *equations*, not coefficients. Instead of fitting `y = ax + by + c`, they discover `y = log(x) * sin(z/y)` if that's what the data says. Output is **human-readable formulas** that transfer across markets and timeframes.

Why this matters for autonomy: a parametric model overfits because it can twist itself into the noise. A formula constrained by parsimony pressure (operator-count penalty) **can't overfit easily** because it has limited expressivity. It also tells you *why* — you can read the formula and check if the mechanism makes sense.

Run PySR over (price, volume, fundamentals, macro) every night. Promote formulas that survive walk-forward + transfer tests. ~$0 in dependencies.

## 2. **Quality-Diversity algorithms (MAP-Elites, Novelty Search)**

Standard GA converges on one local optimum. **MAP-Elites maintains a diverse archive** — for every cell in a "behavior space" (e.g., (Sharpe, drawdown, holding period)), it keeps the best edge for that cell. Result: a *whole population* of qualitatively different alphas, not 28 variations of momentum.

**Novelty Search** rewards being different rather than being good. Sounds insane, paradoxically finds better alphas because it escapes the strip-mined region of the search space. This single algorithm replaces Engine D's GA and is documented to outperform GA on hard search problems.

## 3. **The AutoML stack (tsfresh + AutoGluon + Featuretools)**

- **tsfresh** automatically extracts ~800 features per time series (entropy measures, peak counts, spectral statistics, autocorrelations at every lag, etc.)
- **AutoGluon** automatically tries dozens of model classes and ensembles
- **Featuretools** automatically generates interaction features

Point this at every (ticker, date) tensor. **You get 1000s of features without writing a single feature.** Pure code. Mostly free.

## 4. **Self-play reinforcement learning (AlphaZero for trading)**

Spawn N copies of the system. Each gets slightly different parameters. They trade against simulated markets and **against each other's flow**. Wins propagate, losses get pruned. Over millions of episodes, strategies evolve that no human (or LLM) would design.

This is what made AlphaZero superhuman at chess in 24 hours. The same machinery applied to trading is computationally heavy but conceptually identical. **It's the closest thing to genuine emergent strategy discovery.** Use distributional RL (C51, QR-DQN) so the agent learns the full return distribution, including tails.

## 5. **Causal discovery (PC, NOTEARS, GES)**

Already mentioned but worth elevating. These algorithms — **without an LLM** — take a feature matrix and output a causal graph: "feature A causes feature B causes return R." Trade only on causal edges.

`causalnex`, `dowhy`, `cdt` libraries. Pure statistics, no ML black box. **Causal alphas survive regime changes** because the *mechanism* is preserved when surface statistics shift. This is the thing the Discovery engine should be running daily.

## 6. **Graph Neural Networks for the universe**

Stocks aren't independent. They're nodes in a graph (sector, supply chain, ETF co-membership, correlation). A GNN learns the graph structure *while* learning to predict returns. Message passing automatically discovers influence patterns.

When NVDA moves, the GNN already knows AVGO/TSM/AMD should be checked. **The relational structure is a free feature space.** PyTorch Geometric, DGL. ~600 lines. Actively researched at Two Sigma, AQR.

## 7. **Topological Data Analysis (TDA)**

The dark horse. **Persistent homology** detects the "shape" of a feature manifold — holes, voids, connected components. Markets in different regimes have different topological signatures.

The Mapper algorithm builds a graph of state space showing which configurations are connected. This catches **non-linear, non-stationary patterns conventional ML misses entirely**. `giotto-tda`, `kepler-mapper`. Esoteric but genuinely powerful for regime detection and crisis prediction.

## 8. **Differentiable backtesting (JAX)**

Rewrite the backtest core in **JAX**. Suddenly your entire backtest is differentiable end-to-end. Alpha discovery becomes **gradient descent over strategy parameters** with vectorized batch parallelism. 1000–10,000× speedup over loop-based search.

This is infrastructure, not algorithm — but it's the multiplier that makes everything else feasible. Without it, you can run 100 hypotheses/day. With it, 100,000.

## 9. **Bayesian optimization with active learning**

Instead of grid search or GA over hyperparameters, **Bayesian optimization with Gaussian processes** picks the next point to evaluate by maximum expected information gain. Specifically: where uncertainty about the objective is highest *and* where the GP predicts good performance.

`BoTorch`, `optuna`, `Dragonfly`. **The system decides what experiment to run next, autonomously.** This is curiosity formalized as math. ~200 lines.

## 10. **Coevolutionary alphas (predator-prey)**

Run two populations: **alphas** trying to predict returns, **anti-alphas** trying to find data patterns that fool the alphas. Both populations evolve against each other. Equilibrium produces alphas that are robust to the most adversarial features the anti-alpha population can construct.

This is generative-adversarial training applied to alpha discovery. Pure population dynamics, no LLM, no human curation. Originated in evolutionary biology, applies cleanly here.

## 11. **Reservoir computing / Echo State Networks**

For online learning without retraining. ESNs have a fixed random recurrent layer; only the readout is trained. Result: **train in milliseconds, adapt to new data instantly**. Excellent at chaotic dynamics, which markets are.

You can run thousands of ESNs in parallel on different feature subsets, ensemble the survivors. Cheap, fast, well-suited to non-stationary signals. Vastly underused outside academic chaos research.

## 12. **Conformal prediction + Thompson sampling bandits**

The honest-uncertainty + dynamic-allocation pair:

- **Conformal prediction** gives distribution-free, honest prediction intervals. No assumptions, just exchangeability. The width of the interval IS your uncertainty.
- **Thompson sampling bandits** allocate capital across edges based on posterior over their performance. Self-balancing exploration vs exploitation.

Combined: when uncertainty is high, the bandit explores. When confidence is high, it concentrates. **The system manages its own discovery-vs-exploitation tradeoff.**

## 13. **Information-theoretic feature discovery**

`sklearn.feature_selection.mutual_info_regression` is one line. Run it nightly across the entire feature space. Surface features with high mutual information *and* high transfer entropy (lagged causal relevance) to returns.

Add **conditional mutual information** — "feature X carries info about return *given* features {already-known}". This finds *additive* signal, not redundant signal. Pure information theory, mathematically rigorous, no ML black box.

## 14. **Self-supervised time-series representation learning (no LLM)**

TS2Vec, SimMTM, TNC — **contrastive learning on time series**. Train without labels, learn representations where similar market states are nearby. Use embeddings as features OR as the search space for nearest-neighbor strategies ("what stocks looked like this state historically? what happened next?").

This is the case-based reasoning approach to autonomy: the system learns its own state representation and queries its own history.

## 15. **Active inference / curiosity-driven exploration**

Schmidhuber's intrinsic motivation: **the system rewards itself for finding patterns it can't predict.** High prediction error → high intrinsic reward → search there. Drives the data crawler and the feature search toward novel regions.

Implements as a small "curiosity head" on the model: predict prediction error, search where predicted error is high. The machine *wants* to be surprised. This is genuine self-directed exploration, not a heuristic.

## 16. **Wild card: agent-based market simulation**

Build a synthetic market with thousands of simulated traders (zero-intelligence agents, momentum chasers, mean-reverters, market makers). Discover alphas in the synthetic market first — they're cheap and you can simulate any regime. Then test on real data.

The agents that find alpha in simulation tend to be those that exploit microstructure dynamics that exist in real markets too. **Discovery in synthetic worlds, validation in real ones.** Used by some of the more sophisticated HFT shops. `mesa`, `abides` libraries.

---

## How they combine into autonomy

The richest autonomous discovery loop uses **multiple methods in parallel** because each finds different alphas:

```
Symbolic Regression  → interpretable formulas
Causal Discovery     → mechanism-grounded edges
Quality-Diversity    → diverse strategy population
GNN                  → relational/network alpha
TDA                  → non-linear regime structure
Self-play RL         → emergent strategies
Coevolution          → adversarially robust edges
Active Learning      → directs compute efficiently
Conformal + Bandits  → honest uncertainty + allocation
LLM                  → hypothesis-level reasoning
```

**The LLM is one researcher in a department of researchers.** Each method has a different cognitive style and finds different alphas. The unified system runs all of them, validates through the same gauntlet (transfer tests, multiple-testing correction, adversarial validation), and lets survivors compound.

## The deeper point

True autonomy isn't *any single method*. It's **methodological diversity** — multiple paradigms searching the same space, validated against the same standards, voting on what's real. **No single approach is robust enough alone.** The LLM hallucinates. GAs overfit. Causal discovery is sample-hungry. GNNs are opaque. But combine them and the failure modes are uncorrelated — what one method fools itself with, another catches.

This is also how serious science works. Multiple labs, multiple methods, replication. **Build the trading equivalent: multiple discovery engines voting on what's real, with a validation gauntlet none of them can game.**

That stack is genuinely autonomous, doesn't require a human in the loop, and *cannot* be replicated by retail competitors who are still doing single-method GA searches over RSI variants.