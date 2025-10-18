# research/edge_harness.py
from __future__ import annotations

"""
Batch Edge Research Harness
---------------------------

Runs walk-forward backtests over a parameter grid for a single edge module,
collects cross-validated performance, and exports CSV + HTML (Plotly) report.

Assumptions:
• You have a working BacktestController pipeline and config JSONs.
• The harness clones a template edge_config.json for each run and injects params under:
    config['edge_params'][<edge_name>] = { ... }
  If your AlphaEngine reads params another way, adapt _write_edge_config() accordingly.

Outputs:
• data/research/<edge_name>_<timestamp>/results.csv
• data/research/<edge_name>_<timestamp>/report.html
"""

import argparse
import itertools
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Iterable, List, Tuple

import numpy as np
import pandas as pd
import plotly.graph_objects as go

# repo-local imports
from backtester.backtest_controller import BacktestController
from engines.data_manager.data_manager import DataManager
from engines.engine_a_alpha.alpha_engine import AlphaEngine
from engines.engine_b_risk.risk_engine import RiskEngine
from engines.engine_c_portfolio.portfolio_engine import PortfolioEngine
from cockpit.metrics import PerformanceMetrics


@dataclass
class HarnessSpec:
    edge_name: str
    param_grid: Dict[str, Iterable[Any]]
    walk_forward_slices: List[Tuple[str, str]]  # list of (start,end) ISO strings
    backtest_config_path: str
    risk_config_path: str
    edge_config_template: str
    out_dir: str = "data/research"
    slippage_bps: float = 10.0
    commission: float = 0.0


def _grid_iter(grid: Dict[str, Iterable[Any]]) -> List[Dict[str, Any]]:
    keys = list(grid.keys())
    vals = [list(v) for v in grid.values()]
    combos = []
    for tup in itertools.product(*vals):
        combos.append({k: v for k, v in zip(keys, tup)})
    return combos


def _write_edge_config(template_path: str, edge_name: str, params: Dict[str, Any], out_path: Path) -> None:
    """
    Creates a modified edge_config.json with edge-specific params inserted under:
      {"active_edges": [...], "edge_params": { edge_name: params }, "edge_weights": {...}}
    Keeps other template keys intact.
    """
    with open(template_path, "r") as f:
        cfg = json.load(f)

    # Ensure active edge is listed
    act = set(cfg.get("active_edges", []))
    act.add(edge_name)
    cfg["active_edges"] = sorted(list(act))

    # Insert param payload
    ep = cfg.get("edge_params", {})
    ep[edge_name] = params
    cfg["edge_params"] = ep

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        json.dump(cfg, f, indent=2)


