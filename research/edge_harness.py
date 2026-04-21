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

import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import itertools
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Iterable, List, Tuple

from debug_config import is_debug_enabled, is_info_enabled

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf

# Global cache for regime data
GLOBAL_SPY_DF = None

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


# Helper to recursively convert numpy/pandas objects to native Python types
def _to_native(obj):
    import numpy as np
    import pandas as pd
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_native(v) for v in obj]
    if isinstance(obj, (np.generic, pd.Series)):
        try:
            return obj.item()
        except Exception:
            return float(obj)
    return obj


import threading
import time
import gc

def _run_single_bt(
    bt_cfg: Dict[str, Any],
    risk_cfg: Dict[str, Any],
    edge_cfg_path: Path,
    start: str,
    end: str,
    slippage_bps: float,
    commission: float,
    edge_name: str = None,
) -> Tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """
    Wires up a backtest directly (bypassing ModeController for fewer assumptions).
    Returns (snapshots_df, trades_df, stats_dict) or, in case of error, (EmptyDF, EmptyDF, {"error": ...})
    """
    import traceback
    import tempfile
    import shutil
    tmp_dir = tempfile.mkdtemp(prefix="cockpit_logs_")
    # Defensive: always remove tmp_dir at the end, no matter what
    try:
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
                
                # Find the class in the module that is an EdgeBase subclass
                from engines.engine_a_alpha.edge_base import EdgeBase
                import inspect
                
                edge_instance = None
                for attr_name in dir(mod):
                    attr = getattr(mod, attr_name)
                    if isinstance(attr, type) and issubclass(attr, EdgeBase) and attr is not EdgeBase:
                        edge_instance = attr()
                        break
                
                if edge_instance:
                    if edge_cfg.get("edge_params", {}).get(name):
                        edge_instance.set_params(edge_cfg["edge_params"][name])
                    edges[name] = edge_instance
                else:
                    # Fallback to module if no class found (legacy support)
                    if hasattr(mod, "set_params") and edge_cfg.get("edge_params", {}).get(name):
                        mod.set_params(edge_cfg["edge_params"][name])
                    edges[name] = mod
            except Exception as e:
                print(f"[HARNESS][WARN] Failed to load edge {name}: {e}")
                continue

        # Load alpha config if specified in bt_cfg or env
        # Note: We rely on the caller to provide alpha settings, but here we can try to load the production one
        # To make this robust, let's load config/alpha_settings.prod.json if it exists, else alpha_settings.json
        alpha_config_path = "config/alpha_settings.prod.json"
        if not os.path.exists(alpha_config_path):
            alpha_config_path = "config/alpha_settings.json"
        
        with open(alpha_config_path, "r") as f:
            alpha_config = json.load(f)

        alpha = AlphaEngine(
            edges=edges,
            edge_weights=edge_cfg.get("edge_weights", {}),
            config=alpha_config,
            debug=False,
        )

        risk = RiskEngine(risk_cfg)

        from backtester.execution_simulator import ExecutionSimulator
        exec_params = {"slippage_bps": slippage_bps, "commission": commission}
        from cockpit.logger import CockpitLogger

        # Build a throwaway logger that writes to a temp in-memory dataframes
        logger = CockpitLogger(out_dir=tmp_dir)  # will still write CSVs; PerformanceMetrics will read from memory after

        controller = BacktestController(
            data_map=data_map,
            alpha_engine=alpha,
            risk_engine=risk,
            cockpit_logger=logger,
            exec_params=exec_params,
            initial_capital=float(bt_cfg["initial_capital"]),
        )

        history = controller.run(start, end)
        
        # New CockpitLogger writes to {tmp_dir}/{run_id}/portfolio_snapshots.csv
        # We need to find the run_id folder
        subdirs = [d for d in os.listdir(tmp_dir) if os.path.isdir(os.path.join(tmp_dir, d))]
        run_dir = tmp_dir
        for d in subdirs:
            candidate = os.path.join(tmp_dir, d)
            if os.path.exists(os.path.join(candidate, "portfolio_snapshots.csv")):
                run_dir = candidate
                break
        else:
            run_dir = tmp_dir # Fallback
            
        # Load snapshots/trades directly from logger outputs
        from cockpit.metrics import PerformanceMetrics
        pm = PerformanceMetrics(
            snapshots_path=os.path.join(run_dir, "portfolio_snapshots.csv"),
            trades_path=os.path.join(run_dir, "trades.csv"),
        )
        snaps = pm.snapshots.copy() if pm.snapshots is not None else pd.DataFrame()
        trades = pm.trades.copy() if pm.trades is not None else pd.DataFrame()
        # Try to compute performance stats using PerformanceMetrics, with fallback for print-only .summary()
        try:
            stats = None
            if hasattr(pm, "summary_metrics"):
                stats = pm.summary_metrics()
            elif hasattr(pm, "summary"):
                # Try calling summary(), if it returns a dict, use it; else, capture printed output
                s = pm.summary()
                if isinstance(s, dict):
                    stats = s
                elif s is None:
                    # Fallback: capture printed output
                    import io
                    import contextlib
                    buf = io.StringIO()
                    with contextlib.redirect_stdout(buf):
                        pm.summary()
                    output = buf.getvalue()
                    # Parse lines like 'Sharpe Ratio: 1.23'
                    lines = output.splitlines()
                    parsed = {}
                    for line in lines:
                        if ":" in line:
                            k, v = line.split(":", 1)
                            key = k.strip().lower().replace(" ", "_")
                            val = v.strip().replace("%", "")
                            try:
                                valf = float(val)
                            except Exception:
                                valf = val
                            parsed[key] = valf
                    # Try to map known keys to expected ones
                    mapping = {
                        "total_return": "total_return_pct",
                        "cagr": "cagr_pct",
                        "max_drawdown": "max_drawdown_pct",
                        "sharpe_ratio": "sharpe",
                        "volatility": "vol_pct",
                        "win_rate": "win_rate_pct",
                        "trades": "trades"
                    }
                    stats = {}
                    for orig_k, v in parsed.items():
                        mapped = mapping.get(orig_k, orig_k)
                        # Cast to float if possible
                        try:
                            v2 = float(v)
                        except Exception:
                            v2 = v
                        stats[mapped] = v2
                else:
                    stats = {}
            else:
                print("[HARNESS][WARN] PerformanceMetrics has no summary method — skipping metrics extraction.")
                stats = {}
            if stats is None:
                stats = {}
        except Exception as e:
            err_msg = f"[HARNESS][METRIC ERROR] {edge_name or ''} {start}–{end}: {e}"
            print(err_msg)
            print(traceback.format_exc())
            shutil.rmtree(tmp_dir, ignore_errors=True)
            return snaps, trades, {"error": f"PerformanceMetrics error: {str(e)}"}
        # Defensive: if stats is not dict, or is None, wrap
        if not isinstance(stats, dict):
            stats = {}
        # Normalize keys in case PerformanceMetrics returns display names
        normalized = {}
        for k, v in stats.items():
            lk = str(k).strip().lower()
            # Normalize possible numeric types to float where applicable
            try:
                v_native = float(v)
            except Exception:
                v_native = v
            if "total return" in lk:
                normalized["total_return_pct"] = v_native
            elif "cagr" in lk:
                normalized["cagr_pct"] = v_native
            elif "max drawdown" in lk:
                normalized["max_drawdown_pct"] = v_native
            elif "sharpe" in lk:
                normalized["sharpe"] = v_native
            elif "volatility" in lk or "vol" in lk:
                normalized["vol_pct"] = v_native
            elif "win rate" in lk:
                normalized["win_rate_pct"] = v_native
            elif "trade" in lk:
                normalized["trades"] = v_native
        # Merge normalized metrics with the original, giving priority to normalized keys
        merged_stats = {**stats, **normalized}
        # Explicitly cast numeric fields to float (or int for trades) before return
        for k in [
            "total_return_pct", "cagr_pct", "max_drawdown_pct",
            "sharpe", "vol_pct", "win_rate_pct"
        ]:
            if k in merged_stats:
                try:
                    merged_stats[k] = float(merged_stats[k])
                except Exception:
                    pass
        if "trades" in merged_stats:
            try:
                merged_stats["trades"] = float(merged_stats["trades"])
            except Exception:
                pass
        shutil.rmtree(tmp_dir, ignore_errors=True)
        return snaps, trades, merged_stats
    except Exception as e:
        import traceback
        err_msg = f"[HARNESS][RUN ERROR] {edge_name or ''} {start}–{end}: {e}"
        print(err_msg)
        print(traceback.format_exc())
        try:
            shutil.rmtree(tmp_dir, ignore_errors=True)
        except Exception:
            pass
        # Return empty DataFrames and error dict
        return pd.DataFrame(), pd.DataFrame(), {"error": str(e)}


