"""
Genetic Algorithm engine for CompositeEdge genome evolution.

Completes the GA cycle that was missing from the discovery system:
- Tournament selection (fitness-proportional survival)
- Single-point crossover (gene swapping between winners)
- Targeted mutation (parameter perturbation + structural changes)
- Elitism (preserve top performers across generations)
- Population persistence (survives across discovery cycles)
"""

from __future__ import annotations

import copy
import logging
import random
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import yaml

logger = logging.getLogger("GENETIC_ALG")


class GeneticAlgorithm:
    """
    Manages a persistent population of CompositeEdge genomes and evolves
    them through selection, crossover, and mutation.

    Population is persisted to YAML so evolution continues across cycles.
    """

    def __init__(
        self,
        population_path: str = "data/governor/ga_population.yml",
        population_size: int = 20,
        elite_size: int = 3,
        crossover_prob: float = 0.7,
        mutation_prob: float = 0.3,
        tournament_k: int = 3,
        max_genes: int = 4,
        gene_factory: Optional[Callable[[], Dict[str, Any]]] = None,
    ):
        self.population_path = Path(population_path)
        self.population_size = population_size
        self.elite_size = elite_size
        self.crossover_prob = crossover_prob
        self.mutation_prob = mutation_prob
        self.tournament_k = tournament_k
        self.max_genes = max_genes
        self.gene_factory = gene_factory  # Callable that creates a random gene

        self.population: List[Dict[str, Any]] = []
        self.generation: int = 0
        self.fitness_cache: Dict[str, float] = {}  # edge_id -> fitness

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_population(self) -> bool:
        """Load population from YAML. Returns True if loaded, False if empty/new."""
        if not self.population_path.exists():
            return False

        try:
            data = yaml.safe_load(self.population_path.read_text()) or {}
            self.population = data.get("population", [])
            self.generation = data.get("generation", 0)
            self.fitness_cache = data.get("fitness_cache", {})
            logger.info(
                f"[GA] Loaded generation {self.generation} with "
                f"{len(self.population)} genomes."
            )
            return len(self.population) > 0
        except Exception as e:
            logger.error(f"[GA] Failed to load population: {e}")
            return False

    def save_population(self) -> None:
        """Persist population to YAML."""
        self.population_path.parent.mkdir(parents=True, exist_ok=True)

        data = {
            "generation": self.generation,
            "population_size": len(self.population),
            "fitness_cache_size": len(self.fitness_cache),
            "population": self.population,
            "fitness_cache": self.fitness_cache,
        }

        with self.population_path.open("w") as f:
            yaml.dump(data, f, sort_keys=False, default_flow_style=False)

        logger.info(
            f"[GA] Saved generation {self.generation} "
            f"({len(self.population)} genomes) to {self.population_path}"
        )

    def seed_from_registry(self, registry_specs: List[Dict[str, Any]]) -> None:
        """
        Seed Gen 0 from existing composite edges in the registry.
        Only imports specs with "genes" in params (CompositeEdge format).
        """
        for spec in registry_specs:
            params = spec.get("params", {})
            if "genes" in params:
                genome = {
                    "edge_id": spec.get("edge_id", f"seed_{len(self.population)}"),
                    "genes": copy.deepcopy(params["genes"]),
                    "direction": params.get("direction", "long"),
                }
                self.population.append(genome)

        logger.info(f"[GA] Seeded {len(self.population)} genomes from registry.")

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def tournament_select(
        self, population: List[Dict], fitnesses: Dict[str, float], k: int = 3
    ) -> Dict[str, Any]:
        """
        Tournament selection: pick k random individuals, return the one
        with highest fitness.
        """
        candidates = random.sample(population, min(k, len(population)))
        best = max(candidates, key=lambda g: fitnesses.get(g["edge_id"], -999.0))
        return copy.deepcopy(best)

    # ------------------------------------------------------------------
    # Crossover
    # ------------------------------------------------------------------

    def crossover(
        self, parent_a: Dict[str, Any], parent_b: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Single-point crossover: take a prefix of genes from parent_a and
        suffix from parent_b. Cap at max_genes.
        """
        genes_a = parent_a.get("genes", [])
        genes_b = parent_b.get("genes", [])

        if not genes_a and not genes_b:
            return copy.deepcopy(parent_a)

        # Choose crossover point
        total = len(genes_a) + len(genes_b)
        if total <= 1:
            return copy.deepcopy(parent_a)

        cut_a = random.randint(0, len(genes_a))
        cut_b = random.randint(0, len(genes_b))

        child_genes = copy.deepcopy(genes_a[:cut_a]) + copy.deepcopy(genes_b[cut_b:])

        # Cap at max_genes, ensure at least 1
        if len(child_genes) > self.max_genes:
            child_genes = child_genes[: self.max_genes]
        if len(child_genes) == 0:
            child_genes = [copy.deepcopy(random.choice(genes_a or genes_b))]

        # Inherit direction from parent_a (arbitrary)
        suffix = "".join(random.choices("abcdef0123456789", k=6))
        child = {
            "edge_id": f"composite_gen{self.generation + 1}_{suffix}",
            "genes": child_genes,
            "direction": parent_a.get("direction", "long"),
        }
        return child

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def mutate(self, genome: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mutate a genome with several possible operations:
        - Numeric threshold: Gaussian noise (sigma = 10% of value)
        - Window params: +/- random(1, 5)
        - Operator flip: 5% chance less <-> greater
        - Gene addition: 10% chance to add a random gene
        - Gene deletion: 10% chance to remove a gene (if > 1)
        """
        genome = copy.deepcopy(genome)
        genes = genome.get("genes", [])

        # Per-gene mutations
        for gene in genes:
            if random.random() > self.mutation_prob:
                continue

            # Threshold mutation
            if "threshold" in gene:
                old_val = gene["threshold"]
                if isinstance(old_val, (int, float)) and old_val != 0:
                    sigma = abs(old_val) * 0.10
                    gene["threshold"] = old_val + random.gauss(0, sigma)
                elif old_val == 0:
                    gene["threshold"] = random.gauss(0, 0.01)

            # Window mutation
            for key in ("window", "window_fast", "window_slow"):
                if key in gene:
                    delta = random.randint(-5, 5)
                    gene[key] = max(2, gene[key] + delta)

            # Operator flip (5% chance)
            if random.random() < 0.05 and "operator" in gene:
                op = gene["operator"]
                if op == "less":
                    gene["operator"] = "greater"
                elif op == "greater":
                    gene["operator"] = "less"
                elif op == "top_percentile":
                    gene["operator"] = "bottom_percentile"
                elif op == "bottom_percentile":
                    gene["operator"] = "top_percentile"

        # Structural mutations
        # Gene addition (10% chance)
        if random.random() < 0.10 and len(genes) < self.max_genes and self.gene_factory:
            new_gene = self.gene_factory()
            genes.append(new_gene)

        # Gene deletion (10% chance, only if > 1 gene)
        if random.random() < 0.10 and len(genes) > 1:
            genes.pop(random.randrange(len(genes)))

        # Direction mutation (5% chance)
        if random.random() < 0.05:
            genome["direction"] = random.choice(["long", "short", "market_neutral"])

        # Assign new ID to mutated genome
        suffix = "".join(random.choices("abcdef0123456789", k=6))
        genome["edge_id"] = f"composite_gen{self.generation + 1}_{suffix}"
        genome["genes"] = genes

        return genome

    # ------------------------------------------------------------------
    # Evolution
    # ------------------------------------------------------------------

    def evolve(self, fitnesses: Dict[str, float]) -> List[Dict[str, Any]]:
        """
        Run one generation of evolution.

        1. Sort by fitness, keep top elite_size unchanged.
        2. Fill remaining via tournament selection + crossover + mutation.
        3. Return new population of same size.
        4. Increment generation counter.
        """
        if len(self.population) < 2:
            logger.warning("[GA] Population too small to evolve.")
            return self.population

        # Update fitness cache
        self.fitness_cache.update(fitnesses)

        # Sort by fitness (descending)
        scored = sorted(
            self.population,
            key=lambda g: self.fitness_cache.get(g["edge_id"], -999.0),
            reverse=True,
        )

        # Elitism: preserve top performers
        elite_count = min(self.elite_size, len(scored))
        new_population = [copy.deepcopy(g) for g in scored[:elite_count]]

        # Fill rest via tournament + crossover + mutation
        remaining = self.population_size - elite_count

        for _ in range(remaining):
            parent_a = self.tournament_select(scored, self.fitness_cache, self.tournament_k)
            parent_b = self.tournament_select(scored, self.fitness_cache, self.tournament_k)

            # Crossover
            if random.random() < self.crossover_prob:
                child = self.crossover(parent_a, parent_b)
            else:
                child = copy.deepcopy(parent_a)

            # Mutation
            child = self.mutate(child)
            new_population.append(child)

        self.population = new_population
        self.generation += 1

        # Log stats
        fit_values = [
            self.fitness_cache.get(g["edge_id"], -999.0)
            for g in self.population
            if g["edge_id"] in self.fitness_cache
        ]
        if fit_values:
            logger.info(
                f"[GA] Generation {self.generation}: "
                f"pop={len(self.population)}, "
                f"elite={elite_count}, "
                f"best_fitness={max(fit_values):.3f}, "
                f"avg_fitness={sum(fit_values)/len(fit_values):.3f}"
            )
        else:
            logger.info(
                f"[GA] Generation {self.generation}: "
                f"pop={len(self.population)} (no fitness data yet)"
            )

        return self.population

    def get_unevaluated(self) -> List[Dict[str, Any]]:
        """Return genomes that don't have fitness scores yet."""
        return [g for g in self.population if g["edge_id"] not in self.fitness_cache]

    def to_candidate_specs(self, genomes: Optional[List[Dict]] = None) -> List[Dict[str, Any]]:
        """
        Convert genomes to EdgeRegistry-compatible candidate specs
        for validation via DiscoveryEngine.validate_candidate().
        """
        if genomes is None:
            genomes = self.population

        specs = []
        for genome in genomes:
            spec = {
                "edge_id": genome["edge_id"],
                "module": "engines.engine_a_alpha.edges.composite_edge",
                "class": "CompositeEdge",
                "category": "evolutionary",
                "params": {
                    "genes": genome.get("genes", []),
                    "direction": genome.get("direction", "long"),
                },
                "status": "candidate",
                "version": f"1.0.0-gen{self.generation}",
                "origin": "genetic_algorithm",
            }
            specs.append(spec)
        return specs
