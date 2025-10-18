# engines/engine_a_alpha/alpha_engine.py
"""
AlphaEngine (Engine A)
======================

Purpose
-------
Convert raw per-edge scores into clean, risk-aware, portfolio-ready *signals*.

Key features
------------
- Per-edge score normalization to [-1, +1]
- Optional trend & volatility regime gates (config-driven)
- Signal hygiene: min history, NaN/inf handling, de-duplication
- Flip cooldown (rate-limit side changes)
- Ensemble shrinkage to avoid over-confident aggregates
- Clean output for Engine B: [{'ticker','side','strength','meta':{...}}]

Inputs
------
- data_map: dict[ticker] -> pd.DataFrame (index=datetime, columns include 'Close', 'High','Low')
- now: pd.Timestamp of the bar being evaluated

Outputs
-------
- List[dict] where each dict contains:
    ticker: str
    side:   'long' | 'short'
    strength: float in [0, 1] (magnitude of conviction)
    meta:   { 'edges_triggered': [{'edge','raw','norm','weight'}],
              'regimes': {'trend': bool, 'vol_ok': bool} }

Config
------
- read from config/alpha_settings.json (see example in repo)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import json
import math
import numpy as np
import pandas as pd

from .signal_collector import SignalCollector
from .signal_processor import SignalProcessor, RegimeSettings, HygieneSettings, EnsembleSettings
from .signal_formatter import SignalFormatter

from typing import Optional
from engines.engine_d_research.governor import StrategyGovernor


# ----------------------------- Data classes ----------------------------- #

@dataclass
class AlphaConfig:
    """Configuration container for AlphaEngine."""

    # thresholds to create a discrete side from aggregate score
    enter_threshold: float = 0.2
    exit_threshold: float = 0.05

    # regime gates
    regime: RegimeSettings = field(default_factory=RegimeSettings)

    # hygiene
    hygiene: HygieneSettings = field(default_factory=HygieneSettings)

    # ensemble shrinkage
    ensemble: EnsembleSettings = field(default_factory=EnsembleSettings)

    # edge-specific weights (multiplies normalized scores before aggregation)
    edge_weights: Dict[str, float] = field(default_factory=dict)

    # cooldown: bars to wait after a flip
    flip_cooldown_bars: int = 5

    # minimum contribution to include an edge in meta
    min_edge_contribution: float = 0.05

    # debug prints
    debug: bool = False


def _load_json(path: Path) -> dict:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return {}


def _coerce_float(x, default: float = 0.0) -> float:
    try:
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


# ----------------------------- Engine ----------------------------- #

class AlphaEngine:
    """
    Main class orchestrating Edge collection -> processing -> aggregation -> signals.
    """
    def __init__(
        self,
        edges: Dict[str, object],
        edge_weights: Optional[Dict[str, float]] = None,
        config_path: Optional[str] = None,
        debug: bool = True,
        governor: Optional["StrategyGovernor"] = None,  # NEW
    ):
        # 1️⃣ Initialize base edges
        self.edges = dict(edges or {})

        # 2️⃣ Try to import our test edge dynamically
        import importlib
        try:
            test_edge = importlib.import_module("engines.engine_a_alpha.edges.test_edge")
            self.edges["test_edge"] = test_edge
            print(f"[ALPHA][DEBUG] test_edge imported successfully: {test_edge}")
        except Exception as e:
            print(f"[ALPHA][DEBUG] Failed to import test_edge: {e}")

        # 3️⃣ Print out all loaded edges for confirmation
        print(f"[ALPHA][DEBUG] Active edges after init: {list(self.edges.keys())}")

        # 4️⃣ Continue with the rest of your existing code
        self._edge_weights_external = dict(edge_weights or {})
        self.debug = bool(debug)
        self.governor = governor  # optional reference

        # Load config (file overrides defaults; CLI overrides file)
        cfg_file = Path(config_path) if config_path else Path("config/alpha_settings.json")
        cfg_raw = _load_json(cfg_file)

        # Build AlphaConfig from JSON (with sensible defaults)
        regime = RegimeSettings(
            enable_trend=bool(cfg_raw.get("regime", {}).get("enable_trend", True)),
            trend_fast=int(cfg_raw.get("regime", {}).get("trend_fast", 20)),
            trend_slow=int(cfg_raw.get("regime", {}).get("trend_slow", 50)),
            enable_vol=bool(cfg_raw.get("regime", {}).get("enable_vol", True)),
            vol_lookback=int(cfg_raw.get("regime", {}).get("vol_lookback", 20)),
            vol_z_max=_coerce_float(cfg_raw.get("regime", {}).get("vol_z_max", 2.5)),
            shrink_off=_coerce_float(cfg_raw.get("regime", {}).get("shrink_off", 0.3)),
        )

        hygiene = HygieneSettings(
            min_history=int(cfg_raw.get("hygiene", {}).get("min_history", 60)),
            dedupe_last_n=int(cfg_raw.get("hygiene", {}).get("dedupe_last_n", 1)),
            clamp=_coerce_float(cfg_raw.get("hygiene", {}).get("clamp", 6.0)),  # raw clamp before norm
        )

        ensemble = EnsembleSettings(
            enable_shrink=bool(cfg_raw.get("ensemble", {}).get("enable_shrink", True)),
            shrink_lambda=_coerce_float(cfg_raw.get("ensemble", {}).get("shrink_lambda", 0.35)),
            combine="weighted_mean",
        )

        self.cfg = AlphaConfig(
            enter_threshold=_coerce_float(cfg_raw.get("enter_threshold", 0.2)),
            exit_threshold=_coerce_float(cfg_raw.get("exit_threshold", 0.05)),
            regime=regime,
            hygiene=hygiene,
            ensemble=ensemble,
            edge_weights=cfg_raw.get("edge_weights", {}),
            flip_cooldown_bars=int(cfg_raw.get("flip_cooldown_bars", 5)),
            min_edge_contribution=_coerce_float(cfg_raw.get("min_edge_contribution", 0.05)),
            debug=bool(cfg_raw.get("debug", debug)),
        )

        # External edge weight overrides (e.g., Governor later)
        for k, v in self._edge_weights_external.items():
            self.cfg.edge_weights[k] = _coerce_float(v, 1.0)

        # Components
        self.collector = SignalCollector(edges=self.edges, debug=self.cfg.debug)
        self.processor = SignalProcessor(
            regime=self.cfg.regime,
            hygiene=self.cfg.hygiene,
            ensemble=self.cfg.ensemble,
            edge_weights=self.cfg.edge_weights,
            debug=self.cfg.debug,
        )
        self.formatter = SignalFormatter(
            enter_threshold=self.cfg.enter_threshold,
            exit_threshold=self.cfg.exit_threshold,
            min_edge_contribution=self.cfg.min_edge_contribution,
        )

        # State for cooldown & last known side per ticker
        self._last_side: Dict[str, Optional[str]] = {}
        self._last_flip_ts: Dict[str, Optional[pd.Timestamp]] = {}

    # ------------------------------------------------------------------ #

    def _cooldown_blocks(self, ticker: str, proposed_side: Optional[str], now: pd.Timestamp) -> bool:
        """
        Returns True if flip cooldown should block a new side for this ticker.
        """
        if proposed_side is None:
            return False
        last = self._last_side.get(ticker)
        if last is None:
            return False
        if last == proposed_side:
            return False
        # Enforce bars since flip
        last_ts = self._last_flip_ts.get(ticker)
        if last_ts is None:
            return False
        # In bar-based world, we approximate cooldown by requiring at least N bars elapsed.
        # Caller passes a single bar timestamp 'now'; we can't count bars without the index length.
        # We rely on SignalProcessor supplying a sequential 'bar_index' if needed. For MVP, skip.
        # To keep behavior: block the *first* change after a recent flip (stored as same day).
        if (now.normalize() == last_ts.normalize()):
            return True
        return False

    def _update_flip_state(self, ticker: str, new_side: Optional[str], now: pd.Timestamp) -> None:
        last = self._last_side.get(ticker)
        if new_side is None:
            return
        if last is None:
            self._last_side[ticker] = new_side
            self._last_flip_ts[ticker] = now
            return
        if last != new_side:
            self._last_side[ticker] = new_side
            self._last_flip_ts[ticker] = now

    # ------------------------------------------------------------------ #

    def generate_signals(
        self,
        data_map: Dict[str, pd.DataFrame],
        now: pd.Timestamp,
    ) -> List[dict]:
        """
        Main entry point (used by BacktestController / PaperTradeController / LiveTradeController).

        Parameters
        ----------
        data_map : dict
            ticker -> DataFrame with at least 'Close' (ideally also 'High','Low')
        now : pd.Timestamp
            Bar timestamp being processed.

        Returns
        -------
        List[dict] of signals ready for Engine B.
        """
        if not data_map:
            return []

        if self.cfg.debug:
            print(f"[ALPHA][DEBUG] Active edges: {list(self.edges.keys())}")
        
        if self.cfg.debug:
            print(f"[ALPHA][DEBUG] Collecting signals from edges: {list(self.edges.keys())}")

        raw_scores: Dict[str, Dict[str, float]] = self.collector.collect(data_map, now)

        if self.cfg.debug:
            print(f"[ALPHA][DEBUG] Raw scores collected at {now}: {raw_scores}")

        # 2) Process: normalize, regime-gate, shrinkage, hygiene checks
        proc = self.processor.process(data_map, now, raw_scores)

        # 3) Aggregate per ticker and turn into discrete side if above thresholds
        signals: List[dict] = []
        for ticker, info in proc.items():
            agg = info["aggregate_score"]  # in [-1, +1] after normalization/shrinkage
            regimes = info["regimes"]
            edges_detail = info["edges_detail"]  # list of dicts per edge

            side, strength = self.formatter.to_side_and_strength(agg)

            # Cooldown (optional, light-touch): block flip immediately after a flip within same day
            if self._cooldown_blocks(ticker, side, now):
                side = None
                strength = 0.0

            if side is None:
                continue

            self._update_flip_state(ticker, side, now)

            # Package signal
            # Determine the primary contributing edge
            if edges_detail:
                # Choose the edge with the largest absolute normalized contribution
                top_edge = max(edges_detail, key=lambda ed: abs(ed["norm"] * ed["weight"]))
                edge_name = top_edge.get("edge", "Unknown")
                edge_group = top_edge.get("group", "technical")  # group is optional per-edge attribute
            else:
                edge_name = "Unknown"
                edge_group = "technical"

            # Package signal with explicit edge attribution
            signals.append({
                "ticker": ticker,
                "side": side,
                "strength": float(max(0.0, min(1.0, strength))),
                "edge": edge_name,
                "edge_group": edge_group,
                "meta": {
                    "edges_triggered": [
                        {
                            "edge": ed["edge"],
                            "raw": float(ed["raw"]),
                            "norm": float(ed["norm"]),
                            "weight": float(ed["weight"]),
                        }
                        for ed in edges_detail
                        if abs(ed["norm"] * ed["weight"]) >= self.cfg.min_edge_contribution
                    ],
                    "regimes": regimes,
                },
            })

        # Governor adjustment (if present)
        if self.governor and signals:
            weights = self.governor.get_edge_weights()
            for sig in signals:
                # Get the list of edges that fired for this ticker
                triggered_edges = sig.get("meta", {}).get("edges_triggered", [])
                if not triggered_edges:
                    continue
                # Average the governor weights of all contributing edges
                contrib_weights = [
                    float(weights.get(e["edge"], 1.0)) for e in triggered_edges
                ]
                avg_w = float(np.mean(contrib_weights)) if contrib_weights else 1.0
                sig["strength"] *= avg_w  # scale by edge-level weights
                sig["meta"]["governor_weight"] = round(avg_w, 3)

        if self.cfg.debug and signals:
            print(f"[ALPHA] {now} generated {len(signals)} signals")

        return signals
    
if __name__ == "__main__":
    import yfinance as yf
    import pandas as pd

    print("[DEBUG] Downloading test data for AAPL...")
    df = yf.download("AAPL", period="1y", interval="1d")

    ae = AlphaEngine(edges={}, debug=True)
    now = pd.Timestamp(df.index[-1])
    signals = ae.generate_signals({"AAPL": df}, now)

    print("\n[DEBUG] Example output:")
    print(signals)