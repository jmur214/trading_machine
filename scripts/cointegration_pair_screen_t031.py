"""
scripts/cointegration_pair_screen_t031.py
==========================================
T-2026-05-11-031: pairs MA/V cointegration pool expansion.

T-017 surfaced MA/V as the only survivor of 12 candidate pairs.
Today's threshold-calibration audit flagged pairs_trading_MA_V_v1 as
the second-closest miss to t > 2 (α point +18%, t = 1.41 limited by
n=167 trades over 5 years).

This dispatch: screen additional candidate pairs from the literature
(sector ETFs + sub-industry baskets + bond-equity divergence) using
T-017's existing cointegration tooling. Survivors register as new
paused pairs_trading_*_v1 edges, growing the pool's aggregate trade
count toward the n=300+ threshold where the factor decomp's t-stat
on MA/V's α might clear the t > 2 bar.

Reuses `scripts.cointegration_pair_screen.screen_pair` directly.

ETF DATA GAP — surfaced during recon:
Most sector ETFs (XLF, KBE, XLE, XLY, XLP, XLK, SOXX, XLV, IBB, XLI,
XAR) are MISSING from `data/processed/`. Per brief hard constraint
"DO NOT add new external dependencies", this dispatch proceeds with
only the 3 candidates that have data on disk:
  - CSCO / JNPR (networking)
  - AMAT / LRCX (semi equipment)
  - SPY / TLT (bond-equity divergence)
USO is available but XLE isn't, so the energy pair is unbuildable.
ETF data fetch deferred to a separate dispatch.

Output:
  data/research/cointegrated_pairs_t031_2026_05_11.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Tuple

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.cointegration_pair_screen import (  # noqa: E402
    screen_pair, DEFAULT_DATA_DIR,
)

OUTPUT = Path("data/research/cointegrated_pairs_t031_2026_05_11.json")

T031_CANDIDATES: List[Tuple[str, str, str, str]] = [
    ("CSCO", "JNPR", "Networking equipment",
     "Both networking-equipment vendors; similar telco/enterprise demand cycle"),
    ("AMAT", "LRCX", "Semi capital equipment",
     "Both semi-cap-equipment vendors; same fab investment cycle"),
    ("SPY",  "TLT",  "Bond-equity divergence",
     "Classic risk-on/risk-off pair; cointegration is regime-conditional and may fail outside stress windows"),
    # Brief's other candidates (XLF/KBE, XLE/USO, XLY/XLP, XLK/SOXX,
    # XLV/IBB, XLI/XAR) have at least one missing ticker in
    # `data/processed/` and are deferred. See module docstring.
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--is-start", default="2021-01-01")
    parser.add_argument("--is-end", default="2024-12-31")
    parser.add_argument("--coint-p-max", type=float, default=0.05)
    parser.add_argument("--adf-p-max", type=float, default=0.05)
    parser.add_argument("--halflife-min", type=float, default=5.0)
    parser.add_argument("--halflife-max", type=float, default=30.0)
    parser.add_argument("--beta-instability-max-pct", type=float, default=30.0)
    args = parser.parse_args()

    print(f"[T-031] Screening {len(T031_CANDIDATES)} candidate pairs", flush=True)
    print(f"[T-031] In-sample: {args.is_start} → {args.is_end}", flush=True)
    print(f"[T-031] Thresholds: coint_p≤{args.coint_p_max}, "
          f"adf_p≤{args.adf_p_max}, "
          f"halflife∈[{args.halflife_min},{args.halflife_max}] days, "
          f"β instability ≤{args.beta_instability_max_pct}%", flush=True)

    results = []
    for tx, ty, sector, rationale in T031_CANDIDATES:
        print(f"\n[T-031] Screening {tx}/{ty} ({sector})...", flush=True)
        out = screen_pair(
            ticker_x=tx, ticker_y=ty, sector=sector, rationale=rationale,
            data_dir=args.data_dir,
            is_start=args.is_start, is_end=args.is_end,
            coint_p_max=args.coint_p_max, adf_p_max=args.adf_p_max,
            halflife_min=args.halflife_min, halflife_max=args.halflife_max,
            beta_instability_max_pct=args.beta_instability_max_pct,
        )
        print(f"  survives={out['survives']}", flush=True)
        if not out["survives"]:
            print(f"  drop_reasons={out['drop_reasons']}", flush=True)
        else:
            print(f"  β={out['beta']:.4f}, half-life={out['half_life_days']:.1f}d, "
                  f"coint_p={out['coint_p']:.4f}", flush=True)
        results.append(out)

    survivors = [r for r in results if r["survives"]]
    payload = {
        "task_id": "T-2026-05-11-031",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_screened": len(results),
        "n_survivors": len(survivors),
        "in_sample_window": [args.is_start, args.is_end],
        "thresholds": {
            "coint_p_max": args.coint_p_max,
            "adf_p_max": args.adf_p_max,
            "halflife_min": args.halflife_min,
            "halflife_max": args.halflife_max,
            "beta_instability_max_pct": args.beta_instability_max_pct,
        },
        "deferred_pairs_missing_data": [
            "XLF/KBE", "XLE/USO", "XLY/XLP", "XLK/SOXX",
            "XLV/IBB", "XLI/XAR",
        ],
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, default=str))
    print(f"\n[T-031] Wrote {args.output}: {len(survivors)}/{len(results)} survivors", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
