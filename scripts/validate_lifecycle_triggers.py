"""Phase 2.10d Task A validation driver.

Run the extended autonomous LifecycleManager against the 5-year
integration data (in-sample anchor abf68c8e + 2025 OOS 72ec531d) in
**readonly** mode and check whether the trigger output matches
docs/Measurements/<year-month>/pruning_proposal_2026_04.md's hand classification.

Falsifiable spec:
  - 6 KEEP edges must NOT be paused/retired by any trigger.
  - 14 CUT edges must be paused or retired (any of: Trigger 1
    zero-fill, Trigger 2 sustained-noise, or the legacy
    benchmark-relative gate).
  - 2 REVIEW edges (pead_predrift_v1, growth_sales_v1) can go
    either way; result is documented but not asserted.

Usage:
    python scripts/validate_lifecycle_triggers.py [--out PATH]

Writes a side-by-side comparison table + an event-by-event log.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from engines.engine_f_governance.lifecycle_manager import (  # noqa: E402
    LifecycleConfig,
    LifecycleManager,
)


# Hand classification from docs/Measurements/<year-month>/pruning_proposal_2026_04.md
HAND_CLASSIFICATION: Dict[str, str] = {
    # KEEP (6)
    "volume_anomaly_v1": "KEEP",
    "herding_v1": "KEEP",
    "gap_fill_v1": "KEEP",
    "macro_credit_spread_v1": "KEEP",
    "macro_dollar_regime_v1": "KEEP",
    "pead_v1": "KEEP",
    # REVIEW (2)
    "pead_predrift_v1": "REVIEW",
    "growth_sales_v1": "REVIEW",
    # CUT (14)
    "panic_v1": "CUT",
    "value_trap_v1": "CUT",
    "value_deep_v1": "CUT",
    "pead_short_v1": "CUT",
    "rsi_bounce_v1": "CUT",
    "bollinger_reversion_v1": "CUT",
    "earnings_vol_v1": "CUT",
    "insider_cluster_v1": "CUT",
    "macro_real_rate_v1": "CUT",
    "atr_breakout_v1": "CUT",
    "momentum_edge_v1": "CUT",
    "low_vol_factor_v1": "CUT",
    "macro_yield_curve_v1": "CUT",
    "macro_unemployment_momentum_v1": "CUT",
}


def _load_combined_trades() -> pd.DataFrame:
    frames = []
    for uuid_ in ("abf68c8e-1384-4db4-822c-d65894af70a1",
                  "72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34"):
        p = ROOT / "data" / "trade_logs" / uuid_ / "trades.csv"
        df = pd.read_csv(p, usecols=[
            "timestamp", "edge", "pnl", "trigger",
        ])
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


def _seed_synthetic_registry(tmp_dir: Path) -> Path:
    """Seed a temporary edges.yml with the 22 registered active+paused
    edges in their pre-trigger state, so the validation run sees the
    same starting state the original lifecycle would."""
    src = ROOT / "data" / "governor" / "edges.yml"
    data = yaml.safe_load(src.read_text())
    keep = [
        e for e in data.get("edges", [])
        if e.get("status") in ("active", "paused")
    ]
    out = tmp_dir / "edges.yml"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.dump({"edges": keep}, sort_keys=False))
    return out


def _seed_synthetic_pause_history(history_path: Path) -> None:
    """Seed lifecycle_history.csv so that already-paused edges have a
    plausible pause date >= zero_fill_paused_retire_days in the past.

    We use 2024-04-25 as the historical pause date — that's the
    real lifecycle_history's first-pause date for atr_breakout_v1
    per project_first_autonomous_pause_2026_04_24.md, and it puts
    days_since_pause well above the 365-day retire threshold against
    as_of = 2025-12-31.
    """
    rows = [
        ("2024-04-25T00:00:00+00:00", eid, "active", "paused",
         "loss_fraction_-0.41", "-0.30", "0.85", "-0.41", "150", "200", "")
        for eid in (
            "atr_breakout_v1", "momentum_edge_v1", "low_vol_factor_v1",
            "macro_yield_curve_v1", "macro_unemployment_momentum_v1",
        )
    ]
    history_path.parent.mkdir(parents=True, exist_ok=True)
    with history_path.open("w") as f:
        f.write(
            "timestamp,edge_id,old_status,new_status,triggering_gate,"
            "edge_sharpe,benchmark_sharpe,edge_mdd,trade_count,days_active,notes\n"
        )
        for r in rows:
            f.write(",".join(r) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default="docs/Measurements/2026-04/lifecycle_triggers_validation_2026_04.md")
    ap.add_argument("--scratch-dir", default="/tmp/lifecycle_validation_2026_04")
    args = ap.parse_args()

    scratch = Path(args.scratch_dir)
    scratch.mkdir(parents=True, exist_ok=True)
    registry_path = _seed_synthetic_registry(scratch)
    history_path = scratch / "lifecycle_history.csv"
    _seed_synthetic_pause_history(history_path)

    print(f"[VALIDATE] Scratch dir: {scratch}")
    print(f"[VALIDATE] Loading 5-year trade history...")
    trades = _load_combined_trades()
    print(f"[VALIDATE] Loaded {len(trades):,} rows from 2 trade logs")

    cfg = LifecycleConfig(
        enabled=True,
        # Phase 2.10d trigger calibration
        zero_fill_lookback_days=365,
        zero_fill_min_fills=2,
        zero_fill_paused_retire_days=365,
        noise_window_years=3,
        noise_mean_threshold=0.001,
        noise_negative_year_threshold=-0.0003,
        noise_min_fills_in_window=5,
        noise_min_history_days=365,
        # Allow the validation to fire as many transitions as needed —
        # this is a one-shot diagnostic, not a continuous-run cap context.
        max_zero_fill_pauses_per_cycle=50,
        max_zero_fill_retirements_per_cycle=50,
        max_noise_pauses_per_cycle=50,
        max_pauses_per_cycle=50,
        max_retirements_per_cycle=50,
        # Legacy benchmark-relative gates — leave as designed
        retirement_min_trades=100,
        retirement_min_days=90,
        retirement_margin=0.3,
        readonly=False,  # WRITE to scratch registry, NOT prod
        initial_capital=100_000.0,
    )
    lcm = LifecycleManager(cfg=cfg, registry_path=registry_path,
                           history_path=history_path)

    # Use SPY-2021-2024 as benchmark Sharpe — roughly what the in-sample
    # window observed. Approximate, but within 0.1 of any reasonable
    # benchmark and below most of our edges' bar regardless.
    benchmark_sharpe = 0.875

    print(f"[VALIDATE] Running LifecycleManager.evaluate(...)")
    events = lcm.evaluate(trades, benchmark_sharpe=benchmark_sharpe)
    print(f"[VALIDATE] {len(events)} transitions fired")

    # Read the post-eval registry state
    final_registry = yaml.safe_load(registry_path.read_text())
    final_status: Dict[str, str] = {
        e["edge_id"]: e["status"] for e in final_registry.get("edges", [])
    }

    # ----- Build comparison table -----
    rows = []
    for edge_id, hand in HAND_CLASSIFICATION.items():
        final = final_status.get(edge_id, "<not-in-registry>")
        # Map 'final' to expected category
        if final in ("paused", "retired"):
            auto = "CUT"
        elif final == "active":
            auto = "KEEP"
        else:
            auto = f"<{final}>"

        # Match logic — REVIEW is wildcard
        if hand == "REVIEW":
            match = "n/a (REVIEW)"
        elif hand == auto:
            match = "MATCH"
        else:
            match = "MISMATCH"

        # Find the gate that fired (if any)
        edge_events = [e for e in events if e.edge_id == edge_id]
        gates = [f"{e.old_status}→{e.new_status}({e.triggering_gate})"
                 for e in edge_events]
        gates_str = "; ".join(gates) if gates else "no transition"

        rows.append({
            "edge_id": edge_id,
            "hand_class": hand,
            "final_status": final,
            "auto_class": auto,
            "match": match,
            "gates": gates_str,
        })

    df = pd.DataFrame(rows)
    # Reorder by hand_class for readability
    order = {"KEEP": 0, "REVIEW": 1, "CUT": 2}
    df["_sort"] = df["hand_class"].map(order)
    df = df.sort_values(["_sort", "edge_id"]).drop(columns=["_sort"])

    # ----- Summary stats -----
    keep_total = (df["hand_class"] == "KEEP").sum()
    cut_total = (df["hand_class"] == "CUT").sum()
    review_total = (df["hand_class"] == "REVIEW").sum()
    keep_match = ((df["hand_class"] == "KEEP") & (df["match"] == "MATCH")).sum()
    cut_match = ((df["hand_class"] == "CUT") & (df["match"] == "MATCH")).sum()
    review_pause = ((df["hand_class"] == "REVIEW") & (df["auto_class"] == "CUT")).sum()
    review_keep = ((df["hand_class"] == "REVIEW") & (df["auto_class"] == "KEEP")).sum()

    overall_decisive_match = keep_match + cut_match
    overall_decisive_total = keep_total + cut_total
    match_rate = overall_decisive_match / overall_decisive_total if overall_decisive_total else 0.0

    print()
    print(f"[VALIDATE] KEEP  match: {keep_match}/{keep_total}")
    print(f"[VALIDATE] CUT   match: {cut_match}/{cut_total}")
    print(f"[VALIDATE] REVIEW: {review_pause} paused, {review_keep} kept active")
    print(f"[VALIDATE] Decisive match rate: {match_rate:.1%}")
    print()
    print(df.to_string(index=False))

    # Write summary JSON for the audit doc to include
    summary_json = {
        "as_of": pd.Timestamp.now().isoformat(timespec="seconds"),
        "trade_log_uuids": [
            "abf68c8e-1384-4db4-822c-d65894af70a1",
            "72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34",
        ],
        "n_events_fired": len(events),
        "match_summary": {
            "keep_match": int(keep_match),
            "keep_total": int(keep_total),
            "cut_match": int(cut_match),
            "cut_total": int(cut_total),
            "review_paused": int(review_pause),
            "review_kept_active": int(review_keep),
            "decisive_match_rate": float(match_rate),
        },
        "config": {
            "zero_fill_lookback_days": cfg.zero_fill_lookback_days,
            "zero_fill_min_fills": cfg.zero_fill_min_fills,
            "zero_fill_paused_retire_days": cfg.zero_fill_paused_retire_days,
            "noise_window_years": cfg.noise_window_years,
            "noise_mean_threshold": cfg.noise_mean_threshold,
            "noise_negative_year_threshold": cfg.noise_negative_year_threshold,
            "noise_min_fills_in_window": cfg.noise_min_fills_in_window,
            "noise_min_history_days": cfg.noise_min_history_days,
            "retirement_min_trades": cfg.retirement_min_trades,
            "retirement_margin": cfg.retirement_margin,
        },
        "comparison_table": df.to_dict(orient="records"),
        "events": [
            {
                "edge_id": e.edge_id,
                "old_status": e.old_status,
                "new_status": e.new_status,
                "gate": e.triggering_gate,
                "edge_sharpe": e.edge_sharpe,
                "trade_count": e.trade_count,
            }
            for e in events
        ],
    }

    out_json = scratch / "validation_summary.json"
    out_json.write_text(json.dumps(summary_json, indent=2, default=str))
    print(f"[VALIDATE] Wrote {out_json}")

    out_csv = scratch / "validation_table.csv"
    df.to_csv(out_csv, index=False)
    print(f"[VALIDATE] Wrote {out_csv}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
