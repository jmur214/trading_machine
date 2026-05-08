"""Run the trend Phase-0 verdict on the wider universe (all 722 tickers
on disk, not just the 115 static mega-caps) to test the prior verdict's
hypothesis: 'trend on mega-caps is beta-amplified; needs a more
dispersion-rich universe to produce upside skew'.

This is a phantom-allocation measurement run — the trend sleeve is
NOT YET wired into PortfolioEngine.allocate. The verdict informs
whether the sleeve concept improves under wider universe.

Usage: python -m scripts.run_trend_wider_universe
"""
from __future__ import annotations

from pathlib import Path

from scripts.sleeve_phase0_verdict import run_trend_verdict


REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data" / "processed"
OUT = REPO / "docs" / "Measurements" / "2026-05"


def main() -> int:
    # Load all tickers with OHLCV CSVs on disk
    tickers = sorted(p.stem.replace("_1d", "") for p in DATA.glob("*_1d.csv"))
    print(f"[wider] {len(tickers)} tickers on disk")

    # Run with a tag so the output doesn't collide with the mega-cap
    # verdict file from yesterday
    out_dir = OUT / "trend_wider_universe"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = run_trend_verdict(out_dir, tickers, start="2021-01-01", end="2025-12-31")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
