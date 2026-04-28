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
from statistics import fmean
import numpy as np
import pandas as pd
import os

from .signal_collector import SignalCollector
from .signal_processor import SignalProcessor, RegimeSettings, HygieneSettings, EnsembleSettings
from .signal_formatter import SignalFormatter

from typing import Optional
from engines.engine_f_governance.governor import StrategyGovernor

from debug_config import is_debug_enabled

def is_info_enabled() -> bool:
    from debug_config import DEBUG_LEVELS
    return DEBUG_LEVELS.get("ALPHA_INFO", False)


# ----------------------------- Data classes ----------------------------- #

@dataclass
class AlphaConfig:
    """Configuration container for AlphaEngine."""

    # thresholds to create a discrete side from aggregate score
    enter_threshold: float = 0.1
    exit_threshold: float = 0.03

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
    """Load alpha settings safely, applying defaults and validation."""
    defaults = {
        "enter_threshold": 0.2,
        "exit_threshold": 0.05,
        "hygiene": {"min_history": 60, "dedupe_last_n": 1, "clamp": 6.0},
        "ensemble": {"enable_shrink": True, "shrink_lambda": 0.35},
        "min_edge_contribution": 0.05,
        "flip_cooldown_bars": 5,
    }

    def _validate_num(value, default, min_val=1e-6):
        try:
            v = float(value)
            if not math.isfinite(v) or v <= 0:
                return default
            return v
        except Exception:
            return default

    try:
        with open(path, "r") as f:
            cfg = json.load(f)
    except Exception:
        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][WARN] Could not load config {path}, using defaults.")
        return defaults

    # Merge defaults and sanitize
    for k, v in defaults.items():
        if k not in cfg:
            cfg[k] = v

    cfg["enter_threshold"] = _validate_num(cfg.get("enter_threshold"), defaults["enter_threshold"])
    cfg["exit_threshold"] = _validate_num(cfg.get("exit_threshold"), defaults["exit_threshold"])
    cfg["min_edge_contribution"] = _validate_num(cfg.get("min_edge_contribution"), defaults["min_edge_contribution"])
    cfg["flip_cooldown_bars"] = int(cfg.get("flip_cooldown_bars", defaults["flip_cooldown_bars"]))
    
    # Sanitize hygiene section
    hygiene = cfg.get("hygiene", {})
    hygiene["min_history"] = int(hygiene.get("min_history", defaults["hygiene"]["min_history"]))
    if hygiene["min_history"] <= 0:
        hygiene["min_history"] = defaults["hygiene"]["min_history"]
    hygiene["dedupe_last_n"] = int(hygiene.get("dedupe_last_n", defaults["hygiene"]["dedupe_last_n"]))
    hygiene["clamp"] = _validate_num(hygiene.get("clamp", defaults["hygiene"]["clamp"]), defaults["hygiene"]["clamp"])
    cfg["hygiene"] = hygiene

    # Sanitize ensemble section
    ensemble = cfg.get("ensemble", {})
    ensemble["enable_shrink"] = bool(ensemble.get("enable_shrink", defaults["ensemble"]["enable_shrink"]))
    ensemble["shrink_lambda"] = _validate_num(ensemble.get("shrink_lambda", defaults["ensemble"]["shrink_lambda"]),
                                              defaults["ensemble"]["shrink_lambda"])
    cfg["ensemble"] = ensemble

    if is_debug_enabled("ALPHA"):
        print(f"[ALPHA][DEBUG] Validated alpha config from {path}: enter={cfg['enter_threshold']} exit={cfg['exit_threshold']} "
              f"min_hist={cfg['hygiene']['min_history']} shrink_lambda={cfg['ensemble']['shrink_lambda']}")

    return cfg


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
    def _normalize_dataframe(self, df):
        """Standardize incoming market data from Alpaca, yfinance, or CSV to OHLCV format."""
        import pandas as pd
        if df is None or len(df) == 0:
            return df

        if isinstance(df, (list, dict)) and not isinstance(df, pd.DataFrame):
            df = pd.DataFrame(df)

        # --- Flatten multi-index columns (e.g., ('Close','AAPL')) ---
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = ["_".join(map(str, c)).strip() for c in df.columns]

        # --- Ensure column normalization (case-insensitive) ---
        rename_map = {
            "o": "Open", "h": "High", "l": "Low", "c": "Close", "v": "Volume",
            "open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume",
            "adj close": "Adj Close", "adjusted close": "Adj Close"
        }
        # Lowercase columns for matching, but preserve original casing
        col_map = {c.lower(): c for c in df.columns}
        # Build rename dict for columns present (case-insensitive)
        rename_actual = {}
        for k, v in rename_map.items():
            if k in col_map:
                rename_actual[col_map[k]] = v
        df = df.rename(columns=rename_actual)

        # --- Handle missing Close (fallbacks) ---
        if "Close" not in df.columns:
            if "Adj Close" in df.columns:
                df["Close"] = df["Adj Close"]
            elif len(df.columns) > 0:
                df["Close"] = pd.to_numeric(df.iloc[:, -1], errors="coerce")

        # --- Handle timestamp-based index if missing ---
        if not isinstance(df.index, pd.DatetimeIndex):
            ts_col = next((c for c in df.columns if "time" in c.lower() or "date" in c.lower()), None)
            if ts_col:
                df[ts_col] = pd.to_datetime(df[ts_col], errors="coerce")
                df = df.set_index(ts_col)
        df.index = pd.to_datetime(df.index, errors="coerce")
        df = df.sort_index()
        # Safely strip timezone (compatible with pandas ≥2.2)
        try:
            df.index = df.index.tz_localize(None)
        except TypeError:
            # Older pandas versions support `errors=`
            df.index = df.index.tz_localize(None, errors="ignore")

        # --- Drop invalid Close values safely ---
        if "Close" in df.columns:
            df = df.dropna(subset=["Close"])
        else:
            if is_debug_enabled("ALPHA"):
                print("[ALPHA][WARN] No 'Close' column found even after normalization; skipping dropna.")

        # --- Ensure numeric floats ---
        for col in ["Open", "High", "Low", "Close", "Volume"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce").astype(float)

        return df
    def __init__(
        self,
        edges: Dict[str, object],
        edge_weights: Optional[Dict[str, float]] = None,
        config_path: Optional[str] = None,
        debug: bool = True,
        governor: Optional["StrategyGovernor"] = None,  # NEW
        config: Optional[dict] = None,
    ):
        # 1️⃣ Initialize base edges
        self.edges = dict(edges or {})
        # --- Dynamically import edge modules if only names are given ---
        # Default edges only fire when caller doesn't supply any explicit edges
        # (test/sandbox path). Prod always passes loaded_edges via mode_controller.
        # `rsi_mean_reversion` was removed 2025-11-12; use `rsi_bounce` instead.
        from importlib import import_module
        if not self.edges:
            default_edges = ["rsi_bounce", "xsec_momentum"]
            for e in default_edges:
                try:
                    mod = import_module(f"engines.engine_a_alpha.edges.{e}")
                    if hasattr(mod, "compute_signals"):
                        self.edges[e] = mod
                        print(f"[ALPHA][INFO] Registered edge: {e}")
                    else:
                        print(f"[ALPHA][WARN] Edge {e} missing compute_signals()")
                except ImportError as err:
                    # Programmer error — module path is wrong. Fail loudly.
                    raise ImportError(
                        f"Default edge module engines.engine_a_alpha.edges.{e} "
                        f"could not be imported. If renamed/moved, update "
                        f"alpha_engine.default_edges. Original error: {err}"
                    ) from err

        # Environment overrides for key thresholds/hygiene
        self._env_enter = os.getenv("ALPHA_ENTER_THRESH")
        self._env_exit = os.getenv("ALPHA_EXIT_THRESH")
        self._env_min_hist = os.getenv("ALPHA_MIN_HISTORY")
        self._env_min_contrib = os.getenv("ALPHA_MIN_EDGE_CONTRIB")
        self._force_signals = os.getenv("ALPHA_FORCE_SIGNALS", "0").lower() in {"1","true","yes","on"}
        self._debug_env = os.getenv("ALPHA_DEBUG", "0").lower() in {"1","true","yes","on"}
        self._cfg_source = None

        # 2️⃣ Optionally import experimental edges (guarded)
        import importlib
        include_extras = os.getenv("ALPHA_INCLUDE_EXTRAS", "0").lower() in {"1","true","yes","on"}
        if include_extras:
            try:
                test_edge = importlib.import_module("engines.engine_a_alpha.edges.test_edge")
                self.edges.setdefault("test_edge", test_edge)
                if is_info_enabled() or is_debug_enabled("ALPHA"):
                    print(f"[ALPHA][INFO] test_edge imported successfully: {test_edge}")
            except Exception as e:
                if is_info_enabled() or is_debug_enabled("ALPHA"):
                    print(f"[ALPHA][DEBUG] Failed to import test_edge: {e}")
            try:
                news_edge = importlib.import_module("engines.engine_a_alpha.edges.news_sentiment_boost")
                self.edges.setdefault("news_sentiment_boost", news_edge)
                if is_info_enabled() or is_debug_enabled("ALPHA"):
                    print(f"[ALPHA][INFO] news_sentiment_boost imported successfully: {news_edge}")
            except Exception as e:
                if is_info_enabled() or is_debug_enabled("ALPHA"):
                    print(f"[ALPHA][DEBUG] Failed to import news_sentiment_boost: {e}")

        # Registers News Sentiment Edge (Phase 15) - Always Active
        try:
            ns = importlib.import_module("engines.engine_a_alpha.edges.news_sentiment_edge")
            self.edges.setdefault("news_sentiment_edge", ns.NewsSentimentEdge)
            if is_info_enabled() or is_debug_enabled("ALPHA"):
                print(f"[ALPHA][INFO] Registered edge: news_sentiment_edge")
        except Exception as e:
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][WARN] Could not register news_sentiment_edge: {e}")


        # 3️⃣ Print out all loaded edges for confirmation
        if is_info_enabled() or is_debug_enabled("ALPHA"):
            print(f"[ALPHA][INFO] Active edges after init: {list(self.edges.keys())}")

        # 4️⃣ Continue with the rest of your existing code
        self._edge_weights_external = dict(edge_weights or {})
        self.debug = bool(debug)
        self.governor = governor  # optional reference

        # Load config: support direct config injection, otherwise use file, then env overrides.
        if config is not None:
            # Merge with file defaults to ensure missing keys are filled.
            cfg_file = Path(config_path) if config_path else Path("config/alpha_settings.json")
            file_defaults = _load_json(cfg_file)
            # Merge file_defaults and config, with config taking precedence
            cfg_raw = dict(file_defaults)
            cfg_raw.update(config)
            self._cfg_source = "provided_config"
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][CONFIG] Loaded from provided config (env override active)")
        else:
            cfg_file = Path(config_path) if config_path else Path("config/alpha_settings.json")
            cfg_raw = _load_json(cfg_file)
            self._cfg_source = str(cfg_file)
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][CONFIG] Loaded from file: {cfg_file}")

        # --- APPLY EDGE PARAMS FROM CONFIG ---
        edge_params = cfg_raw.get("edge_params", {})
        for edge_name, edge_instance in self.edges.items():
            # Check edge_name directly or edge_id
            # Edge naming is tricky (key in dict vs EDGE_ID attr)
            # Try to match key first
            params = edge_params.get(edge_name)
            
            # If edge has .EDGE_ID, check that too
            if not params and hasattr(edge_instance, "EDGE_ID"):
                params = edge_params.get(edge_instance.EDGE_ID)
                
            if params and hasattr(edge_instance, "set_params"):
                if is_info_enabled():
                    print(f"[ALPHA][INFO] Setting params for {edge_name}: {params}")
                edge_instance.set_params(params)


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

        # Apply env override for min_history if provided
        min_history_val = int(self._env_min_hist) if (self._env_min_hist and self._env_min_hist.isdigit()) else int(cfg_raw.get("hygiene", {}).get("min_history", 60))

        hygiene = HygieneSettings(
            min_history=min_history_val,
            dedupe_last_n=int(cfg_raw.get("hygiene", {}).get("dedupe_last_n", 1)),
            clamp=_coerce_float(cfg_raw.get("hygiene", {}).get("clamp", 6.0)),
        )

        ensemble = EnsembleSettings(
            enable_shrink=bool(cfg_raw.get("ensemble", {}).get("enable_shrink", True)),
            shrink_lambda=_coerce_float(cfg_raw.get("ensemble", {}).get("shrink_lambda", 0.35)),
            combine="weighted_mean",
        )

        self.cfg = AlphaConfig(
            enter_threshold=_coerce_float(self._env_enter if self._env_enter is not None else cfg_raw.get("enter_threshold", 0.2)),
            exit_threshold=_coerce_float(self._env_exit if self._env_exit is not None else cfg_raw.get("exit_threshold", 0.05)),
            regime=regime,
            hygiene=hygiene,
            ensemble=ensemble,
            edge_weights=cfg_raw.get("edge_weights", {}),
            flip_cooldown_bars=int(cfg_raw.get("flip_cooldown_bars", 5)),
            min_edge_contribution=_coerce_float(self._env_min_contrib if self._env_min_contrib is not None else cfg_raw.get("min_edge_contribution", 0.05)),
            debug=bool(cfg_raw.get("debug", debug)),
        )

        # External edge weight overrides (e.g., Governor later)
        for k, v in self._edge_weights_external.items():
            self.cfg.edge_weights[k] = _coerce_float(v, 1.0)

        # Load regime gates from EdgeRegistry (edge_id -> {regime -> multiplier})
        try:
            from engines.engine_a_alpha.edge_registry import EdgeRegistry as _ER
            _regime_gates = {
                s.edge_id: s.regime_gate
                for s in _ER().get_all_specs()
                if s.regime_gate
            }
        except Exception:
            _regime_gates = {}

        # Components
        self.collector = SignalCollector(edges=self.edges, debug=self.cfg.debug)
        self.processor = SignalProcessor(
            regime=self.cfg.regime,
            hygiene=self.cfg.hygiene,
            ensemble=self.cfg.ensemble,
            edge_weights=self.cfg.edge_weights,
            regime_gates=_regime_gates,
            debug=self.cfg.debug,
        )
        self.formatter = SignalFormatter(
            enter_threshold=self.cfg.enter_threshold,
            exit_threshold=self.cfg.exit_threshold,
            min_edge_contribution=self.cfg.min_edge_contribution,
        )


        # 5️⃣ Ensure at least the default edges are available if none were supplied.
        # `rsi_mean_reversion` was removed 2025-11-12; use `rsi_bounce` instead.
        if not self.edges:
            try:
                rb = importlib.import_module("engines.engine_a_alpha.edges.rsi_bounce")
                self.edges["rsi_bounce"] = rb
            except ImportError as e:
                raise ImportError(
                    "Default edge `rsi_bounce` could not be imported — "
                    f"alpha_engine fallback path is broken. Original: {e}"
                ) from e
            try:
                xm = importlib.import_module("engines.engine_a_alpha.edges.xsec_momentum")
                self.edges["xsec_momentum"] = xm
            except ImportError as e:
                raise ImportError(
                    "Default edge `xsec_momentum` could not be imported. "
                    f"Original: {e}"
                ) from e
            if is_info_enabled() or is_debug_enabled("ALPHA"):
                print(f"[ALPHA][INFO] Default edges in use: {list(self.edges.keys())}")



        # State for cooldown & last known side per ticker
        self._last_side: Dict[str, Optional[str]] = {}
        self._last_flip_ts: Dict[str, Optional[pd.Timestamp]] = {}

    def _edge_meta_from_detail(self, edge_detail: dict) -> dict:
        """Normalize edge descriptor from SignalProcessor edges_detail item.
        Expected keys in edge_detail: 'edge' (name), optional 'group', 'category', 'version'.
        Fallbacks ensure JSON-safe primitives.
        """
        import re as _re
        name = str(edge_detail.get("edge", "Unknown"))
        group = str(edge_detail.get("group", edge_detail.get("category", "technical") or "technical"))
        # Use explicit edge_id if present (avoids double-versioning when name already ends in _v\d+)
        explicit_id = edge_detail.get("edge_id")
        if explicit_id:
            edge_id = str(explicit_id)
        elif _re.search(r"_v\d+$", name):
            edge_id = name  # name already carries the version suffix
        else:
            version = edge_detail.get("version")
            try:
                ver_str = (str(version).strip() if version is not None else "1")
            except Exception:
                ver_str = "1"
            edge_id = f"{name}_v{ver_str}"
        category = str(edge_detail.get("category", group))
        return {"name": name, "group": group, "category": category, "id": edge_id}

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

    # ------------------------------------------------------------------ #

    def _get_spy_history(self, now: pd.Timestamp, data_map: Optional[Dict[str, pd.DataFrame]] = None) -> pd.DataFrame:
        """Helper to get SPY/Benchmark history for Regime Detection.
        Prioritizes data_map['SPY'] if available (Backtest mode).
        Falls back to yfinance download (Live mode).
        """
        # 1. Backtest / DataMap path
        if data_map and "SPY" in data_map:
            spy = data_map["SPY"]
            # Slice up to 'now' (inclusive) to prevent lookahead
            return spy.loc[:now]

        # 2. Live Download path
        try:
            import yfinance as yf
            end_str = now.strftime("%Y-%m-%d")
            # Fetch enough history for SMA200
            start_date = (now - pd.Timedelta(days=400)).strftime("%Y-%m-%d")
            df = yf.download("SPY", start=start_date, end=end_str, progress=False, auto_adjust=True)
            if df.empty:
                return pd.DataFrame()
            return df
        except Exception as e:
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][WARN] Failed to fetch SPY for regime: {e}")
            return pd.DataFrame()

    def generate_signals(
        self,
        data_map: Dict[str, pd.DataFrame],
        now: pd.Timestamp,
        regime_meta: Optional[dict] = None,
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

        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][TRACE] Entered generate_signals() with tickers={list(data_map.keys())} at {now}")
        
        # ----------------------------------------------------------------
        # 🧠 COGNITIVE GOVERNOR: Detect Regime
        # ----------------------------------------------------------------
        if regime_meta is None:
            regime_meta = {
                "regime": "unknown", "trend": "unknown", "volatility": "unknown",
                "regime_int": 0, "details": {},
            }
        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][COGNITION] Market State: {regime_meta.get('regime', 'unknown')} (Trend={regime_meta.get('trend', 'unknown')}, Vol={regime_meta.get('volatility', 'unknown')})")

        # Normalize incoming data from any source (Alpaca, yfinance, CSV)
        data_map = {t: self._normalize_dataframe(df) for t, df in data_map.items()}

        # Propagate regime_meta to edges so they don't self-detect
        for edge_obj in self.edges.values():
            if hasattr(edge_obj, "regime_meta"):
                edge_obj.regime_meta = regime_meta

        if self.cfg.debug and (self._debug_env or is_debug_enabled("ALPHA")):
            print(f"[ALPHA][DEBUG] cfg_source={self._cfg_source} enter={self.cfg.enter_threshold} exit={self.cfg.exit_threshold} min_hist={self.cfg.hygiene.min_history} min_edge_contrib={self.cfg.min_edge_contribution} force_signals={self._force_signals}")

        if self.cfg.debug:
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][DEBUG] Active edges: {list(self.edges.keys())}")
        
        if self.cfg.debug:
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][DEBUG] Collecting signals from edges: {list(self.edges.keys())}")

        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][TRACE] Starting signal collection at {now}")

        raw_scores: Dict[str, Dict[str, float]] = self.collector.collect(data_map, now)

        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][TRACE] Collected raw_scores keys={list(raw_scores.keys())}")

        if self.cfg.debug:
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][DEBUG] Raw scores collected at {now}: {raw_scores}")

        # 2) Process: normalize, regime-gate, shrinkage, hygiene checks
        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][TRACE] Beginning signal processing for {len(raw_scores)} tickers")
        proc = self.processor.process(data_map, now, raw_scores, regime_meta=regime_meta)
        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][TRACE] Processor output size={len(proc) if proc else 0}")
        # --- Fallback: if processor yields nothing but we have raw_scores, build a minimal proc ---
        if (not proc) and raw_scores:
            proc = {}
            # normalize via tanh and simple weighted mean
            ew = self.cfg.edge_weights or {}
            for ticker, edge_map in raw_scores.items():
                details = []
                contribs = []
                weights = []
                for edge_name, raw in edge_map.items():
                    try:
                        r = float(raw)
                    except Exception:
                        r = 0.0
                    # clamp then normalize with tanh for safety
                    r = max(-self.cfg.hygiene.clamp, min(self.cfg.hygiene.clamp, r))
                    norm = math.tanh(r)
                    w = float(ew.get(edge_name, 1.0))
                    details.append({
                        "edge": edge_name,
                        "group": "technical",
                        "category": "technical",
                        "version": "1",
                        "raw": r,
                        "norm": norm,
                        "weight": w,
                    })
                    contribs.append(norm * w)
                    weights.append(abs(w))
                agg = 0.0
                if contribs:
                    try:
                        agg = sum(contribs) / (sum(weights) if sum(weights) != 0 else len(contribs))
                    except Exception:
                        agg = fmean(contribs)
                proc[ticker] = {
                    "aggregate_score": float(max(-1.0, min(1.0, agg))),
                    "regimes": {"trend": True, "vol_ok": True},
                    "edges_detail": details,
                }
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][TRACE] Fallback processor built with {len(proc)} entries")
            if is_info_enabled() or is_debug_enabled("ALPHA"):
                print(f"[ALPHA][INFO] Fallback processor used at {now}; built proc for {len(proc)} tickers")

        # 3) Aggregate per ticker and turn into discrete side if above thresholds
        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][TRACE] Aggregating to discrete signals for {len(proc)} tickers")
        signals: List[dict] = []
        for ticker, info in proc.items():
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][TRACE] {ticker}: aggregate_score={info.get('aggregate_score')}")
            agg = info["aggregate_score"]  # in [-1, +1] after normalization/shrinkage
            regimes = info["regimes"]
            edges_detail = info["edges_detail"]  # list of dicts per edge

            side, strength = self.formatter.to_side_and_strength(agg)
            if (side is None or strength <= 0) and self._force_signals:
                # Force a weak signal in debug/diagnostic mode based purely on sign of agg
                if agg > 0:
                    side = "long"
                elif agg < 0:
                    side = "short"
                else:
                    side = None
                strength = abs(float(agg))

            # Cooldown (optional, light-touch): block flip immediately after a flip within same day
            if self._cooldown_blocks(ticker, side, now):
                side = None
                strength = 0.0

            # Ensure we skip signals with non-positive strength (prevents empty backtest output)
            # FIX: "Bagholder Bug" - If we have a position (tracked by _last_side) but signal is weak,
            # we MUST emit a signal (side="none") so RiskEngine sees it and can exit.
            is_weak = (side is None or strength <= 0)
            was_active = (self._last_side.get(ticker) is not None)
            
            if is_weak and not was_active:
                if self.cfg.debug and (self._debug_env or is_debug_enabled("ALPHA")):
                    print(f"[ALPHA][DEBUG] Dropping {ticker} at {now} agg={agg:.4f} (below enter_threshold={self.cfg.enter_threshold})")
                continue
            elif is_weak and was_active:
                # Signal has faded, but we were active. Send explicit "none" (neutral) signal.
                side = "none"
                strength = 0.0
                if self.cfg.debug and (self._debug_env or is_debug_enabled("ALPHA")):
                    print(f"[ALPHA][DEBUG] Fading {ticker} at {now} (agg={agg:.4f}). Sending neutral signal to trigger exit.")

            self._update_flip_state(ticker, side, now)

            # Package signal with robust edge attribution
            if not isinstance(edges_detail, list):
                edges_detail = []
            if edges_detail:
                top_edge = max(edges_detail, key=lambda ed: abs(float(ed.get("norm", 0.0)) * float(ed.get("weight", 0.0))))
                top_meta = self._edge_meta_from_detail(top_edge)
                # Fallback logic for edge_id and edge_category
                if not top_meta.get("id"):
                    top_meta["id"] = f"{top_meta['name']}_v1"
                if not top_meta.get("category"):
                    top_meta["category"] = top_meta.get("group", "technical")
            else:
                top_meta = {"name": "Unknown", "group": "technical", "category": "technical", "id": "Unknown_v1"}

            # JSON-safe, compact meta (avoid leaking large dicts into CSV columns later)
            edges_triggered = []
            for ed in edges_detail:
                if not isinstance(ed, dict):
                    continue
                contrib = abs(float(ed.get("norm", 0.0)) * float(ed.get("weight", 0.0)))
                if contrib >= self.cfg.min_edge_contribution:
                    em = self._edge_meta_from_detail(ed)
                    edges_triggered.append({
                        "edge": em["name"],
                        "edge_id": em["id"],
                        "edge_category": em["category"],
                        "raw": float(ed.get("raw", 0.0)),
                        "norm": float(ed.get("norm", 0.0)),
                        "weight": float(ed.get("weight", 0.0)),
                    })

            signals.append({
                "ticker": ticker,
                "side": side,
                "strength": float(max(0.0, min(1.0, strength))),
                # top-level attribution (consumed by Risk/Logger)
                "edge": top_meta["name"],
                "edge_group": top_meta["group"],
                "edge_id": top_meta["id"],
                "edge_category": top_meta["category"],
                # compact meta only
                "meta": {
                    "edges_triggered": edges_triggered,
                    "regimes": regimes,
                    "market_state": regime_meta, # COGNITION INJECTION
                },
            })

        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][TRACE] Built {len(signals)} pre-governor signals at {now}")
            
        # ----------------------------------------------------------------
        # ----------------------------------------------------------------
        # 🤖 AI SIGNAL GATING (Integrated ML)
        # ----------------------------------------------------------------
        # 1. Try to load ML Predictor
        # In a real production system, this would be loaded once in __init__
        # For this MVP, we lazy-load or assume it's available if trained.
        
        try:
            # We check if a model exists. If so, we use it to filter/boost signals.
            from engines.engine_a_alpha.ml_predictor import MLPredictor
            ml_model_path = "data/models/rf_model.pkl"
            
            if os.path.exists(ml_model_path) and signals:
                predictor = MLPredictor(model_path=ml_model_path)
                
                for sig in signals:
                    tkr = sig["ticker"]
                    if tkr in data_map:
                        prob_up = predictor.predict(data_map[tkr])
                        
                        # AI Logic:
                        # If Signal is LONG but ML says Prob(Up) < 45%, CUT IT.
                        if sig["side"] == "long" and prob_up < 0.45:
                            sig["strength"] *= 0.5
                            sig["meta"]["ml_confidence"] = f"LOW ({prob_up:.2f})"
                        
                        # If Signal is LONG and ML says Prob(Up) > 60%, BOOST IT.
                        elif sig["side"] == "long" and prob_up > 0.60:
                            sig["strength"] = min(1.0, sig["strength"] * 1.2)
                            sig["meta"]["ml_confidence"] = f"HIGH ({prob_up:.2f})"
                        else:
                            sig["meta"]["ml_confidence"] = f"NEUTRAL ({prob_up:.2f})"
                            
        except Exception as e:
            if is_debug_enabled("ALPHA"):
                print(f"[ALPHA][ML] Inference skipped: {e}")

        # Legacy hook (kept for backward compat)
        if hasattr(self, "signal_gate"):
            signals = self.signal_gate.predict(signals, data_map)

        # Governor adjustment (if present) — regime-conditional weights
        if self.governor and signals:
            weights = self.governor.get_edge_weights(regime_meta=regime_meta)
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

        if is_debug_enabled("ALPHA"):
            print(f"[ALPHA][TRACE] Returning {len(signals)} signals for {now}")

        if not signals and (self._debug_env or is_debug_enabled("ALPHA")):
            print(f"[ALPHA][DEBUG] No signals generated at {now}. Check thresholds/hygiene or enable ALPHA_FORCE_SIGNALS=1 for diagnostics.")

        if (is_info_enabled() or is_debug_enabled("ALPHA")):
            print(f"[ALPHA][INFO] {now} generated {len(signals)} signals from edges={list(self.edges.keys())}")
            if signals[:3]:
                preview = [{k: s[k] for k in ("ticker","side","strength","edge","edge_id","edge_category")} for s in signals[:3]]
                print(f"[ALPHA][INFO] Sample signals: {preview}")

        return signals
    
if __name__ == "__main__":
    import yfinance as yf
    import pandas as pd
    from debug_config import is_debug_enabled
    if is_debug_enabled("ALPHA"):
        print("[DEBUG] Downloading test data for AAPL...")
    df = yf.download("AAPL", period="1y", interval="1d")

    ae = AlphaEngine(edges={}, debug=True)
    now = pd.Timestamp(df.index[-1])
    signals = ae.generate_signals({"AAPL": df}, now)
    if is_debug_enabled("ALPHA"):
        print("\n[DEBUG] Example output:")
    print(signals)
