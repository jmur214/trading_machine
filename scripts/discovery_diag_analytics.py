"""
scripts/discovery_diag_analytics.py
====================================
Post-process Discovery diagnostic JSONL into a first-failed-gate
histogram + per-gate pass-rate breakdown (T-2026-05-10-021).

Reads a JSONL emitted by scripts/run_discovery_diagnostic.py and
produces both a markdown summary and a structured JSON payload for
inclusion in the T-021 audit doc.

Re-runnable: deterministic on the same input JSONL.

Usage:
  python -m scripts.discovery_diag_analytics --jsonl <path>
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, List, Optional


def load_jsonl(p: Path) -> List[dict]:
    if not p.exists():
        return []
    out: List[dict] = []
    for line in p.open():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def first_failed_histogram(records: List[dict]) -> Dict[str, int]:
    """Count of candidates by first_failed_gate label."""
    c: Counter = Counter()
    for r in records:
        gate = r.get("first_failed_gate") or "PROMOTED"
        c[gate] += 1
    return dict(c)


def per_gate_pass_rate(records: List[dict]) -> Dict[str, Dict[str, int]]:
    """For each gate, count (n_evaluated, n_passed). A gate is
    'evaluated' if any earlier gate didn't already kill the candidate
    before reaching this gate."""
    out: Dict[str, Dict[str, int]] = defaultdict(
        lambda: {"evaluated": 0, "passed": 0}
    )
    gate_order = ["gate_1", "gate_2", "gate_4", "gate_5", "gate_6",
                  "gate_7", "gate_8"]
    for r in records:
        gp = r.get("gate_passed", {})
        first_failed = r.get("first_failed_gate")
        stopped = False
        for gate in gate_order:
            if stopped:
                continue
            passed = bool(gp.get(gate, False))
            out[gate]["evaluated"] += 1
            if passed:
                out[gate]["passed"] += 1
            elif first_failed == gate:
                stopped = True
    return dict(out)


def wall_time_stats(records: List[dict]) -> Dict[str, float]:
    """Per-candidate wall-time distribution."""
    times = [float(r.get("wall_seconds_total", 0.0)) for r in records]
    if not times:
        return {"n": 0}
    return {
        "n": len(times),
        "min_sec": float(min(times)),
        "max_sec": float(max(times)),
        "mean_sec": float(sum(times) / len(times)),
        "total_min": float(sum(times) / 60.0),
    }


def candidate_origin_distribution(records: List[dict]) -> Dict[str, int]:
    """Distribution of candidate archetypes — informs GA vocabulary diagnostic."""
    origins: Counter = Counter()
    for r in records:
        cid = r.get("candidate_id", "?")
        # Strip the GA mutation suffix to get the parent archetype
        parent = cid.rsplit("_mut_", 1)[0] if "_mut_" in cid else cid
        origins[parent] += 1
    return dict(origins)


def gene_type_distribution(records: List[dict]) -> Dict[str, int]:
    """What gene primitives is the GA composing candidates from?
    Spec open Q2: are post-T-006 Foundry features reachable?"""
    types: Counter = Counter()
    for r in records:
        for g in r.get("gene_types", []) or []:
            types[g] += 1
    return dict(types)


def bootstrap_survival_ci(records: List[dict],
                          n_iter: int = 1000,
                          seed: int = 0,
                          alpha: float = 0.05) -> Dict[str, float]:
    """Bootstrap 95% CI on the binary survive-the-gauntlet rate.
    Per CLAUDE.md non-negotiable 6: report ci_low alongside the
    point estimate, even for proportions."""
    import numpy as np
    n = len(records)
    if n == 0:
        return {"n": 0, "point": 0.0, "ci_low": 0.0, "ci_high": 0.0}
    survived = sum(1 for r in records if r.get("first_failed_gate") is None)
    point = survived / n
    rng = np.random.default_rng(seed)
    boots = np.empty(n_iter, dtype=float)
    for i in range(n_iter):
        idx = rng.integers(0, n, size=n)
        b_survived = sum(
            1 for j in idx if records[j].get("first_failed_gate") is None
        )
        boots[i] = b_survived / n
    return {
        "n": n,
        "n_survived": survived,
        "point": float(point),
        "ci_low": float(np.percentile(boots, 100 * alpha / 2)),
        "ci_high": float(np.percentile(boots, 100 * (1 - alpha / 2))),
    }


def summarize(jsonl_path: Path) -> Dict:
    records = load_jsonl(jsonl_path)
    return {
        "jsonl_path": str(jsonl_path),
        "n_records": len(records),
        "first_failed_histogram": first_failed_histogram(records),
        "per_gate_pass_rate": per_gate_pass_rate(records),
        "wall_time_stats": wall_time_stats(records),
        "candidate_origin_distribution": candidate_origin_distribution(records),
        "gene_type_distribution": gene_type_distribution(records),
        "gauntlet_survival_ci": bootstrap_survival_ci(records),
        "per_candidate": [{
            "candidate_id": r.get("candidate_id"),
            "first_failed_gate": r.get("first_failed_gate"),
            "wall_seconds_total": r.get("wall_seconds_total"),
            "sharpe": r.get("metrics", {}).get("sharpe"),
            "sortino": r.get("metrics", {}).get("sortino"),
            "benchmark_threshold": r.get("metrics", {}).get("benchmark_threshold"),
            "factor_alpha_tstat": r.get("metrics", {}).get("factor_alpha_tstat"),
        } for r in records],
    }


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--jsonl", required=True, type=Path)
    p.add_argument("--out-json", type=Path,
                   default=Path("docs/Measurements/2026-05/discovery_substrate_honest_2026_05_10.json"))
    args = p.parse_args()
    summary = summarize(args.jsonl)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    print(f"\n[ANALYTICS] Wrote {args.out_json}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
