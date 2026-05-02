"""Capture falsifiable-spec results for the gauntlet architectural fix.

Runs `validate_candidate` (v2 production-pipeline-invocation) against
each FALSIFIABLE_CANDIDATES entry on a small representative window and
prints the contribution numbers to stdout. Used by the architectural-fix
audit doc to record the actual verdict.

Usage:
    PYTHONHASHSEED=0 python scripts/run_falsifiable_spec.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pandas as pd

if os.environ.get("PYTHONHASHSEED") != "0":
    os.environ["PYTHONHASHSEED"] = "0"
    os.execv(sys.executable, [sys.executable, *sys.argv])

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engines.engine_d_discovery.discovery import DiscoveryEngine
from engines.engine_a_alpha.edge_registry import EdgeRegistry


CANDIDATES = ["volume_anomaly_v1", "herding_v1"]
WINDOW_START = "2024-01-01"
WINDOW_END = "2024-06-30"
N_TICKERS = 30


def build_candidate_spec(edge_id: str) -> dict | None:
    registry = EdgeRegistry(store_path=str(ROOT / "data" / "governor" / "edges.yml"))
    spec = registry.get(edge_id)
    if spec is None:
        return None
    import importlib
    mod_name = spec.module
    if "." not in mod_name:
        mod_name = f"engines.engine_a_alpha.edges.{mod_name}"
    mod = importlib.import_module(mod_name)
    edge_class = None
    for attr in dir(mod):
        if attr.lower().endswith("edge") and attr not in ("BaseEdge",):
            v = getattr(mod, attr)
            if hasattr(v, "__module__") and v.__module__ == mod.__name__:
                edge_class = v
                break
    if edge_class is None:
        return None
    return {
        "edge_id": edge_id,
        "module": mod_name,
        "class": edge_class.__name__,
        "category": spec.category,
        "params": spec.params or {},
        "status": "candidate",
        "version": spec.version,
        "origin": "falsifiable_spec",
    }


def load_data_map(tickers, start, end):
    out = {}
    for t in tickers:
        p = ROOT / "data" / "processed" / f"{t}_1d.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        df = df.loc[start:end]
        if not df.empty and len(df) >= 50:
            out[t] = df
    return out


def main() -> int:
    cfg_bt = json.loads((ROOT / "config" / "backtest_settings.json").read_text())
    tickers = cfg_bt.get("tickers", [])[:N_TICKERS]
    if "SPY" not in tickers:
        tickers = ["SPY"] + tickers[: N_TICKERS - 1]
    data_map = load_data_map(tickers, WINDOW_START, WINDOW_END)
    if len(data_map) < 5:
        print("[falsifiable] Insufficient data", file=sys.stderr)
        return 2

    print(f"[falsifiable] window={WINDOW_START} → {WINDOW_END}, "
          f"tickers={len(data_map)}")
    disc = DiscoveryEngine(
        registry_path=str(ROOT / "data" / "governor" / "edges.yml"),
        processed_data_dir=str(ROOT / "data" / "processed"),
    )

    results = []
    for cand_id in CANDIDATES:
        spec = build_candidate_spec(cand_id)
        if spec is None:
            print(f"[falsifiable] {cand_id}: spec lookup failed")
            continue
        result = disc.validate_candidate(
            spec, data_map,
            significance_threshold=None,
            start_date=WINDOW_START, end_date=WINDOW_END,
            gate1_contribution_threshold=0.10,
        )
        record = {
            "edge_id": cand_id,
            "baseline_sharpe": result.get("baseline_sharpe"),
            "with_candidate_sharpe": result.get("with_candidate_sharpe"),
            "contribution_sharpe": result.get("contribution_sharpe"),
            "attribution_sharpe": result.get("attribution_sharpe"),
            "robustness_survival": result.get("robustness_survival"),
            "wfo_consistency": result.get("wfo_degradation"),
            "significance_p": result.get("significance_p"),
            "factor_alpha_tstat": result.get("factor_alpha_tstat"),
            "factor_alpha_annualized": result.get("factor_alpha_annualized"),
            "gate_1_passed": result.get("gate_1_passed"),
            "gate_2_passed": result.get("gate_2_passed"),
            "gate_4_passed": result.get("gate_4_passed"),
            "gate_5_passed": result.get("gate_5_passed"),
            "gate_6_passed": result.get("gate_6_passed"),
            "passed_all_gates": result.get("passed_all_gates"),
        }
        results.append(record)
        print(json.dumps(record, indent=2, default=str))

    out_path = ROOT / "docs" / "Audit" / "falsifiable_spec_results.json"
    out_path.write_text(json.dumps(results, indent=2, default=str))
    print(f"[falsifiable] Wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
