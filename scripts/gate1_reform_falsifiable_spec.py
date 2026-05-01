"""Falsifiable-spec driver for the Phase 2.10e Gate 1 reform.

The reform replaces standalone single-edge Gate 1 with an
ensemble-simulation contribution gate. The falsifiable spec from the
director:

    Re-run the new Gate 1 on volume_anomaly_v1 and herding_v1.
    Both must PASS. If either fails, the gate is mis-designed.

This driver runs only the Gate 1 portion of validate_candidate (we
short-circuit by stubbing gates 2-6) so the verification doesn't take
30+ minutes. It produces:

  - per-edge baseline_sharpe / with_candidate_sharpe / contribution
  - both edges' verdict against the configured threshold
  - the standalone Sharpe diagnostic alongside the ensemble result so
    the geometry-mismatch is visible

Run:
    python scripts/gate1_reform_falsifiable_spec.py [--smoke] \
        [--out docs/Audit/gate1_reform_2026_05.md] \
        [--threshold 0.10]

`--smoke` shrinks the universe + window for a fast wiring check.
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from engines.engine_a_alpha.edge_registry import EdgeRegistry  # noqa: E402
from engines.engine_d_discovery.discovery import DiscoveryEngine  # noqa: E402


TARGETS = ["volume_anomaly_v1", "herding_v1"]


def _resolve_class_name(module_path: str) -> str:
    mod = importlib.import_module(module_path)
    for name in dir(mod):
        obj = getattr(mod, name)
        if (
            isinstance(obj, type)
            and obj.__module__ == module_path
            and name.endswith("Edge")
        ):
            return name
    raise RuntimeError(f"Could not resolve edge class from module {module_path}")


def _spec_to_candidate(spec) -> Dict[str, Any]:
    cls_name = _resolve_class_name(spec.module)
    return {
        "edge_id": spec.edge_id,
        "module": spec.module,
        "class": cls_name,
        "category": spec.category,
        "params": spec.params or {},
        "status": spec.status,
        "version": spec.version,
        "origin": "phase_2_10e_falsifiable_spec",
    }


def _load_data_map(
    tickers: List[str],
    start: str,
    end: str,
    processed_dir: Path,
) -> Dict[str, pd.DataFrame]:
    dm: Dict[str, pd.DataFrame] = {}
    missing: List[str] = []
    for t in tickers:
        p = processed_dir / f"{t}_1d.csv"
        if not p.exists():
            missing.append(t)
            continue
        df = pd.read_csv(p, index_col=0, parse_dates=True)
        df = df.loc[(df.index >= start) & (df.index <= end)]
        if len(df) >= 100:
            dm[t] = df
    if missing:
        print(f"[GATE1-REFORM] Missing CSVs for {len(missing)} tickers (skipped): "
              f"{missing[:5]}{'...' if len(missing) > 5 else ''}")
    return dm


def _load_exec_params() -> Dict[str, Any]:
    cfg = json.loads((ROOT / "config" / "backtest_settings.json").read_text())
    return {
        "slippage_bps": cfg.get("slippage_bps", 10.0),
        "slippage_model": cfg.get("slippage_model", "realistic"),
        "commission": cfg.get("commission", 0.0),
        "slippage_extra": cfg.get("slippage_extra"),
    }


def _run_gate1_only(
    discovery: DiscoveryEngine,
    candidate_spec: Dict[str, Any],
    data_map: Dict[str, pd.DataFrame],
    exec_params: Dict[str, Any],
    threshold: float,
) -> Dict[str, Any]:
    """Run ONLY Gate 1 (ensemble-sim) + the standalone diagnostic backtest.

    Bypasses gates 2-6 to keep total run time under ~30 min for the
    falsifiable spec. Returns a result dict matching the keys
    validate_candidate emits for Gate 1.
    """
    from importlib import import_module
    from backtester.backtest_controller import BacktestController
    from engines.engine_a_alpha.alpha_engine import AlphaEngine
    from engines.engine_b_risk.risk_engine import RiskEngine
    from cockpit.logger import CockpitLogger
    from core.metrics_engine import MetricsEngine

    result: Dict[str, Any] = {
        "edge_id": candidate_spec["edge_id"],
        "standalone_sharpe": float("nan"),
        "baseline_sharpe": float("nan"),
        "with_candidate_sharpe": float("nan"),
        "contribution_sharpe": float("nan"),
        "contribution_threshold": threshold,
        "passed": False,
    }

    mod = import_module(candidate_spec["module"])
    cls_ = getattr(mod, candidate_spec["class"])
    edge = cls_()
    edge.set_params(candidate_spec["params"])

    if not data_map:
        return result

    first_ticker = list(data_map.keys())[0]
    start_date = data_map[first_ticker].index[0].isoformat()
    end_date = data_map[first_ticker].index[-1].isoformat()

    # 1. Standalone diagnostic — same wiring as the legacy Gate 1.
    print(f"[GATE1-REFORM] {candidate_spec['edge_id']}: running standalone diagnostic backtest...")
    t0 = time.time()
    sa_alpha = AlphaEngine(edges={candidate_spec["edge_id"]: edge}, debug=False)
    sa_risk = RiskEngine({"risk_per_trade_pct": 0.01})
    sa_logger = CockpitLogger(out_dir="/tmp/gate1_reform_standalone", flush_each_fill=False)
    sa_controller = BacktestController(
        data_map=data_map, alpha_engine=sa_alpha, risk_engine=sa_risk,
        cockpit_logger=sa_logger, exec_params=exec_params,
        initial_capital=100_000, batch_flush_interval=99999,
    )
    sa_history = sa_controller.run(start_date, end_date)
    if sa_history:
        sa_curve = pd.Series(
            [h["equity"] for h in sa_history],
            index=pd.to_datetime([h["timestamp"] for h in sa_history]),
        )
        sa_metrics = MetricsEngine.calculate_all(sa_curve)
        result["standalone_sharpe"] = float(sa_metrics.get("Sharpe", 0.0))
    print(f"[GATE1-REFORM] {candidate_spec['edge_id']} standalone "
          f"Sharpe={result['standalone_sharpe']:.3f} "
          f"({(time.time() - t0)/60:.1f} min)")

    # 2. Ensemble-simulation Gate 1.
    print(f"[GATE1-REFORM] {candidate_spec['edge_id']}: running ensemble-sim Gate 1...")
    t0 = time.time()
    ens_result = discovery._run_gate1_ensemble(
        candidate_spec=candidate_spec, candidate_edge=edge,
        data_map=data_map, start_date=start_date, end_date=end_date,
        exec_params=exec_params, contribution_threshold=threshold,
    )
    print(f"[GATE1-REFORM] {candidate_spec['edge_id']} ensemble-sim "
          f"baseline={ens_result['baseline_sharpe']:.3f} "
          f"with_cand={ens_result['with_candidate_sharpe']:.3f} "
          f"contrib={ens_result['contribution_sharpe']:+.3f} "
          f"({(time.time() - t0)/60:.1f} min)")

    result.update({
        "baseline_ids": list(ens_result["baseline_ids"]),
        "baseline_sharpe": float(ens_result["baseline_sharpe"]),
        "with_candidate_sharpe": float(ens_result["with_candidate_sharpe"]),
        "contribution_sharpe": float(ens_result["contribution_sharpe"]),
        "passed": bool(ens_result["passed"]),
    })
    return result


def _format_table(results: Dict[str, Dict[str, Any]], threshold: float) -> str:
    """Render the falsifiable-spec verification table."""
    lines = [
        "| edge | baseline (3-edge) | with-candidate | **contribution** | "
        f"threshold | verdict | standalone diag |",
        "| --- | ---: | ---: | ---: | ---: | --- | ---: |",
    ]
    for eid, r in results.items():
        if "crash" in r:
            lines.append(
                f"| `{eid}` | — | — | — | {threshold:.2f} | "
                f"**CRASH**: {r['crash']} | — |"
            )
            continue
        verdict = "**PASS**" if r.get("passed", False) else "**FAIL**"
        lines.append(
            f"| `{eid}` | {r.get('baseline_sharpe', float('nan')):.3f} | "
            f"{r.get('with_candidate_sharpe', float('nan')):.3f} | "
            f"**{r.get('contribution_sharpe', float('nan')):+.3f}** | "
            f"{threshold:.2f} | {verdict} | "
            f"{r.get('standalone_sharpe', float('nan')):.3f} |"
        )
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="20-ticker × 6-month window for fast wiring check")
    ap.add_argument("--out", default="docs/Audit/gate1_reform_2026_05_run.md",
                    help="Where to dump the JSON+table summary")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2024-12-31")
    ap.add_argument("--threshold", type=float, default=0.10,
                    help="Contribution-Sharpe threshold (default 0.10 — see "
                         "docs/Audit/gate1_reform_2026_05.md for calibration)")
    args = ap.parse_args()

    if args.smoke:
        args.start = "2024-01-01"
        args.end = "2024-06-30"

    cfg = json.loads((ROOT / "config" / "backtest_settings.json").read_text())
    universe: List[str] = list(cfg.get("tickers", []))
    if args.smoke:
        universe = universe[:20]

    processed_dir = ROOT / "data" / "processed"
    print(f"[GATE1-REFORM] Loading data: {len(universe)} tickers, "
          f"{args.start} → {args.end}")
    data_map = _load_data_map(universe, args.start, args.end, processed_dir)
    print(f"[GATE1-REFORM] data_map ready: {len(data_map)} tickers with ≥100 bars")

    if not data_map:
        print("[GATE1-REFORM] No data — abort.")
        return 1

    exec_params = _load_exec_params()
    print(f"[GATE1-REFORM] exec_params: model={exec_params['slippage_model']}, "
          f"base={exec_params['slippage_bps']}bps")

    registry = EdgeRegistry()
    discovery = DiscoveryEngine()

    # Inform the operator which edges are in the active baseline (so the
    # contribution attribution is reproducible).
    baseline_v_anomaly = sorted(
        s["edge_id"] for s in discovery._load_active_ensemble_specs(
            exclude_id="volume_anomaly_v1",
        )
    )
    baseline_herding = sorted(
        s["edge_id"] for s in discovery._load_active_ensemble_specs(
            exclude_id="herding_v1",
        )
    )
    print(f"[GATE1-REFORM] Baseline for volume_anomaly_v1: {baseline_v_anomaly}")
    print(f"[GATE1-REFORM] Baseline for herding_v1:        {baseline_herding}")

    results: Dict[str, Dict[str, Any]] = {}
    timings: Dict[str, float] = {}

    for edge_id in TARGETS:
        spec = registry.get(edge_id)
        if spec is None:
            print(f"[GATE1-REFORM] {edge_id} not in registry — skipping")
            continue
        candidate_spec = _spec_to_candidate(spec)
        print(f"\n[GATE1-REFORM] === {edge_id} ===")
        print(f"[GATE1-REFORM] module={candidate_spec['module']} "
              f"class={candidate_spec['class']} params={candidate_spec['params']}")
        t0 = time.time()
        try:
            r = _run_gate1_only(
                discovery, candidate_spec, data_map,
                exec_params=exec_params, threshold=args.threshold,
            )
        except Exception as e:
            print(f"[GATE1-REFORM] {edge_id} crashed: {type(e).__name__}: {e}")
            import traceback
            traceback.print_exc()
            r = {"crash": f"{type(e).__name__}: {e}"}
        elapsed = time.time() - t0
        timings[edge_id] = elapsed
        results[edge_id] = r
        print(f"[GATE1-REFORM] {edge_id} total: {elapsed/60:.1f} min")

    # ----- write report -----
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")

    md_parts: List[str] = [
        f"# Gate 1 Reform Falsifiable-Spec Run ({now})",
        "",
        f"- Window: `{args.start} → {args.end}`",
        f"- Universe: {len(data_map)} of {len(universe)} production tickers",
        f"- Slippage model: `{exec_params['slippage_model']}` "
        f"(base {exec_params['slippage_bps']} bps + ADV-bucketed half-spread + "
        f"Almgren-Chriss impact)",
        f"- Contribution threshold: {args.threshold:.2f}",
        f"- Gate-1 reform spec: see `docs/Audit/gate1_reform_2026_05.md`",
        "",
        "## Verification table",
        "",
        _format_table(results, args.threshold),
        "",
        "## Per-edge ensemble baselines",
        "",
        f"- volume_anomaly_v1 baseline = `{baseline_v_anomaly}`",
        f"- herding_v1 baseline       = `{baseline_herding}`",
        "",
        "## Timings",
        "",
    ]
    for eid, sec in timings.items():
        md_parts.append(f"- {eid}: {sec/60:.1f} min")
    md_parts.append("")
    md_parts.append("## Raw result JSON")
    md_parts.append("")
    md_parts.append("```json")
    def _sanitize(o):
        if isinstance(o, dict):
            return {k: _sanitize(v) for k, v in o.items()}
        if isinstance(o, float) and (pd.isna(o) or o != o):
            return None
        return o
    md_parts.append(json.dumps(_sanitize(results), indent=2, default=str))
    md_parts.append("```")
    out_path.write_text("\n".join(md_parts))
    print(f"\n[GATE1-REFORM] Wrote {out_path}")

    print("\n=== HEADLINE ===")
    for eid, r in results.items():
        if "crash" in r:
            print(f"- {eid}: CRASHED: {r['crash']}")
            continue
        verdict = "PASS" if r["passed"] else "FAIL"
        print(f"- {eid}: {verdict}  contribution={r['contribution_sharpe']:+.3f} "
              f"(baseline={r['baseline_sharpe']:.3f}, "
              f"with_cand={r['with_candidate_sharpe']:.3f}; "
              f"standalone diag={r['standalone_sharpe']:.3f})")

    # Exit code reflects falsifiable-spec verdict
    all_pass = all(
        results.get(eid, {}).get("passed", False) for eid in TARGETS
    )
    return 0 if all_pass else 2


if __name__ == "__main__":
    sys.exit(main())
