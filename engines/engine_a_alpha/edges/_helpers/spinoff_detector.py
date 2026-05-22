"""engines/engine_a_alpha/edges/_helpers/spinoff_detector.py
==============================================================
Spin-off event detector for `spinoff_reversion_v1` (T-2026-05-12-041).

Sources, in priority order:
1. **Curated YAML** at `data/spinoff_events_curated.yml` — hand-
   maintained list of known historical spin-offs. Authoritative when
   present; highest confidence (1.0).
2. **yfinance `Ticker.actions`** — flags "stock split" distributions
   that are often spin-offs. Coverage variable; confidence 0.7. Looks
   up via parent_ticker → derived from the existing trade universe.
3. **SEC EDGAR Form 10 / 10-12B** — authoritative registration source.
   Confidence 1.0. **DEFERRED to T-041b** because the 10 req/sec rate
   limit + 500+ filings would dominate the time budget; the curated
   list covers the validation set the audit requires.

The detector returns a flat list of `SpinoffEvent` records keyed by
`distribution_date`. Caller filters by window / universe.

Determinism: pure function of (curated file + optional yfinance cache).
No floating I/O; results stable across reps.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd
import yaml

logger = logging.getLogger("spinoff_detector")

PROJECT_ROOT = Path(__file__).resolve().parents[4]
CURATED_PATH = PROJECT_ROOT / "config" / "spinoff_events_curated.yml"


@dataclass(frozen=True)
class SpinoffEvent:
    """One spin-off event. Frozen for use in sets/dict keys."""
    parent_ticker: str
    child_ticker: str
    distribution_date: pd.Timestamp  # tz-naive, normalized
    distribution_ratio: float
    source: str  # 'curated' | 'yfinance' | 'edgar'
    confidence: float
    notes: str = ""

    def __post_init__(self):
        # Defensive normalization done via object.__setattr__ to keep
        # frozen=True semantics.
        ts = pd.Timestamp(self.distribution_date)
        if ts.tzinfo is not None:
            ts = ts.tz_localize(None)
        ts = ts.normalize()
        object.__setattr__(self, "distribution_date", ts)
        object.__setattr__(self, "parent_ticker", str(self.parent_ticker).upper())
        object.__setattr__(self, "child_ticker", str(self.child_ticker).upper())


# In-process cache: detector results are reused across calls within a
# backtest run. Cleared by `clear_cache()` for tests.
_CACHED_EVENTS: Optional[List[SpinoffEvent]] = None
_CACHED_YFINANCE: Dict[str, pd.DataFrame] = {}


def clear_cache() -> None:
    """Reset all module-level caches. Use in tests."""
    global _CACHED_EVENTS, _CACHED_YFINANCE
    _CACHED_EVENTS = None
    _CACHED_YFINANCE = {}


def load_curated_events(curated_path: Path = CURATED_PATH) -> List[SpinoffEvent]:
    """Read the hand-curated YAML and return parsed events.

    Returns an empty list if the file is missing or empty. Logs (does
    not raise) on parse errors — detector caller falls through to
    other sources.
    """
    if not curated_path.exists():
        logger.debug(f"curated events file not found at {curated_path}")
        return []
    try:
        data = yaml.safe_load(curated_path.read_text()) or {}
    except Exception as e:
        logger.warning(f"could not parse {curated_path}: {e}")
        return []

    raw_events = data.get("events", []) if isinstance(data, dict) else []
    out: List[SpinoffEvent] = []
    for raw in raw_events:
        try:
            out.append(SpinoffEvent(
                parent_ticker=raw["parent_ticker"],
                child_ticker=raw["child_ticker"],
                distribution_date=pd.Timestamp(raw["distribution_date"]),
                distribution_ratio=float(raw.get("distribution_ratio", 1.0)),
                source="curated",
                confidence=1.0,
                notes=str(raw.get("notes", "")),
            ))
        except (KeyError, ValueError, TypeError) as e:
            logger.warning(f"skipping malformed curated event {raw}: {e}")
            continue
    return out


def detect_from_yfinance(
    parent_tickers: List[str],
    *,
    min_split_ratio: float = 1.001,
    max_split_ratio: float = 10.0,
) -> List[SpinoffEvent]:
    """Best-effort spin-off detection from yfinance `Ticker.actions`.

    yfinance encodes spin-offs as "stock splits" in `Ticker.splits`
    with non-integer ratios. True stock splits use integer ratios
    (2:1, 3:1, etc.), so non-integer ratios in the [1.001, 10.0]
    range are candidate spin-offs. False positives are inevitable
    (real stock splits, rights offerings); confidence is capped at
    0.7 so curated entries override.

    Note: yfinance does NOT expose the child ticker; we can detect
    that a spin-off-like event occurred but cannot reliably name the
    child symbol. For child-symbol resolution, fall back to curated.

    This function is included for completeness + future use; the
    primary path for T-041 is the curated YAML. The `child_ticker`
    field is set to `<parent>_SPINOFF_<date>` as a placeholder so
    callers can detect "yfinance saw a split-like event we don't have
    a curated mapping for" and surface for review.
    """
    out: List[SpinoffEvent] = []
    try:
        import yfinance as yf
    except ImportError:
        logger.debug("yfinance not installed; skipping yfinance detection")
        return out

    for tkr in parent_tickers:
        try:
            if tkr in _CACHED_YFINANCE:
                splits = _CACHED_YFINANCE[tkr]
            else:
                t = yf.Ticker(tkr)
                splits = t.splits
                if splits is None or len(splits) == 0:
                    _CACHED_YFINANCE[tkr] = pd.DataFrame()
                    continue
                df = pd.DataFrame({"date": splits.index, "ratio": splits.values})
                if pd.api.types.is_datetime64_any_dtype(df["date"]):
                    if getattr(df["date"].dt, "tz", None) is not None:
                        df["date"] = df["date"].dt.tz_localize(None)
                _CACHED_YFINANCE[tkr] = df
                splits = df

            if splits is None or splits.empty:
                continue
            for _, row in splits.iterrows():
                ratio = float(row["ratio"])
                # Skip true integer splits (2:1, 3:1, ...)
                if abs(ratio - round(ratio)) < 1e-6:
                    continue
                if ratio < min_split_ratio or ratio > max_split_ratio:
                    continue
                date_ts = pd.Timestamp(row["date"]).normalize()
                placeholder_child = (
                    f"{tkr}_SPINOFF_{date_ts.date().isoformat()}"
                )
                out.append(SpinoffEvent(
                    parent_ticker=tkr,
                    child_ticker=placeholder_child,
                    distribution_date=date_ts,
                    distribution_ratio=ratio,
                    source="yfinance",
                    confidence=0.7,
                    notes="yfinance-detected non-integer split (candidate spin-off)",
                ))
        except Exception as e:
            logger.debug(f"yfinance detection failed for {tkr}: {e}")
            continue
    return out


def get_events(
    *,
    use_yfinance: bool = False,
    yfinance_parent_tickers: Optional[List[str]] = None,
    curated_path: Path = CURATED_PATH,
    use_cache: bool = True,
) -> List[SpinoffEvent]:
    """Return the merged list of spin-off events from all configured sources.

    Curated entries take precedence on (parent, distribution_date) collisions
    (highest confidence). yfinance entries are appended for any (parent, date)
    not already covered by curated.

    Parameters
    ----------
    use_yfinance
        Enable yfinance-based detection. Default False because it's slow
        and the placeholder child_ticker is rarely actionable; the curated
        list is the primary signal source.
    yfinance_parent_tickers
        Parent tickers to query when `use_yfinance=True`. Default None
        (no-op).
    curated_path
        Override for the curated YAML location. Tests use this.
    use_cache
        If True, return the cached result from a prior call. Tests set False.
    """
    global _CACHED_EVENTS
    if use_cache and _CACHED_EVENTS is not None:
        return list(_CACHED_EVENTS)

    curated = load_curated_events(curated_path)

    yf_events: List[SpinoffEvent] = []
    if use_yfinance and yfinance_parent_tickers:
        yf_events = detect_from_yfinance(yfinance_parent_tickers)

    seen_keys = {(e.parent_ticker, e.distribution_date) for e in curated}
    merged: List[SpinoffEvent] = list(curated)
    for ev in yf_events:
        if (ev.parent_ticker, ev.distribution_date) in seen_keys:
            continue
        merged.append(ev)
        seen_keys.add((ev.parent_ticker, ev.distribution_date))

    merged.sort(key=lambda e: (e.distribution_date, e.parent_ticker))

    if use_cache:
        _CACHED_EVENTS = list(merged)
    return merged


def events_in_window(
    events: List[SpinoffEvent],
    start: pd.Timestamp,
    end: pd.Timestamp,
) -> List[SpinoffEvent]:
    """Filter `events` to those whose distribution_date is in [start, end].

    Both bounds inclusive. Caller is responsible for tz-naive timestamps;
    SpinoffEvent normalizes to tz-naive in __post_init__.
    """
    start_ts = pd.Timestamp(start).normalize()
    end_ts = pd.Timestamp(end).normalize()
    if start_ts.tzinfo is not None:
        start_ts = start_ts.tz_localize(None)
    if end_ts.tzinfo is not None:
        end_ts = end_ts.tz_localize(None)
    return [
        ev for ev in events
        if start_ts <= ev.distribution_date <= end_ts
    ]


def events_by_child(
    events: List[SpinoffEvent],
) -> Dict[str, SpinoffEvent]:
    """Index events by child_ticker for fast O(1) lookup in compute_signals.

    If the same child appears in multiple events (re-listings, ticker
    recycle), the latest distribution_date wins. Real spin-offs that
    share a parent (e.g., GE → GEHC then GE → GEV) have different
    children and don't collide.
    """
    out: Dict[str, SpinoffEvent] = {}
    for ev in events:
        existing = out.get(ev.child_ticker)
        if existing is None or ev.distribution_date > existing.distribution_date:
            out[ev.child_ticker] = ev
    return out
