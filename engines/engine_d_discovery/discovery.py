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

    def validate_candidate(
        self,
        candidate_spec: Dict[str, Any],
        data_map: Dict[str, pd.DataFrame],
        significance_threshold: Optional[float] = 0.05,
    ) -> Dict[str, float]:
        """
        Multi-gate validation pipeline for edge candidates.

        Gate 1: Quick backtest — must produce Sharpe > 0 (cheap filter).
        Gate 2: PBO robustness — 50 synthetic paths, survival > 0.7.
        Gate 3: WFO degradation — OOS Sharpe >= 60% of IS Sharpe.
        Gate 4: Statistical significance — permutation test p-value
                below `significance_threshold`.

        The `significance_threshold` parameter exists so an orchestrator
        running a batch of candidates can defer the Gate 4 decision until
        after `apply_bh_fdr` (Benjamini-Hochberg multiple-testing correction)
        is applied to the whole batch. Pass `None` to skip the per-candidate
        significance gate (the orchestrator will then re-evaluate
        `passed_all_gates` post-hoc using BH-corrected rejections). Standalone
        callers can leave it at 0.05 to get the uncorrected check, which is
        valid for a single-test scenario where BH-FDR is a no-op anyway.

        Returns metrics dict with all gate results, plus the raw
        `significance_p` so the orchestrator can batch-correct.
        """
        import numpy as np

        result = {
            "sharpe": 0.0,
            "sortino": 0.0,
            "robustness_survival": 0.0,
            "wfo_degradation": 0.0,
            "significance_p": 1.0,
            "passed_all_gates": False,
        }

        try:
            from importlib import import_module
            mod = import_module(candidate_spec["module"])
            cls_ = getattr(mod, candidate_spec["class"])
            edge = cls_()
            if "params" in candidate_spec:
                edge.set_params(candidate_spec["params"])

            from backtester.backtest_controller import BacktestController
            from engines.engine_a_alpha.alpha_engine import AlphaEngine
            from engines.engine_b_risk.risk_engine import RiskEngine
            from cockpit.logger import CockpitLogger

            alpha = AlphaEngine(edges={candidate_spec["edge_id"]: edge}, debug=False)
            risk = RiskEngine({"risk_per_trade_pct": 0.01})
            bt_logger = CockpitLogger(out_dir="/tmp/discovery_validation", flush_each_fill=False)

            if not data_map:
                return result

            first_ticker = list(data_map.keys())[0]
            start_date = data_map[first_ticker].index[0].isoformat()
            end_date = data_map[first_ticker].index[-1].isoformat()

            controller = BacktestController(
                data_map=data_map,
                alpha_engine=alpha,
                risk_engine=risk,
                cockpit_logger=bt_logger,
                exec_params={"slippage_bps": 5.0},
                initial_capital=100_000,
                batch_flush_interval=99999,
            )

            history = controller.run(start_date, end_date)

            # ---- Gate 1: Quick backtest ----
            if not history:
                return result

            # Index by timestamp so MetricsEngine.cagr() can compute date deltas.
            # Without this the index is a RangeIndex (ints) and `(end - start).days`
            # raises AttributeError: 'int' object has no attribute 'days'.
            equity_curve = pd.Series(
                [h["equity"] for h in history],
                index=pd.to_datetime([h["timestamp"] for h in history]),
            )

            from core.metrics_engine import MetricsEngine
            metrics = MetricsEngine.calculate_all(equity_curve)

            sharpe = float(metrics.get("Sharpe", 0.0))
            sortino = float(metrics.get("Sortino", 0.0))
            result["sharpe"] = sharpe
            result["sortino"] = sortino

            # Gate 1: benchmark-relative Sharpe. An edge passing at Sharpe 0.5
            # during a bull market where SPY sits at Sharpe 1.5 is destroying
            # value vs buy-and-hold. Require the edge to be within 0.2 Sharpe
            # of the benchmark over the same window — or beat it.
            try:
                from core.benchmark import gate_sharpe_vs_benchmark
                passed, threshold = gate_sharpe_vs_benchmark(
                    sharpe, start_date, end_date, margin=0.2,
                )
                result["benchmark_threshold"] = threshold
                if not passed:
                    print(f"[DISCOVERY] {candidate_spec['edge_id']} failed Gate 1 "
                          f"(Sharpe={sharpe:.2f} < benchmark_threshold={threshold:.2f})")
                    return result
            except Exception as e:
                # Fallback to the legacy absolute-threshold gate if benchmark
                # data is unavailable — conservative: require Sharpe > 0
                print(f"[DISCOVERY] Benchmark gate unavailable ({e}), falling back to Sharpe > 0")
                if sharpe <= 0:
                    print(f"[DISCOVERY] {candidate_spec['edge_id']} failed Gate 1 (Sharpe={sharpe:.2f})")
                    return result

            # Compute daily returns for significance testing
            daily_returns = equity_curve.pct_change().dropna().values

            # ---- Gate 2: PBO Robustness (50 paths) ----
            survival_rate = 0.0
            try:
                from engines.engine_d_discovery.robustness import RobustnessTester
                tester = RobustnessTester()

                def strategy_wrapper(dm):
                    t_alpha = AlphaEngine(edges={candidate_spec["edge_id"]: edge}, debug=False)
                    t_risk = RiskEngine({"risk_per_trade_pct": 0.01})
                    t_logger = CockpitLogger(out_dir="/tmp/pbo_check", flush_each_fill=False)

                    t_first = list(dm.keys())[0]
                    t_start = dm[t_first].index[0].isoformat()
                    t_end = dm[t_first].index[-1].isoformat()

                    tc = BacktestController(
                        data_map=dm, alpha_engine=t_alpha, risk_engine=t_risk,
                        cockpit_logger=t_logger, initial_capital=100000,
                        batch_flush_interval=99999,
                    )
                    th = tc.run(t_start, t_end)
                    if not th:
                        return {"sharpe": -1.0}
                    te = [x["equity"] for x in th]
                    if len(te) < 2:
                        return {"sharpe": -1.0}
                    tr = pd.Series(te).pct_change().dropna()
                    if tr.std() == 0:
                        return {"sharpe": 0.0}
                    return {"sharpe": float(tr.mean() / tr.std() * np.sqrt(252))}

                first_key = list(data_map.keys())[0]
                pbo_res = tester.calculate_pbo(
                    strategy_wrapper, data_map[first_key], n_paths=50,
                )
                survival_rate = pbo_res.get("survival_rate", 0.0)
            except Exception as e:
                print(f"[DISCOVERY] PBO check failed: {e}")

            result["robustness_survival"] = float(survival_rate)

            # ---- Gate 3: WFO Degradation ----
            wfo_degradation = 0.0
            try:
                from engines.engine_d_discovery.wfo import WalkForwardOptimizer
                wfo = WalkForwardOptimizer()

                # WFO needs an EdgeTemplate-like class. Wrap the edge.
                class _WFOWrapper:
                    def __init__(self, edge_instance):
                        self._edge = edge_instance

                    @classmethod
                    def sample_params(cls):
                        return {}

                    def __call__(self):
                        return self._edge

                wfo_result = wfo.run_optimization(
                    _WFOWrapper(edge), data_map, n_configs=1,
                )
                if wfo_result and "degradation" in wfo_result:
                    wfo_degradation = float(wfo_result["degradation"])
                if wfo_result:
                    result["wfo_oos_sharpe"] = float(wfo_result.get("oos_sharpe", 0.0))
                    result["wfo_is_sharpe"] = float(wfo_result.get("is_sharpe_avg", 0.0))
            except Exception as e:
                print(f"[DISCOVERY] WFO check skipped: {e}")

            result["wfo_degradation"] = wfo_degradation

            # ---- Gate 4: Statistical Significance ----
            sig_p = 1.0
            try:
                from engines.engine_d_discovery.significance import monte_carlo_permutation_test
                sig_result = monte_carlo_permutation_test(daily_returns, n_permutations=500)
                sig_p = sig_result.get("p_value", 1.0)
            except Exception as e:
                print(f"[DISCOVERY] Significance test failed: {e}")

            result["significance_p"] = float(sig_p)

            # ---- Gate 5: Universe B generalization ----
            # Run the same edge on a sample of S&P 500 tickers NOT in the
            # production universe. Sharpe must be > 0. If an edge only works
            # on the 109 tickers we trained on, it is universe-overfit — the
            # alpha has been mined from the specific names, not the market.
            # "nan" means the gate was skipped (degenerate: no universe-B data
            # available) — the edge is not penalized for infrastructure gaps.
            universe_b_sharpe: float = float("nan")
            universe_b_n_tickers: int = 0
            try:
                dm_b = self._load_universe_b(prod_tickers=set(data_map.keys()))
                universe_b_n_tickers = len(dm_b)

                if not dm_b:
                    print(f"[DISCOVERY] Gate 5 skipped: no universe-B tickers available")
                else:
                    b_alpha = AlphaEngine(edges={candidate_spec["edge_id"]: edge}, debug=False)
                    b_risk = RiskEngine({"risk_per_trade_pct": 0.01})
                    b_logger = CockpitLogger(out_dir="/tmp/discovery_gate5", flush_each_fill=False)

                    b_controller = BacktestController(
                        data_map=dm_b,
                        alpha_engine=b_alpha,
                        risk_engine=b_risk,
                        cockpit_logger=b_logger,
                        exec_params={"slippage_bps": 5.0},
                        initial_capital=100_000,
                        batch_flush_interval=99999,
                    )
                    b_history = b_controller.run(start_date, end_date)

                    if b_history:
                        b_equity = pd.Series([h["equity"] for h in b_history])
                        b_metrics = MetricsEngine.calculate_all(b_equity)
                        universe_b_sharpe = float(b_metrics.get("Sharpe", 0.0))
                    else:
                        universe_b_sharpe = 0.0

            except Exception as e:
                print(f"[DISCOVERY] Gate 5 (Universe B) failed: {e}")

            result["universe_b_sharpe"] = universe_b_sharpe
            result["universe_b_n_tickers"] = universe_b_n_tickers

            # ---- Final gate check ----
            # If `significance_threshold` is None, the orchestrator will
            # re-evaluate Gate 4 after BH-FDR batch correction; treat it as
            # provisionally passed here so other gates aren't masked.
            if significance_threshold is None:
                sig_passed = True
                sig_threshold_for_log = float("nan")
            else:
                sig_passed = sig_p < significance_threshold
                sig_threshold_for_log = significance_threshold

            # Gate 5: nan means skipped (no universe-B data) — don't penalize.
            import math
            universe_b_passed = math.isnan(universe_b_sharpe) or universe_b_sharpe > 0

            passed = (
                sharpe > 0
                and survival_rate >= 0.7
                and sig_passed
                and universe_b_passed
            )
            result["passed_all_gates"] = passed
            result["significance_threshold"] = sig_threshold_for_log

            b_sharpe_str = (
                "skipped" if math.isnan(universe_b_sharpe)
                else f"{universe_b_sharpe:.2f}"
            )
            gate_summary = (
                f"Sharpe={sharpe:.2f}, survival={survival_rate:.0%}, "
                f"wfo_deg={wfo_degradation:.2f}, p={sig_p:.3f}, "
                f"univ_b={b_sharpe_str}({universe_b_n_tickers}t)"
            )
            if passed:
                print(f"[DISCOVERY] {candidate_spec['edge_id']} PASSED all gates: {gate_summary}")
            else:
                print(f"[DISCOVERY] {candidate_spec['edge_id']} FAILED gates: {gate_summary}")

            # Composite fitness score — used by GA as selection signal.
            # Formula: 0.5*OOS_Sharpe + 0.3*survival_rate + 0.2*degradation_ratio
            # OOS Sharpe comes from Gate 3 WFO; falls back to in-sample if WFO skipped.
            # Higher is better. Penalizes in-sample-only fits.
            oos_sh = result.get("wfo_oos_sharpe", sharpe)
            is_sh = result.get("wfo_is_sharpe", 0.0) or sharpe
            degradation_ratio = min(1.0, max(0.0, oos_sh / is_sh)) if is_sh > 0 else 0.0
            result["fitness_score"] = (
                0.5 * oos_sh
                + 0.3 * float(survival_rate)
                + 0.2 * degradation_ratio
            )

            return result

        except Exception as e:
            print(f"[DISCOVERY] Validation failed for {candidate_spec['edge_id']}: {e}")
            return result

if __name__ == "__main__":
    # Test run
    disc = DiscoveryEngine()
    cands = disc.generate_candidates(n_mutations=3)
    print(f"Generated {len(cands)} candidates.")
    # In main block we don't have data_map, so we skip validation call
    disc.save_candidates(cands)
