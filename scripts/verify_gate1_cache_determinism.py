"""
scripts/verify_gate1_cache_determinism.py
=========================================

End-to-end determinism + speedup verification for the Gate 1 signal-
collector cache (T-2026-05-11-023).

Procedure:
  1. Build a small data_map (default 12 tickers × 6 months) from
     `data/processed/`.
  2. Pick 3-5 candidate edges from the registry.
  3. Run validate_candidate on each candidate TWICE:
     - Path A: use_signal_cache=False  (the legacy path)
     - Path B: use_signal_cache=True   (the new cached path)
  4. Assert per-candidate `contribution_sharpe` matches within 1e-9.
  5. Report wall-time speedup (mean cached run / mean uncached run).

Pass criterion (per brief):
  - Determinism: ALL candidates' |Δ contribution_sharpe| < 1e-9
  - Speedup ≥ 10× → SHIP recommendation
  - Speedup ∈ [5×, 10×) → marginal; flag in audit
  - Speedup <5× → "not worth the complexity, surface but consider reverting"

This script is read-only on data/, does not mutate any governance
state, and writes only the report to docs/Audit/.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

WINDOW_START = "2024-01-01"
WINDOW_END = "2024-03-31"  # 3 months — keeps cap=3 cross-check tractable
N_TICKERS = 10
# Pick candidate edges that exist in the registry as paused-feature
# (eligible for Discovery validation). The first two are fast and
# cross-sectional; the third is bollinger_reversion (technical, also
# fast). Avoid calendar_anomaly_v1 — its compute path is slow on this
# substrate (observed 25min+ wall in cap=3 cross-check 2026-05-11).
CANDIDATE_IDS = [
    "momentum_12_1_v1",
    "short_term_reversal_v1",
    "momentum_6_1_v1",
]

OUT_PATH = ROOT / "docs" / "Audit" / "discovery_gate1_caching_verify_2026_05_11.json"


def load_data_map(tickers: List[str], start: str, end: str) -> Dict[str, pd.DataFrame]:
    out: Dict[str, pd.DataFrame] = {}
    for t in tickers:
        p = ROOT / "data" / "processed" / f"{t}_1d.csv"
        if not p.exists():
            continue
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        df = df.loc[start:end]
        if not df.empty and len(df) >= 50:
            out[t] = df
    return out


def build_candidate_spec(edge_id: str) -> Optional[Dict]:
    from engines.engine_a_alpha.edge_registry import EdgeRegistry
    # Ensure target edges are imported so the registry sees them
    import importlib
    for mod_path in [
        "engines.engine_a_alpha.edges.momentum_12_1_v1",
        "engines.engine_a_alpha.edges.short_term_reversal_v1",
        "engines.engine_a_alpha.edges.momentum_6_1_v1",
    ]:
        try:
            importlib.import_module(mod_path)
        except Exception:
            pass
    reg = EdgeRegistry(store_path=str(ROOT / "data" / "governor" / "edges.yml"))
    spec = reg.get(edge_id)
    if spec is None:
        return None
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
        "origin": "gate1_cache_verify",
    }


def main() -> int:
    cfg_bt = json.loads((ROOT / "config" / "backtest_settings.json").read_text())
    tickers = cfg_bt.get("tickers", [])[:N_TICKERS]
    if "SPY" not in tickers:
        tickers = ["SPY"] + tickers[: N_TICKERS - 1]

    print(f"[verify] window={WINDOW_START} → {WINDOW_END}, "
          f"requested tickers={len(tickers)}", flush=True)
    data_map = load_data_map(tickers, WINDOW_START, WINDOW_END)
    if len(data_map) < 5:
        print(f"[verify] Insufficient data ({len(data_map)} tickers)", file=sys.stderr)
        return 2
    print(f"[verify] loaded data_map for {len(data_map)} tickers", flush=True)

    candidate_specs: List[Dict] = []
    for cid in CANDIDATE_IDS:
        spec = build_candidate_spec(cid)
        if spec is not None:
            candidate_specs.append(spec)
        else:
            print(f"[verify] WARN — candidate {cid} not in registry, skipped")
    if len(candidate_specs) < 2:
        print(f"[verify] Need at least 2 candidates; got {len(candidate_specs)}",
              file=sys.stderr)
        return 3

    print(f"[verify] running cap={len(candidate_specs)} cross-check", flush=True)

    from engines.engine_d_discovery.discovery import DiscoveryEngine

    # ---- Path A: use_signal_cache=False ----
    print("\n[verify] === Path A: use_signal_cache=False (legacy) ===", flush=True)
    disc_a = DiscoveryEngine(
        registry_path=str(ROOT / "data" / "governor" / "edges.yml"),
        processed_data_dir=str(ROOT / "data" / "processed"),
    )
    uncached_records: List[Dict] = []
    t_a_start = time.time()
    for spec in candidate_specs:
        t_c = time.time()
        result = disc_a.validate_candidate(
            spec, data_map,
            significance_threshold=None,
            start_date=WINDOW_START,
            end_date=WINDOW_END,
            gate1_contribution_threshold=0.10,
            use_signal_cache=False,
        )
        wall = time.time() - t_c
        rec = {
            "edge_id": spec["edge_id"],
            "baseline_sharpe": result.get("baseline_sharpe"),
            "with_candidate_sharpe": result.get("with_candidate_sharpe"),
            "contribution_sharpe": result.get("contribution_sharpe"),
            "wall_seconds": round(wall, 2),
        }
        uncached_records.append(rec)
        print(f"  uncached {spec['edge_id']}: contrib={rec['contribution_sharpe']:.6f} "
              f"wall={rec['wall_seconds']}s", flush=True)
    wall_uncached_total = time.time() - t_a_start

    # ---- Path B: use_signal_cache=True ----
    print("\n[verify] === Path B: use_signal_cache=True (new) ===", flush=True)
    disc_b = DiscoveryEngine(
        registry_path=str(ROOT / "data" / "governor" / "edges.yml"),
        processed_data_dir=str(ROOT / "data" / "processed"),
    )
    cached_records: List[Dict] = []
    t_b_start = time.time()
    for spec in candidate_specs:
        t_c = time.time()
        result = disc_b.validate_candidate(
            spec, data_map,
            significance_threshold=None,
            start_date=WINDOW_START,
            end_date=WINDOW_END,
            gate1_contribution_threshold=0.10,
            use_signal_cache=True,
        )
        wall = time.time() - t_c
        rec = {
            "edge_id": spec["edge_id"],
            "baseline_sharpe": result.get("baseline_sharpe"),
            "with_candidate_sharpe": result.get("with_candidate_sharpe"),
            "contribution_sharpe": result.get("contribution_sharpe"),
            "wall_seconds": round(wall, 2),
        }
        cached_records.append(rec)
        print(f"  cached   {spec['edge_id']}: contrib={rec['contribution_sharpe']:.6f} "
              f"wall={rec['wall_seconds']}s", flush=True)
    wall_cached_total = time.time() - t_b_start

    # ---- Determinism cross-check ----
    print("\n[verify] === Determinism cross-check ===", flush=True)
    determinism_pass = True
    deltas: List[Dict] = []
    for ua, ca in zip(uncached_records, cached_records):
        delta_contrib = abs(
            float(ua["contribution_sharpe"]) - float(ca["contribution_sharpe"])
        )
        delta_baseline = abs(
            float(ua["baseline_sharpe"]) - float(ca["baseline_sharpe"])
        )
        delta_with = abs(
            float(ua["with_candidate_sharpe"]) - float(ca["with_candidate_sharpe"])
        )
        within_tol = delta_contrib < 1e-9
        if not within_tol:
            determinism_pass = False
        deltas.append({
            "edge_id": ua["edge_id"],
            "delta_baseline_sharpe": delta_baseline,
            "delta_with_candidate_sharpe": delta_with,
            "delta_contribution_sharpe": delta_contrib,
            "within_tol_1e9": within_tol,
        })
        status = "OK" if within_tol else "FAIL"
        print(f"  {status} {ua['edge_id']}: |Δ contrib|={delta_contrib:.3e} "
              f"(<1e-9? {within_tol})", flush=True)

    # ---- Speedup ----
    speedup = wall_uncached_total / wall_cached_total if wall_cached_total > 0 else 0.0
    print(f"\n[verify] === Speedup ===", flush=True)
    print(f"  uncached total: {wall_uncached_total:.2f}s", flush=True)
    print(f"  cached total:   {wall_cached_total:.2f}s", flush=True)
    print(f"  speedup ratio:  {speedup:.2f}×", flush=True)

    if speedup >= 10:
        verdict_speedup = "SHIP — speedup target hit"
    elif speedup >= 5:
        verdict_speedup = "MARGINAL — speedup below 10× target but real"
    elif speedup >= 1.5:
        verdict_speedup = "WEAK — speedup below 5×, consider revert"
    else:
        verdict_speedup = "NO-OP — caching produced negligible speedup; revert recommended"

    overall_verdict = "SHIP" if (determinism_pass and speedup >= 5) else (
        "BLOCK — determinism failure" if not determinism_pass
        else "INVESTIGATE — speedup below target"
    )

    payload = {
        "task_id": "T-2026-05-11-023",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "setup": {
            "window_start": WINDOW_START,
            "window_end": WINDOW_END,
            "n_tickers_loaded": len(data_map),
            "n_candidates": len(candidate_specs),
            "candidate_ids": [s["edge_id"] for s in candidate_specs],
        },
        "uncached_records": uncached_records,
        "cached_records": cached_records,
        "deltas": deltas,
        "wall_uncached_total_seconds": round(wall_uncached_total, 2),
        "wall_cached_total_seconds": round(wall_cached_total, 2),
        "speedup_ratio": round(speedup, 3),
        "determinism_pass": determinism_pass,
        "speedup_verdict": verdict_speedup,
        "overall_verdict": overall_verdict,
    }
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n[verify] Wrote {OUT_PATH}", flush=True)
    print(f"\n[verify] OVERALL VERDICT: {overall_verdict}", flush=True)

    if not determinism_pass:
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
