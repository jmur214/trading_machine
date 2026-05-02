"""
orchestration/run_backtest_pure.py
==================================
Pure callable backtest function — invoked from inside Discovery's
`validate_candidate` to produce production-equivalent measurements
without governance side-effects.

Why this exists
---------------
The standalone single-edge backtest used by Gate 1 historically (and
copied into Gates 2/3/5) gives a different verdict from the production
ensemble for the same candidate, because the realistic cost model is
non-linear in trade size (Almgren-Chriss square-root impact) and a
single-edge-at-100%-allocation backtest crosses the impact knee that
the ensemble keeps sub-knee.

Two prior reform attempts (`gate1-reform-ensemble-simulation`,
`gate1-reform-baseline-fix`) tried to *reimplement* the ensemble inside
the gate. They closed most but not all of the baseline-vs-harness gap
(residual ~0.3 Sharpe from init-order, model-state, config subtleties).

This module's promise: invoke the actual production pipeline with
explicit edge sets and return the result, instead of reimplementing.

Differences from `ModeController.run_backtest`
----------------------------------------------
- Takes explicit `edges` (already-instantiated) and `edge_weights`.
  Caller is responsible for soft-pause weight multiplication, candidate
  inclusion/exclusion, and any other ensemble-shape decisions.
- Uses an in-memory cockpit logger, no CSV files written. Trade log
  and equity curve are returned as DataFrames.
- Skips `governor.update_from_trades`, `evaluate_lifecycle`,
  `evaluate_tiers`, performance_summary.json, flat-CSV promotion.
- Skips post-backtest discovery cycle.
- Per-run RNG seeding (random + numpy) preserved for determinism.

The intent is bit-for-bit reproducible backtests under the determinism
harness (`scripts/run_isolated.py`).
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

import numpy as np
import pandas as pd

# Lazy imports inside the function body avoid pulling Engine A/B/C at
# import time — keeps test imports fast and avoids cycles.


# =============================================================================
# Result type
# =============================================================================

@dataclass
class PureBacktestResult:
    """Return value of `run_backtest_pure`.

    Fields
    ------
    metrics
        Dict with at least: ``Sharpe Ratio``, ``Sortino``, ``CAGR (%)``,
        ``Max Drawdown (%)``, ``Volatility (%)``, ``Win Rate (%)``,
        ``Net Profit``. Computed via `cockpit.metrics.PerformanceMetrics`
        in-memory from the trade log + snapshot history.
    trade_log
        DataFrame of fills (entries + exits + SL/TP triggers) with the
        cockpit logger schema: timestamp, ticker, side, qty, fill_price,
        commission, pnl, edge, edge_group, trigger, edge_id, edge_category,
        regime_label.
    equity_curve
        pd.Series of portfolio equity indexed by timestamp. The first
        entry is the initial snapshot (initial_capital); subsequent
        entries are per-bar snapshots from BacktestController.
    daily_returns
        equity_curve.pct_change().dropna() — convenience for Sharpe /
        regression callers.
    attributed_pnl_per_edge
        Dict[edge_id -> pd.Series] of daily attributed PnL per edge.
        Each series is indexed by trading day; values sum across all
        fills of that edge realized that day.
        PnL is realized per-fill (only exit/stop/take_profit rows
        carry PnL); intra-trade unrealized PnL is not attributed.
    fingerprint
        Cache key for the configuration that produced this result.
        See `_fingerprint_inputs`.
    """

    metrics: Dict[str, float]
    trade_log: pd.DataFrame
    equity_curve: pd.Series
    daily_returns: pd.Series
    attributed_pnl_per_edge: Dict[str, pd.Series] = field(default_factory=dict)
    fingerprint: str = ""


# =============================================================================
# In-memory cockpit logger
# =============================================================================

class _MemoryCockpitLogger:
    """Drop-in cockpit logger that captures fills + snapshots in memory.

    Mimics enough of the `cockpit.logger.CockpitLogger` interface so that
    `BacktestController` can run unmodified. Notably:
      - `log_fill(fill, ts)` appends to `self.trades`
      - `log_snapshot(snap)` appends to `self.snaps`
      - `flush()`, `close()`, `set_portfolio()` are no-ops
      - `out_dir`, `run_id`, `trade_path`, `snap_path` are set to a
        non-existent tmp path so `BacktestController._post_run`'s
        existence check skips the flat-CSV promotion block.
    """

    def __init__(self, portfolio: Optional[Any] = None):
        self.run_id = str(uuid4())
        # Point trade/snap paths at a non-existent dir so _post_run skips file ops.
        self.out_dir = Path(f"/tmp/_pure_bt_{self.run_id}")
        self.trade_path = self.out_dir / "trades.csv"
        self.snap_path = self.out_dir / "portfolio_snapshots.csv"
        self.portfolio = portfolio
        self.mode = "pure"
        self.trades: List[dict] = []
        self.snaps: List[dict] = []

    def set_portfolio(self, portfolio: Any) -> None:
        self.portfolio = portfolio

    def log_fill(self, fill: Dict[str, Any], timestamp: Any) -> None:
        if not fill or "ticker" not in fill:
            return
        row = {
            "timestamp": pd.to_datetime(timestamp),
            "ticker": fill.get("ticker"),
            "side": fill.get("side"),
            "qty": fill.get("qty"),
            "fill_price": fill.get("price") or fill.get("fill_price"),
            "commission": fill.get("commission", 0.0),
            "pnl": fill.get("pnl"),
            "edge": fill.get("edge", "Unknown"),
            "edge_group": fill.get("edge_group"),
            "trigger": fill.get("trigger"),
            "meta": str(fill.get("meta", {})) if fill.get("meta") else None,
            "edge_id": fill.get("edge_id"),
            "edge_category": fill.get("edge_category"),
            "run_id": self.run_id,
            "regime_label": fill.get("regime_label", ""),
        }
        self.trades.append(row)

    def log_trade(self, fill: Dict[str, Any], timestamp: Any = None) -> None:
        if timestamp is None:
            timestamp = pd.Timestamp.utcnow()
        self.log_fill(fill, timestamp)

    def log_snapshot(self, snap: Dict[str, Any]) -> None:
        if not isinstance(snap, dict):
            return
        s = dict(snap)
        s["timestamp"] = pd.to_datetime(s.get("timestamp", pd.Timestamp.utcnow()))
        s["run_id"] = self.run_id
        self.snaps.append(s)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        return None


# =============================================================================
# Fingerprinting (for caching)
# =============================================================================

def _fingerprint_inputs(
    *,
    edge_set_keys: Tuple[str, ...],
    edge_weights: Dict[str, float],
    start_date: str,
    end_date: str,
    exec_params: Dict[str, Any],
    initial_capital: float,
) -> str:
    """Stable hash for caching pure-backtest results.

    Edge_set_keys is sorted for stability. Edge_weights is sorted by
    edge_id and rounded so trivial float wobble doesn't bust the cache.
    Exec_params is filtered to the keys that actually affect fills
    (slippage_model, slippage_bps, commission, slippage_extra) and the
    rest is ignored.
    """
    import hashlib
    import json

    payload = {
        "edges": sorted(edge_set_keys),
        "weights": sorted(
            (eid, round(float(w), 6)) for eid, w in edge_weights.items()
        ),
        "start": start_date,
        "end": end_date,
        "exec": {
            "slippage_model": str(exec_params.get("slippage_model", "fixed")),
            "slippage_bps": round(float(exec_params.get("slippage_bps", 0.0)), 4),
            "commission": round(float(exec_params.get("commission", 0.0)), 6),
            "slippage_extra": exec_params.get("slippage_extra"),
        },
        "capital": round(float(initial_capital), 2),
    }
    return hashlib.md5(
        json.dumps(payload, sort_keys=True, default=str).encode()
    ).hexdigest()


# =============================================================================
# Attribution computation
# =============================================================================

def _compute_attributed_pnl_per_edge(
    trade_log: pd.DataFrame,
) -> Dict[str, pd.Series]:
    """Per-edge daily realized-PnL series.

    Convention: PnL is realized at exit/stop/take_profit rows (entries
    have NaN PnL). For each edge, sum per-day PnL across all realized
    fills of that edge.

    Returns a dict {edge_id -> pd.Series indexed by date (normalized
    to midnight)}. Edges with no realized fills emit an empty series.
    """
    if trade_log.empty:
        return {}

    df = trade_log.copy()
    df = df.dropna(subset=["pnl"])
    if df.empty:
        return {}

    df["date"] = pd.to_datetime(df["timestamp"]).dt.normalize()
    df["edge"] = df["edge"].fillna("Unknown")

    out: Dict[str, pd.Series] = {}
    for edge_id, sub in df.groupby("edge"):
        daily = sub.groupby("date")["pnl"].sum()
        daily.name = edge_id
        out[str(edge_id)] = daily
    return out


# =============================================================================
# Metrics computation (pure, no CSV reads)
# =============================================================================

def _compute_metrics(
    snaps: List[dict],
    trades: List[dict],
    initial_capital: float,
) -> Tuple[Dict[str, float], pd.Series, pd.DataFrame]:
    """Compute Sharpe / Sortino / CAGR / MDD / WR from in-memory data.

    Avoids `cockpit.metrics.PerformanceMetrics` (which reads CSVs from
    disk) — duplicates the small subset of math we need.
    """
    if not snaps:
        empty = pd.Series(dtype=float)
        return (
            {"Sharpe Ratio": 0.0, "Sortino": 0.0, "CAGR (%)": 0.0,
             "Max Drawdown (%)": 0.0, "Volatility (%)": 0.0,
             "Win Rate (%)": 0.0, "Net Profit": 0.0},
            empty,
            pd.DataFrame(trades),
        )

    snap_df = pd.DataFrame(snaps)
    snap_df["timestamp"] = pd.to_datetime(snap_df["timestamp"])
    snap_df = snap_df.sort_values("timestamp").drop_duplicates(
        subset="timestamp", keep="last"
    )
    equity = pd.Series(
        snap_df["equity"].astype(float).values,
        index=snap_df["timestamp"].values,
    )

    trades_df = pd.DataFrame(trades)
    if not trades_df.empty:
        trades_df["timestamp"] = pd.to_datetime(trades_df["timestamp"])

    daily_ret = equity.pct_change().dropna()
    if len(daily_ret) < 2 or daily_ret.std() == 0:
        sharpe = 0.0
        sortino = 0.0
        vol = 0.0
    else:
        ann = float(np.sqrt(252))
        mu = float(daily_ret.mean())
        sigma = float(daily_ret.std())
        sharpe = (mu / sigma) * ann
        downside = daily_ret[daily_ret < 0]
        if len(downside) > 0 and downside.std() > 0:
            sortino = (mu / float(downside.std())) * ann
        else:
            sortino = 0.0
        vol = sigma * ann * 100.0

    if len(equity) >= 2:
        years = (equity.index[-1] - equity.index[0]).days / 365.25
        if years > 0:
            cagr = ((equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1) * 100.0
        else:
            cagr = 0.0
        cum_max = equity.cummax()
        mdd = float(((equity - cum_max) / cum_max).min()) * 100.0
        net_profit = float(equity.iloc[-1] - initial_capital)
    else:
        cagr = 0.0
        mdd = 0.0
        net_profit = 0.0

    win_rate = 0.0
    if not trades_df.empty and "pnl" in trades_df.columns:
        pnls = trades_df["pnl"].dropna()
        if len(pnls) > 0:
            win_rate = float((pnls > 0).mean()) * 100.0

    metrics = {
        "Sharpe Ratio": float(sharpe),
        "Sortino": float(sortino),
        "CAGR (%)": float(cagr),
        "Max Drawdown (%)": float(mdd),
        "Volatility (%)": float(vol),
        "Win Rate (%)": float(win_rate),
        "Net Profit": float(net_profit),
    }
    return metrics, equity, trades_df


# =============================================================================
# Main entry point
# =============================================================================

def run_backtest_pure(
    *,
    data_map: Dict[str, pd.DataFrame],
    edges: Dict[str, Any],
    edge_weights: Dict[str, float],
    start_date: str,
    end_date: str,
    exec_params: Dict[str, Any],
    initial_capital: float = 100_000.0,
    risk_settings: Optional[Dict[str, Any]] = None,
    alpha_config: Optional[Dict[str, Any]] = None,
    portfolio_settings: Optional[Dict[str, Any]] = None,
    use_regime_detector: bool = True,
    use_governor: bool = True,
    project_root: Optional[Path] = None,
    seed: int = 0,
) -> PureBacktestResult:
    """Run a production-equivalent backtest without governance side-effects.

    Parameters
    ----------
    data_map
        Ticker -> OHLCV DataFrame (datetime index). Pre-loaded by the
        caller (no DataManager I/O inside this function).
    edges
        Already-instantiated edges to deploy. Caller decides which
        edges are present (active set, soft-paused set, candidate, etc.).
    edge_weights
        edge_id -> float weight. Caller is responsible for any soft-pause
        multiplier already baked in.
    start_date, end_date
        ISO date strings.
    exec_params
        slippage_model / slippage_bps / commission / slippage_extra.
    initial_capital
        Starting capital for the simulated portfolio.
    risk_settings, alpha_config, portfolio_settings
        Config dicts. If None, the production prod env files are loaded.
    use_regime_detector
        If True, instantiate a RegimeDetector (production parity). If
        False, runs without regime context (faster but not production-
        equivalent).
    use_governor
        If True, instantiate a `StrategyGovernor` with reset weights
        (matches `--reset-governor` semantics). State_path is set to a
        tmp file so any writes don't touch the real governor state.
    project_root
        Repo root for config loading. Defaults to discovering it via
        the current working directory.
    seed
        RNG seed for determinism.

    Returns
    -------
    PureBacktestResult — see dataclass docstring.

    Notes
    -----
    - This function does NOT mutate any persistent state. governor
      lifecycle / tier writes are skipped, performance_summary.json is
      not written, flat-CSV promotion is suppressed.
    - The full warmup (365-day fetch_start) is the caller's
      responsibility; this function honors `start_date` exactly.
    """
    # Lazy imports
    from utils.config_loader import load_json
    from engines.engine_a_alpha.alpha_engine import AlphaEngine
    from engines.engine_b_risk.risk_engine import RiskEngine
    from engines.engine_c_portfolio.policy import PortfolioPolicyConfig
    from engines.engine_e_regime.regime_detector import RegimeDetector
    from engines.engine_f_governance.governor import StrategyGovernor
    from backtester.backtest_controller import BacktestController

    # Determinism
    random.seed(seed)
    np.random.seed(seed)

    # Project root
    if project_root is None:
        # Heuristic: walk up from this file to find the repo (where CLAUDE.md sits).
        here = Path(__file__).resolve()
        for parent in [here.parent, *here.parents]:
            if (parent / "CLAUDE.md").exists() or (parent / "engines").exists():
                project_root = parent
                break
        else:
            project_root = here.parents[1]

    project_root = Path(project_root)

    # Configs
    if risk_settings is None:
        try:
            risk_settings = load_json(str(project_root / "config" / "risk_settings.prod.json"))
        except Exception:
            risk_settings = {"risk_per_trade_pct": 0.01}

    if alpha_config is None:
        try:
            alpha_config = load_json(str(project_root / "config" / "alpha_settings.prod.json"))
        except Exception:
            alpha_config = {}

    if portfolio_settings is None:
        try:
            portfolio_settings = load_json(str(project_root / "config" / "portfolio_settings.json"))
        except Exception:
            portfolio_settings = {}

    pp_cfg = PortfolioPolicyConfig(
        **{k: v for k, v in (portfolio_settings or {}).items()
           if k in PortfolioPolicyConfig.__annotations__}
    )

    # Governor (with tmp state to avoid real-state writes)
    governor = None
    if use_governor:
        import tempfile
        tmp_state = Path(tempfile.mkdtemp(prefix="_pure_gov_")) / "edge_weights.json"
        try:
            governor = StrategyGovernor(
                config_path=str(project_root / "config" / "governor_settings.json"),
                state_path=str(tmp_state),
            )
            governor.reset_weights()
        except Exception as e:
            # If governor fails to construct (missing config etc.) run without it.
            print(f"[run_backtest_pure] Governor unavailable ({type(e).__name__}: {e}); running without")
            governor = None

    # Memory logger
    cockpit = _MemoryCockpitLogger()

    # Alpha
    alpha = AlphaEngine(
        edges=edges,
        edge_weights=edge_weights,
        config=alpha_config,
        debug=False,
        governor=governor,
    )

    # Risk
    risk = RiskEngine(risk_settings)

    # Regime detector
    regime_detector = RegimeDetector() if use_regime_detector else None

    # Controller
    controller = BacktestController(
        data_map=data_map,
        alpha_engine=alpha,
        risk_engine=risk,
        cockpit_logger=cockpit,
        exec_params=exec_params,
        initial_capital=initial_capital,
        regime_detector=regime_detector,
        portfolio_cfg=pp_cfg,
    )
    controller.run(start_date, end_date)

    # Compute metrics from in-memory data (no CSV reads)
    metrics, equity_curve, trade_log = _compute_metrics(
        cockpit.snaps, cockpit.trades, initial_capital
    )

    # Sortino / Sharpe present in metrics; build daily returns
    daily_returns = (
        equity_curve.pct_change().dropna() if len(equity_curve) > 1 else pd.Series(dtype=float)
    )

    # Attribution per edge
    attributed = _compute_attributed_pnl_per_edge(trade_log)

    # Fingerprint
    fp = _fingerprint_inputs(
        edge_set_keys=tuple(edges.keys()),
        edge_weights=edge_weights,
        start_date=start_date,
        end_date=end_date,
        exec_params=exec_params,
        initial_capital=initial_capital,
    )

    return PureBacktestResult(
        metrics=metrics,
        trade_log=trade_log,
        equity_curve=equity_curve,
        daily_returns=daily_returns,
        attributed_pnl_per_edge=attributed,
        fingerprint=fp,
    )


# =============================================================================
# Caching wrapper — safe within a single Discovery cycle
# =============================================================================

class PureBacktestCache:
    """In-memory cache keyed by `_fingerprint_inputs`.

    Use within a single Discovery cycle so N candidates cost N+1 backtests
    (one baseline, N with-candidate runs) instead of 2N. The cache is NOT
    thread-safe and NOT cross-process; instantiate one per cycle.
    """

    def __init__(self) -> None:
        self._cache: Dict[str, PureBacktestResult] = {}

    def get_or_run(
        self,
        *,
        data_map: Dict[str, pd.DataFrame],
        edges: Dict[str, Any],
        edge_weights: Dict[str, float],
        start_date: str,
        end_date: str,
        exec_params: Dict[str, Any],
        initial_capital: float = 100_000.0,
        **run_kwargs: Any,
    ) -> PureBacktestResult:
        fp = _fingerprint_inputs(
            edge_set_keys=tuple(edges.keys()),
            edge_weights=edge_weights,
            start_date=start_date,
            end_date=end_date,
            exec_params=exec_params,
            initial_capital=initial_capital,
        )
        if fp in self._cache:
            return self._cache[fp]
        result = run_backtest_pure(
            data_map=data_map,
            edges=edges,
            edge_weights=edge_weights,
            start_date=start_date,
            end_date=end_date,
            exec_params=exec_params,
            initial_capital=initial_capital,
            **run_kwargs,
        )
        self._cache[fp] = result
        return result

    def clear(self) -> None:
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)


__all__ = [
    "PureBacktestResult",
    "run_backtest_pure",
    "PureBacktestCache",
    "_fingerprint_inputs",
    "_compute_attributed_pnl_per_edge",
]
