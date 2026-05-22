"""T-2026-05-12-038-CONT profile: identify the hot path inside
`engines.engine_d_discovery.feature_engineering.FeatureEngineer.
_compute_foundry_features`.

Runs a small substrate (default 10 tickers × 1 year) through the
ACTUAL per-ticker scalar-call loop, with `time.perf_counter`
checkpoints per feature, and writes per-feature CPU breakdown to
`docs/Audit/discovery_seed_from_foundry_profile_2026_05_12.json`.

Does NOT modify any engine code — pure observation.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.feature_foundry import get_feature_registry  # noqa: E402
import core.feature_foundry.features as _foundry_features  # noqa: E402,F401
from engines.engine_d_discovery.feature_engineering import (  # noqa: E402
    _classify_feature_ticker_independence,
    _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE,
    _CACHE_MISS,
)


def _list_processed_tickers(limit: int) -> List[str]:
    proc = REPO / "data" / "processed"
    if not proc.exists():
        return []
    tickers = sorted(p.stem.replace("_1d", "") for p in proc.glob("*_1d.csv"))
    return tickers[:limit]


def _load_ticker_panel(ticker: str, window_years: int) -> pd.DataFrame:
    fp = REPO / "data" / "processed" / f"{ticker}_1d.csv"
    if not fp.exists():
        return pd.DataFrame()
    df = pd.read_csv(fp)
    if df.empty:
        return df
    for col in ("Date", "date", "timestamp"):
        if col in df.columns:
            df = df.set_index(pd.to_datetime(df[col]))
            break
    if not isinstance(df.index, pd.DatetimeIndex):
        return pd.DataFrame()
    cutoff = df.index.max() - pd.Timedelta(days=window_years * 365)
    return df[df.index >= cutoff]


def profile_substrate(n_tickers: int, window_years: int) -> Dict:
    tickers = _list_processed_tickers(n_tickers)
    print(f"[PROFILE] sampling {len(tickers)} tickers, {window_years}yr window")

    reg = get_feature_registry()
    feats = [f for f in reg.list_features() if f.tier in ("A", "B")]
    print(f"[PROFILE] tier-A+B features: {len(feats)}")

    classify_t = time.perf_counter()
    independence: Dict[str, bool] = {}
    for f in feats:
        independence[f.feature_id] = _classify_feature_ticker_independence(f)
    classify_elapsed = time.perf_counter() - classify_t
    print(f"[PROFILE] classification pass took {classify_elapsed:.3f}s")
    n_ind = sum(1 for v in independence.values() if v)
    print(f"[PROFILE] ticker-independent: {n_ind}, ticker-dependent: {len(feats) - n_ind}")

    per_feature_total: Dict[str, float] = {f.feature_id: 0.0 for f in feats}
    per_feature_calls: Dict[str, int] = {f.feature_id: 0 for f in feats}
    per_feature_cache_hits: Dict[str, int] = {f.feature_id: 0 for f in feats}
    per_feature_first_call_us: Dict[str, float] = {}
    per_ticker_total: Dict[str, float] = {}

    overall_start = time.perf_counter()

    for ti, ticker in enumerate(tickers):
        df = _load_ticker_panel(ticker, window_years)
        if df.empty:
            continue
        date_seq = [
            (d.date() if hasattr(d, "date") else d) for d in df.index
        ]
        t_ticker_start = time.perf_counter()
        for f in feats:
            fid = f.feature_id
            func = f.func
            t_ind = independence[fid]
            t_feat_start = time.perf_counter()
            first_call_us = None
            for dt in date_seq:
                if t_ind:
                    cache_key = (fid, dt)
                    cached = _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE.get(
                        cache_key, _CACHE_MISS
                    )
                    if cached is not _CACHE_MISS:
                        per_feature_cache_hits[fid] += 1
                        continue
                t_call = time.perf_counter()
                try:
                    v = func(ticker, dt)
                except Exception:
                    v = None
                elapsed_us = (time.perf_counter() - t_call) * 1e6
                if first_call_us is None:
                    first_call_us = elapsed_us
                per_feature_calls[fid] += 1
                if t_ind:
                    _FOUNDRY_TICKER_INDEPENDENT_VALUE_CACHE[(fid, dt)] = v
            per_feature_total[fid] += time.perf_counter() - t_feat_start
            if fid not in per_feature_first_call_us and first_call_us is not None:
                per_feature_first_call_us[fid] = first_call_us
        per_ticker_total[ticker] = time.perf_counter() - t_ticker_start
        if (ti + 1) % 2 == 0 or ti == len(tickers) - 1:
            elapsed = time.perf_counter() - overall_start
            print(f"[PROFILE] {ti + 1}/{len(tickers)} tickers done; total elapsed {elapsed:.1f}s")

    overall_elapsed = time.perf_counter() - overall_start

    # Build report
    rows = []
    for f in feats:
        fid = f.feature_id
        total = per_feature_total[fid]
        calls = per_feature_calls[fid]
        cache_hits = per_feature_cache_hits[fid]
        per_call_us = (total / calls * 1e6) if calls else 0.0
        rows.append({
            "feature_id": fid,
            "tier": f.tier,
            "ticker_independent": independence[fid],
            "total_sec": round(total, 4),
            "n_calls": calls,
            "n_cache_hits": cache_hits,
            "per_call_us": round(per_call_us, 1),
            "first_call_us": round(per_feature_first_call_us.get(fid, 0.0), 1),
        })
    rows.sort(key=lambda r: r["total_sec"], reverse=True)

    report = {
        "task": "T-2026-05-12-038-CONT",
        "n_tickers": len(tickers),
        "n_tickers_with_data": len(per_ticker_total),
        "window_years": window_years,
        "n_features": len(feats),
        "n_ticker_independent_features": n_ind,
        "classify_pass_sec": round(classify_elapsed, 3),
        "overall_loop_sec": round(overall_elapsed, 2),
        "per_feature": rows,
        "per_ticker_median_sec": float(np.median(list(per_ticker_total.values()))) if per_ticker_total else 0.0,
        "per_ticker_p95_sec": float(np.percentile(list(per_ticker_total.values()), 95)) if per_ticker_total else 0.0,
        "extrapolation_700t_4yr": {
            "scaling_factor_tickers": 700 / max(1, len(per_ticker_total)),
            "scaling_factor_window": 4 / window_years,
            "extrapolated_sec": (
                overall_elapsed
                * (700 / max(1, len(per_ticker_total)))
                * (4 / window_years)
            ),
        },
    }
    return report


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-tickers", type=int, default=10)
    ap.add_argument("--window-years", type=int, default=1)
    ap.add_argument(
        "--out",
        type=str,
        default="docs/Audit/discovery_seed_from_foundry_profile_2026_05_12.json",
    )
    args = ap.parse_args()

    report = profile_substrate(args.n_tickers, args.window_years)
    out_path = REPO / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2))
    print(f"[PROFILE] wrote {out_path}")
    print("\n[PROFILE] Top 10 features by total time:")
    for row in report["per_feature"][:10]:
        print(
            f"  {row['feature_id']:30s} tier={row['tier']} "
            f"total={row['total_sec']:7.2f}s "
            f"calls={row['n_calls']:6d} "
            f"per_call={row['per_call_us']:8.1f}us "
            f"indep={row['ticker_independent']}"
        )
    print(f"\n[PROFILE] Extrapolation to 700-ticker × 4-year cycle: "
          f"{report['extrapolation_700t_4yr']['extrapolated_sec']:.0f} sec "
          f"({report['extrapolation_700t_4yr']['extrapolated_sec'] / 60:.1f} min)")
