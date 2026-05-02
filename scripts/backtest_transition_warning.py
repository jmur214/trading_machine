"""
scripts/backtest_transition_warning.py
======================================
Validate the TransitionWarningDetector against historical regime changes.

Acceptance criterion (from `05-1-26_1-percent.md` Workstream C):
  Detector should fire ≥48 hours ahead of regime changes in ≥80% of
  historical cases.

Anchor events (curated from prior session memory + reviewer doc):
  1. March 2020 — COVID crash. Regime flip benign → crisis around 2020-02-24
  2. October 2022 — rate selloff. Argmax flip benign → stressed/crisis
     in late September → mid October.
  3. April 2025 — market_turmoil. Argmax flip benign → crisis around 2025-04-02.

Procedure:
  1. Build extended daily feature panel (2018 → 2025).
     - SPY/TLT cached CSV begins 2020-04. Extension via yfinance fetched
       into RAM (no CSV mutation), prepended to the cached series.
  2. Run the daily HMM through the extended panel → posterior sequence.
  3. Identify "true" regime transitions: argmax state change that persists
     for >= 5 consecutive days (filters out single-bar HMM noise).
  4. Stream posteriors through TransitionWarningDetector, record warning
     events.
  5. For each anchor event, find lead time = (event_date - first_warning_in_window).
     Pass = lead_time >= 2 trading days.

Outputs:
  data/research/transition_warning_backtest_2026_05.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
log = logging.getLogger("BacktestTransitionWarning")


# Anchor events: (event_label, expected_flip_date, expected_to_state)
# We allow the detector to fire any time in [expected_flip_date - 30 calendar days,
# expected_flip_date], and report the lead time.
ANCHOR_EVENTS = [
    ("march_2020_covid",   "2020-02-24", "crisis"),
    ("october_2022_rates", "2022-09-26", "crisis"),  # peak of the selloff
    ("april_2025_turmoil", "2025-04-02", "crisis"),
]

DEFAULT_LOOKBACK_DAYS = 30
PERSISTENCE_BARS = 5  # how many consecutive bars of new argmax to count as a real transition
ACCEPTANCE_LEAD_TRADING_DAYS = 2  # ≥48 trading hours ≈ 2 trading days


def _fetch_extended_price(ticker: str, start: str, end: str) -> Optional[pd.Series]:
    """Pull historical Close prices from yfinance into RAM. Returns None on failure."""
    try:
        import yfinance as yf
    except ImportError:
        log.warning("yfinance unavailable; cannot extend %s history", ticker)
        return None
    try:
        df = yf.download(ticker, start=start, end=end, progress=False, auto_adjust=False)
    except Exception as exc:
        log.warning("yfinance fetch failed for %s: %s", ticker, exc)
        return None
    if df is None or df.empty:
        return None
    # yfinance may return MultiIndex columns
    if isinstance(df.columns, pd.MultiIndex):
        try:
            close = df[("Close", ticker)]
        except KeyError:
            close = df["Close"]
            if isinstance(close, pd.DataFrame):
                close = close.iloc[:, 0]
    else:
        close = df["Close"]
    close = close.dropna().astype(float)
    close.index = pd.to_datetime(close.index).tz_localize(None) if hasattr(close.index, "tz_localize") else pd.to_datetime(close.index)
    try:
        close.index = close.index.tz_localize(None)
    except (TypeError, AttributeError):
        pass
    return close.sort_index()


def _load_cached_price(ticker: str) -> Optional[pd.Series]:
    """Load the cached daily close series for a ticker."""
    p = ROOT / "data" / "processed" / f"{ticker}_1d.csv"
    if not p.exists():
        return None
    df = pd.read_csv(p, index_col=0, parse_dates=True)
    if "Close" not in df.columns:
        return None
    s = df["Close"].dropna().astype(float)
    try:
        s.index = pd.to_datetime(s.index).tz_localize(None)
    except (TypeError, AttributeError):
        pass
    return s.sort_index()


def build_extended_panel(start: str, end: str) -> pd.DataFrame:
    """Build an extended daily feature panel covering `start` → `end`.

    Strategy:
      - SPY/TLT: take cached CSV, extend backward via yfinance if required.
      - FRED series (VIX, T10Y2Y, BAA-AAA, DTWEXBGS): use existing
        macro_features helpers (FRED cache covers 2000+).
    """
    from engines.engine_e_regime.macro_features import (
        FEATURE_COLUMNS, _safe_load_fred,
    )

    # 1. SPY: cached + yfinance extension
    spy_cached = _load_cached_price("SPY")
    cached_start = spy_cached.index.min() if spy_cached is not None else pd.Timestamp("2099-01-01")
    if pd.Timestamp(start) < cached_start:
        # Need to extend backward
        ext_end = (cached_start - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        log.info(f"Extending SPY history: yfinance {start} → {ext_end}")
        spy_ext = _fetch_extended_price("SPY", start, ext_end)
        if spy_ext is not None:
            spy = pd.concat([spy_ext, spy_cached]).sort_index()
            spy = spy[~spy.index.duplicated(keep="last")]
        else:
            spy = spy_cached
    else:
        spy = spy_cached

    # 2. TLT: cached + yfinance extension
    tlt_cached = _load_cached_price("TLT")
    if tlt_cached is not None and pd.Timestamp(start) < tlt_cached.index.min():
        ext_end = (tlt_cached.index.min() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
        log.info(f"Extending TLT history: yfinance {start} → {ext_end}")
        tlt_ext = _fetch_extended_price("TLT", start, ext_end)
        if tlt_ext is not None:
            tlt = pd.concat([tlt_ext, tlt_cached]).sort_index()
            tlt = tlt[~tlt.index.duplicated(keep="last")]
        else:
            tlt = tlt_cached
    else:
        tlt = tlt_cached

    if spy is None or spy.empty:
        raise RuntimeError("Cannot build extended panel — SPY series empty")

    # 3. FRED — use the existing loader (handles cache)
    vix = _safe_load_fred("VIXCLS")
    t10y2y = _safe_load_fred("T10Y2Y")
    baa = _safe_load_fred("BAA10Y")
    aaa = _safe_load_fred("AAA10Y")
    dollar = _safe_load_fred("DTWEXBGS")

    # 4. Build daily index from SPY
    daily_idx = spy.loc[start:end].index
    out = pd.DataFrame(index=daily_idx)
    spy_log = np.log(spy).diff()
    out["spy_log_return"] = spy_log.reindex(daily_idx)
    out["spy_ret_5d"] = spy_log.rolling(5).sum().reindex(daily_idx)
    out["spy_vol_20d"] = spy_log.rolling(20).std(ddof=0).reindex(daily_idx)

    if tlt is not None and not tlt.empty:
        tlt_log = np.log(tlt).diff()
        out["tlt_ret_20d"] = tlt_log.rolling(20).sum().reindex(daily_idx)
    else:
        out["tlt_ret_20d"] = np.nan

    out["vix_level"] = (
        vix.reindex(daily_idx, method="ffill") if vix is not None else np.nan
    )
    out["yield_curve_spread"] = (
        t10y2y.reindex(daily_idx, method="ffill") if t10y2y is not None else np.nan
    )
    if baa is not None and aaa is not None and not baa.empty and not aaa.empty:
        joined = pd.concat([baa.rename("baa"), aaa.rename("aaa")], axis=1, join="inner")
        joined = joined.dropna()
        spread = (joined["baa"] - joined["aaa"]).sort_index()
        out["credit_spread_baa_aaa"] = spread.reindex(daily_idx, method="ffill")
    else:
        out["credit_spread_baa_aaa"] = np.nan
    if dollar is not None and not dollar.empty:
        dollar_aligned = dollar.reindex(daily_idx, method="ffill")
        out["dollar_ret_63d"] = np.log(dollar_aligned).diff(63)
    else:
        out["dollar_ret_63d"] = np.nan

    return out[list(FEATURE_COLUMNS)]


def detect_real_transitions(
    posterior_seq: pd.DataFrame, persistence: int = PERSISTENCE_BARS
) -> List[Tuple[pd.Timestamp, str, str]]:
    """Identify durable argmax-state transitions in a posterior sequence.

    A transition is "real" only if the new argmax state persists for at
    least `persistence` bars. Returns (timestamp, from_state, to_state).
    """
    if posterior_seq.empty:
        return []
    argmax = posterior_seq.idxmax(axis=1)
    transitions = []
    last_durable = argmax.iloc[0]
    i = 1
    while i < len(argmax):
        cur = argmax.iloc[i]
        if cur != last_durable:
            # Check persistence
            window_end = min(i + persistence, len(argmax))
            window_states = argmax.iloc[i:window_end]
            if (window_states == cur).sum() >= persistence:
                transitions.append((argmax.index[i], last_durable, cur))
                last_durable = cur
        i += 1
    return transitions


def evaluate_anchor_events(
    posterior_seq: pd.DataFrame,
    warning_seq: pd.DataFrame,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
) -> List[dict]:
    """For each anchor event, find lead time of the first warning fire."""
    out = []
    for label, event_iso, to_state in ANCHOR_EVENTS:
        event_date = pd.Timestamp(event_iso)
        # Find the actual durable transition near this date
        # (use ±lookback window)
        win_start = event_date - pd.Timedelta(days=lookback_days)
        win_end = event_date + pd.Timedelta(days=lookback_days)
        if posterior_seq.index.max() < win_end:
            out.append({
                "event": label,
                "expected_date": event_iso,
                "status": "out_of_data_range",
                "data_max": str(posterior_seq.index.max().date()),
            })
            continue

        # Find the first detector warning in [event_date - lookback, event_date]
        pre_window = warning_seq.loc[win_start:event_date]
        first_warning_idx = pre_window.index[pre_window["warning"]]
        first_warning_date = first_warning_idx.min() if len(first_warning_idx) else None

        # Find the first durable transition into `to_state` in [event_date - 5, event_date + 30]
        # — but per spec we measure lead-up to the EVENT date, not the
        # detected-transition date. We'll report both.
        transitions = detect_real_transitions(
            posterior_seq.loc[win_start:win_end]
        )
        actual_flip_date = None
        for ts, frm, to in transitions:
            if to == to_state and ts >= event_date - pd.Timedelta(days=lookback_days):
                actual_flip_date = ts
                break

        # Lead time of warning before event
        lead_trading_days = None
        if first_warning_date is not None:
            spans = posterior_seq.loc[first_warning_date:event_date].index
            lead_trading_days = max(0, len(spans) - 1)
        passes = (lead_trading_days is not None
                  and lead_trading_days >= ACCEPTANCE_LEAD_TRADING_DAYS)

        out.append({
            "event": label,
            "expected_event_date": event_iso,
            "actual_durable_flip_date": (
                str(actual_flip_date.date()) if actual_flip_date is not None else None
            ),
            "first_warning_date": (
                str(first_warning_date.date()) if first_warning_date is not None else None
            ),
            "lead_trading_days_before_event": lead_trading_days,
            "passes_2day_lead_criterion": bool(passes),
            "argmax_states_in_window": {
                str(d.date()): str(s)
                for d, s in posterior_seq.loc[
                    event_date - pd.Timedelta(days=10):event_date + pd.Timedelta(days=5)
                ].idxmax(axis=1).items()
            },
        })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2019-06-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument(
        "--out-json",
        default=str(ROOT / "data/research/transition_warning_backtest_2026_05.json"),
    )
    parser.add_argument(
        "--daily-pickle",
        default=str(ROOT / "engines/engine_e_regime/models/hmm_3state_v1.pkl"),
    )
    args = parser.parse_args()

    from engines.engine_e_regime.hmm_classifier import HMMRegimeClassifier
    from engines.engine_e_regime.transition_warning import (
        TransitionWarningDetector, TransitionWarningConfig,
    )

    log.info("Building extended feature panel %s → %s", args.start, args.end)
    panel = build_extended_panel(args.start, args.end)
    log.info("Extended panel shape=%s, NaN/col total=%d",
             panel.shape, int(panel.isna().sum().sum()))

    # Drop NaN rows for HMM scoring
    panel_valid = panel.dropna()
    log.info("After dropna: %d rows (%s → %s)",
             len(panel_valid),
             panel_valid.index.min().date(),
             panel_valid.index.max().date())

    log.info("Loading daily HMM artifact %s", args.daily_pickle)
    clf = HMMRegimeClassifier.load(Path(args.daily_pickle))

    log.info("Running daily HMM forward pass...")
    posterior_seq = clf.predict_proba_sequence(panel_valid)
    log.info("Posterior sequence: %d bars × %d states", *posterior_seq.shape)

    detector = TransitionWarningDetector(TransitionWarningConfig())
    warning_seq = detector.detect_sequence(posterior_seq)
    n_warnings = int(warning_seq["warning"].sum())
    log.info(
        "TransitionWarningDetector fired %d warnings across %d bars (rate=%.2f%%)",
        n_warnings, len(warning_seq), 100 * n_warnings / max(1, len(warning_seq))
    )

    # Run the anchor evaluation
    event_results = evaluate_anchor_events(posterior_seq, warning_seq)

    # Also identify all durable transitions for diagnostic context
    transitions = detect_real_transitions(posterior_seq)
    log.info(
        "Found %d durable argmax transitions over the full sequence",
        len(transitions)
    )

    summary = {
        "panel_start": str(panel_valid.index.min().date()),
        "panel_end": str(panel_valid.index.max().date()),
        "n_bars_scored": int(len(posterior_seq)),
        "n_warnings_total": n_warnings,
        "warning_rate_pct": round(100 * n_warnings / max(1, len(warning_seq)), 3),
        "n_durable_transitions": len(transitions),
        "durable_transitions": [
            {"date": str(ts.date()), "from": frm, "to": to}
            for ts, frm, to in transitions
        ],
        "anchor_event_results": event_results,
        "config": {
            "window": detector.cfg.window,
            "entropy_threshold": detector.cfg.entropy_threshold,
            "kl_threshold": detector.cfg.kl_threshold,
            "smoothing_window": detector.cfg.smoothing_window,
            "min_history": detector.cfg.min_history,
            "persistence_bars": PERSISTENCE_BARS,
            "acceptance_lead_trading_days": ACCEPTANCE_LEAD_TRADING_DAYS,
        },
    }
    n_anchor_pass = sum(
        1 for e in event_results if e.get("passes_2day_lead_criterion")
    )
    n_anchor_total = sum(
        1 for e in event_results if "status" not in e
    )
    summary["anchor_pass_count"] = int(n_anchor_pass)
    summary["anchor_total_evaluable"] = int(n_anchor_total)
    summary["anchor_pass_rate_pct"] = (
        round(100 * n_anchor_pass / n_anchor_total, 1)
        if n_anchor_total > 0 else None
    )

    print("\n=== Anchor event results ===")
    for e in event_results:
        if "status" in e:
            print(f"  {e['event']:<25} {e['status']}")
            continue
        print(
            f"  {e['event']:<25} "
            f"event={e['expected_event_date']} "
            f"warn={e['first_warning_date']} "
            f"lead_days={e['lead_trading_days_before_event']} "
            f"pass={'PASS' if e['passes_2day_lead_criterion'] else 'FAIL'}"
        )
    print(f"\n=> {n_anchor_pass}/{n_anchor_total} events passed ≥2-trading-day lead criterion")

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n[BACKTEST] wrote {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
