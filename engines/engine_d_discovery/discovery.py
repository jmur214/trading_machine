from __future__ import annotations
import random
import yaml
import pandas as pd
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional, Type

# Import Template Interface from Engine A
from engines.engine_a_alpha.edge_template import EdgeTemplate
from engines.engine_a_alpha.edges.rsi_bounce import RSIBounceEdge
from engines.engine_a_alpha.edges.fundamental_value import ValueTrapEdge
from engines.engine_a_alpha.edges.fundamental_ratio import FundamentalRatioEdge
from engines.engine_a_alpha.edges.rule_based_edge import RuleBasedEdge
from engines.engine_a_alpha.edges.seasonality_edge import SeasonalityEdge
from engines.engine_a_alpha.edges.gap_edge import GapEdge
from engines.engine_a_alpha.edges.volume_anomaly_edge import VolumeAnomalyEdge
from engines.engine_a_alpha.edges.panic_edge import PanicEdge
from engines.engine_a_alpha.edges.herding_edge import HerdingEdge
from engines.engine_a_alpha.edges.earnings_vol_edge import EarningsVolEdge

# Research Modules
from engines.engine_d_discovery.tree_scanner import DecisionTreeScanner
from engines.engine_d_discovery.feature_engineering import FeatureEngineer

class DiscoveryEngine:
    """
    Engine D (Discovery): The Evolutionary Lab.
    
    Responsibilities:
    1. Scan for valid EdgeTemplates.
    2. Generate N candidate configurations (Mutations).
    3. Save candidates to registry for validation.
    """
    
    def __init__(
        self,
        registry_path: str = "data/governor/edges.yml",
        processed_data_dir: str = "data/processed",
    ):
        self.registry_path = Path(registry_path)
        self.registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._processed_data_dir = Path(processed_data_dir)
        self.templates: List[Type[EdgeTemplate]] = [
            RSIBounceEdge,
            ValueTrapEdge,
            FundamentalRatioEdge,
            SeasonalityEdge,
            GapEdge,
            VolumeAnomalyEdge,
            PanicEdge,
            HerdingEdge,
            EarningsVolEdge,
        ]

    def hunt(
        self,
        data_map: Dict[str, pd.DataFrame],
        regime_meta: Optional[Dict[str, Any]] = None,
        fundamentals_map: Optional[Dict[str, pd.DataFrame]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Phase 2 Core: The "Hunter".
        1. Calculate Features for all data (including cross-sectional, calendar,
           microstructure, inter-market, and regime context).
        2. Run TreeScanner to find patterns.
        3. Convert Rules -> RuleBasedEdge Candidates.
        """
        logger = logging.getLogger("DISCOVERY")

        # 1. Feature Prep
        fe = FeatureEngineer()
        scanner = DecisionTreeScanner(max_depth=4, min_prob=0.55)

        # Extract benchmark / cross-asset DataFrames for inter-market features
        spy_df = data_map.get("SPY")
        tlt_df = data_map.get("TLT")
        gld_df = data_map.get("GLD")

        all_dfs = []
        for ticker, df in data_map.items():
            if df.empty:
                continue

            # Get fundamentals for this ticker (if available)
            fund_df = pd.DataFrame()
            if fundamentals_map and ticker in fundamentals_map:
                fund_df = fundamentals_map[ticker]

            # Compute all features (technical + calendar + microstructure + inter-market + regime)
            f_df = fe.compute_all_features(
                df, fund_df,
                spy_df=spy_df, tlt_df=tlt_df, gld_df=gld_df,
                regime_meta=regime_meta,
            )

            # Add Targets
            t_df = scanner.generate_targets(f_df)
            t_df["ticker"] = ticker

            all_dfs.append(t_df)

        if not all_dfs:
            return []

        big_data = pd.concat(all_dfs).reset_index(drop=True)

        # Cross-sectional features (rank across universe per date)
        big_data = FeatureEngineer.compute_cross_sectional_features(big_data, ticker_col="ticker")

        logger.info(f"Hunting on {len(big_data)} rows of data, {len(big_data.columns)} features...")
        
        # 2. Scan
        rules = scanner.scan(big_data, target_col="Target")
        
        # 3. Convert to Candidates
        candidates = []
        
        for r in rules:
            # Hash rule string to get ID
            import hashlib
            rule_hash = hashlib.md5(r["rule_string"].encode()).hexdigest()[:8]
            cand_id = f"hunter_{rule_hash}"
            
            spec = {
                "edge_id": cand_id,
                "module": RuleBasedEdge.__module__,
                "class": RuleBasedEdge.__name__,
                "category": "discovered_rule",
                "params": {
                    "rule_string": r["rule_string"],
                    "target_class": r["target_class"],
                    "probability": r["probability"],
                    "description": f"Target {r['target_name']} ({r['probability']:.1%})"
                },
                "status": "candidate",
                "version": "1.0.0-auto",
                "origin": "tree_scanner"
            }
            candidates.append(spec)
            
        return candidates

    def generate_candidates(self, n_mutations: int = 5) -> List[Dict[str, Any]]:
        """
        Produce candidate specs via two paths:
        1. Standard template mutation (random hyperparameter sampling).
        2. Genetic algorithm evolution of CompositeEdge genomes
           (selection, crossover, mutation across generations).
        """
        candidates = []

        # 1. Standard Template Mutation
        for template in self.templates:
            if template.__name__ == "CompositeEdge":
                continue  # Handled by GA below

            base_id = getattr(template, "EDGE_ID", "unknown_edge")

            for i in range(n_mutations):
                params = template.sample_params()

                suffix = "".join(random.choices("abcdef0123456789", k=4))
                candidate_id = f"{base_id}_mut_{suffix}"

                spec = {
                    "edge_id": candidate_id,
                    "module": template.__module__,
                    "class": template.__name__,
                    "category": getattr(template, "EDGE_CATEGORY", "experimental"),
                    "params": params,
                    "status": "candidate",
                    "version": "1.0.0-mut",
                    "origin": "discovery_engine",
                }
                candidates.append(spec)

        # 2. Composite Evolution via Genetic Algorithm
        ga_candidates = self._run_ga_evolution(n_mutations)
        candidates.extend(ga_candidates)

        return candidates

    def _run_ga_evolution(self, n_random_seed: int = 5) -> List[Dict[str, Any]]:
        """
        Run one generation of the genetic algorithm for CompositeEdge genomes.
        On first run (no population), seeds with random genomes.
        On subsequent runs, evolves from the persisted population.
        """
        from engines.engine_d_discovery.genetic_algorithm import GeneticAlgorithm

        ga_pop_path = str(self.registry_path.parent / "ga_population.yml")
        ga = GeneticAlgorithm(
            population_path=ga_pop_path,
            population_size=max(20, n_random_seed * 4),
            gene_factory=self._create_random_gene,
        )

        if ga.load_population():
            # Subsequent run: evolve from persisted population
            # Get fitness for evaluated genomes from the registry
            fitnesses = self._load_fitness_from_registry()
            ga.fitness_cache.update(fitnesses)

            # Evolve to next generation
            ga.evolve(fitnesses)
        else:
            # First run: seed with random genomes
            # Try to seed from existing composite edges in registry
            existing = self.get_queued_candidates(status="active")
            existing += self.get_queued_candidates(status="candidate")
            ga.seed_from_registry(existing)

            # Fill remaining with random genomes
            while len(ga.population) < ga.population_size:
                n_genes = random.randint(1, 3)
                genes = [self._create_random_gene() for _ in range(n_genes)]

                suffix = "".join(random.choices("abcdef0123456789", k=6))
                direction = "long"
                rand = random.random()
                if rand < 0.10:
                    direction = "short"
                elif rand < 0.20:
                    direction = "market_neutral"

                genome = {
                    "edge_id": f"composite_gen0_{suffix}",
                    "genes": genes,
                    "direction": direction,
                }
                ga.population.append(genome)

            ga.generation = 0

        ga.save_population()

        # Return unevaluated genomes as candidate specs for validation
        unevaluated = ga.get_unevaluated()
        return ga.to_candidate_specs(unevaluated)

    def _load_fitness_from_registry(self) -> Dict[str, float]:
        """
        Extract fitness scores from the registry for composite edges.
        Uses the 'sharpe' field stored during validation.
        """
        fitnesses = {}
        all_edges = []
        if self.registry_path.exists():
            try:
                data = yaml.safe_load(self.registry_path.read_text()) or {}
                all_edges = data.get("edges", [])
            except Exception:
                pass

        for edge in all_edges:
            eid = edge.get("edge_id", "")
            if "composite" not in eid and edge.get("origin") != "genetic_algorithm":
                continue
            params = edge.get("params", {})
            # Prefer composite fitness_score (OOS-weighted) over in-sample validation_sharpe.
            fitness_val = params.get("fitness_score", None)
            if fitness_val is None:
                fitness_val = params.get("validation_sharpe", None)
            if fitness_val is not None:
                fitnesses[eid] = float(fitness_val)
            # Active edges without stored fitness get a baseline so they're
            # not invisible to tournament selection.
            if edge.get("status") == "active" and eid not in fitnesses:
                fitnesses[eid] = 0.5

        return fitnesses

    def _create_random_gene(self) -> Dict[str, Any]:
        """
        Creates a random Gene (Condition) using expanded vocabulary.

        Categories (weighted selection):
        - Technical (35%): RSI, Volatility, SMA Distance, SMA Cross, Donchian,
          Pivot, Momentum ROC, Residual Momentum, Vol Diff
        - Macro (10%): Yield curve (T10Y2Y), VIX level, unemployment delta
        - Earnings (5%): EPS surprise % look-back
        - Fundamental (10%): PE, PS, PB, PFCF, Debt
        - Calendar (10%): Day-of-week, month, quarter-end, opex proximity
        - Microstructure (10%): Overnight gap, close location, intraday range
        - Intermarket (10%): SPY/TLT/GLD returns, SPY-TLT correlation
        - Regime (5%): Bull/bear/vol context
        - Behavioral (5%): Panic score, herding breadth
        """
        roll = random.random()

        # --- Regime (5%) ---
        if roll < 0.05:
            return {
                "type": "regime",
                "is": random.choice(["bull", "bear", "neutral_low_vol"]),
                "operator": "is",
            }

        # --- Calendar (10%) ---
        if roll < 0.15:
            indicator = random.choice([
                "day_of_week_sin", "month_sin",
                "quarter_end_proximity", "opex_proximity",
            ])
            gene = {"type": "calendar", "indicator": indicator, "operator": "less"}
            if indicator == "day_of_week_sin":
                gene["threshold"] = round(random.uniform(-1.0, 1.0), 2)
            elif indicator == "month_sin":
                gene["threshold"] = round(random.uniform(-1.0, 1.0), 2)
            elif indicator == "quarter_end_proximity":
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = random.choice([3, 5, 10])
            elif indicator == "opex_proximity":
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = random.choice([2, 5])
            return gene

        # --- Microstructure (10%) ---
        if roll < 0.25:
            indicator = random.choice([
                "overnight_gap", "close_location", "intraday_range",
            ])
            gene = {"type": "microstructure", "indicator": indicator}
            if indicator == "overnight_gap":
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = round(random.choice([-0.02, -0.01, 0.01, 0.02]), 3)
            elif indicator == "close_location":
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = random.choice([0.2, 0.3, 0.7, 0.8])
            elif indicator == "intraday_range":
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = round(random.uniform(0.01, 0.05), 3)
            return gene

        # --- Intermarket (10%) ---
        if roll < 0.35:
            indicator = random.choice([
                "spy_return_5d", "tlt_return_5d", "gld_return_5d", "spy_tlt_corr",
            ])
            gene = {"type": "intermarket", "indicator": indicator}
            if indicator in ("spy_return_5d", "tlt_return_5d", "gld_return_5d"):
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = round(random.choice([-0.03, -0.01, 0.0, 0.01, 0.03]), 3)
                gene["window"] = 5
            elif indicator == "spy_tlt_corr":
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = round(random.choice([-0.3, -0.1, 0.0, 0.2, 0.4]), 2)
            return gene

        # --- Macro (10%) — economy-wide FRED signals, all with data back to 2000+ ---
        if roll < 0.45:
            indicator = random.choice(["yield_curve", "vix_level", "unemployment_delta"])
            gene = {"type": "macro", "indicator": indicator}
            if indicator == "yield_curve":
                # T10Y2Y: inverted (<0) = stress, steep (>1.5) = expansion
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = round(random.choice([-0.5, 0.0, 0.5, 1.0, 1.5]), 2)
            elif indicator == "vix_level":
                # VIX: > 20 = elevated vol, > 30 = panic
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = random.choice([15, 20, 25, 30])
            elif indicator == "unemployment_delta":
                # UNRATE month-over-month change: positive = worsening labor market
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = round(random.choice([-0.2, -0.1, 0.0, 0.1, 0.2]), 2)
            return gene

        # --- Earnings (5%) — per-ticker EPS surprise look-back ---
        if roll < 0.50:
            gene = {
                "type": "earnings",
                "indicator": "eps_surprise_pct",
                "operator": random.choice(["less", "greater"]),
                "threshold": round(random.choice([-0.10, -0.05, 0.0, 0.05, 0.10, 0.15]), 2),
                "lookback_days": random.choice([30, 60, 90]),
            }
            return gene

        # --- Behavioral (5%) ---
        if roll < 0.55:
            indicator = random.choice(["panic_score", "herding_breadth"])
            gene = {"type": "behavioral", "indicator": indicator}
            if indicator == "panic_score":
                # Panic score is composite: low RSI + high vol + low close_location
                # For now, proxy via RSI threshold (will be expanded later)
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = random.choice([20, 25, 30])
            elif indicator == "herding_breadth":
                # % of universe moving same direction
                gene["operator"] = random.choice(["less", "greater"])
                gene["threshold"] = random.choice([0.7, 0.8, 0.9])
            return gene

        # --- Standard operator selection for technical/fundamental ---
        op_choices = ["less", "greater"]
        if random.random() < 0.30:
            op_choices += ["top_percentile", "bottom_percentile"]
        operator = random.choice(op_choices)

        # --- Fundamental (10%) ---
        if roll < 0.65:
            metric = random.choice([
                "PE_Ratio", "PS_Ratio", "PB_Ratio", "PFCF_Ratio", "Debt_to_Equity",
            ])
            gene = {"type": "fundamental", "metric": metric, "operator": operator}
            if "percentile" in operator:
                gene["threshold"] = 20 if "bottom" in operator else 80
            else:
                if metric == "PE_Ratio":
                    gene["threshold"] = 15
                elif metric == "PS_Ratio":
                    gene["threshold"] = 2
                else:
                    gene["threshold"] = 1.0
            return gene

        # --- Technical (35% — remainder) ---
        indicators = [
            "rsi", "volatility", "sma_dist_pct",
            "sma_cross", "donchian_breakout", "pivot_position", "momentum_roc",
            "residual_momentum", "volatility_diff",
        ]
        indicator = random.choice(indicators)
        gene = {"type": "technical", "indicator": indicator, "operator": operator}

        if indicator == "rsi":
            gene["window"] = 14
            gene["threshold"] = random.choice([30, 70]) if "percentile" not in operator else 50
        elif indicator == "volatility":
            gene["window"] = 20
            gene["threshold"] = 0.02
        elif indicator == "sma_dist_pct":
            gene["window"] = 50
            gene["threshold"] = 0.0
        elif indicator == "sma_cross":
            gene["window_fast"] = random.choice([10, 20])
            gene["window_slow"] = random.choice([50, 200])
            gene["threshold"] = 0.0
        elif indicator == "donchian_breakout":
            gene["window"] = 20
            gene["threshold"] = 0.0
        elif indicator == "pivot_position":
            gene["threshold"] = 0.0
        elif indicator == "momentum_roc":
            gene["window"] = random.choice([20, 60, 120])
            gene["threshold"] = 0.0
        elif indicator == "residual_momentum":
            gene["window"] = 60
            gene["threshold"] = 0.0
        elif indicator == "volatility_diff":
            gene["threshold"] = 0.0

        # Adjust threshold for ranking operators
        if "percentile" in operator:
            if operator == "top_percentile":
                gene["threshold"] = random.choice([80, 90, 95])
            else:
                gene["threshold"] = random.choice([5, 10, 20])

        return gene

    def get_queued_candidates(self, status: str = "candidate") -> List[Dict[str, Any]]:
        """
        Retrieve candidates from registry that are ready for validation.
        """
        if not self.registry_path.exists():
            return []
            
        try:
            data = yaml.safe_load(self.registry_path.read_text())
            edges = data.get("edges", [])
            return [e for e in edges if e.get("status") == status]
        except Exception as e:
            print(f"[DISCOVERY] Error reading registry: {e}")
            return []

    def save_candidates(self, candidates: List[Dict[str, Any]]) -> None:
        """
        Append candidates to the active edges.yml (or a separate staging registry).
        For now, we append to edges.yml but with status='candidate'.
        """
        if not self.registry_path.exists():
            existing = {"edges": []}
        else:
            try:
                existing = yaml.safe_load(self.registry_path.read_text()) or {"edges": []}
                # Handle legacy format where root might be missing or list
                if isinstance(existing, list):
                    existing = {"edges": existing}
            except Exception as e:
                print(f"[DISCOVERY] Error reading registry: {e}")
                existing = {"edges": []}

        # Deduplicate by ID
        current_map = {e.get("edge_id"): e for e in existing.get("edges", [])}
        
        new_count = 0
        update_count = 0
        for cand in candidates:
            cid = cand["edge_id"]
            if cid not in current_map:
                new_count += 1
            else:
                update_count += 1
            current_map[cid] = cand
        
        # Write back
        final_list = list(current_map.values())
        with self.registry_path.open("w") as f:
            yaml.dump({"edges": final_list}, f, sort_keys=False)
            
        print(f"[DISCOVERY] Registry saved. New: {new_count}, Updated: {update_count}. Path: {self.registry_path}")

    def _load_universe_b(
        self,
        prod_tickers: set,
        n_sample: int = 50,
        seed: int = 42,
    ) -> Dict[str, pd.DataFrame]:
        """
        Load a random sample of tickers NOT in the production universe.

        Reads directly from `self._processed_data_dir` (CSV fallback only —
        no Parquet, no network). Skips files shorter than 100 rows so that
        thinly-traded or delisted names don't pollute the Gate 5 result.

        Parameters
        ----------
        prod_tickers : set
            The production universe (data_map keys). Universe B = all
            cached tickers minus this set.
        n_sample : int
            Maximum number of universe-B tickers to load. 50 is enough to
            detect universe-specificity while keeping Gate 5 cost under ~50%
            of the production backtest.
        seed : int
            Reproducible random selection within a cycle.

        Returns
        -------
        dict — ticker → DataFrame, possibly empty if no universe-B data found.
        """
        import numpy as np

        all_csvs = {
            f.stem.replace("_1d", "")
            for f in self._processed_data_dir.glob("*_1d.csv")
        }
        candidates = sorted(all_csvs - prod_tickers)

        if not candidates:
            return {}

        rng = np.random.RandomState(seed)
        sampled: List[str] = rng.choice(
            candidates, size=min(n_sample, len(candidates)), replace=False,
        ).tolist()

        dm_b: Dict[str, pd.DataFrame] = {}
        for ticker in sampled:
            csv_path = self._processed_data_dir / f"{ticker}_1d.csv"
            try:
                df = pd.read_csv(csv_path, index_col=0, parse_dates=True)
                if not df.empty and len(df) >= 100:
                    dm_b[ticker] = df
            except Exception:
                pass

        return dm_b

    # ====================================================================
    # Production-equivalent edge ensemble construction
    # ====================================================================

    @staticmethod
    def _build_production_edges(
        *,
        registry_path: Path,
        alpha_config: Optional[Dict[str, Any]],
        exclude_edge_ids: Optional[set] = None,
    ) -> tuple[Dict[str, Any], Dict[str, float]]:
        """Construct the production-equivalent edges_dict + edge_weights.

        Mirrors `ModeController.run_backtest`'s edge-loading + soft-pause
        logic exactly:
          - Loads active + paused specs from `EdgeRegistry.list_tradeable()`.
          - Instantiates each edge from its module + class via importlib.
          - Applies config-driven `edge_weights` from alpha_settings.
          - Applies `PAUSED_WEIGHT_MULTIPLIER = 0.25` and
            `PAUSED_MAX_WEIGHT = 0.5` to status='paused' edges.

        Excludes any edge_id in `exclude_edge_ids` (used to pull the
        candidate out of the baseline before adding it back into the
        with-candidate set).

        Returns
        -------
        (edges, edge_weights) — drop-in inputs for `run_backtest_pure`.
        """
        import importlib

        from engines.engine_a_alpha.edge_registry import EdgeRegistry

        # Load registry from the same path the orchestrator uses
        registry = EdgeRegistry(store_path=str(registry_path))
        excluded = set(exclude_edge_ids or set())

        loaded_edges: Dict[str, Any] = {}
        spec_status_by_id: Dict[str, str] = {}
        for spec in registry.list_tradeable():
            if spec.edge_id in excluded:
                continue
            mod_name = spec.module
            params = (spec.params or {}).copy()
            try:
                if "." in mod_name:
                    mod = importlib.import_module(mod_name)
                else:
                    mod = importlib.import_module(
                        f"engines.engine_a_alpha.edges.{mod_name}"
                    )
                edge_class = None
                for attr in dir(mod):
                    if attr.lower().endswith("edge") and attr not in ("BaseEdge",):
                        val = getattr(mod, attr)
                        if hasattr(val, "__module__") and val.__module__ == mod.__name__:
                            edge_class = val
                            break
                if edge_class is None:
                    for attr in dir(mod):
                        if attr.lower().endswith("edge") and attr not in ("BaseEdge",):
                            edge_class = getattr(mod, attr)
                            break
                if edge_class is None:
                    continue
                try:
                    loaded_edges[spec.edge_id] = edge_class(params=params)
                except TypeError:
                    loaded_edges[spec.edge_id] = edge_class()
                spec_status_by_id[spec.edge_id] = spec.status
            except Exception as e:
                print(f"[VALIDATE] Could not import {mod_name} for {spec.edge_id}: {e}")
                continue

        # Build edge_weights from alpha config (matches mode_controller)
        config_ew = (alpha_config or {}).get("edge_weights", {}) if alpha_config else {}
        edge_weights = {
            eid: float(config_ew.get(eid, 1.0)) for eid in loaded_edges
        }
        PAUSED_WEIGHT_MULTIPLIER = 0.25
        PAUSED_MAX_WEIGHT = 0.5
        for eid in list(edge_weights.keys()):
            if spec_status_by_id.get(eid) == "paused":
                edge_weights[eid] = min(
                    edge_weights[eid] * PAUSED_WEIGHT_MULTIPLIER,
                    PAUSED_MAX_WEIGHT,
                )

        return loaded_edges, edge_weights

    @staticmethod
    def _instantiate_candidate(candidate_spec: Dict[str, Any]) -> Any:
        """Import + instantiate a candidate edge from its spec dict."""
        from importlib import import_module
        mod = import_module(candidate_spec["module"])
        cls_ = getattr(mod, candidate_spec["class"])
        edge = cls_()
        if "params" in candidate_spec and candidate_spec["params"]:
            edge.set_params(candidate_spec["params"])
        return edge

    def validate_candidate(
        self,
        candidate_spec: Dict[str, Any],
        data_map: Dict[str, pd.DataFrame],
        significance_threshold: Optional[float] = 0.05,
        exec_params: Optional[Dict[str, Any]] = None,
        diagnostic_log_path: Optional[str] = None,
        cache: Optional[Any] = None,
        gate1_contribution_threshold: float = 0.10,
        gate2_survival_threshold: float = 0.60,
        gate3_consistency_threshold: float = 0.40,
        candidate_default_weight: float = 1.0,
        alpha_config: Optional[Dict[str, Any]] = None,
        risk_settings: Optional[Dict[str, Any]] = None,
        portfolio_settings: Optional[Dict[str, Any]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Dict[str, float]:
        """Production-equivalent multi-gate validation (architectural-fix v2).

        Per `project_gauntlet_consolidated_fix_2026_05_01.md`: invokes the
        actual production pipeline twice (baseline = active+paused minus
        candidate; with-candidate = baseline + candidate) instead of running
        a standalone single-edge backtest. The candidate's *attribution
        stream* (with_returns - baseline_returns) is then threaded through
        gates 2-6.

        This fixes the standalone-vs-ensemble geometry mismatch that drove
        Gate 1 to kill 30/30 candidates in the 2026-05-01 diagnostic
        (Audit doc `discovery_diagnostic_2026_05.md`) and was inherited
        by gates 2-6 (Audit doc `gates_2_to_6_audit_2026_05.md`).

        Gates
        -----
        - Gate 1: Sharpe(with_candidate) - Sharpe(baseline) > threshold.
        - Gate 2: PBO survival on bootstrap of attribution stream.
        - Gate 3: WFO consistency = mean rolling-window Sharpe / overall
                  Sharpe of the attribution stream.
        - Gate 4: Permutation-null p-value on attribution stream.
        - Gate 5: Universe-B production-equivalent contribution > 0.
        - Gate 6: FF5+Mom regression on attribution stream — t > 2 AND
                  α annualized > 2%.

        Threshold rationale — see `docs/Measurements/2026-05/gauntlet_architectural_fix_2026_05.md`
        for calibration.

        Caching
        -------
        If `cache` (a `PureBacktestCache` instance) is passed, the baseline
        is fingerprinted and reused across candidates in the same Discovery
        cycle. N candidates → N+1 backtests instead of 2N.
        """
        import numpy as np
        import time as _time
        import math

        from orchestration.run_backtest_pure import (
            run_backtest_pure,
            PureBacktestCache,
        )
        from engines.engine_d_discovery.attribution import (
            treatment_effect_returns,
            stream_sharpe,
            attribution_diagnostics,
        )
        from engines.engine_d_discovery.robustness import RobustnessTester

        _diag_t_start = _time.time()
        _diag_gate_seconds: Dict[str, float] = {}
        _diag_gates_run: List[str] = []
        _diag_error: Optional[str] = None

        def _stamp(gate_name: str, t0: float) -> None:
            _diag_gate_seconds[gate_name] = round(_time.time() - t0, 3)
            _diag_gates_run.append(gate_name)

        result = {
            "sharpe": 0.0,
            "sortino": 0.0,
            "baseline_sharpe": 0.0,
            "with_candidate_sharpe": 0.0,
            "contribution_sharpe": 0.0,
            "attribution_sharpe": 0.0,
            "robustness_survival": 0.0,
            "wfo_degradation": 0.0,
            "significance_p": 1.0,
            "passed_all_gates": False,
            "gate_1_passed": False,
            "gate_2_passed": False,
            "gate_3_evaluated": False,
            "gate_4_passed": False,
            "gate_5_passed": False,
            "gate_6_passed": False,
        }

        def _emit_diag() -> None:
            if not diagnostic_log_path:
                return
            try:
                # Compute first-failed-gate. Gate 3 is metric-only (not in
                # final pass-check), so it is excluded from kill-attribution.
                gate_pass_order = [
                    ("gate_1", bool(result.get("gate_1_passed", False))),
                    ("gate_2", bool(result.get("gate_2_passed", False))),
                    ("gate_4", bool(result.get("gate_4_passed", False))),
                    ("gate_5", bool(result.get("gate_5_passed", False))),
                    ("gate_6", bool(result.get("gate_6_passed", False))),
                ]
                first_failed = None
                for name, passed in gate_pass_order:
                    if not passed:
                        first_failed = name
                        break
                params = candidate_spec.get("params", {}) or {}
                gene_count = 0
                gene_types: List[str] = []
                if "genes" in params and isinstance(params["genes"], list):
                    gene_count = len(params["genes"])
                    for g in params["genes"]:
                        if isinstance(g, dict):
                            gene_types.append(str(g.get("type", "?")))
                rec = {
                    "candidate_id": candidate_spec.get("edge_id", "?"),
                    "module": candidate_spec.get("module", "?"),
                    "class": candidate_spec.get("class", "?"),
                    "category": candidate_spec.get("category", "?"),
                    "origin": candidate_spec.get("origin", "?"),
                    "gene_count": gene_count,
                    "gene_types": gene_types,
                    "direction": params.get("direction"),
                    "wall_seconds_total": round(_time.time() - _diag_t_start, 3),
                    "gate_seconds": _diag_gate_seconds,
                    "gates_run": _diag_gates_run,
                    "first_failed_gate": first_failed,
                    "error": _diag_error,
                    "metrics": {
                        "sharpe": float(result.get("sharpe", 0.0) or 0.0),
                        "sortino": float(result.get("sortino", 0.0) or 0.0),
                        "robustness_survival": float(result.get("robustness_survival", 0.0) or 0.0),
                        "wfo_degradation": float(result.get("wfo_degradation", 0.0) or 0.0),
                        "wfo_oos_sharpe": float(result.get("wfo_oos_sharpe", 0.0) or 0.0),
                        "wfo_is_sharpe": float(result.get("wfo_is_sharpe", 0.0) or 0.0),
                        "significance_p": float(result.get("significance_p", 1.0) or 1.0),
                        "benchmark_threshold": float(result.get("benchmark_threshold", float("nan")) or float("nan")),
                        "universe_b_sharpe": float(result.get("universe_b_sharpe", float("nan")) or float("nan")),
                        "universe_b_n_tickers": int(result.get("universe_b_n_tickers", 0) or 0),
                        "factor_alpha_annualized": float(result.get("factor_alpha_annualized", 0.0) or 0.0),
                        "factor_alpha_tstat": float(result.get("factor_alpha_tstat", 0.0) or 0.0),
                        "factor_alpha_reason": str(result.get("factor_alpha_reason", "")),
                    },
                    "gate_passed": {
                        "gate_1": bool(result.get("gate_1_passed", False)),
                        "gate_2": bool(result.get("gate_2_passed", False)),
                        "gate_3_evaluated": bool(result.get("gate_3_evaluated", False)),
                        "gate_4": bool(result.get("gate_4_passed", False)),
                        "gate_5": bool(result.get("gate_5_passed", False)),
                        "gate_6": bool(result.get("gate_6_passed", False)),
                    },
                    "passed_all_gates": bool(result.get("passed_all_gates", False)),
                }
                import json as _json
                from pathlib import Path as _Path
                _p = _Path(diagnostic_log_path)
                _p.parent.mkdir(parents=True, exist_ok=True)
                with open(_p, "a") as _f:
                    _f.write(_json.dumps(rec) + "\n")
            except Exception as _emit_err:
                print(f"[DISCOVERY-DIAG] emit failed: {_emit_err}")

        try:
            # ---------------------------------------------------------------
            # Setup: build production-equivalent baseline + with-candidate
            # edge ensembles. Run pure backtests for both. Compute
            # attribution stream from the diff.
            # ---------------------------------------------------------------
            if not data_map:
                _diag_error = "empty_data_map"
                _emit_diag()
                return result

            cand_id = candidate_spec["edge_id"]
            first_ticker = list(data_map.keys())[0]
            if start_date is None:
                start_date = data_map[first_ticker].index[0].isoformat()
            if end_date is None:
                end_date = data_map[first_ticker].index[-1].isoformat()

            # Default exec_params: cheap 5bps for discovery scans; callers
            # passing realistic-cost ADV-bucketed Almgren-Chriss configs
            # override this.
            _exec_params = exec_params if exec_params is not None else {"slippage_bps": 5.0}

            # Lazy-load alpha config so soft-pause weights match production.
            if alpha_config is None:
                try:
                    from utils.config_loader import load_json
                    repo_root = Path(__file__).resolve().parents[2]
                    alpha_config = load_json(
                        str(repo_root / "config" / "alpha_settings.prod.json")
                    )
                except Exception:
                    alpha_config = {}

            # Build the baseline ensemble (production minus this candidate)
            baseline_edges, baseline_weights = self._build_production_edges(
                registry_path=self.registry_path,
                alpha_config=alpha_config,
                exclude_edge_ids={cand_id},
            )

            # Build the with-candidate ensemble (baseline + candidate at default weight)
            cand_edge = self._instantiate_candidate(candidate_spec)
            with_edges = dict(baseline_edges)
            with_edges[cand_id] = cand_edge
            with_weights = dict(baseline_weights)
            with_weights[cand_id] = float(candidate_default_weight)

            # Caching: if the orchestrator passed a cache, fingerprint and
            # reuse the baseline; the with-candidate run is candidate-
            # specific and not cacheable.
            local_cache = cache if cache is not None else PureBacktestCache()

            run_kwargs = dict(
                data_map=data_map,
                start_date=start_date,
                end_date=end_date,
                exec_params=_exec_params,
                initial_capital=100_000.0,
                alpha_config=alpha_config,
                risk_settings=risk_settings,
                portfolio_settings=portfolio_settings,
            )

            _g1_t0 = _time.time()
            baseline_result = local_cache.get_or_run(
                edges=baseline_edges,
                edge_weights=baseline_weights,
                **run_kwargs,
            )
            with_candidate_result = run_backtest_pure(
                edges=with_edges,
                edge_weights=with_weights,
                **run_kwargs,
            )

            # Pull Sharpes
            baseline_sharpe = float(baseline_result.metrics.get("Sharpe Ratio", 0.0))
            with_candidate_sharpe = float(
                with_candidate_result.metrics.get("Sharpe Ratio", 0.0)
            )
            contribution = with_candidate_sharpe - baseline_sharpe
            result["baseline_sharpe"] = baseline_sharpe
            result["with_candidate_sharpe"] = with_candidate_sharpe
            result["contribution_sharpe"] = contribution
            # `sharpe` retained for backward-compat consumers (orchestrator
            # passed_all_gates final-check, fitness score, GA selection).
            # Now reports the with-candidate ensemble Sharpe rather than a
            # standalone single-edge Sharpe.
            result["sharpe"] = with_candidate_sharpe
            result["sortino"] = float(
                with_candidate_result.metrics.get("Sortino", 0.0)
            )

            # Attribution stream = with - baseline (treatment effect).
            attribution = treatment_effect_returns(
                with_candidate_result.daily_returns,
                baseline_result.daily_returns,
            )
            attribution_sharpe = stream_sharpe(attribution)
            result["attribution_sharpe"] = attribution_sharpe
            attr_diag = attribution_diagnostics(attribution, capital=100_000.0)
            result["attribution_diagnostics"] = attr_diag

            # ---- Gate 1: Sharpe contribution ----
            # Pass criterion: with-candidate Sharpe lifts the baseline by
            # at least `gate1_contribution_threshold` (default 0.10).
            # This replaces the legacy benchmark-relative standalone gate
            # which kills 30/30 candidates that have positive ensemble
            # contribution (Audit doc discovery_diagnostic_2026_05.md).
            result["gate_1_passed"] = bool(contribution > gate1_contribution_threshold)
            result["benchmark_threshold"] = float(gate1_contribution_threshold)
            if not result["gate_1_passed"]:
                print(
                    f"[DISCOVERY] {cand_id} failed Gate 1 "
                    f"(contribution={contribution:+.3f} <= {gate1_contribution_threshold})"
                )
                _stamp("gate_1", _g1_t0)
                _emit_diag()
                return result
            _stamp("gate_1", _g1_t0)

            # ---- Gate 2: PBO survival on attribution stream ----
            _g2_t0 = _time.time()
            survival_rate = 0.0
            try:
                tester = RobustnessTester()
                pbo = tester.calculate_pbo_returns_stream(
                    attribution, n_paths=200, block_size=20, seed=42,
                )
                survival_rate = pbo.get("survival_rate", 0.0)
                result["pbo_actual_sharpe"] = pbo.get("actual_sharpe", 0.0)
                result["pbo_avg_synthetic_sharpe"] = pbo.get("avg_synthetic_sharpe", 0.0)
            except Exception as e:
                if isinstance(e, (TypeError, AttributeError, NameError, AssertionError, ImportError)):
                    raise
                print(f"[Gate 2] {type(e).__name__}: {e}")
                survival_rate = 0.0

            result["robustness_survival"] = float(survival_rate)
            result["gate_2_passed"] = bool(survival_rate >= gate2_survival_threshold)
            _stamp("gate_2", _g2_t0)

            # ---- Gate 3: WFO consistency on attribution stream ----
            # Replaces hyperparameter-optimization WFO with a simpler
            # rolling-window Sharpe-consistency check on the attribution
            # stream (the architectural fix means the candidate's
            # contribution is the right substrate, not its standalone
            # parameters). Computes mean rolling-63d Sharpe and divides
            # by overall Sharpe — > threshold means contribution is
            # temporally stable.
            _g3_t0 = _time.time()
            wfo_consistency = 0.0
            try:
                if len(attribution) >= 126:  # need at least 2 windows of 63d
                    win = 63  # ~3 months of trading days
                    rolling_sharpes = []
                    for start_i in range(0, len(attribution) - win + 1, win // 2):
                        chunk = attribution.iloc[start_i : start_i + win]
                        s = stream_sharpe(chunk)
                        rolling_sharpes.append(s)
                    if rolling_sharpes and attribution_sharpe > 0:
                        mean_window_sharpe = float(np.mean(rolling_sharpes))
                        wfo_consistency = mean_window_sharpe / attribution_sharpe
                        result["wfo_oos_sharpe"] = mean_window_sharpe
                        result["wfo_is_sharpe"] = float(attribution_sharpe)
                        result["wfo_window_sharpes"] = [float(x) for x in rolling_sharpes]
            except Exception as e:
                if isinstance(e, (TypeError, AttributeError, NameError, AssertionError, ImportError)):
                    raise
                print(f"[Gate 3] {type(e).__name__}: {e}")

            result["wfo_degradation"] = float(wfo_consistency)
            result["gate_3_evaluated"] = bool(wfo_consistency != 0.0)
            _stamp("gate_3", _g3_t0)

            # ---- Gate 4: Permutation significance on attribution stream ----
            _g4_t0 = _time.time()
            sig_p = 1.0
            try:
                from engines.engine_d_discovery.significance import (
                    monte_carlo_permutation_test,
                )
                sig_result = monte_carlo_permutation_test(
                    attribution.values, n_permutations=500,
                )
                sig_p = sig_result.get("p_value", 1.0)
            except Exception as e:
                if isinstance(e, (TypeError, AttributeError, NameError, AssertionError, ImportError)):
                    raise
                print(f"[Gate 4] {type(e).__name__}: {e}")
                sig_p = 1.0

            result["significance_p"] = float(sig_p)
            # None threshold means "skip" — but skip cannot pass; failing
            # closed is the correct default for an un-runnable gate.
            if significance_threshold is None:
                result["gate_4_passed"] = False
            else:
                result["gate_4_passed"] = bool(sig_p < significance_threshold)
            _stamp("gate_4", _g4_t0)

            # ---- Gate 5: Universe-B production-equivalent transfer ----
            _g5_t0 = _time.time()
            universe_b_sharpe: float = float("nan")
            universe_b_n_tickers: int = 0
            universe_b_contribution: float = float("nan")
            try:
                dm_b = self._load_universe_b(prod_tickers=set(data_map.keys()))
                universe_b_n_tickers = len(dm_b)
                if not dm_b:
                    print(f"[DISCOVERY] Gate 5 skipped: no universe-B tickers available")
                else:
                    # Production-equivalent ensemble on Universe-B too.
                    # Run baseline + with-candidate; contribution = diff.
                    ub_start = list(dm_b.values())[0].index[0].isoformat()
                    ub_end = list(dm_b.values())[0].index[-1].isoformat()
                    ub_run_kwargs = dict(
                        data_map=dm_b,
                        start_date=ub_start,
                        end_date=ub_end,
                        exec_params=_exec_params,
                        initial_capital=100_000.0,
                        alpha_config=alpha_config,
                        risk_settings=risk_settings,
                        portfolio_settings=portfolio_settings,
                    )
                    ub_baseline = run_backtest_pure(
                        edges=baseline_edges,
                        edge_weights=baseline_weights,
                        **ub_run_kwargs,
                    )
                    ub_with = run_backtest_pure(
                        edges=with_edges,
                        edge_weights=with_weights,
                        **ub_run_kwargs,
                    )
                    ub_contribution = (
                        float(ub_with.metrics.get("Sharpe Ratio", 0.0))
                        - float(ub_baseline.metrics.get("Sharpe Ratio", 0.0))
                    )
                    ub_attribution = treatment_effect_returns(
                        ub_with.daily_returns, ub_baseline.daily_returns,
                    )
                    universe_b_sharpe = stream_sharpe(ub_attribution)
                    universe_b_contribution = ub_contribution
            except Exception as e:
                if isinstance(e, (TypeError, AttributeError, NameError, AssertionError, ImportError)):
                    raise
                print(f"[Gate 5] {type(e).__name__}: {e}")
                universe_b_sharpe = float("nan")
                universe_b_contribution = float("nan")

            result["universe_b_sharpe"] = universe_b_sharpe
            result["universe_b_contribution"] = universe_b_contribution
            result["universe_b_n_tickers"] = universe_b_n_tickers
            # NaN means we couldn't measure — fail closed. Previously NaN
            # short-circuited to pass, which let any gate-5 setup error
            # silently green-light a candidate.
            result["gate_5_passed"] = bool(
                not math.isnan(universe_b_sharpe) and universe_b_sharpe > 0
            )
            _stamp("gate_5", _g5_t0)

            # ---- Gate 6: FF5+Mom factor decomposition on attribution stream ----
            _g6_t0 = _time.time()
            # Fail-closed default: a candidate that cannot prove non-trivial
            # alpha vs FF5+Mom should not pass on the absence of evidence.
            # FileNotFoundError (missing factor cache) is the one preserved
            # skip-pass case — no factor data available at all is an
            # operational state, not an attribute of the candidate.
            factor_alpha_passed = False
            factor_alpha_reason = "failed: not run"
            try:
                from core.factor_decomposition import (
                    load_factor_data,
                    regress_returns_on_factors,
                    gate_factor_alpha,
                )
                factors = load_factor_data(auto_download=False)
                decomp = regress_returns_on_factors(
                    returns=attribution,
                    factors=factors,
                    edge_name=cand_id,
                )
                factor_alpha_passed, factor_alpha_reason = gate_factor_alpha(decomp)
                if decomp is not None:
                    result["factor_alpha_annualized"] = decomp.alpha_annualized
                    result["factor_alpha_tstat"] = decomp.alpha_tstat
                    result["factor_r_squared"] = decomp.r_squared
            except FileNotFoundError as e:
                factor_alpha_passed = True
                factor_alpha_reason = "skipped: factor cache missing"
                print(f"[DISCOVERY] Gate 6 skipped: {e}")
            except Exception as e:
                if isinstance(e, (TypeError, AttributeError, NameError, AssertionError, ImportError)):
                    raise
                factor_alpha_passed = False
                factor_alpha_reason = f"failed: {type(e).__name__}"
                print(f"[Gate 6] {type(e).__name__}: {e}")

            result["factor_alpha_passed"] = factor_alpha_passed
            result["factor_alpha_reason"] = factor_alpha_reason
            result["gate_6_passed"] = bool(factor_alpha_passed)
            _stamp("gate_6", _g6_t0)
            if not factor_alpha_passed:
                print(f"[DISCOVERY] {cand_id} failed Gate 6 ({factor_alpha_reason})")

            # ---- Final pass check ----
            # Fail-closed: a None threshold or NaN universe-B reading both
            # mean the gate could not be evaluated, which is not the same
            # as evidence of a pass.
            if significance_threshold is None:
                sig_passed = False
                sig_threshold_for_log = float("nan")
            else:
                sig_passed = sig_p < significance_threshold
                sig_threshold_for_log = significance_threshold

            universe_b_passed = (
                not math.isnan(universe_b_sharpe) and universe_b_sharpe > 0
            )

            passed = (
                contribution > gate1_contribution_threshold
                and survival_rate >= gate2_survival_threshold
                and sig_passed
                and universe_b_passed
                and factor_alpha_passed
            )
            result["passed_all_gates"] = passed
            result["significance_threshold"] = sig_threshold_for_log

            b_sharpe_str = (
                "skipped" if math.isnan(universe_b_sharpe)
                else f"{universe_b_sharpe:.2f}"
            )
            gate_summary = (
                f"contrib={contribution:+.3f}, "
                f"attr_sh={attribution_sharpe:.2f}, "
                f"survival={survival_rate:.0%}, "
                f"wfo_cons={wfo_consistency:.2f}, "
                f"p={sig_p:.3f}, "
                f"univ_b={b_sharpe_str}({universe_b_n_tickers}t), "
                f"alpha={factor_alpha_reason}"
            )
            if passed:
                print(f"[DISCOVERY] {cand_id} PASSED all gates: {gate_summary}")
            else:
                print(f"[DISCOVERY] {cand_id} FAILED gates: {gate_summary}")

            # Composite fitness score: weight the contribution Sharpe lift
            # heavily (production-relevant). Survival + WFO consistency are
            # secondary stability signals.
            result["fitness_score"] = float(
                0.5 * contribution
                + 0.3 * float(survival_rate)
                + 0.2 * float(max(0.0, min(1.0, wfo_consistency)))
            )

            _emit_diag()
            return result

        except Exception as e:
            # Programmer errors must propagate so they surface in CI / logs
            # instead of silently masking a candidate as "failed validation."
            if isinstance(e, (TypeError, AttributeError, NameError, AssertionError, ImportError)):
                _diag_error = f"{type(e).__name__}: {e}"
                _emit_diag()
                raise
            print(f"[validate_candidate] {type(e).__name__}: {e}")
            _diag_error = f"{type(e).__name__}: {e}"
            _emit_diag()
            return result

if __name__ == "__main__":
    # Test run
    disc = DiscoveryEngine()
    cands = disc.generate_candidates(n_mutations=3)
    print(f"Generated {len(cands)} candidates.")
    # In main block we don't have data_map, so we skip validation call
    disc.save_candidates(cands)
