# orchestration/mode_controller.py
"""
ModeController
==============

Orchestrates the end-to-end trading pipeline in three modes:
- BACKTEST: historical run using BacktestController (fills at next bar open; slippage/commission applied)
- PAPER: streaming simulation on rolling bars (supports configurable fill delay and partial fills)
- LIVE: same pipeline, but execution routes to a broker adapter interface (dry_run by default)

This module keeps strict separation between components:
    Engine A (Alpha)       -> signal generation
    Engine B (Risk)        -> sizing & order constraints
    Engine C (Portfolio)   -> accounting (cash + positions = equity)
    Engine D (Discovery)   -> edge hunting & evolution (offline)
    Engine E (Regime)      -> market state detection (called once per bar by ModeController)
    Engine F (Governance)  -> edge lifecycle & weight management
    Execution              -> simulator or live adapter
    Cockpit                -> logging snapshots & trades to CSV (mode-aware if logger supports it)

Assumptions / Notes
-------------------
- We reuse your existing DataManager, AlphaEngine, RiskEngine, PortfolioEngine, ExecutionSimulator,
  BacktestController, and CockpitLogger.
- Paper mode here simulates a bar-by-bar "near-live" feed from DataManager, applying a configurable
  bar-delay for fills (e.g., signal on bar t, fill on bar t+delay).
- Live mode uses a broker adapter interface with dry_run=True by default. It *logs* orders
  and produces synthetic fills at the quoted price so the portfolio stays internally consistent.
- CSV schema changes are handled by CockpitLogger (which should auto-add columns if missing). If your
  logger hasn’t been updated to include a 'mode' column, this controller will still work.

Configuration Sources
---------------------
- config/backtest_settings.json
- config/risk_settings.json
- config/edge_config.json
(Optional future configs for alpha/governor/policy can be added without changing this file.)

Author: Quant Systems Architect
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import importlib
import time

import pandas as pd

# --- Project imports (existing in your repo) ---
from utils.config_loader import load_json
from engines.data_manager.data_manager import DataManager
from engines.engine_a_alpha.alpha_engine import AlphaEngine
from engines.engine_b_risk.risk_engine import RiskEngine
from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine, Position
from backtester.execution_simulator import ExecutionSimulator
from backtester.backtest_controller import BacktestController
from cockpit.logger import CockpitLogger
from cockpit.metrics import PerformanceMetrics
# --- Engine E: Regime Intelligence ---
from engines.engine_e_regime.regime_detector import RegimeDetector
# --- EdgeRegistry for dynamic edge loading ---
from engines.engine_a_alpha.edge_registry import EdgeRegistry
# --- StrategyGovernor ---
from engines.engine_f_governance.governor import StrategyGovernor
# --- NEW: Alpaca broker adapter ---
from brokers.alpaca_broker import AlpacaBroker
from analytics.edge_feedback import update_edge_weights_from_latest_trades

# =============================================================================
# Modes / Interfaces
# =============================================================================

class Mode(str, Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"


class ExecutionAdapter:
    """
    Base interface for live execution. Implement for Alpaca, IBKR, etc.
    """
    def __init__(self, dry_run: bool = True):
        self.dry_run = bool(dry_run)

    def place_order(self, order: dict) -> Optional[dict]:
        """
        Place a live order. Return a fill dict compatible with PortfolioEngine.apply_fill:
          {'ticker','side','qty','price','commission'}
        If dry_run is True, return a simulated fill without sending to broker.
        """
        raise NotImplementedError


class DryRunExecutionAdapter(ExecutionAdapter):
    """
    Default "live" adapter that does NOT send to a broker.
    It simply echoes a synthetic fill at the requested price field if provided,
    otherwise it uses side-dependent slippage around a reference price (the caller
    should pass 'price' in the order for deterministic behavior).
    """

    def __init__(self, slippage_bps: float = 10.0, commission: float = 0.0, dry_run: bool = True):
        super().__init__(dry_run=dry_run)
        self.slippage_bps = float(slippage_bps)
        self.commission = float(commission)

    def _apply_slippage(self, price: float, side: str) -> float:
        slip = price * (self.slippage_bps / 10000.0)
        side = str(side).lower()
        if side == "long":
            return price + slip
        if side == "short":
            return price - slip
        return price

    def place_order(self, order: dict) -> Optional[dict]:
        """
        For dry-run, we simulate an immediate fill at provided 'price' (post-slippage).
        For real brokers later, implement order routing and return actual fill or None.
        """
        if not order or order.get("qty", 0) <= 0:
            return None
        side = str(order.get("side", "")).lower()
        px = float(order.get("price", 0.0))  # caller should pass a reference price
        if px <= 0:
            # If not given, we can’t create a sensible fill. Fail closed.
            return None

        fill_price = self._apply_slippage(px, side)
        return {
            "ticker": order.get("ticker"),
            "side": side,
            "qty": int(order.get("qty", 0)),
            "price": float(fill_price),
            "commission": float(self.commission),
        }
    
# --- NEW: Alpaca Broker Adapter ---
class AlpacaExecutionAdapter(ExecutionAdapter):
    """
    Adapter that routes live/paper trades through AlpacaBroker.
    """
    def __init__(self, paper: bool = True):
        super().__init__(dry_run=False)
        self.broker = AlpacaBroker(paper=paper)

    def place_order(self, order: dict) -> Optional[dict]:
        ticker = order.get("ticker")
        side = order.get("side")
        qty = float(order.get("qty", 0))
        if not ticker or qty <= 0:
            print(f"[ALPACA_ADAPTER][WARN] Invalid order: {order}")
            return None

        try:
            result = self.broker.place_order(ticker, side, qty)
            print(f"[ALPACA_ADAPTER][INFO] Sent {side.upper()} {qty} {ticker}")
            # Build synthetic fill to keep the portfolio consistent
            return {
                "ticker": ticker,
                "side": side,
                "qty": int(qty),
                "price": float(order.get("price", 0.0)),  # fallback to intended price
                "commission": 0.0,
                "edge": order.get("edge", "Unknown"),
            }
        except Exception as e:
            print(f"[ALPACA_ADAPTER][ERROR] Failed to place order: {e}")
            return None

# =============================================================================
# Paper Trade Controller (streaming simulation)
# =============================================================================

@dataclass
class PaperParams:
    """
    Parameters for paper trading realism.
    """
    fill_bar_delay: int = 1         # bars after signal to fill (e.g., 1 = next bar open sim)
    sleep_seconds: float = 0.0      # optional real-time sleep between bars
    allow_partials: bool = False    # stub for future partial-fill logic


class PaperTradeController:
    """
    Streaming-like controller that *simulates* a live feed from historical data.
    Uses Engine A (alpha) + Engine B (risk) for new orders each bar, and PortfolioEngine for accounting.
    Execution is handled by ExecutionSimulator at a delayed bar (fill_bar_delay).
    """

    def __init__(
        self,
        data_map: Dict[str, pd.DataFrame],
        alpha_engine: AlphaEngine,
        risk_engine: RiskEngine,
        cockpit_logger: CockpitLogger,
        initial_capital: float,
        exec_params: dict,
        paper_params: Optional[PaperParams] = None,
        mode_label: str = "paper",
        portfolio_cfg: Optional[Any] = None,
    ):
        self.data_map: Dict[str, pd.DataFrame] = {}
        for t, df in data_map.items():
            if df is None or df.empty:
                continue
            _df = df.copy()
            _df.index = pd.to_datetime(_df.index, errors="coerce")
            try:
                _df.index = _df.index.tz_localize(None)
            except Exception:
                pass
            _df = _df.sort_index()
            self.data_map[t] = _df

        self.alpha = alpha_engine
        self.risk = risk_engine
        self.portfolio = PortfolioEngine(initial_capital, policy_cfg=portfolio_cfg)
        self.exec = ExecutionSimulator(
            slippage_bps=float(exec_params.get("slippage_bps", 10.0)),
            commission=float(exec_params.get("commission", 0.0)),
        )
        self.logger = cockpit_logger
        # Let logger know which portfolio it tracks (and mode if supported)
        self.logger.portfolio = self.portfolio
        if hasattr(self.logger, "mode"):
            self.logger.mode = mode_label

        self.params = paper_params or PaperParams()

        # Construct the union of timestamps
        all_sets = [set(df.index) for df in self.data_map.values() if not df.empty]
        self.timestamps: List[pd.Timestamp] = sorted(set().union(*all_sets)) if all_sets else []

    def _close_scalar(self, row_or_series) -> float:
        if isinstance(row_or_series, pd.Series):
            return float(row_or_series["Close"])
        return float(row_or_series["Close"].iloc[0])

    def run(self, start: str, end: str) -> List[dict]:
        if not self.timestamps:
            print("[PAPER] No timestamps available.")
            return []

        start_dt = pd.to_datetime(start).tz_localize(None)
        end_dt = pd.to_datetime(end).tz_localize(None)
        ts = [t for t in self.timestamps if (start_dt <= t <= end_dt)]
        if len(ts) < 2:
            print("[PAPER] Not enough timestamps in selected range.")
            return self.portfolio.history

        # Initial snapshot at the first available bar
        t0 = ts[0]
        first_prices = {t: float(df.loc[t0]["Close"]) for t, df in self.data_map.items() if t0 in df.index}
        snap0 = self.portfolio.snapshot(t0, first_prices)
        if hasattr(self.logger, "log_snapshot"):
            self.logger.log_snapshot(snap0)

        # Main streaming loop
        delay = max(0, int(self.params.fill_bar_delay))
        for i, now in enumerate(ts[:-1]):
            # Slice up to 'now' for alpha
            slice_map = {t: df.loc[:now] for t, df in self.data_map.items() if now in df.index}
            if not slice_map:
                continue

            # Alpha -> signals (at bar 'now')
            signals = self.alpha.generate_signals(slice_map, now)

            # Equity at 'now'
            last_prices_now = {t: self._close_scalar(df.loc[now]) for t, df in slice_map.items()}
            equity_now = self.portfolio.total_equity(last_prices_now)

            # Risk -> orders
            orders: List[dict] = []
            for sig in signals:
                tkr = sig["ticker"]
                pos = self.portfolio.positions.get(tkr)
                if pos and pos.qty != 0:
                    # In paper mode we block adding duplicates within same bar; can be a tunable later.
                    continue
                od = self.risk.prepare_order(sig, equity_now, slice_map[tkr])
                if od:
                    # Attach edge meta if present in signal for cockpit attribution
                    if "meta" in sig and "edges_triggered" in sig["meta"]:
                        # pick strongest contributing edge name if available
                        edges = sig["meta"]["edges_triggered"]
                        if edges:
                            od["edge"] = edges[0].get("edge", "Unknown")
                    orders.append(od)

            # Determine fill bar index (now + delay)
            fill_idx = i + delay
            if fill_idx >= len(ts):
                # No future bar available to fill; skip
                break
            fill_ts = ts[fill_idx]

            # Build next_rows at fill timestamp
            next_rows = {
                t: self.data_map[t].loc[fill_ts]
                for t in slice_map
                if fill_ts in self.data_map[t].index
            }

            # Execute orders on the fill bar
            for order in orders:
                tkr = order["ticker"]
                if tkr not in next_rows:
                    continue
                fill = self.exec.fill_at_next_open(order, next_rows[tkr])
                if fill:
                    # Carry edge tag through to the logger if present
                    if "edge" in order:
                        fill["edge"] = order["edge"]
                    self.portfolio.apply_fill(fill)
                    if hasattr(self.logger, "log_fill"):
                        self.logger.log_fill(fill, fill_ts)

            # --- Trailing stop management (parity with BacktestController) ---
            if hasattr(self.risk, "manage_positions"):
                try:
                    current_prices = {t: self._close_scalar(df.loc[now]) for t, df in slice_map.items()}
                    updates = self.risk.manage_positions(current_prices, data_map=slice_map)
                    for upd in updates:
                        tkr = upd.get("ticker")
                        new_stop = upd.get("new_stop")
                        if tkr and new_stop is not None:
                            pos = self.portfolio.positions.get(tkr)
                            if pos:
                                pos.stop = new_stop
                except Exception:
                    pass

            # --- SL/TP evaluation on fill bar (parity with BacktestController) ---
            for ticker, pos in list(self.portfolio.positions.items()):
                if pos.qty == 0 or ticker not in next_rows:
                    continue
                stop_or_tp = self.exec.check_stops_and_targets(ticker, pos, next_rows[ticker])
                if stop_or_tp:
                    if "fill_price" not in stop_or_tp and "price" in stop_or_tp:
                        stop_or_tp["fill_price"] = stop_or_tp["price"]
                    if "price" not in stop_or_tp and "fill_price" in stop_or_tp:
                        stop_or_tp["price"] = stop_or_tp["fill_price"]
                    stop_or_tp.setdefault("commission", float(getattr(self.exec, "commission", 0.0)))
                    self.portfolio.apply_fill(stop_or_tp)
                    if hasattr(self.logger, "log_fill"):
                        self.logger.log_fill(stop_or_tp, fill_ts)

            # Snapshot on the fill bar
            px_map = {t: self._close_scalar(next_rows[t]) for t in next_rows}
            snap = self.portfolio.snapshot(fill_ts, px_map)
            if hasattr(self.logger, "log_snapshot"):
                self.logger.log_snapshot(snap)

            # Optional pacing for realism
            if self.params.sleep_seconds and self.params.sleep_seconds > 0:
                time.sleep(self.params.sleep_seconds)

        return self.portfolio.history


# =============================================================================
# Live Controller (broker-adapter ready; dry-run by default)
# =============================================================================

@dataclass
class LiveParams:
    """
    Parameters for live trading.
    This MVP uses a DryRunExecutionAdapter by default.
    """
    poll_seconds: float = 5.0
    dry_run: bool = True


class LiveTradeController:
    """
    Live controller skeleton.
    - Polls a "latest bar" view from DataManager (MVP uses end-of-day bars or last cached bar).
    - Routes orders to an ExecutionAdapter (dry-run by default).
    - Writes fills and snapshots via CockpitLogger so dashboard remains consistent.

    NOTE: In true live, you’d subscribe to a streaming feed and compute signals on each tick/bar close.
    """

    def __init__(
        self,
        alpha_engine: AlphaEngine,
        risk_engine: RiskEngine,
        cockpit_logger: CockpitLogger,
        initial_capital: float,
        adapter: Optional[ExecutionAdapter] = None,
        live_params: Optional[LiveParams] = None,
        mode_label: str = "live",
        portfolio_cfg: Optional[Any] = None,
    ):
        self.alpha = alpha_engine
        self.risk = risk_engine
        self.portfolio = PortfolioEngine(initial_capital, policy_cfg=portfolio_cfg)
        self.logger = cockpit_logger
        self.logger.portfolio = self.portfolio
        if hasattr(self.logger, "mode"):
            self.logger.mode = mode_label

        self.params = live_params or LiveParams()
        self.adapter = adapter or DryRunExecutionAdapter(dry_run=self.params.dry_run)

        # Keep last seen timestamp per ticker to avoid reprocessing identical bars
        self._last_bar_ts: Dict[str, pd.Timestamp] = {}

    def _close_scalar(self, row_or_series) -> float:
        if isinstance(row_or_series, pd.Series):
            return float(row_or_series["Close"])
        return float(row_or_series["Close"].iloc[0])

    def step_once(self, market_map: Dict[str, pd.DataFrame]) -> Optional[pd.Timestamp]:
        """
        Process a single "latest bar" snapshot per ticker.
        market_map: dict[ticker] -> DF whose last row is latest complete bar for that ticker.
        Returns the max timestamp processed, or None if nothing new.
        """
        # Build per-ticker latest row if it's new
        latest_rows: Dict[str, pd.Series] = {}
        for t, df in market_map.items():
            if df is None or df.empty:
                continue
            last_ts = df.index[-1]
            if self._last_bar_ts.get(t) == last_ts:
                continue  # already processed
            latest_rows[t] = df.loc[last_ts]
            self._last_bar_ts[t] = last_ts

        if not latest_rows:
            return None

        # Prepare slice_map (history up to latest for each ticker)
        slice_map = {}
        for t, df in market_map.items():
            if t in latest_rows:
                slice_map[t] = df.loc[: self._last_bar_ts[t]]

        # Alpha on the max timestamp
        current_ts = max(self._last_bar_ts.values())
        signals = self.alpha.generate_signals(slice_map, current_ts)

        # Portfolio equity at current snapshot
        last_prices = {t: self._close_scalar(latest_rows[t]) for t in latest_rows}
        equity = self.portfolio.total_equity(last_prices)

        # Risk -> orders
        orders: List[dict] = []
        for sig in signals:
            tkr = sig["ticker"]
            pos = self.portfolio.positions.get(tkr)
            if pos and pos.qty != 0:
                continue
            od = self.risk.prepare_order(sig, equity, slice_map[tkr])
            if od:
                # Pass a reference price for adapter-based fills
                od["price"] = float(latest_rows[tkr].get("Open", latest_rows[tkr].get("Close", 0.0)))
                if "meta" in sig and "edges_triggered" in sig["meta"]:
                    edges = sig["meta"]["edges_triggered"]
                    if edges:
                        od["edge"] = edges[0].get("edge", "Unknown")
                orders.append(od)

        # Route to adapter
        for order in orders:
            fill = self.adapter.place_order(order)
            if fill:
                # keep edge tag for cockpit attribution
                if "edge" in order:
                    fill["edge"] = order["edge"]
                self.portfolio.apply_fill(fill)
                if hasattr(self.logger, "log_fill"):
                    self.logger.log_fill(fill, current_ts)

        # Snapshot after orders
        snap = self.portfolio.snapshot(current_ts, last_prices)
        if hasattr(self.logger, "log_snapshot"):
            self.logger.log_snapshot(snap)

        return current_ts

    def run_loop(self, feed, max_steps: Optional[int] = None) -> None:
        """
        Run a simple polling loop using a provided feed (must expose .latest_map()).
        """
        steps = 0
        while True:
            market_map = feed.latest_map()
            self.step_once(market_map)
            steps += 1
            if max_steps is not None and steps >= max_steps:
                break
            time.sleep(self.params.poll_seconds)


# =============================================================================
# Mode Controller
# =============================================================================

class ModeController:
    """
    High-level orchestrator that prepares data, wires engines, and runs the chosen mode.
    """

    def __init__(self, project_root: Path, env: str = "prod"):
        self.root = Path(project_root)
        self.env = env

        # --- Load configuration files ---
        self.cfg_bt = load_json(str(self.root / "config" / "backtest_settings.json"))
        self.cfg_risk = load_json(str(self.root / f"config/risk_settings.{env}.json"))
        self.cfg_portfolio = load_json(str(self.root / "config" / "portfolio_settings.json"))

        # --- Core run params ---
        self.tickers: List[str] = self.cfg_bt["tickers"]
        self.start: str = self.cfg_bt["start_date"]
        self.end: str = self.cfg_bt["end_date"]
        self.timeframe: str = self.cfg_bt["timeframe"]
        self.init_cap: float = float(self.cfg_bt["initial_capital"])

        # --- Exec params (slippage/commission) ---
        # `slippage_model` defaults to 'fixed' for backward compatibility.
        # Set to 'realistic' in backtest_settings.json to enable
        # ADV-bucketed half-spread + Almgren-Chriss square-root impact.
        self.exec_params = {
            "slippage_bps": float(self.cfg_bt.get("slippage_bps", 10.0)),
            "slippage_model": str(self.cfg_bt.get("slippage_model", "fixed")),
            "commission": float(self.cfg_bt.get("commission", 0.0)),
        }
        if "slippage_extra" in self.cfg_bt:
            self.exec_params["slippage_extra"] = self.cfg_bt["slippage_extra"]
        # Cost-completeness layer: pass through alpaca_fees / borrow /
        # tax configs so BacktestController can construct the
        # post-processor. Modules are individually toggleable; absence
        # → disabled (legacy behavior).
        for _key in ("alpaca_fees", "borrow_rate_model", "tax_drag_model"):
            if _key in self.cfg_bt:
                self.exec_params[_key] = self.cfg_bt[_key]

        # --- Prepare data manager ---
        import os as _os
        self.dm = DataManager(
            cache_dir=str(self.root / "data" / "processed"),
            api_key=_os.getenv("ALPACA_API_KEY"),
            secret_key=_os.getenv("ALPACA_SECRET_KEY"),
            base_url=_os.getenv("ALPACA_BASE_URL"),
        )

        # --- Default edge loading for paper/live modes ---
        # run_backtest() creates its own per-call edges with full override support;
        # paper/live modes use this default set loaded from the registry.
        default_edges = self._load_edges_via_registry()
        cfg_alpha = load_json(str(self.root / f"config/alpha_settings.{self.env}.json"))
        config_ew = cfg_alpha.get("edge_weights", {})
        default_edge_weights = {eid: float(config_ew.get(eid, 1.0))
                                for eid in default_edges}
        self.alpha = AlphaEngine(
            edges=default_edges,
            edge_weights=default_edge_weights,
            config=cfg_alpha,
            debug=True,
        )

        # --- Risk Engine (with Path A tax-aware modules wired from portfolio cfg) ---
        self.risk = RiskEngine(
            self.cfg_risk,
            wash_sale_cfg=self.cfg_portfolio.get("wash_sale_avoidance"),
            lt_hold_cfg=self.cfg_portfolio.get("lt_hold_preference"),
        )

        # --- Portfolio Config Object ---
        from engines.engine_c_portfolio.policy import PortfolioPolicyConfig
        pp_cfg = PortfolioPolicyConfig(**{k: v for k, v in self.cfg_portfolio.items() if k in PortfolioPolicyConfig.__annotations__})
        self.portfolio_cfg = pp_cfg

        # --- Engine E: Regime Intelligence ---
        self.regime_detector = RegimeDetector()

        # --- Cockpit ---
        self.cockpit = CockpitLogger(out_dir=str(self.root / "data" / "trade_logs"), flush_each_fill=True)
        print(f"[COCKPIT] Trade log -> {self.cockpit.trade_path}")
        print(f"[COCKPIT] Snapshot log -> {self.cockpit.snap_path}")

    # ---------------------------- Helpers ---------------------------- #

    def _load_edges_via_registry(
        self,
        override_params: Optional[Dict] = None,
        exact_edge_ids: Optional[List[str]] = None,
        alpha_debug: bool = False,
    ) -> Dict[str, object]:
        """
        Load edges using EdgeRegistry (new approach).
        Supports isolation mode (exact_edge_ids) and override_params injection.
        """
        registry = EdgeRegistry()
        loaded_edges: Dict[str, object] = {}
        specs_to_load: Dict[str, object] = {}

        if exact_edge_ids and len(exact_edge_ids) > 0:
            print(f"[RUN_BACKTEST] Isolation Mode: Loading exact edges {exact_edge_ids}")
            for eid in exact_edge_ids:
                spec = registry.get(eid)
                if spec:
                    specs_to_load[eid] = spec
                else:
                    print(f"[RUN_BACKTEST] Edge ID {eid} not found in registry.")
        else:
            # Default Mode: Load tradeable (active + paused).
            # Phase α v2 soft-pause: paused edges trade at reduced weight
            # (applied later when constructing edge_weights) rather than being
            # silenced entirely. This is what lets the revival gate observe
            # post-pause performance data and decide whether to re-activate.
            tradeable_specs = registry.list_tradeable()
            for spec in tradeable_specs:
                specs_to_load[spec.edge_id] = spec

            # Also load any edge implied by override_params keys, even if candidate
            if override_params:
                for edge_id_or_module_name in override_params.keys():
                    # Avoid trying to load "alpha" or config keys as edges
                    if edge_id_or_module_name in ["alpha", "risk", "portfolio"]:
                        continue

                    spec = registry.get(edge_id_or_module_name)
                    if not spec:
                        # Try to find by module name matching
                        for s in registry.get_all_specs():
                            if s.module == edge_id_or_module_name:
                                spec = s
                                break

                    if spec and spec.edge_id not in specs_to_load:
                        print(f"[RUN_BACKTEST] Injecting candidate/override edge {spec.edge_id} for testing.")
                        specs_to_load[spec.edge_id] = spec

        print(f"[RUN_BACKTEST] Loading {len(specs_to_load)} edges: {list(specs_to_load.keys())}")

        # Import and register
        for edge_id, spec in specs_to_load.items():
            mod_name = spec.module
            params = spec.params.copy() if spec.params else {}

            # INJECT OPTIMIZATION PARAMS
            if override_params:
                if edge_id in override_params:
                    if isinstance(override_params[edge_id], dict):
                        params.update(override_params[edge_id])
                        if alpha_debug:
                            print(f"[RUN_BACKTEST] Overriding {edge_id} params: {override_params[edge_id]}")
                # Fallback for module-level overrides if needed
                elif mod_name in override_params and isinstance(override_params[mod_name], dict):
                    params.update(override_params[mod_name])

            try:
                if "." in mod_name:
                    mod = importlib.import_module(mod_name)
                else:
                    mod = importlib.import_module(f"engines.engine_a_alpha.edges.{mod_name}")

                # Check if the module defines a subclassed Edge class with params
                edge_class = None
                for attr in dir(mod):
                    if attr.lower().endswith("edge") and attr not in ["BaseEdge"]:
                        # Avoid importing imported classes like EdgeBase
                        val = getattr(mod, attr)
                        if hasattr(val, "__module__") and val.__module__ == mod.__name__:
                            edge_class = val
                            break

                # Fallback check if strict module match failed
                if edge_class is None:
                    for attr in dir(mod):
                        if attr.lower().endswith("edge") and attr not in ["BaseEdge"]:
                            edge_class = getattr(mod, attr)
                            break

                if edge_class is not None:
                    try:
                        loaded_edges[edge_id] = edge_class(params=params)
                    except TypeError:
                        loaded_edges[edge_id] = edge_class()
                else:
                    # Fallback if no specific Edge class is found, assume module itself is the edge
                    loaded_edges[edge_id] = mod

                print(f"[ALPHA] Loaded edge '{edge_id}' with params: {params}")

            except Exception as e:
                print(f"[ALPHA][ERROR] Could not import edge module '{mod_name}': {e}")

        return loaded_edges

    def _ensure_data_map(self, fetch_start: Optional[str] = None) -> Dict[str, pd.DataFrame]:
        start = fetch_start or self.start
        return self.dm.ensure_data(self.tickers, start, self.end, timeframe=self.timeframe)

    # ---------------------------- Mode Runners ---------------------------- #

    def run_backtest(
        self,
        mode: str = "prod",
        fresh: bool = False,
        no_governor: bool = False,
        reset_governor: bool = False,
        alpha_debug: bool = False,
        override_start: Optional[str] = None,
        override_end: Optional[str] = None,
        override_params: Optional[Dict] = None,
        exact_edge_ids: Optional[List[str]] = None,
        discover: bool = False,
        override_capital: Optional[float] = None,
        log_per_ticker_scores: bool = False,
        use_historical_universe: Optional[bool] = None,
    ) -> dict:
        """
        Full backtest orchestration with all features previously in run_backtest_logic().
        Returns a performance summary dict.
        """
        import os
        import json
        import random
        import shutil
        from datetime import datetime, timedelta

        import numpy as np

        # Deterministic RNG seed for the backtest pipeline. Prevents any future
        # stochastic code path (ML inference, evolution invoked mid-run, etc.)
        # from injecting wall-clock entropy into trade decisions.
        random.seed(0)
        np.random.seed(0)

        if alpha_debug:
            os.environ["ALPHA_DEBUG"] = "1"

        # --- Optional: Clear previous trade and snapshot logs (--fresh) ---
        if fresh:
            log_dir = self.root / "data" / "trade_logs"
            backup_dir = log_dir / "backup"
            backup_dir.mkdir(parents=True, exist_ok=True)
            for fn in ["trades.csv", "portfolio_snapshots.csv"]:
                fpath = log_dir / fn
                if fpath.exists() and fpath.stat().st_size > 0:
                    ts = int(time.time())
                    shutil.copy(fpath, backup_dir / f"{fn}_{ts}.bak")
                    fpath.write_text("")
            print("[RUN_BACKTEST] Cleared previous logs (fresh run mode).")

        # --- Apply overrides to config ---
        if override_start:
            self.cfg_bt["start_date"] = override_start
        if override_end:
            self.cfg_bt["end_date"] = override_end
        if override_capital:
            self.cfg_bt["initial_capital"] = override_capital

        start = self.cfg_bt.get("start_date", "2024-01-01")
        end = self.cfg_bt.get("end_date", "2024-01-01")
        tickers = self.cfg_bt.get("tickers", ["AAPL"])
        timeframe = self.cfg_bt["timeframe"]
        init_cap = float(self.cfg_bt.get("initial_capital", 100000.0))

        # --- F6 universe-loader wire: optionally swap the static ticker
        # list for the survivorship-bias-aware S&P 500 union over the
        # backtest window. Default behavior is preserved (no flag, no
        # config key, or flag=False → static list verbatim) so existing
        # measurements remain reproducible. See
        # `engines/data_manager/universe_resolver.py` for the resolver
        # contract.
        if use_historical_universe is None:
            use_historical_universe = bool(
                self.cfg_bt.get("use_historical_universe", False)
            )
        if use_historical_universe:
            from engines.data_manager.universe_resolver import (
                resolve_universe,
                discover_cached_tickers,
            )
            cache_root = self.root / "data"
            cached = discover_cached_tickers(cache_root, timeframe=timeframe)
            essentials = self.cfg_bt.get(
                "essential_tickers",
                ["SPY", "QQQ", "IWM", "TLT", "GLD"],
            )
            anchor_override = self.cfg_bt.get("historical_universe_anchor_dates")
            tickers, uni_info = resolve_universe(
                static_tickers=tickers,
                start=start,
                end=end,
                use_historical=True,
                cache_dir=cache_root,
                anchor_dates=anchor_override,
                essential_tickers=essentials,
                available_filter=cached or None,
            )
            print(
                f"[RUN_BACKTEST] Universe resolver: mode={uni_info['mode']} "
                f"static={uni_info['n_static']} → "
                f"historical_union={uni_info['n_historical_union']} → "
                f"after_essentials={uni_info['n_after_essentials']} → "
                f"after_available_filter={uni_info['n_after_available_filter']} "
                f"(anchors={len(uni_info['anchor_dates'])}, "
                f"missing_from_cache={len(uni_info['missing_from_cache'])})"
            )
            if uni_info["fallback_reason"]:
                print(
                    f"[RUN_BACKTEST][WARN] Universe fallback: {uni_info['fallback_reason']}"
                )

        # Update instance state so other helpers stay consistent
        self.start = start
        self.end = end
        self.tickers = tickers
        self.timeframe = timeframe
        self.init_cap = init_cap

        # --- 365-day warmup calculation ---
        try:
            sim_start_dt = pd.to_datetime(start)
        except Exception:
            sim_start_dt = pd.to_datetime("2024-01-01")

        fetch_start_dt = sim_start_dt - timedelta(days=365)
        fetch_start_str = fetch_start_dt.strftime("%Y-%m-%d")
        print(f"[RUN_BACKTEST] Warmup: Fetching data from {fetch_start_str} to enable indicators.")

        # --- Load data with warmup ---
        data_map = self.dm.ensure_data(tickers, fetch_start_str, end, timeframe=timeframe)
        self.dm.prefetch_fundamentals(tickers)

        # --- Load edges via EdgeRegistry ---
        loaded_edges = self._load_edges_via_registry(
            override_params=override_params,
            exact_edge_ids=exact_edge_ids,
            alpha_debug=alpha_debug,
        )

        # --- Governor initialization ---
        governor_state_path = self.root / "data" / "governor"
        if mode == "sandbox":
            governor_state_path = governor_state_path / "sandbox"
        governor_state_path.mkdir(parents=True, exist_ok=True)

        governor = StrategyGovernor(
            config_path=str(self.root / "config" / "governor_settings.json"),
            state_path=str(governor_state_path / "edge_weights.json"),
        )
        if reset_governor:
            governor.reset_weights()
            print("[RUN_BACKTEST] Governor weights reset to neutral (1.0) for this run.")

        # --- Alpha config with override injection ---
        cfg_alpha = load_json(str(self.root / f"config/alpha_settings.{self.env}.json"))
        if override_params and "alpha" in override_params:
            for k, v in override_params["alpha"].items():
                cfg_alpha[k] = v
            print(f"[OPTIMIZER] Injected Alpha Config: {override_params['alpha']}")

        # --- Initialize engines ---
        # Use config edge_weights (from alpha_settings); default to 1.0 only for
        # edges not mentioned in config.  Previously this hardcoded 1.0 for every
        # edge, overriding config weights and keeping disabled edges (weight=0) active.
        config_edge_weights = cfg_alpha.get("edge_weights", {})
        edge_weights = {eid: float(config_edge_weights.get(eid, 1.0))
                        for eid in loaded_edges}

        # Phase α v2 soft-pause: edges with status=paused trade at reduced
        # weight (default 0.25x) so the lifecycle revival gate has continuous
        # post-pause data to work with. Without this, paused edges would be
        # silenced entirely → no trades → no revival evidence → paused forever.
        #
        # PAUSED_MAX_WEIGHT caps the post-multiplier weight so edges with
        # inflated pre-pause alpha_settings weights (e.g. atr_breakout at 2.5)
        # don't dominate the signal ensemble during soft-pause. Without the cap,
        # 2.5 × 0.25 = 0.625 is still higher than most active edges at 0.5,
        # causing the paused edge to drive attribution and sizing.
        PAUSED_WEIGHT_MULTIPLIER = 0.25
        PAUSED_MAX_WEIGHT = 0.5  # paused edges cannot exceed a typical active edge weight
        _paused_ids = {
            s.edge_id for s in EdgeRegistry().get_all_specs() if s.status == "paused"
        }
        paused_count = 0
        for eid in list(edge_weights.keys()):
            if eid in _paused_ids:
                edge_weights[eid] = min(edge_weights[eid] * PAUSED_WEIGHT_MULTIPLIER, PAUSED_MAX_WEIGHT)
                paused_count += 1
        if paused_count:
            print(f"[RUN_BACKTEST] Applied {PAUSED_WEIGHT_MULTIPLIER}x soft-pause weight (max {PAUSED_MAX_WEIGHT}) to {paused_count} edge(s)")
        # Cockpit logger first — its run_uuid is the join key for the
        # per-ticker-scores parquet, so we need it before constructing
        # AlphaEngine when the per-ticker logger is enabled.
        cockpit = CockpitLogger(out_dir=str(self.root / "data" / "trade_logs"))

        # Phase 2.11 prep — optional per-bar score logger for meta-learner
        # training. Off by default; the --log-per-ticker-scores CLI flag
        # threads through ModeController.run_backtest's parameter.
        per_ticker_logger = None
        if log_per_ticker_scores:
            from engines.engine_a_alpha.per_ticker_score_logger import (
                PerTickerScoreLogger,
            )
            per_ticker_logger = PerTickerScoreLogger(
                run_uuid=cockpit.run_id,
                out_dir=self.root / "data" / "research" / "per_ticker_scores",
            )
            print(f"[RUN_BACKTEST] Per-ticker score logging ENABLED → "
                  f"data/research/per_ticker_scores/{cockpit.run_id}.parquet")

        alpha = AlphaEngine(
            edges=loaded_edges,
            edge_weights=edge_weights,
            config=cfg_alpha,
            debug=True,
            governor=governor,
            per_ticker_score_logger=per_ticker_logger,
        )
        risk = RiskEngine(
            self.cfg_risk,
            wash_sale_cfg=self.cfg_portfolio.get("wash_sale_avoidance"),
            lt_hold_cfg=self.cfg_portfolio.get("lt_hold_preference"),
        )

        exec_params = {
            "slippage_bps": float(self.cfg_bt.get("slippage_bps", 10.0)),
            "slippage_model": str(self.cfg_bt.get("slippage_model", "fixed")),
            "commission": float(self.cfg_bt.get("commission", 0.0)),
        }
        # Optional model-specific config block (e.g. realistic-model knobs:
        # impact_coefficient, mega_cap_threshold_usd, ...). Forwarded as-is
        # to ExecutionSimulator -> get_slippage_model.
        if "slippage_extra" in self.cfg_bt:
            exec_params["slippage_extra"] = self.cfg_bt["slippage_extra"]
        # Cost-completeness layer: alpaca_fees / borrow / tax configs.
        for _key in ("alpaca_fees", "borrow_rate_model", "tax_drag_model"):
            if _key in self.cfg_bt:
                exec_params[_key] = self.cfg_bt[_key]

        # --- Engine E: Regime ---
        regime_detector = RegimeDetector()

        controller = BacktestController(
            data_map=data_map,
            alpha_engine=alpha,
            risk_engine=risk,
            cockpit_logger=cockpit,
            exec_params=exec_params,
            initial_capital=init_cap,
            regime_detector=regime_detector,
            portfolio_cfg=self.portfolio_cfg,
        )

        history = controller.run(start, end)

        # Flush Logger
        controller.logger.flush()
        controller.logger.close()

        # Flush per-ticker score logger (Phase 2.11 prep). Done outside
        # any try/except so a parquet write failure surfaces to the user;
        # the in-memory buffer would otherwise be silently lost. The
        # logger itself has a CSV fallback for missing parquet engine.
        if per_ticker_logger is not None:
            out_path = per_ticker_logger.flush()
            if out_path is not None:
                print(f"[RUN_BACKTEST] Per-ticker scores: "
                      f"{per_ticker_logger.n_rows():,} rows → {out_path}")

        # --- Calculate Metrics ---
        metrics = None
        try:
            metrics = PerformanceMetrics(
                snapshots_path=str(self.root / "data" / "trade_logs" / "portfolio_snapshots.csv"),
                trades_path=str(self.root / "data" / "trade_logs" / "trades.csv"),
            )
            if not no_governor:
                governor.update_from_trades(metrics.trades, metrics.snapshots)
                governor.save_weights()
                # Phase α: autonomous lifecycle evaluation after weight updates.
                # Gated by governor.cfg.lifecycle_enabled (default False). Fires
                # retire/pause/revive transitions and appends to lifecycle_history.csv.
                governor.evaluate_lifecycle(metrics.trades)
                # Phase 2.10d Trigger 3: post-backtest tier reclassification.
                # Gated by governor.cfg.tier_reclassification_enabled (default
                # False). Re-runs FF5+Mom decomp per edge against the just-finished
                # backtest's trades.csv and updates `tier`/`combination_role`
                # in edges.yml so stale classifications self-correct.
                trades_path = self.root / "data" / "trade_logs" / "trades.csv"
                governor.evaluate_tiers(trades_path=trades_path)
        except Exception as e:
            print(f"[GOVERNOR][WARN] Could not update governor: {e}")

        # --- POST-BACKTEST DISCOVERY CYCLE (Engine D) ---
        if discover:
            self._run_discovery_cycle(data_map, regime_detector)

        # --- Return summary stats ---
        summary: dict = {}
        if metrics:
            summary = metrics.summary_dict if hasattr(metrics, "summary_dict") else metrics.summary()

        # Persist performance summary to file
        try:
            perf_path = self.root / "data" / "research" / "performance_summary.json"
            perf_path.parent.mkdir(parents=True, exist_ok=True)
            summary["timestamp"] = datetime.utcnow().isoformat() + "Z"
            with open(perf_path, "w") as f:
                json.dump(summary, f, indent=2)
        except Exception:
            pass

        # --- Decision Diary: structured measurement_run record ---
        # Append-only JSONL audit of every backtest. Wrapped in try/except
        # because a diary failure must NEVER fail a backtest.
        try:
            from core.observability import append_entry, DecisionType
            sharpe_val = summary.get("sharpe") or summary.get("sharpe_ratio")
            cagr_val = summary.get("cagr") or summary.get("CAGR")
            mdd_val = summary.get("max_drawdown") or summary.get("MDD")
            what = (
                f"backtest mode={mode} {start}..{end} "
                f"tickers={len(tickers)} edges={len(loaded_edges)}"
            )
            # Truncate defensively to fit the ≤200-char rule.
            what = what[:200]
            extra: Dict[str, Any] = {
                "sharpe": sharpe_val,
                "cagr": cagr_val,
                "max_drawdown": mdd_val,
                "n_tickers": len(tickers),
                "n_edges_loaded": len(loaded_edges),
                "mode": mode,
                "start": start,
                "end": end,
                "no_governor": bool(no_governor),
                "discover": bool(discover),
            }
            append_entry(
                decision_type=DecisionType.MEASUREMENT_RUN,
                what_changed=what,
                expected_impact=None,
                actual_impact=None,
                rationale_link=None,
                extra=extra,
                diary_path=self.root / "data" / "governor" / "decision_diary.jsonl",
            )
        except Exception as e:
            # WARN-level only — never crash a backtest because the diary
            # could not be written.
            print(f"[DECISION_DIARY][WARN] Could not append measurement_run: {e}")

        return summary

    def _run_discovery_cycle(self, data_map: Dict[str, pd.DataFrame], regime_detector: RegimeDetector) -> None:
        """
        Post-backtest discovery cycle (Engine D).
        Hunts for new edge candidates, validates them, promotes winners.
        """
        try:
            from engines.engine_d_discovery.discovery import DiscoveryEngine
            from engines.engine_d_discovery.discovery_logger import DiscoveryLogger

            discovery = DiscoveryEngine(registry_path=str(self.root / "data" / "governor" / "edges.yml"))
            disc_logger = DiscoveryLogger(log_path=str(self.root / "data" / "research" / "discovery_log.jsonl"))
            print("\n[DISCOVERY] Starting post-backtest discovery cycle...")

            # Step 1: REGIME -- get current regime context from Engine E
            regime_meta = None
            try:
                spy_df = data_map.get("SPY")
                if spy_df is not None and not spy_df.empty:
                    regime_meta = regime_detector.detect_regime(spy_df, data_map=data_map)
                    print(f"[DISCOVERY] Regime context: {regime_meta.get('regime_summary', regime_meta)}")
            except Exception as re_err:
                print(f"[DISCOVERY] Regime detection skipped: {re_err}")

            # Step 2: HUNT -- TreeScanner with expanded features + regime context
            hunt_candidates = discovery.hunt(
                data_map,
                regime_meta=regime_meta,
            )
            print(f"[DISCOVERY] Hunt found {len(hunt_candidates)} rule-based candidates.")

            # Step 3: EVOLVE -- GA cycle + template mutations
            mutation_candidates = discovery.generate_candidates(n_mutations=3)
            print(f"[DISCOVERY] Generated {len(mutation_candidates)} mutation/GA candidates.")

            all_candidates = hunt_candidates + mutation_candidates
            if all_candidates:
                discovery.save_candidates(all_candidates)

            # Step 4: VALIDATE — 4-gate pipeline with BH-FDR batch correction.
            # Pass significance_threshold=None so Gate 4 is deferred; we collect
            # all candidates' p-values, apply Benjamini-Hochberg FDR correction
            # across the batch, then re-evaluate passed_all_gates.
            from engines.engine_d_discovery.significance import apply_bh_fdr

            # Diagnostic harness override — env var DISCOVERY_DIAG_BATCH lets
            # `scripts/run_discovery_diagnostic.py` cap candidate count at 15
            # (vs the production cap of 10) and capture a per-candidate jsonl.
            import os as _os_diag
            _diag_batch_cap = int(_os_diag.environ.get("DISCOVERY_DIAG_BATCH", "10"))
            _diag_log_path = _os_diag.environ.get("DISCOVERY_DIAG_LOG") or None
            _diag_per_cand_timeout = int(_os_diag.environ.get("DISCOVERY_DIAG_TIMEOUT_SEC", "0"))

            queued = discovery.get_queued_candidates(status="candidate")
            batch = queued[:_diag_batch_cap]
            print(f"[DISCOVERY] {len(queued)} candidates queued for validation ({len(batch)} this cycle).")
            if _diag_log_path:
                print(f"[DISCOVERY-DIAG] writing per-candidate jsonl → {_diag_log_path}")
                print(f"[DISCOVERY-DIAG] per-candidate timeout = {_diag_per_cand_timeout}s (0 = none)")

            # Pass 1: collect raw metrics, defer Gate 4.
            # Share a PureBacktestCache across candidates so the production-
            # equivalent baseline (active+paused minus candidate) is computed
            # once instead of once per candidate. Without this, N candidates
            # cost 2N backtests; with it, N+1 (one baseline + N with-candidate).
            from orchestration.run_backtest_pure import PureBacktestCache
            cycle_cache = PureBacktestCache()
            all_results: list = []
            for cand in batch:
                cand_id = cand.get("edge_id", "unknown")
                print(f"[DISCOVERY] Validating {cand_id}...")
                _t_cand_start = time.time()
                _timed_out = False

                # Optional wall-time alarm — diagnostic-mode only. SIGALRM
                # delivers to the main thread; the gate code is single-threaded
                # so the next Python tick will raise. Restored to no-op after.
                _prev_handler = None
                if _diag_per_cand_timeout > 0:
                    import signal as _signal
                    def _to_handler(_signum, _frame):
                        raise TimeoutError(f"validate_candidate exceeded {_diag_per_cand_timeout}s")
                    _prev_handler = _signal.signal(_signal.SIGALRM, _to_handler)
                    _signal.alarm(_diag_per_cand_timeout)
                try:
                    result = discovery.validate_candidate(
                        cand, data_map, significance_threshold=None,
                        diagnostic_log_path=_diag_log_path,
                        cache=cycle_cache,
                    )
                except TimeoutError as toe:
                    _timed_out = True
                    print(f"[DISCOVERY] TIMEOUT for {cand_id} after {_diag_per_cand_timeout}s: {toe}")
                    result = {
                        "sharpe": 0.0, "significance_p": 1.0, "passed_all_gates": False,
                        "robustness_survival": 0.0, "fitness_score": 0.0,
                    }
                    if _diag_log_path:
                        # Best-effort timeout record so the audit doc shows it.
                        try:
                            import json as _json_to
                            from pathlib import Path as _P_to
                            _P_to(_diag_log_path).parent.mkdir(parents=True, exist_ok=True)
                            with open(_diag_log_path, "a") as _f_to:
                                _f_to.write(_json_to.dumps({
                                    "candidate_id": cand_id,
                                    "module": cand.get("module", "?"),
                                    "class": cand.get("class", "?"),
                                    "category": cand.get("category", "?"),
                                    "origin": cand.get("origin", "?"),
                                    "wall_seconds_total": round(time.time() - _t_cand_start, 3),
                                    "first_failed_gate": "timeout",
                                    "error": "timeout",
                                    "metrics": {},
                                    "gate_passed": {},
                                    "passed_all_gates": False,
                                }) + "\n")
                        except Exception as _to_emit_err:
                            print(f"[DISCOVERY-DIAG] timeout-emit failed: {_to_emit_err}")
                except Exception as ve:
                    print(f"[DISCOVERY] Validation error for {cand_id}: {ve}")
                    result = {"sharpe": 0.0, "significance_p": 1.0, "passed_all_gates": False,
                              "robustness_survival": 0.0, "fitness_score": 0.0}
                finally:
                    if _diag_per_cand_timeout > 0:
                        import signal as _signal
                        _signal.alarm(0)
                        if _prev_handler is not None:
                            _signal.signal(_signal.SIGALRM, _prev_handler)
                if not _timed_out:
                    print(f"[DISCOVERY] {cand_id} done in {time.time() - _t_cand_start:.1f}s")
                all_results.append(result)

            # Pass 2: BH-FDR batch correction on Gate 4 p-values
            raw_p_values = [r.get("significance_p", 1.0) for r in all_results]
            bh = apply_bh_fdr(raw_p_values, alpha=0.05) if raw_p_values else None
            if bh is not None:
                print(
                    f"[DISCOVERY] BH-FDR over {bh['n_tests']} candidates: "
                    f"{bh['n_rejected']} rejected, threshold={bh['threshold']:.4f}"
                )
                for i, result in enumerate(all_results):
                    result["adjusted_significance_p"] = bh["adjusted_p_values"][i]
                    result["passed_all_gates"] = (
                        result.get("sharpe", 0.0) > 0
                        and result.get("robustness_survival", 0.0) >= 0.7
                        and bool(bh["reject_at_alpha"][i])
                    )

            # Pass 3: write status + fitness metrics back to registry
            promoted = 0
            failed = 0
            for cand, result in zip(batch, all_results):
                cand_id = cand.get("edge_id", "unknown")
                if "params" not in cand:
                    cand["params"] = {}
                cand["params"]["validation_sharpe"] = result.get("sharpe", 0.0)
                cand["params"]["fitness_score"] = result.get("fitness_score", 0.0)
                cand["params"]["wfo_oos_sharpe"] = result.get("wfo_oos_sharpe", 0.0)

                if result.get("passed_all_gates", False):
                    cand["status"] = "active"
                    promoted += 1
                    print(
                        f"[DISCOVERY] PROMOTED {cand_id} "
                        f"(Sharpe={result['sharpe']:.2f}, "
                        f"survival={result.get('robustness_survival', 0):.0%}, "
                        f"p={result['significance_p']:.3f}, "
                        f"adj_p={result.get('adjusted_significance_p', float('nan')):.3f})"
                    )
                else:
                    cand["status"] = "failed"
                    failed += 1

                disc_logger.log_validation(cand_id, result, promoted=result.get("passed_all_gates", False))
                discovery.save_candidates([cand])

            disc_logger.log_cycle_summary(
                n_hunt_candidates=len(hunt_candidates),
                n_mutation_candidates=len(mutation_candidates),
                n_validated=len(batch),
                n_promoted=promoted,
                n_failed=failed,
            )
            print(f"[DISCOVERY] Cycle complete: {promoted} promoted, {failed} failed.")
        except Exception as e:
            print(f"[DISCOVERY][WARN] Discovery cycle failed: {e}")

    def run_paper(self, fill_bar_delay: int = 1, sleep_seconds: float = 0.0) -> List[dict]:
        """
        Simulated streaming using historical data, with configurable fill delay.
        Automatically updates StrategyGovernor weights from latest trade logs.
        """
        data_map = self._ensure_data_map()
        paper = PaperTradeController(
            data_map=data_map,
            alpha_engine=self.alpha,
            risk_engine=self.risk,
            cockpit_logger=self.cockpit,
            initial_capital=self.init_cap,
            exec_params=self.exec_params,
            paper_params=PaperParams(fill_bar_delay=fill_bar_delay, sleep_seconds=sleep_seconds),
            mode_label="paper",
            portfolio_cfg=self.portfolio_cfg,
        )

        history = paper.run(self.start, self.end)
        print(f"[PAPER] Complete. Snapshots: {len(history)}")

        # ✅ NEW: adaptive weight update via Governor feedback
        try:
            update_edge_weights_from_latest_trades(
                trade_log_path=str(self.root / "data" / "trade_logs" / "trades.csv"),
                snapshot_path=str(self.root / "data" / "trade_logs" / "portfolio_snapshots.csv"),
                config_path=str(self.root / "config" / "governor_settings.json"),
                state_path=str(self.root / "data" / "governor" / "edge_weights.json"),
            )
        except Exception as e:
            print(f"[EDGE_FEEDBACK][WARN] Could not update edge weights after paper run: {e}")

        self.cockpit.close()
        return history

    def run_live(self, feed, poll_seconds: float = 5.0, dry_run: bool = True, max_steps: Optional[int] = None) -> None:
        """
        Live loop using an external feed (e.g. cached CSV, Alpaca, or data stream).
        Automatically updates StrategyGovernor weights from recent trades after the run.
        """
        live = LiveTradeController(
            alpha_engine=self.alpha,
            risk_engine=self.risk,
            cockpit_logger=self.cockpit,
            initial_capital=self.init_cap,
            adapter=DryRunExecutionAdapter(
                slippage_bps=self.exec_params.get("slippage_bps", 10.0),
                commission=self.exec_params.get("commission", 0.0),
                dry_run=dry_run,
            ),
            live_params=LiveParams(poll_seconds=poll_seconds, dry_run=dry_run),
            mode_label="live" if not dry_run else "live(dry_run)",
            portfolio_cfg=self.portfolio_cfg,
        )

        live.run_loop(feed=feed, max_steps=max_steps)
        print(f"[LIVE] Complete. Total portfolio snapshots: {len(live.portfolio.history)}")

        # ✅ NEW: Adaptive feedback loop — Governor updates weights
        try:
            update_edge_weights_from_latest_trades(
                trade_log_path=str(self.root / "data" / "trade_logs" / "trades.csv"),
                snapshot_path=str(self.root / "data" / "trade_logs" / "portfolio_snapshots.csv"),
                config_path=str(self.root / "config" / "governor_settings.json"),
                state_path=str(self.root / "data" / "governor" / "edge_weights.json"),
            )
        except Exception as e:
            print(f"[EDGE_FEEDBACK][WARN] Could not update edge weights after live run: {e}")
        self.cockpit.close()


# =============================================================================
# Optional: Minimal feeds for LIVE (MVP-friendly)
# =============================================================================

class CachedCSVLiveFeed:
    """
    Minimal live-like feed that reads cached CSVs produced by DataManager.ensure_data().
    Each call to latest_map() re-reads the CSVs and returns the full frames (latest bar is df.iloc[-1]).
    This is NOT for true HFT use; it’s a practical dry-run tool and integration test harness.
    """

    def __init__(self, cache_dir: str, tickers: Iterable[str], timeframe: str):
        self.cache_dir = Path(cache_dir)
        self.tickers = list(tickers)
        self.timeframe = timeframe

    def _path(self, ticker: str) -> Path:
        return self.cache_dir / f"{ticker}_{self.timeframe}.csv"

    def latest_map(self) -> Dict[str, pd.DataFrame]:
        out: Dict[str, pd.DataFrame] = {}
        for t in self.tickers:
            p = self._path(t)
            if not p.exists() or p.stat().st_size == 0:
                continue
            try:
                df = pd.read_csv(p)
                # re-normalize minimal requirements:
                if "Date" in df.columns and "Close" in df.columns:
                    df["timestamp"] = pd.to_datetime(df["Date"], errors="coerce")
                    df = df.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
                else:
                    # Try generic parse
                    if "timestamp" in df.columns:
                        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
                        df = df.dropna(subset=["timestamp"]).set_index("timestamp").sort_index()
                    else:
                        # last resort: assume the first column is date-like
                        df.iloc[:, 0] = pd.to_datetime(df.iloc[:, 0], errors="coerce")
                        df = df.dropna(subset=[df.columns[0]]).set_index(df.columns[0]).sort_index()
                out[t] = df
            except Exception:
                continue
        return out