def _augment_with_regime(snaps: pd.DataFrame) -> pd.DataFrame:
    if GLOBAL_SPY_DF is None or snaps.empty:
        return snaps
    try:
        df = snaps.copy()
        # Normalize to date for merging
        df['date'] = pd.to_datetime(df['timestamp']).dt.normalize()
        spy_subset = GLOBAL_SPY_DF[['is_bull', 'is_high_vol']].copy()
        if spy_subset.empty: return snaps
        spy_subset.index = pd.to_datetime(spy_subset.index).normalize()
        # Merge left to keep all snaps rows
        return df.merge(spy_subset, left_on='date', right_index=True, how='left')
    except Exception:
        return snaps


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
        "sharpe_bull": np.nan,
        "sharpe_bear": np.nan,
        "sharpe_high_vol": np.nan,
        "sharpe_low_vol": np.nan,
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
    
    # --- Regime Specific Stats ---
    try:
        reg_df = _augment_with_regime(snaps)
        if 'is_bull' in reg_df.columns:
            # Bull
            bull = reg_df[reg_df['is_bull'] == True]
            if len(bull) > 20:
                rb = bull['equity'].pct_change().dropna()
                if rb.std() > 0: out['sharpe_bull'] = (rb.mean() / rb.std()) * np.sqrt(252.0)
            # Bear
            bear = reg_df[reg_df['is_bull'] == False]
            if len(bear) > 20:
                rb = bear['equity'].pct_change().dropna()
                if rb.std() > 0: out['sharpe_bear'] = (rb.mean() / rb.std()) * np.sqrt(252.0)
            # High Vol
            hv = reg_df[reg_df['is_high_vol'] == True]
            if len(hv) > 20:
                rb = hv['equity'].pct_change().dropna()
                if rb.std() > 0: out['sharpe_high_vol'] = (rb.mean() / rb.std()) * np.sqrt(252.0)
            # Low Vol
            lv = reg_df[reg_df['is_high_vol'] == False]
            if len(lv) > 20:
                rb = lv['equity'].pct_change().dropna()
                if rb.std() > 0: out['sharpe_low_vol'] = (rb.mean() / rb.std()) * np.sqrt(252.0)
    except Exception:
        pass

    if trades is not None and not trades.empty and "pnl" in trades.columns:
        realized = trades.dropna(subset=["pnl"])
        if not realized.empty:
            out["win_rate_pct"] = 100.0 * (realized["pnl"] > 0).sum() / len(realized)

    # Ensure all keys present with np.nan if missing
    required_keys = ["total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "vol_pct", "win_rate_pct", "trades", "sharpe_bull", "sharpe_bear"]
    for key in required_keys:
        if key not in out:
            out[key] = np.nan

    return out


# --- Helper to clean metrics: ensure no NaN, inf, or dtype pollution ---
def _clean_metrics(df: pd.DataFrame) -> pd.DataFrame:
    """
    Clean metric columns: coerce to float, replace inf/NaN with 0.0,
    and ensure no dtype pollution for DB safety.
    """
    metric_cols = [
        "total_return_pct", "cagr_pct", "max_drawdown_pct",
        "sharpe", "vol_pct", "win_rate_pct", "trades"
    ]
    for col in metric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").replace([np.inf, -np.inf], np.nan).fillna(0.0)
            if col == "trades":
                df[col] = df[col].astype(int)
    return df
def _safe_append_to_db(csv_path: str):
    """Append run results to EdgeResearchDB, catching all errors and logging cleanly."""
    try:
        from research.edge_db import EdgeResearchDB
        db = EdgeResearchDB()
        db.append_run(csv_path)
        ranking = db.rank_edges()
        if is_info_enabled("HARNESS") or is_debug_enabled("HARNESS"):
            print("\n[EDGE DB] Updated global research database.")
            print("[EDGE DB] Current Top Edges:")
            print(ranking.head(10).to_string(index=False))
    except Exception as e:
        if is_debug_enabled("HARNESS"):
            print(f"[EDGE DB][ERROR] Failed to append results: {e}")


def run_harness(spec: HarnessSpec) -> Path:
    import sys
    import psutil
    ts_dir = Path(spec.out_dir) / f"{spec.edge_name}_{pd.Timestamp.utcnow().strftime('%Y%m%d_%H%M%S')}"
    ts_dir.mkdir(parents=True, exist_ok=True)

    # Load base configs
    with open(spec.backtest_config_path, "r") as f:
        bt_cfg = json.load(f)
    with open(spec.risk_config_path, "r") as f:
        risk_cfg = json.load(f)

    # Pre-fetch SPY data for regime detection (Regime-Aware Harness)
    global GLOBAL_SPY_DF
    if GLOBAL_SPY_DF is None:
        try:
            if is_info_enabled("HARNESS"): print("[HARNESS] Fetching SPY data for Regime-Aware metrics...")
            spy_raw = yf.download("SPY", period="10y", progress=False, auto_adjust=True) 
            if not spy_raw.empty:
                if isinstance(spy_raw.columns, pd.MultiIndex):
                    spy_raw.columns = spy_raw.columns.get_level_values(0)
                
                # 1. Trend (SMA200)
                spy_raw['SMA200'] = spy_raw['Close'].rolling(200).mean()
                spy_raw['is_bull'] = spy_raw['Close'] > spy_raw['SMA200']
                
                # 2. Volatility (ATR approx using simple TR)
                high = spy_raw['High']
                low = spy_raw['Low']
                close = spy_raw['Close']
                # Vectorized TR (High-Low, High-PreClose, Low-PreClose)
                tr0 = abs(high - low)
                tr1 = abs(high - close.shift())
                tr2 = abs(low - close.shift())
                tr = pd.concat([tr0, tr1, tr2], axis=1).max(axis=1)
                
                atr = tr.rolling(14).mean()
                vol_75 = atr.rolling(252).quantile(0.75)
                spy_raw['is_high_vol'] = atr > vol_75
                
                GLOBAL_SPY_DF = spy_raw
                if is_info_enabled("HARNESS"): print(f"[HARNESS] SPY data cached. Rows: {len(spy_raw)}")
        except Exception as e:
            print(f"[HARNESS][WARN] Failed to fetch SPY for regime metrics: {e}")

    results: List[Dict[str, Any]] = []
    combos = _grid_iter(spec.param_grid)

    total_combos = len(combos)
    total_wf = len(spec.walk_forward_slices)
    total_runs = total_combos * total_wf
    run_count = 0
    stop_flag = threading.Event()

    def _safety_check():
        # Non-blocking safety mechanism: check for memory bloat, other conditions, etc.
        # Could be extended for timeouts, etc.
        try:
            proc = psutil.Process()
            mem = proc.memory_info().rss / (1024 ** 2)
            if mem > 8 * 1024:  # 8 GB
                print(f"[HARNESS][WARN] High memory usage detected: {mem:.1f} MB")
        except Exception:
            pass
        return True

    try:
        for combo_idx, params in enumerate(combos, start=1):
            edge_cfg_path = ts_dir / f"edge_config_{combo_idx:03d}.json"
            _write_edge_config(spec.edge_config_template, spec.edge_name, params, edge_cfg_path)

            for wf_idx, (start, end) in enumerate(spec.walk_forward_slices, start=1):
                run_count += 1
                # Periodic progress reporting
                if is_debug_enabled("HARNESS"):
                    print(f"[HARNESS][PROGRESS] Combo {combo_idx}/{total_combos} | WF {wf_idx}/{total_wf} | Run {run_count}/{total_runs} | Params: {params} | Slice: {start}–{end}")
                snaps = trades = stats = None
                try:
                    snaps, trades, stats = _run_single_bt(
                        bt_cfg=bt_cfg,
                        risk_cfg=risk_cfg,
                        edge_cfg_path=edge_cfg_path,
                        start=start,
                        end=end,
                        slippage_bps=spec.slippage_bps,
                        commission=spec.commission,
                        edge_name=spec.edge_name,
                    )
                except KeyboardInterrupt:
                    print("[HARNESS][INFO] KeyboardInterrupt detected. Stopping gracefully and saving partial results...")
                    stop_flag.set()
                    # Save partial results and break
                    break
                except Exception as e:
                    # Should not happen, since _run_single_bt now catches its own errors, but for safety:
                    snaps, trades, stats = pd.DataFrame(), pd.DataFrame(), {"error": str(e)}
                # If error present in stats, fill row accordingly and skip metrics
                if isinstance(stats, dict) and "error" in stats:
                    row = {
                        "edge": spec.edge_name,
                        "combo_idx": combo_idx,
                        "wf_idx": wf_idx,
                        "start": start,
                        "end": end,
                        **params,
                        "error": stats["error"],
                    }
                    for col in ["total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe", "vol_pct", "win_rate_pct", "trades"]:
                        row[col] = np.nan if col != "trades" else 0
                    results.append(row)
                else:
                    metrics = stats if stats and isinstance(stats, dict) and len(stats) > 0 else _summarize(snaps, trades)
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

                # Periodic flush and memory cleanup every 5 runs or so
                if run_count % 5 == 0 or stop_flag.is_set():
                    if is_debug_enabled("HARNESS"):
                        print(f"[HARNESS][DEBUG] Flushing partial results and cleaning memory at run {run_count}")
                    # Write partial results to CSV
                    pd.DataFrame(results).to_csv(ts_dir / "partial_results.csv", index=False)
                    gc.collect()
                _safety_check()
                # Small sleep to avoid overwhelming I/O/CPU
                time.sleep(0.1)

            if stop_flag.is_set():
                break
        # Final flush after all runs
        if is_debug_enabled("HARNESS"):
            print("[HARNESS][DEBUG] Final flush and memory cleanup.")
        gc.collect()
    except KeyboardInterrupt:
        print("[HARNESS][INFO] KeyboardInterrupt detected at outer loop. Saving partial results and exiting...")
        stop_flag.set()
    except Exception as e:
        print(f"[HARNESS][ERROR] Unexpected error: {e}")
        import traceback
        print(traceback.format_exc())

    df = pd.DataFrame(results)
    # ✅ Ensure consistent metric columns even if some runs failed
    expected_cols = [
        "edge", "combo_idx", "wf_idx", "start", "end",
        "total_return_pct", "cagr_pct", "max_drawdown_pct",
        "sharpe", "vol_pct", "win_rate_pct", "trades", "error",
        "sharpe_bull", "sharpe_bear", "sharpe_high_vol", "sharpe_low_vol"
    ]
    for col in expected_cols:
        if col not in df.columns:
            if col == "trades":
                df[col] = 0
            elif col == "error":
                df[col] = np.nan
            else:
                df[col] = np.nan

    if is_debug_enabled("HARNESS"):
        print("[HARNESS][DEBUG] Cleaning metrics before DB append.")
    df = _clean_metrics(df)
    if is_debug_enabled("HARNESS"):
        print("[HARNESS][DEBUG] Metrics cleaned successfully.")

    csv_path = ts_dir / "results.csv"
    df.to_csv(csv_path, index=False)

    # Simple interactive report
    try:
        fig = go.Figure()
        if not df.empty and "total_return_pct" in df.columns:
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
    _safe_append_to_db(str(csv_path))

    # --- Auto-promotion: update config with best parameters based on Sharpe or CAGR ---
    try:
        valid_df = df[df["error"].isna()] if "error" in df.columns else df
        metric_cols = [
            "total_return_pct", "cagr_pct", "max_drawdown_pct",
            "sharpe", "vol_pct", "win_rate_pct", "trades"
        ]
        valid_metric_rows = valid_df[
            valid_df[metric_cols].replace(0.0, np.nan).notna().any(axis=1)
        ] if not valid_df.empty else valid_df
        if valid_metric_rows.empty:
            if is_info_enabled("HARNESS") or is_debug_enabled("HARNESS"):
                print("[PROMOTE][INFO] Skipping promotion: no valid metric values.")
        else:
            metrics_df = valid_metric_rows.groupby("combo_idx").agg({
                "sharpe": "mean",
                "cagr_pct": "mean"
            }).reset_index()
            if metrics_df["sharpe"].notna().any():
                best_row = metrics_df.loc[metrics_df["sharpe"].idxmax()]
            else:
                best_row = metrics_df.loc[metrics_df["cagr_pct"].idxmax()]
            best_combo_idx = best_row["combo_idx"]
            param_cols = [k for k in combos[0].keys()] if combos else []
            best_params_row = valid_metric_rows[valid_metric_rows["combo_idx"] == best_combo_idx].iloc[0]
            best_params = {k: best_params_row[k] for k in param_cols if k in best_params_row}
            edge_config_path = Path("config/edge_config.json")
            if edge_config_path.exists():
                with open(edge_config_path, "r") as f:
                    edge_cfg = json.load(f)
            else:
                edge_cfg = {}
            edge_params = edge_cfg.get("edge_params", {})
            best_params_native = _to_native(best_params)
            edge_params[spec.edge_name] = best_params_native
            edge_cfg["edge_params"] = _to_native(edge_params)
            with open(edge_config_path, "w") as f:
                json.dump(_to_native(edge_cfg), f, indent=2)
            if is_info_enabled("HARNESS") or is_debug_enabled("HARNESS"):
                print(f"[PROMOTE] Promoted best params for edge '{spec.edge_name}' to config/edge_config.json:")
                print(json.dumps(best_params_native, indent=2))
    except Exception as e:
        if is_debug_enabled("HARNESS"):
            print(f"[PROMOTE][WARN] Could not auto-promote best params: {e}")

    try:
        from engines.engine_f_governance.promote import promote_best_params
        valid_df = df[df["error"].isna()] if "error" in df.columns else df
        metric_cols = [
            "total_return_pct", "cagr_pct", "max_drawdown_pct",
            "sharpe", "vol_pct", "win_rate_pct", "trades"
        ]
        valid_metric_rows = valid_df[
            valid_df[metric_cols].replace(0.0, np.nan).notna().any(axis=1)
        ] if not valid_df.empty else valid_df
        all_sharpe_nan = True
        all_cagr_nan = True
        if not valid_metric_rows.empty:
            if "sharpe" in valid_metric_rows.columns and valid_metric_rows["sharpe"].notna().any():
                all_sharpe_nan = False
            if "cagr_pct" in valid_metric_rows.columns and valid_metric_rows["cagr_pct"].notna().any():
                all_cagr_nan = False
        if all_sharpe_nan and all_cagr_nan:
            if is_info_enabled("HARNESS") or is_debug_enabled("HARNESS"):
                print("[PROMOTE][INFO] Skipping promotion: no valid metric values.")
        else:
            promote_best_params(
                edge_name=_to_native(spec.edge_name),
                edge_config_path=_to_native("config/edge_config.json"),
                min_wf=2,
            )
    except Exception as e:
        if is_debug_enabled("HARNESS"):
            print(f"[PROMOTE][WARN] Could not auto-promote best params: {e}")
    return ts_dir


def parse_walk_forward(arg: str) -> List[Tuple[str, str]]:
    """
    Parses walk-forward slices from JSON file, JSON string, or colon-separated format.
    Accepts:
    - A path to a JSON file containing [["start","end"], ...]
    - A JSON string of same format
    - A comma-separated list of "start:end" pairs
    """
    import json, os

    # Case 1: File path
    if os.path.exists(arg):
        with open(arg, "r") as f:
            content = f.read().strip()
        if not content:
            raise ValueError(f"Walk-forward file {arg} is empty")

        try:
            data = json.loads(content)
            if isinstance(data, list):
                # JSON array of arrays
                if all(isinstance(x, (list, tuple)) and len(x) == 2 for x in data):
                    return [(x[0], x[1]) for x in data]
                # JSON array of strings
                elif all(isinstance(x, str) and ":" in x for x in data):
                    return [tuple(x.split(":")) for x in data]
        except json.JSONDecodeError:
            # Plain text fallback
            lines = [l.strip() for l in content.splitlines() if l.strip()]
            return [tuple(l.split(":")) for l in lines]

    # Case 2: Inline JSON
    if arg.startswith("["):
        data = json.loads(arg)
        return [(x[0], x[1]) for x in data]

    # Case 3: Colon-separated string
    chunks = [c.strip() for c in arg.split(",") if c.strip()]
    return [tuple(c.split(":")) for c in chunks]


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
    ap.add_argument("--param-grid", default="config/grids/test_edge.json", help="JSON string or path to JSON for grid")
    ap.add_argument("--walk-forward", default="config/wf/default.json", help="CSV of start:end slices or path to JSON")
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
    if is_info_enabled("HARNESS") or is_debug_enabled("HARNESS"):
        print(f"[HARNESS][INFO] Complete. Results in: {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())