"""Re-validate the two factor-decomp-identified real alphas
(volume_anomaly_v1, herding_v1) through all 6 discovery gates under
the realistic-cost slippage model.

This is the third leg of Phase 2.10b (forward_plan_2026_04_29.md). The
"two real alphas" claim rests on intercept t-stats from the in-sample
factor-decomposition. If either edge fails the full 6-gate gauntlet
under honest costs, the claim was a cost-model confound, not signal.

Run:
    python scripts/revalidate_alphas.py [--smoke] [--out PATH]

`--smoke` shrinks the universe + window for a fast wiring check.
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from engines.engine_a_alpha.edge_registry import EdgeRegistry  # noqa: E402
from engines.engine_d_discovery.discovery import DiscoveryEngine  # noqa: E402


TARGETS = ["volume_anomaly_v1", "herding_v1"]


def _resolve_class_name(module_path: str) -> str:
    """The EdgeRegistry stores `module` but not `class`. validate_candidate
    expects `candidate_spec["class"]`. Discovery the EdgeBase subclass by
    importing the module and picking the first class whose name ends in
    'Edge' and is defined in that module (not imported from elsewhere)."""
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
    """Convert EdgeSpec → validate_candidate's expected dict."""
    cls_name = _resolve_class_name(spec.module)
    return {
        "edge_id": spec.edge_id,
        "module": spec.module,
        "class": cls_name,
        "category": spec.category,
        "params": spec.params or {},
        "status": spec.status,
        "version": spec.version,
        "origin": "phase_2_10b_revalidation",
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
        print(f"[REVAL] Missing CSVs for {len(missing)} tickers (skipped): "
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


def _format_gate_table(edge_id: str, r: Dict[str, Any]) -> str:
    """Render the 6-gate result as a markdown table."""
    sharpe = r.get("sharpe", 0.0)
    bench_thr = r.get("benchmark_threshold", float("nan"))
    survival = r.get("robustness_survival", 0.0)
    is_sh = r.get("wfo_is_sharpe", float("nan"))
    oos_sh = r.get("wfo_oos_sharpe", float("nan"))
    deg = r.get("wfo_degradation", float("nan"))
    sig_p = r.get("significance_p", 1.0)
    sig_thr = r.get("significance_threshold", 0.05)
    ub_sh = r.get("universe_b_sharpe", float("nan"))
    ub_n = r.get("universe_b_n_tickers", 0)
    fa_alpha = r.get("factor_alpha_annualized", float("nan"))
    fa_t = r.get("factor_alpha_tstat", float("nan"))
    fa_r2 = r.get("factor_r_squared", float("nan"))
    fa_passed = r.get("factor_alpha_passed", False)
    fa_reason = r.get("factor_alpha_reason", "n/a")

    g1 = "PASS" if (sharpe > 0 and (
        pd.isna(bench_thr) or sharpe >= bench_thr
    )) else "FAIL"
    g2 = "PASS" if survival >= 0.7 else "FAIL"
    # Gate 3: OOS Sharpe ≥ 60% of IS (i.e. degradation ≤ 0.4)
    if pd.isna(deg):
        g3 = "SKIP"
    else:
        g3 = "PASS" if deg <= 0.4 else "FAIL"
    g4 = "PASS" if sig_p < sig_thr else "FAIL"
    if pd.isna(ub_sh):
        g5 = "SKIP"
    else:
        g5 = "PASS" if ub_sh > 0 else "FAIL"
    g6 = "PASS" if fa_passed else "FAIL"

    lines = [
        f"### {edge_id}",
        "",
        f"| Gate | Metric | Value | Pass? |",
        f"| --- | --- | --- | --- |",
        f"| 1. Quick backtest (benchmark-relative) | Sharpe (threshold ≈ {bench_thr:.2f}) | {sharpe:.3f} | {g1} |",
        f"| 2. PBO robustness | survival (≥ 0.70) | {survival:.2%} | {g2} |",
        f"| 3. WFO degradation | IS={is_sh:.2f}, OOS={oos_sh:.2f}, deg={deg:.2f} (≤ 0.40) | {deg:.3f} | {g3} |",
        f"| 4. Statistical significance | p (< {sig_thr}) | {sig_p:.4f} | {g4} |",
        f"| 5. Universe-B transfer | Sharpe ({ub_n} tickers, > 0) | {ub_sh:.3f} | {g5} |",
        f"| 6. Factor-decomp alpha | annualized α={fa_alpha:.2%}, t={fa_t:.2f}, R²={fa_r2:.2f} | t > 2 & α > 2% | {g6} |",
        "",
        f"- factor_alpha_reason: `{fa_reason}`",
        f"- passed_all_gates (per validate_candidate): **{r.get('passed_all_gates', False)}**",
        "",
    ]
    return "\n".join(lines)


def _summary_line(edge_id: str, r: Dict[str, Any]) -> str:
    passed = r.get("passed_all_gates", False)
    return f"- **{edge_id}**: {'PASS' if passed else 'FAIL'}  (Sharpe={r.get('sharpe',0):.2f}, "\
           f"PBO={r.get('robustness_survival',0):.0%}, deg={r.get('wfo_degradation',0):.2f}, "\
           f"p={r.get('significance_p',1):.3f}, "\
           f"univ_b={r.get('universe_b_sharpe',float('nan')):.2f}, "\
           f"α_t={r.get('factor_alpha_tstat',float('nan')):.2f})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true",
                    help="Tiny universe + 6-month window for wiring check")
    ap.add_argument("--out", default="docs/Audit/gauntlet_revalidation_2026_04.md")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--end", default="2024-12-31")
    args = ap.parse_args()

    if args.smoke:
        args.start = "2024-01-01"
        args.end = "2024-06-30"

    cfg = json.loads((ROOT / "config" / "backtest_settings.json").read_text())
    universe: List[str] = list(cfg.get("tickers", []))
    if args.smoke:
        universe = universe[:15]

    processed_dir = ROOT / "data" / "processed"
    print(f"[REVAL] Loading data: {len(universe)} tickers, "
          f"{args.start} → {args.end}")
    data_map = _load_data_map(universe, args.start, args.end, processed_dir)
    print(f"[REVAL] data_map ready: {len(data_map)} tickers with ≥100 bars")

    if not data_map:
        print("[REVAL] No data — abort.")
        return 1

    exec_params = _load_exec_params()
    print(f"[REVAL] exec_params (realistic): "
          f"model={exec_params['slippage_model']}, "
          f"base={exec_params['slippage_bps']}bps")

    registry = EdgeRegistry()
    discovery = DiscoveryEngine()

    results: Dict[str, Dict[str, Any]] = {}
    timings: Dict[str, float] = {}
    artifact_dirs: Dict[str, str] = {}

    for edge_id in TARGETS:
        spec = registry.get(edge_id)
        if spec is None:
            print(f"[REVAL] {edge_id} not in registry — skipping")
            continue
        candidate_spec = _spec_to_candidate(spec)
        print(f"\n[REVAL] === {edge_id} ===")
        print(f"[REVAL] module={candidate_spec['module']} "
              f"class={candidate_spec['class']} params={candidate_spec['params']}")
        t0 = time.time()
        try:
            r = discovery.validate_candidate(
                candidate_spec,
                data_map,
                significance_threshold=0.05,
                exec_params=exec_params,
            )
        except Exception as e:
            print(f"[REVAL] {edge_id} validation crashed: {type(e).__name__}: {e}")
            r = {"crash": f"{type(e).__name__}: {e}"}
        elapsed = time.time() - t0
        timings[edge_id] = elapsed
        results[edge_id] = r
        # /tmp/discovery_validation has gate-1 trade logs; dump UUIDs
        try:
            log_dir = Path("/tmp/discovery_validation")
            run_dirs = sorted(log_dir.glob("*"), key=os.path.getmtime, reverse=True)
            if run_dirs:
                artifact_dirs[edge_id] = str(run_dirs[0])
        except Exception:
            pass
        print(f"[REVAL] {edge_id} took {elapsed/60:.1f} min")

    # ----- write report -----
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat(timespec="seconds")
    bench_window = f"{args.start} → {args.end}"

    md_parts: List[str] = []
    md_parts.append(f"# Gauntlet Re-validation — Phase 2.10b Q3 ({now})")
    md_parts.append("")
    md_parts.append(
        "Re-running the full 6-gate `DiscoveryEngine.validate_candidate` "
        "pipeline against the two edges that the in-sample "
        "factor-decomposition flagged as `tier=alpha`: "
        "`volume_anomaly_v1` (intercept t = +4.36, α = +6.1%) and "
        "`herding_v1` (intercept t = +4.49, α = +10.1%). The "
        "factor-decomp ran under the legacy fixed-cost model. The "
        "question this run answers: **do these edges still clear all "
        "six gates under the realistic Almgren-Chriss + ADV-bucketed "
        "spread cost model?**"
    )
    md_parts.append("")
    md_parts.append(f"- Window: `{bench_window}`")
    md_parts.append(f"- Universe: {len(data_map)} of {len(universe)} "
                    f"production tickers (≥100 bars in window)")
    md_parts.append(f"- Slippage model: `{exec_params['slippage_model']}` "
                    f"(base {exec_params['slippage_bps']} bps + "
                    f"impact_coefficient {exec_params['slippage_extra'].get('impact_coefficient')})")
    md_parts.append(f"- Significance threshold: `0.05` (uncorrected — "
                    f"two edges, BH-FDR is a near-no-op at this batch size)")
    md_parts.append("")
    md_parts.append("## Headline")
    md_parts.append("")
    for eid in TARGETS:
        if eid in results:
            md_parts.append(_summary_line(eid, results[eid]))
        else:
            md_parts.append(f"- **{eid}**: NOT RUN (not in registry)")
    md_parts.append("")
    md_parts.append("## Per-edge gate detail")
    md_parts.append("")
    for eid in TARGETS:
        if eid in results:
            md_parts.append(_format_gate_table(eid, results[eid]))

    md_parts.append("## Run artifacts")
    md_parts.append("")
    for eid, d in artifact_dirs.items():
        md_parts.append(f"- {eid} → `{d}` (most recent gate-1 trade log)")
    md_parts.append("")
    md_parts.append("## Timings")
    md_parts.append("")
    for eid, sec in timings.items():
        md_parts.append(f"- {eid}: {sec/60:.1f} min")
    md_parts.append("")
    md_parts.append("## Raw `validate_candidate` output")
    md_parts.append("")
    md_parts.append("```json")
    # sanitize NaNs for JSON
    def _sanitize(o):
        if isinstance(o, dict):
            return {k: _sanitize(v) for k, v in o.items()}
        if isinstance(o, float) and (pd.isna(o) or o != o):
            return None
        return o
    md_parts.append(json.dumps(_sanitize(results), indent=2, default=str))
    md_parts.append("```")
    md_parts.append("")

    out_path.write_text("\n".join(md_parts))
    print(f"\n[REVAL] Wrote {out_path}")

    # Headline pass/fail to stdout for the director
    print("\n=== HEADLINE ===")
    for eid in TARGETS:
        if eid in results:
            print(_summary_line(eid, results[eid]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
