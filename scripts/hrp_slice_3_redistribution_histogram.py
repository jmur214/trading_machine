"""Sanity histogram for HRP slice 3's redistribution behaviour.

Runs the slice-3 ``hrp_composed`` composition over synthetic two-cluster
returns at production-realistic ticker counts (N=10, 20, 30) and emits a
binned histogram of the resulting ``optimizer_weight`` values. The point
is to show, on data of the right shape, that:

    1. Mean(optimizer_weight) ≈ 1.0 (redistribution invariant).
    2. Mass exists both above and below 1.0.
    3. There is meaningful tail past 1.0 (i.e. the slice-2 clamp is gone).

Output: a markdown-formatted histogram block plus a JSON payload at
``docs/Audit/hrp_slice_3_histogram.json``. Both are referenced from the
slice-3 audit doc.

This is *not* a backtest — it's a structural sanity check on the
composition layer alone. The A/B/C/D harness
(``scripts/ab_path_a_tax_efficient_core.py``) is what measures Sharpe.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, List

import numpy as np
import pandas as pd

from engines.engine_a_alpha.signal_processor import (
    SignalProcessor,
    RegimeSettings,
    HygieneSettings,
    EnsembleSettings,
    PortfolioOptimizerSettings,
)


ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / "docs" / "Audit" / "hrp_slice_3_histogram.json"


def build_data_map(n_tickers: int, n_bars: int = 120, seed: int = 0) -> Dict[str, pd.DataFrame]:
    """Two-cluster synthetic returns with mild within-cluster noise.

    Half the tickers drift up, half drift down — HRP correlation distance
    finds the cluster structure and assigns weights inversely
    proportional to within-cluster variance. Produces a non-degenerate
    HRP weight distribution at any N >= 4.
    """
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2024-01-01", periods=n_bars, freq="D")
    out: Dict[str, pd.DataFrame] = {}
    for i in range(n_tickers):
        # Cluster: bias half up, half down. Within-cluster noise gives
        # the variance asymmetry HRP exploits.
        cluster_drift = 0.02 if i < n_tickers // 2 else -0.01
        # Asymmetric noise — odd indices have lower vol, get higher HRP weight.
        sigma = 0.25 if i % 2 == 0 else 0.10
        base = 100.0 * (1 + cluster_drift) ** np.arange(n_bars)
        noise = rng.normal(0.0, sigma, n_bars)
        close = base + noise.cumsum()
        close = np.maximum(close, 1.0)
        out[f"T{i}"] = pd.DataFrame(
            {
                "Close": close,
                "Open": close * 0.999,
                "High": close * 1.005,
                "Low": close * 0.995,
                "Volume": 1_000_000.0,
            },
            index=idx,
        )
    return out


def collect_optimizer_weights(n_tickers: int, seed: int = 0) -> List[float]:
    proc = SignalProcessor(
        regime=RegimeSettings(enable_trend=False, enable_vol=False),
        hygiene=HygieneSettings(min_history=10, clamp=1.0),
        ensemble=EnsembleSettings(enable_shrink=False),
        edge_weights={"e1": 1.0},
        portfolio_optimizer_settings=PortfolioOptimizerSettings(
            method="hrp_composed",
            cov_lookback=60,
            min_history=20,
            turnover_enabled=False,
        ),
    )
    data = build_data_map(n_tickers=n_tickers, seed=seed)
    out = proc.process(
        data,
        pd.Timestamp("2024-04-30"),
        {t: {"e1": 0.7} for t in data},
    )
    return [
        float(info["optimizer_weight"])
        for info in out.values()
        if "optimizer_weight" in info
    ]


def histogram(weights: List[float], n_bins: int = 12) -> Dict[str, int]:
    """Bucket optimizer_weights into [0, 0.25), [0.25, 0.5), ... up to
    the max observed value rounded up to a 0.25 boundary. Returns an
    OrderedDict-style dict (Python 3.7+ preserves insertion order).
    """
    if not weights:
        return {}
    max_w = max(weights)
    upper = max(1.5, np.ceil(max_w * 4) / 4)  # round up to next 0.25
    edges = np.arange(0.0, upper + 0.25, 0.25)
    counts = Counter()
    for w in weights:
        idx = min(int(w / 0.25), len(edges) - 2)
        lo = edges[idx]
        hi = edges[idx + 1]
        counts[f"[{lo:.2f}, {hi:.2f})"] += 1
    # Preserve sort by lower edge.
    return dict(sorted(counts.items(), key=lambda kv: float(kv[0].split(",")[0][1:])))


def render_md_block(label: str, weights: List[float]) -> str:
    if not weights:
        return f"### {label}\n_(no firing tickers)_\n"
    arr = np.asarray(weights)
    hist = histogram(weights)
    max_count = max(hist.values()) if hist else 1
    lines = [
        f"### {label}",
        "",
        f"- N firing: **{len(weights)}**",
        f"- Mean: **{arr.mean():.4f}**  (slice-3 invariant: ≈ 1.0)",
        f"- Min: **{arr.min():.4f}**",
        f"- Max: **{arr.max():.4f}**  (slice-2 would cap at 1.0)",
        f"- Stdev: **{arr.std(ddof=0):.4f}**",
        f"- Fraction > 1.0 (amplified): **{(arr > 1.0).mean() * 100:.1f}%**",
        f"- Fraction < 1.0 (attenuated): **{(arr < 1.0).mean() * 100:.1f}%**",
        "",
        "Bucket | Count | Bar",
        "------ | ----- | ---",
    ]
    for bucket, count in hist.items():
        bar = "█" * max(1, int(40 * count / max_count))
        lines.append(f"`{bucket}` | {count} | {bar}")
    return "\n".join(lines) + "\n"


def main() -> int:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    payload: Dict[str, Dict] = {}
    md_blocks: List[str] = ["# HRP Slice 3 — `optimizer_weight` Distribution\n"]
    md_blocks.append(
        "Synthetic two-cluster panels at production-realistic N. The "
        "redistribution invariant is `mean ≈ 1.0`; the slice-3-specific "
        "signature is that mass exists meaningfully above 1.0.\n"
    )

    for n in (10, 20, 30):
        weights = collect_optimizer_weights(n_tickers=n, seed=0)
        arr = np.asarray(weights)
        payload[f"N={n}"] = {
            "n_firing": len(weights),
            "mean": float(arr.mean()) if len(weights) else None,
            "std": float(arr.std(ddof=0)) if len(weights) else None,
            "min": float(arr.min()) if len(weights) else None,
            "max": float(arr.max()) if len(weights) else None,
            "frac_above_one": float((arr > 1.0).mean()) if len(weights) else None,
            "frac_below_one": float((arr < 1.0).mean()) if len(weights) else None,
            "weights": [round(w, 6) for w in weights],
            "histogram_bucket_width": 0.25,
            "histogram": histogram(weights),
        }
        md_blocks.append(render_md_block(f"N = {n}", weights))

    OUT_JSON.write_text(json.dumps(payload, indent=2))
    print("\n\n".join(md_blocks))
    print(f"\n[OUTPUT] Histogram payload: {OUT_JSON}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
