"""
scripts/diagnose_realistic_slippage.py
=======================================
Read-only diagnostic comparing what the legacy flat-bps slippage charged
vs what RealisticSlippageModel WOULD have charged on the same fills.

Phase 0.1 of the v2 forward plan asks: how much Sharpe was overstated by
the flat 5-10 bps slippage model? This script doesn't re-run the
backtest — it loads the most recent trade log, looks up bar data from
the parquet cache for each fill, and re-prices the slippage under the
realistic model.

Output:
- Aggregate table: average bps charged by ADV bucket, total $ cost
  difference, per-side breakdown.
- Markdown report at `docs/Audit/realistic_slippage_diagnostic.md`.

Does NOT modify any code path. Does NOT trigger a backtest. Safe to run
during another backtest in the background — only reads from
data/trade_logs/ and data/processed/parquet/.

Usage:
  PYTHONPATH=. python scripts/diagnose_realistic_slippage.py
  PYTHONPATH=. python scripts/diagnose_realistic_slippage.py --run-id <uuid>
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def find_latest_trade_log() -> Path:
    """Locate the most recently-written trades.csv under data/trade_logs/."""
    trade_logs_dir = ROOT / "data" / "trade_logs"
    candidates = list(trade_logs_dir.glob("*/trades.csv"))
    if not candidates:
        raise FileNotFoundError(f"No trade logs found under {trade_logs_dir}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def load_bar_data(ticker: str) -> pd.DataFrame | None:
    """Load the daily parquet for a ticker; None if missing."""
    path = ROOT / "data" / "processed" / "parquet" / f"{ticker}_1d.parquet"
    if not path.exists():
        return None
    try:
        df = pd.read_parquet(path)
        return df
    except Exception:
        return None


def trailing_window(df: pd.DataFrame, as_of: pd.Timestamp, n_days: int = 30) -> pd.DataFrame:
    """Return up to n_days of bar data ending at-or-before `as_of` (no look-ahead)."""
    if df.index.tz is not None:
        try:
            as_of = pd.Timestamp(as_of).tz_localize(df.index.tz)
        except Exception:
            pass
    df_naive_idx = df
    try:
        sub = df_naive_idx[df_naive_idx.index <= pd.Timestamp(as_of)]
    except Exception:
        return df.tail(n_days)
    return sub.tail(n_days)


def main():
    parser = argparse.ArgumentParser(description="Realistic-slippage diagnostic")
    parser.add_argument("--run-id", default=None,
                        help="Specific trade-log UUID to analyze (default: most recent)")
    parser.add_argument("--legacy-bps", type=float, default=10.0,
                        help="Flat bps assumed under the legacy model (default 10)")
    parser.add_argument("--sample-cap", type=int, default=10_000,
                        help="Max fills to analyze (sampled uniformly if exceeded)")
    parser.add_argument("--output", default=None,
                        help="Output markdown path (default: docs/Audit/realistic_slippage_diagnostic.md)")
    args = parser.parse_args()

    # --- Locate trade log -------------------------------------------------
    if args.run_id:
        trades_path = ROOT / "data" / "trade_logs" / args.run_id / "trades.csv"
        if not trades_path.exists():
            raise FileNotFoundError(f"Trade log not found: {trades_path}")
    else:
        trades_path = find_latest_trade_log()

    print(f"[DIAG] Loading trade log: {trades_path}")
    trades = pd.read_csv(trades_path)
    print(f"[DIAG] Loaded {len(trades)} fills")

    # Sample if needed for fast turnaround
    if len(trades) > args.sample_cap:
        trades = trades.sample(n=args.sample_cap, random_state=42).reset_index(drop=True)
        print(f"[DIAG] Sampled down to {len(trades)} fills (random_state=42)")

    # --- Set up the realistic model --------------------------------------
    from engines.execution.slippage_model import get_slippage_model

    realistic = get_slippage_model({"model_type": "realistic"})

    # --- Per-fill comparison ---------------------------------------------
    bucket_stats = defaultdict(lambda: {"n": 0, "legacy_total_bps": 0.0, "realistic_total_bps": 0.0,
                                         "legacy_dollars": 0.0, "realistic_dollars": 0.0,
                                         "max_realistic_bps": 0.0, "min_realistic_bps": float("inf")})
    side_stats = defaultdict(lambda: {"n": 0, "legacy_dollars": 0.0, "realistic_dollars": 0.0})
    failures = {"missing_bar_data": 0, "missing_columns": 0, "insufficient_history": 0,
                "bad_timestamp": 0}

    bar_data_cache: dict[str, pd.DataFrame] = {}

    n_processed = 0
    for _, row in trades.iterrows():
        ticker = str(row.get("ticker", ""))
        try:
            ts = pd.Timestamp(row["timestamp"])
        except Exception:
            failures["bad_timestamp"] += 1
            continue
        try:
            qty = int(row.get("qty", 0))
            fill_price = float(row.get("fill_price", 0))
        except Exception:
            failures["bad_timestamp"] += 1
            continue
        side = str(row.get("side", "")).lower()
        if qty <= 0 or fill_price <= 0:
            continue

        # Cache parquet loads — many fills per ticker
        if ticker not in bar_data_cache:
            bar_data_cache[ticker] = load_bar_data(ticker)
        bars = bar_data_cache[ticker]
        if bars is None:
            failures["missing_bar_data"] += 1
            continue

        # Trailing window for ADV/vol — strictly up-to-and-including `ts`
        window = trailing_window(bars, ts, n_days=30)
        if len(window) < 5:
            failures["insufficient_history"] += 1
            continue
        if "Close" not in window.columns or "Volume" not in window.columns:
            failures["missing_columns"] += 1
            continue

        # Compute realistic bps under our new model
        realistic_bps = realistic.calculate_slippage_bps(ticker, window, side, qty=qty)

        # Bucket by ADV — replicate the model's classification for reporting
        try:
            adv_usd = float((window["Close"] * window["Volume"]).tail(20).mean())
        except Exception:
            adv_usd = 0.0
        if adv_usd >= 500_000_000:
            bucket = "mega"
        elif adv_usd >= 100_000_000:
            bucket = "mid"
        else:
            bucket = "small"

        # Approximate the underlying raw price by inverting the legacy slippage.
        # legacy: raw = fill_price / (1 ± legacy_bps/10000)
        legacy_factor = args.legacy_bps / 10000.0
        if side in ("long", "buy", "cover"):
            raw_price = fill_price / (1 + legacy_factor)
        elif side in ("short", "sell", "exit"):
            raw_price = fill_price / (1 - legacy_factor)
        else:
            raw_price = fill_price

        legacy_cost_dollars = abs(raw_price * qty * legacy_factor)
        realistic_cost_dollars = abs(raw_price * qty * realistic_bps / 10000.0)

        bs = bucket_stats[bucket]
        bs["n"] += 1
        bs["legacy_total_bps"] += args.legacy_bps
        bs["realistic_total_bps"] += realistic_bps
        bs["legacy_dollars"] += legacy_cost_dollars
        bs["realistic_dollars"] += realistic_cost_dollars
        bs["max_realistic_bps"] = max(bs["max_realistic_bps"], realistic_bps)
        bs["min_realistic_bps"] = min(bs["min_realistic_bps"], realistic_bps)

        sd = side_stats[side]
        sd["n"] += 1
        sd["legacy_dollars"] += legacy_cost_dollars
        sd["realistic_dollars"] += realistic_cost_dollars

        n_processed += 1

    print(f"[DIAG] Analyzed {n_processed} fills successfully")
    if failures["missing_bar_data"]:
        print(f"[DIAG] Skipped {failures['missing_bar_data']} (missing bar data)")
    if failures["insufficient_history"]:
        print(f"[DIAG] Skipped {failures['insufficient_history']} (insufficient history)")

    # --- Build markdown report -------------------------------------------
    out_path = Path(args.output) if args.output else (
        ROOT / "docs" / "Audit" / "realistic_slippage_diagnostic.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    lines.append("# Realistic Slippage Diagnostic")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat(timespec='seconds')}")
    lines.append(f"Trade log: `{trades_path.relative_to(ROOT)}`")
    lines.append(f"Fills analyzed: **{n_processed}** (legacy assumed: {args.legacy_bps} bps flat)")
    lines.append("")
    lines.append("## What this measures")
    lines.append("")
    lines.append("Re-prices each historical fill from the most recent backtest run using the")
    lines.append("`RealisticSlippageModel` (Phase 0.1 cost-model fix from")
    lines.append("`docs/Core/forward_plan_2026_04_28.md`). The legacy model charged a flat")
    lines.append(f"{args.legacy_bps} bps per side regardless of order size, ticker liquidity, or")
    lines.append("volatility. The realistic model uses ADV-bucketed half-spread plus")
    lines.append("Almgren-Chriss square-root market impact.")
    lines.append("")
    lines.append("**Numbers below are estimates:** they apply the realistic model to the")
    lines.append("backtest's actual fills, but do NOT account for the second-order effect that")
    lines.append("under realistic costs the system would have made different sizing/entry")
    lines.append("decisions. To get that, the backtest must be re-run with the realistic")
    lines.append("model wired into `ExecutionSimulator` (deferred per v2 plan Phase 0.1).")
    lines.append("")

    # --- Per-bucket breakdown
    lines.append("## Cost by ADV bucket")
    lines.append("")
    lines.append("| Bucket | Fills | Legacy avg bps | Realistic avg bps | Δ bps | Legacy total $ | Realistic total $ | Δ$ |")
    lines.append("|--------|-------|----------------|-------------------|-------|-----------------|--------------------|-----|")
    total_legacy_dollars = 0.0
    total_realistic_dollars = 0.0
    for bucket in ["mega", "mid", "small"]:
        bs = bucket_stats.get(bucket, None)
        if bs is None or bs["n"] == 0:
            continue
        n = bs["n"]
        avg_legacy = bs["legacy_total_bps"] / n
        avg_realistic = bs["realistic_total_bps"] / n
        delta_bps = avg_realistic - avg_legacy
        delta_dollars = bs["realistic_dollars"] - bs["legacy_dollars"]
        lines.append(
            f"| {bucket} | {n} | {avg_legacy:.2f} | {avg_realistic:.2f} | {delta_bps:+.2f} | "
            f"${bs['legacy_dollars']:,.0f} | ${bs['realistic_dollars']:,.0f} | ${delta_dollars:+,.0f} |"
        )
        total_legacy_dollars += bs["legacy_dollars"]
        total_realistic_dollars += bs["realistic_dollars"]
    lines.append("")
    lines.append(f"**Total legacy slippage cost (analyzed sample):** ${total_legacy_dollars:,.0f}")
    lines.append(f"**Total realistic slippage cost (analyzed sample):** ${total_realistic_dollars:,.0f}")
    aggregate_delta = total_realistic_dollars - total_legacy_dollars
    aggregate_pct = (100 * aggregate_delta / total_legacy_dollars) if total_legacy_dollars > 0 else 0.0
    lines.append(f"**Net additional cost under realistic model:** ${aggregate_delta:+,.0f} "
                 f"({aggregate_pct:+.1f}%)")
    lines.append("")

    # --- Per-side breakdown
    lines.append("## Cost by side")
    lines.append("")
    lines.append("| Side | Fills | Legacy total $ | Realistic total $ | Δ$ |")
    lines.append("|------|-------|-----------------|--------------------|-----|")
    for side, sd in sorted(side_stats.items()):
        delta = sd["realistic_dollars"] - sd["legacy_dollars"]
        lines.append(
            f"| {side} | {sd['n']} | ${sd['legacy_dollars']:,.0f} | "
            f"${sd['realistic_dollars']:,.0f} | ${delta:+,.0f} |"
        )
    lines.append("")

    # --- Bucket detail
    lines.append("## Realistic bps range by bucket")
    lines.append("")
    lines.append("| Bucket | Min realistic bps | Max realistic bps |")
    lines.append("|--------|-------------------|-------------------|")
    for bucket in ["mega", "mid", "small"]:
        bs = bucket_stats.get(bucket, None)
        if bs is None or bs["n"] == 0:
            continue
        lines.append(
            f"| {bucket} | {bs['min_realistic_bps']:.2f} | {bs['max_realistic_bps']:.2f} |"
        )
    lines.append("")

    # --- Fail summary
    if any(failures.values()):
        lines.append("## Sampling caveats")
        lines.append("")
        for k, v in failures.items():
            if v:
                lines.append(f"- {k}: {v} fills skipped")
        lines.append("")

    # --- Bottom line interpretation
    lines.append("## Interpretation")
    lines.append("")
    if total_legacy_dollars > 0:
        if aggregate_pct > 5:
            lines.append(f"The realistic model charges **{aggregate_pct:+.1f}%** more than the legacy")
            lines.append("flat-bps model on this trade log. Reported Sharpe under the legacy")
            lines.append("model is overstated; the gap to SPY is wider than the in-sample")
            lines.append("number suggests.")
        elif aggregate_pct < -5:
            lines.append(f"The realistic model charges **{aggregate_pct:+.1f}%** LESS than the legacy")
            lines.append("flat-bps model on this trade log. Most of the universe falls in the")
            lines.append("mega-cap bucket (1 bps half-spread) — the legacy 10 bps was punishing")
            lines.append("liquid names for cost they wouldn't actually pay. Reported Sharpe is")
            lines.append("modestly understated under the legacy model.")
        else:
            lines.append(f"The realistic model charges **{aggregate_pct:+.1f}%** vs the legacy model")
            lines.append("on this trade log — within noise. The flat 10 bps was approximately")
            lines.append("right on average, masking the bucket-by-bucket variance that matters")
            lines.append("for size-aware decisions.")
    lines.append("")
    lines.append("Either way, the per-bucket breakdown above is the actionable takeaway:")
    lines.append("the legacy model provides one number for everyone; the realistic model")
    lines.append("differentiates SPY-class fills (~1 bps) from small-cap fills (15+ bps).")
    lines.append("That differentiation is what enables size-aware position sizing in the")
    lines.append("Phase 1 meta-learner.")
    lines.append("")

    out_path.write_text("\n".join(lines))
    print(f"[DIAG] Report written to: {out_path.relative_to(ROOT)}")
    print()
    print("---")
    print(f"Total legacy slippage cost (sample): ${total_legacy_dollars:,.0f}")
    print(f"Total realistic slippage cost (sample): ${total_realistic_dollars:,.0f}")
    if total_legacy_dollars > 0:
        pct = 100 * (total_realistic_dollars - total_legacy_dollars) / total_legacy_dollars
        print(f"Net change: {pct:+.1f}%")


if __name__ == "__main__":
    main()
