# engines/engine_f_governance/promote.py
from __future__ import annotations
from pathlib import Path
import json
import pandas as pd
from typing import Dict, Any, Optional
from research.edge_db import EdgeResearchDB
import numpy as np
from debug_config import is_debug_enabled

def is_info_enabled() -> bool:
    from debug_config import DEBUG_LEVELS
    return DEBUG_LEVELS.get("PROMOTE_INFO", False)


def _to_native(val: Any) -> Any:
    """Convert numpy/pandas/scalar types to native Python types for JSON serialization."""
    if val is None:
        return None
    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        if np.isnan(val) or np.isinf(val):
            return None
        return float(val)
    if isinstance(val, (np.bool_, bool)):
        return bool(val)
    if isinstance(val, (pd.Timestamp,)):
        return val.isoformat()
    if isinstance(val, (np.ndarray, list, tuple)):
        return [ _to_native(v) for v in val ]
    if pd.isna(val):
        return None
    return val


def _to_native_dict(obj: Any) -> Any:
    """Recursively convert dict/list values to native types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _to_native_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_to_native_dict(i) for i in obj]
    else:
        return _to_native(obj)


def _debug_best_combo(edge_name: str, combo: dict):
    """Print debug info about what combo was selected."""
    if is_debug_enabled("PROMOTE"):
        print(f"[PROMOTE][DEBUG] Top combo for {edge_name}:")
        for k, v in combo.items():
            print(f"  - {k}: {v}")


def promote_best_params(
    edge_name: str,
    edge_config_path: str = "config/edge_config.json",
    min_wf: int = 2,
) -> Optional[Dict[str, Any]]:
    """
    Promotes the best-performing parameter combo for a given edge
    into the global configuration file (config/edge_config.json).

    Workflow:
    ----------
    1. Loads all recorded research runs from EdgeResearchDB.
    2. Identifies the top-scoring parameter combo for the given edge.
    3. Updates edge_config.json:
        - Ensures edge is listed under "active_edges".
        - Writes best params under "edge_params[edge_name]".
        - Keeps other edges intact.
    4. Returns the promoted payload dict for logging or UI feedback.

    Parameters:
    -----------
    edge_name : str
        The edge module name to promote (e.g., "momentum_trend").
    edge_config_path : str
        Path to your config/edge_config.json file.
    min_wf : int
        Minimum number of walk-forward slices required for eligibility.
    """

    db = EdgeResearchDB()
    if is_debug_enabled("PROMOTE") or is_info_enabled():
        print(f"[PROMOTE][INFO] Loaded EdgeResearchDB with {len(db.df)} records")
    best_combo = db.top_combo_for_edge(edge_name, min_wf=min_wf)
    if not best_combo:
        print(f"[PROMOTE] ❌ No eligible results found for edge '{edge_name}'.")
        return None

    _debug_best_combo(edge_name, best_combo)

    # Load full DB to fetch original parameter values
    df = db.df.copy()
    df = df[df["edge"] == edge_name]
    if df.empty:
        print(f"[PROMOTE] ❌ No records found for edge '{edge_name}' in DB.")
        return None

    combo_id = best_combo.get("combo_idx")
    if combo_id is None:
        print(f"[PROMOTE][WARN] ⚠️ No combo_idx found for best combo of '{edge_name}'.")
        return None

    # Pull the parameter row from DB (first matching combo)
    row = df[df["combo_idx"] == combo_id].head(1)
    if row.empty:
        print(f"[PROMOTE][WARN] ⚠️ Could not locate parameter row for '{edge_name}', combo {combo_id}.")
        return None

    # Extract only parameter-like columns (exclude metrics & metadata)
    ignore_cols = {
        "edge", "combo_idx", "wf_idx", "start", "end", "timestamp",
        "total_return_pct", "cagr_pct", "max_drawdown_pct", "sharpe",
        "win_rate_pct", "trades", "error", "n_wf"
    }

    params: Dict[str, Any] = {}
    for c in row.columns:
        if c not in ignore_cols:
            val = row.iloc[0][c]
            if pd.notna(val):
                params[c] = _to_native(val)

    if not params:
        print(f"[PROMOTE][WARN] No usable parameters found for {edge_name}")
        return None

    if is_debug_enabled("PROMOTE"):
        print(f"[PROMOTE][DEBUG] Selected parameters for {edge_name}: {params}")

    # --- Load and update edge_config.json ---
    cfg_path = Path(edge_config_path)
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text())
    else:
        cfg = {"active_edges": [], "edge_params": {}, "edge_weights": {}}

    # Ensure structure is valid
    cfg.setdefault("active_edges", [])
    cfg.setdefault("edge_params", {})
    cfg.setdefault("edge_weights", {})

    # Ensure edge is active
    if edge_name not in cfg["active_edges"]:
        cfg["active_edges"].append(edge_name)

    # Update the promoted params
    cfg["edge_params"][edge_name] = params

    if is_debug_enabled("PROMOTE") or is_info_enabled():
        print("[PROMOTE][INFO] Writing updated config to disk...")
    # Save back to disk with safe conversion
    safe_cfg = _to_native_dict(cfg)
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        cfg_path.write_text(json.dumps(safe_cfg, indent=2))
        if is_debug_enabled("PROMOTE") or is_info_enabled():
            print(f"[PROMOTE][INFO] Config file updated at {edge_config_path}")
            print("[PROMOTE][INFO] Config file updated at {edge_config_path}")
    except Exception as e:
        print(f"[PROMOTE][ERROR] Failed to write config JSON: {e}")

    if is_debug_enabled("PROMOTE") or is_info_enabled():
        print("[PROMOTE][DONE] Config updated successfully.")
    if is_debug_enabled("PROMOTE") or is_info_enabled():
        print(f"[PROMOTE] ✅ Promoted best params for '{edge_name}' to {edge_config_path}:")
        print(json.dumps(params, indent=2))

    return {"edge": edge_name, "params": params}


# --------------------------------------------------------------------------- #
# Example CLI entrypoint (optional)
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Promote best edge params into config/edge_config.json")
    ap.add_argument("--edge", required=True, help="Edge name to promote (e.g., momentum_trend)")
    ap.add_argument("--config", default="config/edge_config.json", help="Path to edge_config.json")
    ap.add_argument("--min-wf", type=int, default=2, help="Minimum required walk-forward slices")
    args = ap.parse_args()

    promote_best_params(edge_name=args.edge, edge_config_path=args.config, min_wf=args.min_wf)