def _run_single_bt(
    bt_cfg: Dict[str, Any],
    risk_cfg: Dict[str, Any],
    edge_cfg_path: Path,
    start: str,
    end: str,
    slippage_bps: float,
    commission: float,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Wires up a backtest directly (bypassing ModeController for fewer assumptions).
    Returns (snapshots_df, trades_df).
    """
    # Load data
    dm = DataManager(cache_dir=bt_cfg.get("cache_dir", "data/processed"))
    data_map = dm.ensure_data(bt_cfg["tickers"], start, end, timeframe=bt_cfg["timeframe"])

    # Alpha — pass edges & params via edge_config file
    with open(edge_cfg_path, "r") as f:
        edge_cfg = json.load(f)
    edges = {}
    for name in edge_cfg.get("active_edges", []):
        try:
            mod = __import__(f"engines.engine_a_alpha.edges.{name}", fromlist=["*"])
            # If the edge supports set_params(dict), call it (optional)
            if hasattr(mod, "set_params") and edge_cfg.get("edge_params", {}).get(name):
                mod.set_params(edge_cfg["edge_params"][name])
            edges[name] = mod
        except Exception:
            continue

    alpha = AlphaEngine(
        edges=edges,
        edge_weights=edge_cfg.get("edge_weights", {}),
        debug=False,
    )

    risk = RiskEngine(risk_cfg)

    from backtester.execution_simulator import ExecutionSimulator
    exec_params = {"slippage_bps": slippage_bps, "commission": commission}
    from cockpit.logger import CockpitLogger

    # Build a throwaway logger that writes to a temp in-memory dataframes
    # (We’ll capture snapshots & trades via controller return)
    logger = CockpitLogger(out_dir="data/trade_logs")  # will still write CSVs; PerformanceMetrics will read from memory after

    controller = BacktestController(
        data_map=data_map,
        alpha_engine=alpha,
        risk_engine=risk,
        cockpit_logger=logger,
        exec_params=exec_params,
        initial_capital=float(bt_cfg["initial_capital"]),
    )

    history = controller.run(start, end)

    # Load snapshots/trades from logger files
    from cockpit.metrics import PerformanceMetrics
    pm = PerformanceMetrics()
    snaps = pm.snapshots
    trades = pm.trades if pm.trades is not None else pd.DataFrame()
    return snaps.copy(), trades.copy()


def _summarize(snaps: pd.DataFrame, trades: pd.DataFrame) -> Dict[str, Any]:
    """
    Keep this function consistent with dashboard metrics logic (sanity-capped MDD, SR, etc.).
    """
    out = {
        "total_return_pct": np.nan,
        "cagr_pct": np.nan,
        "max_drawdown_pct": np.nan,
        "sharpe": np.nan,
        "vol_pct": np.nan,
        "win_rate_pct": np.nan,
        "trades": int(trades.shape[0]) if trades is not None else 0,
    }
    if snaps is None or snaps.empty:
        return out

    snaps = snaps.dropna(subset=["equity"])
    if snaps.empty:
        return out

    start_eq = float(snaps["equity"].iloc[0])
    end_eq = float(snaps["equity"].iloc[-1])
    if start_eq > 0:
        out["total_return_pct"] = (end_eq - start_eq) / start_eq * 100.0

    days = (pd.to_datetime(snaps["timestamp"].iloc[-1]) - pd.to_datetime(snaps["timestamp"].iloc[0])).days
    if days > 0 and start_eq > 0:
        cagr = (end_eq / start_eq) ** (365.0 / days) - 1.0
        out["cagr_pct"] = cagr * 100.0

    eq = snaps["equity"].astype(float)
    rollmax = eq.cummax()
    dd = ((eq - rollmax) / rollmax).replace([np.inf, -np.inf], np.nan).fillna(0.0).clip(lower=-1.0, upper=0.0)
    out["max_drawdown_pct"] = dd.min() * 100.0

    rets = eq.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if not rets.empty and rets.std() > 0:
        out["sharpe"] = (rets.mean() / rets.std()) * np.sqrt(252.0)
        out["vol_pct"] = rets.std() * np.sqrt(252.0) * 100.0

    if trades is not None and not trades.empty and "pnl" in trades.columns:
        realized = trades.dropna(subset=["pnl"])
        if not realized.empty:
            out["win_rate_pct"] = 100.0 * (realized["pnl"] > 0).sum() / len(realized)

    return out


def run_harness(spec: HarnessSpec) -> Path:
    ts_dir = Path(spec.out_dir) / f"{spec.edge_name}_{pd.Timestamp.utcnow().strftime('%Y%m%d_%H%M%S')}"
    ts_dir.mkdir(parents=True, exist_ok=True)

    # Load base configs
    with open(spec.backtest_config_path, "r") as f:
        bt_cfg = json.load(f)
    with open(spec.risk_config_path, "r") as f:
        risk_cfg = json.load(f)

    results: List[Dict[str, Any]] = []
    combos = _grid_iter(spec.param_grid)

    for combo_idx, params in enumerate(combos, start=1):
        # make a per-combo edge_config
        edge_cfg_path = ts_dir / f"edge_config_{combo_idx:03d}.json"
        _write_edge_config(spec.edge_config_template, spec.edge_name, params, edge_cfg_path)

        for wf_idx, (start, end) in enumerate(spec.walk_forward_slices, start=1):
            try:
                snaps, trades = _run_single_bt(
                    bt_cfg=bt_cfg,
                    risk_cfg=risk_cfg,
                    edge_cfg_path=edge_cfg_path,
                    start=start,
                    end=end,
                    slippage_bps=spec.slippage_bps,
                    commission=spec.commission,
                )
                metrics = _summarize(snaps, trades)
                row = {
                    "edge": spec.edge_name,
                    "combo_idx": combo_idx,
                    "wf_idx": wf_idx,
                    "start": start,
                    "end": end,
                    **params,
                    **metrics,
                }
                results.append(row)
            except Exception as e:
                results.append({
                    "edge": spec.edge_name,
                    "combo_idx": combo_idx,
                    "wf_idx": wf_idx,
                    "start": start,
                    "end": end,
                    **params,
                    "error": str(e),
                })

    df = pd.DataFrame(results)
    csv_path = ts_dir / "results.csv"
    df.to_csv(csv_path, index=False)

    # Simple interactive report
    try:
        fig = go.Figure()
        if not df.empty and "total_return_pct" in df.columns:
            # group by combo, plot avg total return across walk-forward
            agg = df.groupby("combo_idx")["total_return_pct"].mean().reset_index()
            fig.add_trace(go.Bar(x=agg["combo_idx"], y=agg["total_return_pct"], name="Avg Total Return (%)"))
            fig.update_layout(
                title=f"Edge Research — {spec.edge_name}",
                xaxis_title="Param Combo Index",
                yaxis_title="Avg Total Return across Walk-Forward (%)",
                template="plotly_dark"
            )
        html_path = ts_dir / "report.html"
        fig.write_html(str(html_path))
    except Exception:
        pass
    # append results to Edge Research DB and show leaderboard
    try:
        from research.edge_db import EdgeResearchDB
        db = EdgeResearchDB()
        db.append_run(str(csv_path))
        ranking = db.rank_edges()
        print("\n[EDGE DB] Updated global research database.")
        print("[EDGE DB] Current Top Edges:")
        print(ranking.head(10).to_string(index=False))
    except Exception as e:
        print(f"[EDGE DB] Could not update global research database: {e}")
        
    return ts_dir


def parse_walk_forward(arg: str) -> List[Tuple[str, str]]:
    """
    Parse --walk-forward like:  "2022-01-01:2022-12-31,2023-01-01:2023-12-31"
    """
    out: List[Tuple[str, str]] = []
    for chunk in arg.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        a, b = chunk.split(":")
        out.append((a.strip(), b.strip()))
    return out


def parse_param_grid(arg: str) -> Dict[str, List[Any]]:
    """
    Accept either a JSON string or a path to a JSON file mapping param->list.
    Example content:
      {"lookback": [10, 20, 50], "threshold": [0.5, 1.0]}
    """
    p = Path(arg)
    if p.exists():
        return json.loads(p.read_text())
    return json.loads(arg)


def main() -> int:
    ap = argparse.ArgumentParser(description="Batch Edge Research Harness")
    ap.add_argument("--edge", required=True, help="edge module name (e.g., momentum_trend)")
    ap.add_argument("--param-grid", required=True, help="JSON string or path to JSON for grid")
    ap.add_argument("--walk-forward", required=True, help="CSV of start:end slices")
    ap.add_argument("--backtest-config", default="config/backtest_settings.json")
    ap.add_argument("--risk-config", default="config/risk_settings.json")
    ap.add_argument("--edge-config-template", default="config/edge_config.json")
    ap.add_argument("--out", default="data/research")
    ap.add_argument("--slippage-bps", type=float, default=10.0)
    ap.add_argument("--commission", type=float, default=0.0)
    args = ap.parse_args()

    spec = HarnessSpec(
        edge_name=args.edge,
        param_grid=parse_param_grid(args.param_grid),
        walk_forward_slices=parse_walk_forward(args.walk_forward),
        backtest_config_path=args.backtest_config,
        risk_config_path=args.risk_config,
        edge_config_template=args.edge_config_template,
        out_dir=args.out,
        slippage_bps=float(args.slippage_bps),
        commission=float(args.commission),
    )
    out_dir = run_harness(spec)
    print(f"[HARNESS] Complete. Results in: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())