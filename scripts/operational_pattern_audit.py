"""scripts/operational_pattern_audit.py
========================================
Periodic audit of the project's *operational* patterns — orthogonal to
the data-pattern audits run by `engine-auditor` and the substrate-bias
audit (F6). The 2026-05-09 evening lessons-learned entry captured the
audit-machinery blind spot: substrate bias was caught; the operational
pattern of "humans hand-tune parameters against biased targets" was
not.

This script runs the operational checks the dev's review flagged. Its
output is a markdown report at
``docs/Measurements/<year-month>/operational_audit_<date>.md`` plus
a one-paragraph summary to stdout.

Usage::

    .venv/bin/python -m scripts.operational_pattern_audit

Run periodically (recommended: weekly during active development,
monthly during steady-state). Findings are advisory — they describe
the operational pattern, not assertions of correctness.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# Parameters known to be load-bearing per the 2026-05-09 lessons_learned
# entry. Future audits should add to this list as new parameters are
# identified as influential.
LOAD_BEARING_PARAMS = [
    "fill_share_cap",
    "PAUSED_MAX_WEIGHT",
    "sustained_score",
    "ADV_FLOOR",
    "risk_per_trade_pct",
    "vol_target",
]


def audit_edge_population() -> Dict[str, Any]:
    """Edge-curation pattern audit.

    Reports on the active set: where do edges come from? How many were
    autonomously discovered vs hand-added?
    """
    import yaml
    edges_yml = ROOT / "data" / "governor" / "edges.yml"
    if not edges_yml.exists():
        return {"error": f"edges.yml missing at {edges_yml}"}
    with open(edges_yml) as f:
        data = yaml.safe_load(f)
    edges = data.get("edges", [])

    by_status = Counter(e.get("status", "unknown") for e in edges)
    by_origin = Counter(e.get("origin", "unknown") for e in edges)

    active_edges = [e for e in edges if e.get("status") == "active"]
    active_with_origin = sum(1 for e in active_edges if e.get("origin"))
    active_with_wfo = sum(
        1 for e in active_edges
        if e.get("validation") or e.get("wfo_result") or e.get("gauntlet_passed")
    )

    # Origin breakdown for active edges specifically
    active_by_origin = Counter(e.get("origin", "unknown") for e in active_edges)
    autonomous_origins = {"discovery", "autonomous", "ga", "bayesian_opt"}
    autonomous_active = sum(
        active_by_origin.get(o, 0) for o in autonomous_origins
    )

    return {
        "total_edges": len(edges),
        "by_status": dict(by_status),
        "by_origin": dict(by_origin),
        "active_count": len(active_edges),
        "active_with_origin_set": active_with_origin,
        "active_with_validation": active_with_wfo,
        "active_by_origin": dict(active_by_origin),
        "autonomous_active_count": autonomous_active,
        "autonomous_active_pct": (
            100.0 * autonomous_active / len(active_edges)
            if active_edges else 0.0
        ),
    }


def audit_oos_lock_status() -> Dict[str, Any]:
    """Is the F8 frozen-code OOS window declared and active?"""
    try:
        from core.oos_lock import load_oos_lock
        lock = load_oos_lock()
        return {
            "active": lock.active,
            "window_start": lock.window_start_iso,
            "frozen_parameters": lock.frozen_parameters,
            "lock_reason": lock.lock_reason,
            "locked_at": lock.locked_at,
        }
    except Exception as e:
        return {"error": str(e)}


def audit_discovery_cycle_activity() -> Dict[str, Any]:
    """When did Engine D last promote a candidate?"""
    history_csv = ROOT / "data" / "governor" / "lifecycle_history.csv"
    findings = {
        "lifecycle_history_exists": history_csv.exists(),
        "most_recent_event": None,
        "promote_events_count": 0,
        "events_last_90_days": 0,
    }
    if not history_csv.exists():
        return findings

    # Lazy imports — pandas only loaded if file exists
    import pandas as pd
    try:
        df = pd.read_csv(history_csv)
    except Exception:
        return findings
    if df.empty:
        return findings

    # Best-effort timestamp parsing — column name varies in older runs
    ts_col = next(
        (c for c in ("timestamp", "ts", "datetime", "event_ts") if c in df.columns),
        None,
    )
    if ts_col is None:
        return findings
    df["__ts"] = pd.to_datetime(df[ts_col], errors="coerce")
    df = df.dropna(subset=["__ts"])
    if df.empty:
        return findings

    findings["most_recent_event"] = df["__ts"].max().isoformat()

    # Event-type column also varies
    type_col = next(
        (c for c in ("event_type", "transition", "action") if c in df.columns),
        None,
    )
    if type_col:
        promote_mask = df[type_col].astype(str).str.contains(
            "promote", case=False, na=False,
        )
        findings["promote_events_count"] = int(promote_mask.sum())

    # Match df["__ts"]'s tz-awareness: if naive, use naive cutoff; else tz-aware
    now_ts = pd.Timestamp.now("UTC")
    df_ts = df["__ts"]
    if df_ts.dt.tz is None:
        now_ts = now_ts.tz_localize(None)
    cutoff = now_ts - pd.Timedelta(days=90)
    findings["events_last_90_days"] = int((df_ts >= cutoff).sum())
    return findings


def audit_metalearner_status() -> Dict[str, Any]:
    """Is the autonomous portfolio meta-learner enabled in production?"""
    config_path = ROOT / "config" / "alpha_settings.prod.json"
    if not config_path.exists():
        return {"error": f"missing {config_path}"}
    try:
        cfg = json.loads(config_path.read_text())
    except Exception as e:
        return {"error": str(e)}
    metalearner = cfg.get("metalearner", {})
    return {
        "enabled": bool(metalearner.get("enabled", False)),
        "profile": metalearner.get("profile_name"),
        "per_ticker": bool(metalearner.get("per_ticker", False)),
    }


def audit_recent_param_sweeps() -> Dict[str, Any]:
    """Scan recent measurement docs for parameter-sweep activity.

    Best-effort: looks for filenames in `docs/Measurements/<year-month>/`
    matching ``*sweep*`` or containing load-bearing parameter names.
    Cannot detect every sweep but flags the obvious ones.
    """
    measurements_dir = ROOT / "docs" / "Measurements"
    if not measurements_dir.exists():
        return {"sweep_docs": [], "scanned_dir": str(measurements_dir)}
    sweep_docs = []
    for md_file in measurements_dir.rglob("*.md"):
        name_lower = md_file.name.lower()
        if "sweep" in name_lower or any(
            p.lower() in name_lower for p in LOAD_BEARING_PARAMS
        ):
            sweep_docs.append(str(md_file.relative_to(ROOT)))
    return {
        "sweep_docs": sorted(sweep_docs)[-20:],   # most recent ~20
        "total_sweep_docs": len(sweep_docs),
    }


def render_markdown_report(findings: Dict[str, Any]) -> str:
    lines = []
    lines.append("# Operational Pattern Audit")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append("")
    lines.append(
        "Captures the dev's 2026-05-09 meta-finding: the audit framework "
        "caught substrate bias (F6) but not operational pattern. This audit "
        "asks _'are decisions being made on autonomous output vs human "
        "curation, and is parameter freezing in effect?'_"
    )
    lines.append("")

    # ---- Edge population ----
    lines.append("## Edge-curation pattern")
    edge = findings.get("edges", {})
    if "error" in edge:
        lines.append(f"- ERROR: {edge['error']}")
    else:
        lines.append(f"- Total edges in registry: **{edge.get('total_edges', 0)}**")
        lines.append(f"- Active edges: **{edge.get('active_count', 0)}**")
        lines.append(
            f"- Active edges from autonomous discovery: "
            f"**{edge.get('autonomous_active_count', 0)} "
            f"({edge.get('autonomous_active_pct', 0.0):.1f}%)**"
        )
        if edge.get("autonomous_active_pct", 0.0) < 10.0:
            lines.append(
                "  - **FLAG: < 10% of active edges came from autonomous discovery.** "
                "The dev's hand-tuning critique applies. Engine D's Discovery cycle "
                "is operating as a watchdog rather than an originator."
            )
        lines.append(
            f"- Active edges with `origin` field set: "
            f"{edge.get('active_with_origin_set', 0)} of {edge.get('active_count', 0)}"
        )
        lines.append("")
        lines.append("### Status breakdown")
        lines.append("")
        lines.append("| Status | Count |")
        lines.append("|---|---:|")
        for status, count in sorted(edge.get("by_status", {}).items(),
                                    key=lambda x: -x[1]):
            lines.append(f"| {status} | {count} |")
        lines.append("")

    # ---- OOS lock ----
    lines.append("## F8 OOS lock status")
    lock = findings.get("oos_lock", {})
    if "error" in lock:
        lines.append(f"- ERROR: {lock['error']}")
    elif lock.get("active"):
        lines.append(f"- **OOS lock ACTIVE** since {lock.get('locked_at')}")
        lines.append(f"- Window starts: {lock.get('window_start')}")
        lines.append(f"- Frozen parameters: {', '.join(lock.get('frozen_parameters', []))}")
        lines.append(f"- Reason: {lock.get('lock_reason')}")
    else:
        lines.append("- **OOS lock INACTIVE.** No parameter freezing in effect.")
        lines.append(
            "  - **FLAG: tuning scripts run unrestricted.** Per F8 + the "
            "2026-05-09 lessons entry, every load-bearing parameter is at "
            "risk of being silently retuned on the OOS window."
        )
    lines.append("")

    # ---- Discovery cycle activity ----
    lines.append("## Engine D autonomous-discovery activity")
    disc = findings.get("discovery", {})
    if "error" in disc:
        lines.append(f"- ERROR: {disc['error']}")
    elif not disc.get("lifecycle_history_exists"):
        lines.append("- No lifecycle_history.csv found — Engine D autonomy not running")
    else:
        lines.append(f"- Most recent lifecycle event: {disc.get('most_recent_event')}")
        lines.append(f"- Total promote events ever: {disc.get('promote_events_count', 0)}")
        lines.append(f"- Lifecycle events last 90 days: {disc.get('events_last_90_days', 0)}")
        if disc.get("promote_events_count", 0) == 0:
            lines.append(
                "  - **FLAG: Discovery cycle has never promoted an edge.** "
                "Confirms the 2026-05-09 finding that the autonomous discovery "
                "machinery exists but doesn't produce. C-engines-4 (Bayesian opt) "
                "is the queued closure."
            )
    lines.append("")

    # ---- MetaLearner ----
    lines.append("## MetaLearner status")
    ml = findings.get("metalearner", {})
    if "error" in ml:
        lines.append(f"- ERROR: {ml['error']}")
    elif ml.get("enabled"):
        lines.append(f"- MetaLearner enabled (profile: {ml.get('profile')}, per_ticker: {ml.get('per_ticker')})")
    else:
        lines.append(
            "- **MetaLearner DISABLED in production.** Memory "
            "`project_metalearner_drift_falsified_2026_05_01` documents the "
            "decision. Autonomous tuning capability remains parked."
        )
    lines.append("")

    # ---- Parameter-sweep activity ----
    lines.append("## Recent parameter-sweep activity (best-effort)")
    sweeps = findings.get("sweeps", {})
    sweep_docs = sweeps.get("sweep_docs", [])
    if sweep_docs:
        lines.append(f"- Found {sweeps.get('total_sweep_docs', 0)} sweep-related docs.")
        lines.append("- Most recent (up to 20):")
        for doc in sweep_docs:
            lines.append(f"  - `{doc}`")
    else:
        lines.append("- No sweep docs found in `docs/Measurements/`.")

    return "\n".join(lines) + "\n"


def render_summary(findings: Dict[str, Any]) -> str:
    """One-paragraph stdout summary."""
    edge = findings.get("edges", {})
    lock = findings.get("oos_lock", {})
    disc = findings.get("discovery", {})
    ml = findings.get("metalearner", {})

    flags = []
    if edge.get("autonomous_active_pct", 0.0) < 10.0:
        flags.append("autonomous-active < 10%")
    if not lock.get("active", False):
        flags.append("OOS lock INACTIVE")
    if disc.get("promote_events_count", 0) == 0:
        flags.append("Discovery has never promoted")
    if not ml.get("enabled", False):
        flags.append("MetaLearner disabled")

    summary_parts = [
        f"Edges: {edge.get('total_edges', 0)} total, {edge.get('active_count', 0)} active "
        f"({edge.get('autonomous_active_count', 0)} autonomous, "
        f"{edge.get('autonomous_active_pct', 0.0):.0f}%)",
        f"OOS lock: {'ACTIVE' if lock.get('active') else 'INACTIVE'}",
        f"Discovery promotes ever: {disc.get('promote_events_count', 0)}",
        f"MetaLearner: {'enabled' if ml.get('enabled') else 'disabled'}",
    ]
    msg = " | ".join(summary_parts)
    if flags:
        msg += f"\nFLAGS ({len(flags)}): " + "; ".join(flags)
    return msg


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Operational-pattern audit (F8 + autonomous-vs-curated patterns)."
    )
    parser.add_argument(
        "--output",
        default=str(
            ROOT / "docs" / "Measurements" / date.today().strftime("%Y-%m") /
            f"operational_audit_{date.today().isoformat()}.md"
        ),
        help="Output markdown path (default: docs/Measurements/<year-month>/operational_audit_<date>.md)",
    )
    parser.add_argument("--no-write", action="store_true", help="Don't write the markdown file; print summary only")
    args = parser.parse_args(argv)

    findings = {
        "edges": audit_edge_population(),
        "oos_lock": audit_oos_lock_status(),
        "discovery": audit_discovery_cycle_activity(),
        "metalearner": audit_metalearner_status(),
        "sweeps": audit_recent_param_sweeps(),
    }

    summary = render_summary(findings)
    print(summary)

    if not args.no_write:
        report = render_markdown_report(findings)
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report)
        print(f"\nFull report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
