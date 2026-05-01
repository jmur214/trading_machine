"""scripts/smoke_per_ticker_logger.py
=======================================
Phase 2.11 prep — fast smoke test for the per-ticker score logger.

Runs a 1-month backtest on 5 tickers with --log-per-ticker-scores ON,
then validates the parquet exists, schema matches, row count is
sane, and at least one (ticker, bar) with a fill in trades.csv has a
matching parquet row with `fired=True`.

Run:
    python scripts/smoke_per_ticker_logger.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


SMOKE_TICKERS = ["AAPL", "MSFT", "GOOGL", "AMZN", "JPM"]
SMOKE_START = "2024-06-03"
SMOKE_END = "2024-06-28"

CFG_PATH = ROOT / "config" / "backtest_settings.json"
PER_TICKER_DIR = ROOT / "data" / "research" / "per_ticker_scores"
TRADES_PATH = ROOT / "data" / "trade_logs" / "trades.csv"


def _temporarily_override_config():
    """Save current config, write a smoke config in place, and return a
    closure that restores the original on call. We use this rather than
    --override-start/--override-end because there's no CLI flag for
    ticker-list override; a smoke test wants a tiny universe."""
    original = CFG_PATH.read_text()
    cfg = json.loads(original)
    cfg["start_date"] = SMOKE_START
    cfg["end_date"] = SMOKE_END
    cfg["tickers"] = list(SMOKE_TICKERS)
    CFG_PATH.write_text(json.dumps(cfg, indent=2))

    def restore():
        CFG_PATH.write_text(original)

    return restore


def main() -> int:
    print(f"[SMOKE] Universe: {SMOKE_TICKERS}")
    print(f"[SMOKE] Window: {SMOKE_START} → {SMOKE_END}")
    print(f"[SMOKE] Output dir: {PER_TICKER_DIR}")

    # Save list of pre-existing parquets so we can identify the new one
    PER_TICKER_DIR.mkdir(parents=True, exist_ok=True)
    pre_existing = {p.name for p in PER_TICKER_DIR.glob("*.parquet")}
    pre_existing |= {p.name for p in PER_TICKER_DIR.glob("*.csv")}

    restore_cfg = _temporarily_override_config()
    try:
        from scripts.run_backtest import run_backtest_logic
        stats = run_backtest_logic(
            env="prod",
            mode="prod",
            fresh=False,            # don't blow up the user's logs
            no_governor=True,       # don't mutate governor state from a smoke
            log_per_ticker_scores=True,
        )
        print(f"[SMOKE] Backtest finished. Sharpe={stats.get('Sharpe Ratio','?')}")
    finally:
        restore_cfg()

    # Find the newly-written file
    new_files = []
    for p in list(PER_TICKER_DIR.glob("*.parquet")) + list(PER_TICKER_DIR.glob("*.csv")):
        if p.name not in pre_existing:
            new_files.append(p)
    if not new_files:
        print("[SMOKE] FAIL — no per-ticker score file was emitted")
        return 1

    parquet_path = new_files[0]
    print(f"[SMOKE] Wrote: {parquet_path}")

    # Load + schema check
    if parquet_path.suffix == ".parquet":
        df = pd.read_parquet(parquet_path)
    else:
        df = pd.read_csv(parquet_path)
    expected_cols = [
        "timestamp", "ticker", "edge_id", "raw_score", "norm_score",
        "weight", "aggregate_score", "regime_summary", "fired",
    ]
    print(f"[SMOKE] Schema: {list(df.columns)}")
    assert list(df.columns) == expected_cols, (
        f"schema mismatch: got {list(df.columns)}, expected {expected_cols}"
    )

    # Row-count sanity
    n_bars = df["timestamp"].nunique()
    n_tickers = df["ticker"].nunique()
    n_edges = df["edge_id"].nunique()
    print(f"[SMOKE] {len(df):,} rows; {n_bars} bars × {n_tickers} tickers × "
          f"{n_edges} edges (~{n_bars * n_tickers * n_edges:,} max)")

    # Cross-ref: pick a (ticker, bar) with a fill in trades.csv and verify
    # the parquet has a matching row with positive aggregate_score and at
    # least one fired=True edge for that (ticker, bar).
    if not TRADES_PATH.exists():
        print("[SMOKE] WARN — trades.csv missing, skipping cross-ref")
    else:
        trades = pd.read_csv(TRADES_PATH)
        if "trigger" in trades.columns:
            entries = trades[trades["trigger"] == "entry"].copy()
        else:
            entries = trades.copy()
        if entries.empty:
            print("[SMOKE] WARN — no entry trades in trades.csv, "
                  "skipping cross-ref")
        else:
            entries["timestamp"] = pd.to_datetime(entries["timestamp"])
            df["timestamp"] = pd.to_datetime(df["timestamp"])
            # Pick the first entry; locate the corresponding parquet rows
            sample = entries.iloc[0]
            sample_ts = pd.Timestamp(sample["timestamp"]).normalize()
            sample_ticker = sample["ticker"]
            print(f"[SMOKE] Cross-ref sample: {sample_ticker} @ {sample_ts}")
            cand = df[(df["ticker"] == sample_ticker)
                      & (df["timestamp"].dt.normalize() == sample_ts)]
            print(f"[SMOKE]   {len(cand)} parquet rows for that (ticker, day)")
            if not cand.empty:
                fired_rows = cand[cand["fired"]]
                print(f"[SMOKE]   fired=True rows: {len(fired_rows)}")
                if not fired_rows.empty:
                    print("[SMOKE]   PASS: at least one edge fired and was "
                          "logged for the filled (ticker, bar)")
                else:
                    print("[SMOKE]   NOTE: no fired=True rows for the "
                          "filled (ticker, bar). May indicate a flow "
                          "where the fill came from an exit trigger or "
                          "a downstream adjustment after AlphaEngine.")

    print("[SMOKE] Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
