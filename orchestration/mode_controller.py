# orchestration/mode_controller.py
"""
ModeController
==============

Orchestrates the end-to-end trading pipeline in three modes:
- BACKTEST: historical run using BacktestController (fills at next bar open; slippage/commission applied)
- PAPER: streaming simulation on rolling bars (supports configurable fill delay and partial fills)
- LIVE: same pipeline, but execution routes to a broker adapter interface (dry_run by default)

This module keeps strict separation between components:
    Engine A (Alpha)     -> signal generation
    Engine B (Risk)      -> sizing & order constraints
    Engine C (Portfolio) -> accounting (cash + positions = equity)
    Execution            -> simulator or live adapter
    Cockpit              -> logging snapshots & trades to CSV (mode-aware if logger supports it)

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
from typing import Dict, Iterable, List, Optional, Tuple

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

            # (Optional) simulate exit logic here if you want paper mode to auto-exit like backtest.
            # For parity with your BacktestController, we’ll close positions if no new order for ticker this turn.
            for ticker, pos in list(self.portfolio.positions.items()):
                if ticker not in next_rows:
                    continue
                if not any(o["ticker"] == ticker for o in orders):
                    exit_fill = self.exec.exit_position(ticker, pos, next_rows[ticker])
                    if exit_fill:
                        if hasattr(self.logger, "log_fill"):
                            self.portfolio.apply_fill(exit_fill)
                            self.logger.log_fill(exit_fill, fill_ts)

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

    def __init__(self, project_root: Path):
        self.root = Path(project_root)

        # --- Load configuration files ---
        self.cfg_bt = load_json(str(self.root / "config" / "backtest_settings.json"))
        self.cfg_risk = load_json(str(self.root / "config" / "risk_settings.json"))
        self.cfg_edges = load_json(str(self.root / "config" / "edge_config.json"))
        self.cfg_portfolio = load_json(str(self.root / "config" / "portfolio_settings.json"))

        # --- Core run params ---
        self.tickers: List[str] = self.cfg_bt["tickers"]
        self.start: str = self.cfg_bt["start_date"]
        self.end: str = self.cfg_bt["end_date"]
        self.timeframe: str = self.cfg_bt["timeframe"]
        self.init_cap: float = float(self.cfg_bt["initial_capital"])

        # --- Exec params (slippage/commission) ---
        self.exec_params = {
            "slippage_bps": float(self.cfg_bt.get("slippage_bps", 10.0)),
            "commission": float(self.cfg_bt.get("commission", 0.0)),
        }

        # --- Prepare data manager ---
        self.dm = DataManager(cache_dir=str(self.root / "data" / "processed"))

        # --- Load edges dynamically ---
        self.edges = self._load_edges()
        self.edge_weights = self.cfg_edges.get("edge_weights", {})

        # --- Engines ---
        self.alpha = AlphaEngine(edges=self.edges, edge_weights=self.edge_weights, debug=True)
        self.risk = RiskEngine(self.cfg_risk)
        
        # --- Portfolio Config Object ---
        from engines.engine_c_portfolio.policy import PortfolioPolicyConfig
        pp_cfg = PortfolioPolicyConfig(**{k:v for k,v in self.cfg_portfolio.items() if k in PortfolioPolicyConfig.__annotations__})
        self.portfolio_cfg = pp_cfg

        # --- Cockpit ---
        self.cockpit = CockpitLogger(out_dir=str(self.root / "data" / "trade_logs"), flush_each_fill=True)
        print(f"[COCKPIT] Trade log -> {self.cockpit.trade_path}")
        print(f"[COCKPIT] Snapshot log -> {self.cockpit.snap_path}")

    # ---------------------------- Helpers ---------------------------- #

    def _load_edges(self) -> Dict[str, object]:
        edges: Dict[str, object] = {}
        active_edges = self.cfg_edges.get("active_edges", [])
        # Load edge parameters from edge_config if present
        edge_params = self.cfg_edges.get("edge_params", {})
        for edge_name in active_edges:
            try:
                mod = importlib.import_module(f"engines.engine_a_alpha.edges.{edge_name}")
                # If the module has set_params and config exists, call it
                params = edge_params.get(edge_name)
                if params and hasattr(mod, "set_params") and callable(getattr(mod, "set_params")):
                    try:
                        mod.set_params(params)
                    except Exception as e:
                        print(f"[ALPHA][WARN] Could not set params for edge '{edge_name}': {e}")
                edges[edge_name] = mod
            except Exception as e:
                print(f"[ALPHA][ERROR] Could not import edge '{edge_name}': {e}")
        print(f"[ALPHA] Loaded {len(edges)} edges: {list(edges.keys())}")
        return edges

    def _ensure_data_map(self) -> Dict[str, pd.DataFrame]:
        return self.dm.ensure_data(self.tickers, self.start, self.end, timeframe=self.timeframe)

    # ---------------------------- Mode Runners ---------------------------- #

    def run_backtest(self) -> List[dict]:
        data_map = self._ensure_data_map()
        controller = BacktestController(
            data_map=data_map,
            alpha_engine=self.alpha,
            risk_engine=self.risk,
            cockpit_logger=self.cockpit,
            exec_params=self.exec_params,
            initial_capital=self.init_cap,
            portfolio_cfg=self.portfolio_cfg,
        )
        history = controller.run(self.start, self.end)
        print(f"[BACKTEST] Complete. Snapshots: {len(history)}")
        self.cockpit.close()
        return history

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