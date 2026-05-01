"""
scripts/analyze_discovery_diagnostic.py
=======================================
Reads the per-candidate jsonl from a discovery diagnostic run and produces
the histogram audit doc summary lines for docs/Audit/discovery_diagnostic_2026_05.md.

Usage:
    python scripts/analyze_discovery_diagnostic.py docs/Audit/discovery_diagnostic_run_2026_05_<ts>.jsonl
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List


def load_records(path: Path) -> List[Dict[str, Any]]:
    out = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                print(f"[ANALYZE] skip malformed line: {e}", file=sys.stderr)
    return out


def fmt_pct(n: int, d: int) -> str:
    if d == 0:
        return "0.0%"
    return f"{100.0 * n / d:.1f}%"


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: analyze_discovery_diagnostic.py <jsonl-path>", file=sys.stderr)
        return 2
    path = Path(sys.argv[1])
    if not path.exists():
        print(f"missing: {path}", file=sys.stderr)
        return 2
    recs = load_records(path)
    n = len(recs)
    if n == 0:
        print("(no records)")
        return 0

    print(f"## Diagnostic source\n\n- jsonl: `{path}`\n- records: {n}\n")

    # Headline
    n_passed = sum(1 for r in recs if r.get("passed_all_gates"))
    kill_counter: Counter[str] = Counter()
    for r in recs:
        ff = r.get("first_failed_gate")
        if ff is None and r.get("passed_all_gates"):
            kill_counter["passed_all"] += 1
        else:
            kill_counter[ff or "unknown"] += 1

    print("## Headline\n")
    print(f"**{n_passed} of {n} candidates passed all gates.**\n")
    parts = []
    for gate in ["gate_1", "gate_2", "gate_3", "gate_4", "gate_5", "gate_6", "timeout", "passed_all", "unknown"]:
        if kill_counter.get(gate, 0) > 0:
            parts.append(f"{kill_counter[gate]} died at {gate}")
    print("Kill attribution: " + ", ".join(parts) + ".\n")

    # Per-gate kill rate table
    print("## Per-gate kill-rate table\n")
    print("| First-failed gate | N candidates | % of run |")
    print("|---|---:|---:|")
    for gate, count in kill_counter.most_common():
        print(f"| {gate} | {count} | {fmt_pct(count, n)} |")
    print()

    # Per-gate pass rate (across all candidates that reached the gate)
    print("## Per-gate pass-rate (among candidates that reached the gate)\n")
    print("| Gate | Reached | Passed | Pass rate |")
    print("|---|---:|---:|---:|")
    gate_keys = ["gate_1", "gate_2", "gate_4", "gate_5", "gate_6"]
    for gate in gate_keys:
        reached = sum(1 for r in recs if r.get("gate_passed") and gate in r.get("gate_passed", {}))
        passed = sum(1 for r in recs if r.get("gate_passed", {}).get(gate, False))
        pct = fmt_pct(passed, reached)
        print(f"| {gate} | {reached} | {passed} | {pct} |")
    print()

    # Standalone Sharpe distribution
    sharpes = [r.get("metrics", {}).get("sharpe", 0.0) for r in recs if r.get("metrics")]
    sharpes_nonzero = [s for s in sharpes if s != 0.0]
    if sharpes:
        s_sorted = sorted(sharpes)
        n_s = len(s_sorted)
        med = s_sorted[n_s // 2]
        p25 = s_sorted[n_s // 4]
        p75 = s_sorted[(3 * n_s) // 4]
        max_s = s_sorted[-1]
        min_s = s_sorted[0]
        positive = sum(1 for s in sharpes if s > 0)
        gt_05 = sum(1 for s in sharpes if s > 0.5)
        gt_1 = sum(1 for s in sharpes if s > 1.0)

        print("## Standalone Gate-1 Sharpe distribution\n")
        print(f"- N with Sharpe recorded: {n_s} (nonzero: {len(sharpes_nonzero)})")
        print(f"- min / p25 / median / p75 / max: {min_s:.3f} / {p25:.3f} / {med:.3f} / {p75:.3f} / {max_s:.3f}")
        print(f"- Sharpe > 0:    {positive} / {n_s} ({fmt_pct(positive, n_s)})")
        print(f"- Sharpe > 0.5:  {gt_05} / {n_s} ({fmt_pct(gt_05, n_s)})")
        print(f"- Sharpe > 1.0:  {gt_1} / {n_s} ({fmt_pct(gt_1, n_s)})")

        # Histogram bins
        bins = [(-99, -0.5), (-0.5, 0.0), (0.0, 0.25), (0.25, 0.5),
                (0.5, 0.75), (0.75, 1.0), (1.0, 99)]
        bin_counts = []
        for lo, hi in bins:
            c = sum(1 for s in sharpes if lo <= s < hi)
            bin_counts.append(c)
        print()
        print("| Sharpe bin | N |")
        print("|---|---:|")
        labels = ["[<-0.5]", "[-0.5, 0)", "[0, 0.25)", "[0.25, 0.5)",
                  "[0.5, 0.75)", "[0.75, 1.0)", "[≥1.0]"]
        for lab, c in zip(labels, bin_counts):
            print(f"| {lab} | {c} |")
        print()

    # Gene-type / class breakdown
    by_class: Counter[str] = Counter()
    by_class_passed: Counter[str] = Counter()
    by_class_g1: Counter[str] = Counter()
    by_class_kill: Dict[str, Counter] = defaultdict(Counter)
    for r in recs:
        cls = r.get("class", "?")
        by_class[cls] += 1
        if r.get("passed_all_gates"):
            by_class_passed[cls] += 1
        if r.get("gate_passed", {}).get("gate_1"):
            by_class_g1[cls] += 1
        ff = r.get("first_failed_gate") or ("passed_all" if r.get("passed_all_gates") else "unknown")
        by_class_kill[cls][ff] += 1

    print("## Candidate class / origin breakdown\n")
    print("| Class | N | Passed Gate 1 | Passed all | Most common kill |")
    print("|---|---:|---:|---:|---|")
    for cls, count in by_class.most_common():
        g1 = by_class_g1.get(cls, 0)
        pa = by_class_passed.get(cls, 0)
        kc = by_class_kill[cls]
        most = kc.most_common(1)[0] if kc else ("?", 0)
        print(f"| `{cls}` | {count} | {g1} | {pa} | {most[0]} ({most[1]}) |")
    print()

    # Gene-type distribution for composite candidates
    gene_counts: Counter[str] = Counter()
    for r in recs:
        for gt in r.get("gene_types") or []:
            gene_counts[gt] += 1
    if gene_counts:
        print("## Gene-type distribution (composite candidates)\n")
        print("| Gene type | Count |")
        print("|---|---:|")
        for gt, c in gene_counts.most_common():
            print(f"| `{gt}` | {c} |")
        print()

    # Wall time
    print("## Wall-time per candidate\n")
    times = [r.get("wall_seconds_total", 0.0) for r in recs]
    if times:
        ts_sorted = sorted(times)
        med_t = ts_sorted[len(ts_sorted) // 2]
        max_t = ts_sorted[-1]
        sum_t = sum(ts_sorted)
        print(f"- median: {med_t:.1f}s")
        print(f"- max:    {max_t:.1f}s")
        print(f"- total:  {sum_t / 60:.1f}min")
    print()

    return 0


if __name__ == "__main__":
    sys.exit(main())
