# scripts/run_evaluator.py
from __future__ import annotations

"""
CLI to run the EdgeEvaluator and print a ranked table.

Usage:
  python -m scripts.run_evaluator \
    --db-parquet data/research/edge_results.parquet \
    --db-csv data/research/edge_results.csv \
    --out data/research \
    --half-life 180 \
    --recent-days 90 \
    --top 15
"""

import argparse
from pathlib import Path
import pandas as pd

from engines.engine_f_governance.evaluator import EdgeEvaluator, EvaluatorConfig


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Edge Evaluator (rank edges with time-decay).")
    ap.add_argument("--db-parquet", default="data/research/edge_results.parquet")
    ap.add_argument("--db-csv", default="data/research/edge_results.csv")
    ap.add_argument("--out", default="data/research")
    ap.add_argument("--half-life", type=float, default=180.0, help="Half-life in days for time decay.")
    ap.add_argument("--recent-days", type=int, default=90, help="Window for trend diagnostics.")
    ap.add_argument("--rank-norm", action="store_true", default=True, help="Use rank-based normalization.")
    ap.add_argument("--no-rank-norm", dest="rank_norm", action="store_false")
    ap.add_argument("--winsor-pct", type=float, default=0.02, help="Winsor pct if not rank-normalizing.")
    ap.add_argument("--top", type=int, default=15, help="Rows to print.")
    args = ap.parse_args()

    cfg = EvaluatorConfig(
        decay_half_life_days=float(args.half_life),
        recent_days=int(args.recent_days),
        rank_normalize=bool(args.rank_norm),
        winsor_pct=float(args.winsor_pct),
    )

    ev = EdgeEvaluator(
        db_path_parquet=args.db_parquet,
        db_path_csv=args.db_csv,
        out_dir=args.out,
        cfg=cfg,
    )
    paths = ev.run()

    if ev.summary is None or ev.summary.empty:
        print("[EVALUATOR] No data available. Make sure research results exist.")
        return 0

    # Pretty print
    cols = [
        "edge", "rows", "mean_score", "stability_sd",
        "recent_trend_per_day", "mean_sharpe", "mean_cagr_pct",
        "mean_win_rate_pct", "mean_max_dd_pct", "total_trades", "last_completed_on",
    ]
    printable = ev.summary[cols].head(int(args.top)).copy()
    pd.set_option("display.width", 140)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.max_colwidth", 40)
    print("\nTop Edges (time-decayed composite score):\n")
    print(printable.to_string(index=False))

    # Show where outputs landed
    if paths:
        print("\nArtifacts:")
        for k, p in paths.items():
            print(f" - {k}: {p}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())