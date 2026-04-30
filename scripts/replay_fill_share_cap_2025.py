"""
scripts/replay_fill_share_cap_2025.py
=====================================
Phase 2.10d Primitive 1 — pre/post 2025-anchor replay.

Reads the Q1 anchor trade log, treats each entry-day's signals as a
single bar's worth of attributions, and reports:
  - pre-cap dominant-edge fill share per day
  - post-cap (proportional scaling at cap=0.25) strength share per day
  - per-edge total budget consumption pre vs post-cap

Pure pandas — no backtest. Output goes to stdout for paste into the
audit doc.

Usage: python -m scripts.replay_fill_share_cap_2025
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

from engines.engine_a_alpha.fill_share_capper import (
    FillShareCapSettings,
    FillShareCapper,
)


Q1_RUN = "72ec531d-7a82-4c2a-97c0-ffb2bf6ddb34"
TRADES_PATH = Path("data/trade_logs") / Q1_RUN / f"trades_{Q1_RUN}.csv"


def main() -> int:
    if not TRADES_PATH.exists():
        print(f"trade log not found: {TRADES_PATH}")
        return 1

    df = pd.read_csv(TRADES_PATH, parse_dates=["timestamp"])
    df = df[df["trigger"] == "entry"].copy()
    df["day"] = df["timestamp"].dt.date

    capper = FillShareCapper(FillShareCapSettings(cap=0.25, min_signals_for_cap=4))

    pre_counts: Counter = Counter()
    post_strength: defaultdict = defaultdict(float)
    binding_days = 0
    total_days = 0
    max_pre_share_overall = 0.0
    max_pre_share_overall_edge = ""
    max_pre_share_overall_day = ""

    for day, day_sigs in df.groupby("day"):
        sigs = []
        for _, row in day_sigs.iterrows():
            sigs.append({
                "ticker": row["ticker"],
                "side": row.get("side", "long"),
                "strength": 1.0,
                "edge_id": row["edge_id"],
                "meta": {},
            })
        if len(sigs) < 4:
            continue
        total_days += 1

        diag = capper.diagnose(sigs)
        if diag["binds"]:
            binding_days += 1
        for edge, share in diag["shares"].items():
            if share > max_pre_share_overall:
                max_pre_share_overall = share
                max_pre_share_overall_edge = edge
                max_pre_share_overall_day = str(day)

        for s in sigs:
            pre_counts[s["edge_id"]] += 1

        out = capper.apply(sigs)
        for s in out:
            post_strength[s["edge_id"]] += float(s["strength"])

    print("=" * 72)
    print("2025 Anchor Replay — Fill-Share Cap (cap=0.25, min_signals=4)")
    print("=" * 72)
    print(f"Trade log:        {TRADES_PATH}")
    print(f"Total entry-days: {total_days}")
    print(f"Cap-binding days: {binding_days} ({binding_days / total_days * 100:.1f}%)")
    print(f"Max single-day single-edge pre-share: "
          f"{max_pre_share_overall:.3f} ({max_pre_share_overall_edge}, "
          f"{max_pre_share_overall_day})")

    print("\nPer-edge pre vs post-cap totals:")
    pre_total = sum(pre_counts.values())
    post_total = sum(post_strength.values())
    print(f"{'edge':<25} {'pre_count':>10} {'pre_share':>10} "
          f"{'post_strength':>14} {'post_share_of_pre':>18}")
    rows = sorted(pre_counts.items(), key=lambda kv: -kv[1])
    for edge, count in rows:
        pre_share = count / pre_total
        post_strength_val = post_strength.get(edge, 0.0)
        post_share_of_pre = post_strength_val / pre_total
        print(f"{edge:<25} {count:>10d} {pre_share:>10.3f} "
              f"{post_strength_val:>14.1f} {post_share_of_pre:>18.3f}")
    print(f"{'TOTAL':<25} {pre_total:>10d} {1.0:>10.3f} "
          f"{post_total:>14.1f} {post_total / pre_total:>18.3f}")

    bottom3 = ["momentum_edge_v1", "low_vol_factor_v1", "atr_breakout_v1"]
    pre_bottom3_share = sum(pre_counts.get(e, 0) for e in bottom3) / pre_total
    post_bottom3_strength = sum(post_strength.get(e, 0.0) for e in bottom3)
    post_bottom3_share = post_bottom3_strength / pre_total
    print(f"\nBottom-3 (capital-rivalry edges) pre-cap share: "
          f"{pre_bottom3_share:.3f} ({pre_bottom3_share * 100:.1f}%)")
    print(f"Bottom-3 post-cap budget consumption (vs pre-total): "
          f"{post_bottom3_share:.3f} ({post_bottom3_share * 100:.1f}%)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
