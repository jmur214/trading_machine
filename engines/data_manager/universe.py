# engines/data_manager/universe.py
"""
Survivorship-bias-aware S&P 500 historical membership pipeline.

Self-contained Wikipedia scraper + parquet cache for the S&P 500's
membership history. Designed to feed any cross-sectional / factor edge
that needs to know "which tickers were in the index on date X" without
peeking at today's constituents — the failure mode that killed
``momentum_factor_v1`` on the 39-ticker universe (see
``docs/Sessions/2026-04/2026-04-24_strategic_pivot.md`` post-experiment
notes).

Why this exists
---------------
The action ranking from the strategic pivot doc lists "expand universe
to a real survivorship-bias-aware S&P 500 historical set" as a hard
prerequisite for any further factor work. This module owns that data
layer; it does not download price data and does not wire into any
engine. ``scripts/fetch_universe.py`` is the explicit user-driven CLI
that uses the membership list to populate ``data/processed/`` via the
existing ``DataManager`` pipeline.

Source
------
Wikipedia's "List of S&P 500 companies" page maintains:
  1. The current constituents table (id="constituents").
  2. A "Selected changes to the list of S&P 500 components" table
     (id="changes") — additions and removals with dates.

Limitations: the changes table only goes back ~30 years and is
maintained by volunteers, so the further back you go, the spottier
the coverage. For tickers currently in the index that have no entry
in the change log, ``included_from`` falls back to the "Date added"
column of the current table (often itself missing, in which case the
field is ``NaT``).

Cached schema
-------------
``data/universe/sp500_membership.parquet`` — long-format DataFrame
with one row per (ticker, spell-of-membership):

    ticker          str        e.g. "AAPL"
    name            object     security name from Wikipedia (NaN if unknown)
    sector          object     GICS sector (NaN if unknown)
    included_from   datetime64[ns]   start of this membership spell, NaT if unknown
    included_until  datetime64[ns]   end of this spell, NaT if currently in the index

A ticker that has been added and removed multiple times will have
multiple rows; consumers can call ``historical_constituents(as_of)`` to
get the as-of snapshot without doing the spell-walking themselves.

Key design choices
------------------
- **No API key required** — Wikipedia is public; no auth.
- **Long refresh window (default 7 days).** S&P 500 changes are rare
  (~25 events/year); refreshing weekly is more than enough.
- **Graceful degradation.** Network down → return cache with a
  warning. No cache and no network → raise ``UniverseError``.
- **Pure-function parser.** ``parse_membership_html`` is a stand-alone
  function so tests can feed it fixture HTML without touching the
  network.
- **No engine wiring.** The loader returns DataFrames. Edges and
  evolution loops decide how to use them.
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd
import requests
from bs4 import BeautifulSoup


ROOT_DIR = Path(__file__).resolve().parents[2]

WIKIPEDIA_SP500_URL = (
    "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
)
DEFAULT_CACHE_DIR = ROOT_DIR / "data" / "universe"
MEMBERSHIP_FILENAME = "sp500_membership.parquet"
META_FILENAME = "_meta.json"
DEFAULT_TIMEOUT_S = 30
# Membership changes are rare (~25/year). Weekly refresh is plenty;
# we don't need to thrash Wikipedia.
DEFAULT_MAX_AGE_HOURS = 24 * 7
# Wikipedia returns 403 to bare requests; identify ourselves politely.
DEFAULT_USER_AGENT = (
    "trading_machine-2/universe-loader "
    "(+https://github.com/anthropics/claude-code; research)"
)

MEMBERSHIP_COLUMNS = [
    "ticker",
    "name",
    "sector",
    "included_from",
    "included_until",
]


class UniverseError(Exception):
    """Raised for non-recoverable failures in the universe pipeline."""


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------
class SP500MembershipLoader:
    """Fetch + cache the Wikipedia S&P 500 membership history.

    Parameters
    ----------
    cache_dir:
        Directory for parquet cache. Defaults to ``data/universe/`` at
        the repo root.
    timeout_s:
        Network timeout for the Wikipedia request.
    user_agent:
        HTTP User-Agent. Wikipedia rejects requests with no UA; the
        default identifies this loader.
    """

    def __init__(
        self,
        cache_dir: Optional[Path | str] = None,
        timeout_s: int = DEFAULT_TIMEOUT_S,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.cache_dir = (
            Path(cache_dir) if cache_dir is not None else DEFAULT_CACHE_DIR
        )
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.user_agent = user_agent
        self._membership_path = self.cache_dir / MEMBERSHIP_FILENAME
        self._meta_path = self.cache_dir / META_FILENAME

    # ----- cache plumbing -----
    def _read_meta(self) -> dict:
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text())
        except (json.JSONDecodeError, OSError):
            return {}

    def _write_meta(self, meta: dict) -> None:
        tmp = self._meta_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta, indent=2, sort_keys=True))
        tmp.replace(self._meta_path)

    def _record_fetch(self, n_rows: int, n_current: int) -> None:
        meta = self._read_meta()
        meta["sp500_membership"] = {
            "last_fetched_utc": datetime.now(timezone.utc).isoformat(),
            "n_rows": int(n_rows),
            "n_current_constituents": int(n_current),
            "source": WIKIPEDIA_SP500_URL,
        }
        self._write_meta(meta)

    def _cache_age_hours(self) -> Optional[float]:
        if not self._membership_path.exists():
            return None
        return (time.time() - self._membership_path.stat().st_mtime) / 3600.0

    # ----- public API -----
    def load_cached(self) -> pd.DataFrame:
        """Read the cached membership parquet without touching the network."""
        if not self._membership_path.exists():
            return _empty_membership_frame()
        df = pd.read_parquet(self._membership_path)
        return _coerce_membership_dtypes(df)

    def fetch_membership(
        self,
        force: bool = False,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ) -> pd.DataFrame:
        """Fetch the S&P 500 membership history, with cache.

        Cache-first: returns the cached parquet if fresher than
        ``max_age_hours``. On network failure the existing cache is
        returned (with a warning); only when there is no cache does the
        failure raise ``UniverseError``.
        """
        cached_age = self._cache_age_hours()
        if not force and cached_age is not None and cached_age < max_age_hours:
            return self.load_cached()

        try:
            html = self._download_html()
            df = parse_membership_html(html)
        except (requests.RequestException, UniverseError) as exc:
            if cached_age is not None:
                _log(f"Wikipedia fetch failed ({exc!s}); falling back to "
                     f"cache aged {cached_age:.1f}h")
                return self.load_cached()
            raise UniverseError(
                f"Wikipedia fetch failed and no cached membership "
                f"available: {exc}"
            ) from exc

        self._save(df)
        return df

    def current_constituents(
        self,
        force: bool = False,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ) -> list[str]:
        """Return the list of tickers currently in the index.

        "Currently" = rows whose ``included_until`` is NaT in the
        cached/fetched membership table.
        """
        df = self.fetch_membership(force=force, max_age_hours=max_age_hours)
        return current_tickers(df)

    def historical_constituents(
        self,
        as_of: str | pd.Timestamp,
        force: bool = False,
        max_age_hours: float = DEFAULT_MAX_AGE_HOURS,
    ) -> list[str]:
        """Tickers active on a given date — the survivorship-bias-aware view.

        A ticker is active on ``as_of`` if some membership spell
        contains the date: ``included_from <= as_of`` (or
        ``included_from`` is NaT) and ``included_until > as_of`` (or
        ``included_until`` is NaT).
        """
        df = self.fetch_membership(force=force, max_age_hours=max_age_hours)
        return active_at(df, as_of)

    def cache_status(self) -> dict:
        """Return a dict describing the on-disk cache state."""
        meta = self._read_meta().get("sp500_membership", {})
        return {
            "cached": self._membership_path.exists(),
            "age_hours": self._cache_age_hours(),
            "n_rows": meta.get("n_rows"),
            "n_current_constituents": meta.get("n_current_constituents"),
            "last_fetched_utc": meta.get("last_fetched_utc"),
            "path": str(self._membership_path),
        }

    # ----- internals -----
    def _download_html(self) -> str:
        resp = requests.get(
            WIKIPEDIA_SP500_URL,
            headers={"User-Agent": self.user_agent},
            timeout=self.timeout_s,
        )
        if resp.status_code != 200:
            raise UniverseError(
                f"Wikipedia returned HTTP {resp.status_code} "
                f"({resp.text[:200]!r})"
            )
        return resp.text

    def _save(self, df: pd.DataFrame) -> None:
        df = _coerce_membership_dtypes(df)
        df.to_parquet(self._membership_path, index=False)
        n_current = int(df["included_until"].isna().sum())
        self._record_fetch(len(df), n_current)


# ---------------------------------------------------------------------------
# Pure parsers — no I/O, used by the loader and by tests directly
# ---------------------------------------------------------------------------
def parse_membership_html(html: str) -> pd.DataFrame:
    """Convert raw Wikipedia HTML into the canonical membership frame.

    Pure function — no network, no cache. Tests feed this fixture HTML
    directly. Raises ``UniverseError`` if neither expected table is
    present.
    """
    soup = BeautifulSoup(html, "lxml")
    current_df = _parse_current_table(soup)
    change_events = _parse_changes_table(soup)

    if current_df.empty and not change_events:
        raise UniverseError(
            "Could not find either the constituents or changes table "
            "in the Wikipedia HTML — page structure may have changed."
        )

    return _build_membership(current_df, change_events)


def _parse_current_table(soup: BeautifulSoup) -> pd.DataFrame:
    """Extract the current constituents table.

    Wikipedia gives this table id='constituents'. Columns vary slightly
    across page revisions; we look up by header text rather than by
    position so the parser stays resilient to column reordering.
    """
    table = soup.find("table", id="constituents")
    if table is None:
        return pd.DataFrame(columns=["ticker", "name", "sector", "date_added"])

    rows = table.find_all("tr")
    if not rows:
        return pd.DataFrame(columns=["ticker", "name", "sector", "date_added"])

    headers = [_clean(th.get_text()) for th in rows[0].find_all(["th", "td"])]
    col = _header_lookup(
        headers,
        symbol={"symbol", "ticker"},
        name={"security", "company"},
        sector={"gics sector", "sector"},
        date_added={"date added", "date first added", "date"},
    )

    out = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue
        if col["symbol"] is None or col["symbol"] >= len(cells):
            continue
        ticker = normalize_ticker(_clean(cells[col["symbol"]].get_text()))
        if not ticker:
            continue
        name = _cell_or_none(cells, col["name"])
        sector = _cell_or_none(cells, col["sector"])
        date_added = _parse_date(_cell_or_none(cells, col["date_added"]))
        out.append({
            "ticker": ticker,
            "name": name,
            "sector": sector,
            "date_added": date_added,
        })

    return pd.DataFrame(out, columns=["ticker", "name", "sector", "date_added"])


def _parse_changes_table(soup: BeautifulSoup) -> list[dict]:
    """Extract addition/removal events from the change-history table.

    The changes table has a two-row header:
        Date | Added              | Removed            | Reason
             | Ticker | Security  | Ticker | Security  |

    We don't try to parse the multi-row header structure; instead we
    locate the table by id='changes' and rely on the well-established
    column order [date, added_ticker, added_security, removed_ticker,
    removed_security, reason]. Empty cells are skipped — many rows
    have only an addition or only a removal.

    Returns a list of {date, ticker, action, name} dicts.
    """
    table = soup.find("table", id="changes")
    if table is None:
        return []

    events: list[dict] = []
    rows = table.find_all("tr")
    # Skip the two header rows. Some revisions have one merged header
    # row, so we just attempt to parse every row and skip ones whose
    # first cell isn't a date.
    for row in rows:
        cells = row.find_all(["td", "th"])
        if len(cells) < 5:
            continue
        date_text = _clean(cells[0].get_text())
        date = _parse_date(date_text)
        if date is None:
            continue
        added_ticker = normalize_ticker(_clean(cells[1].get_text()))
        added_name = _clean(cells[2].get_text()) or None
        removed_ticker = normalize_ticker(_clean(cells[3].get_text()))
        removed_name = _clean(cells[4].get_text()) or None
        if added_ticker:
            events.append({
                "date": date,
                "ticker": added_ticker,
                "action": "added",
                "name": added_name,
            })
        if removed_ticker:
            events.append({
                "date": date,
                "ticker": removed_ticker,
                "action": "removed",
                "name": removed_name,
            })
    return events


def _build_membership(
    current_df: pd.DataFrame,
    change_events: list[dict],
) -> pd.DataFrame:
    """Assemble the long-format membership frame from current + changes.

    For each ticker that ever appears:
      * Walk its events chronologically, pairing each "added" with the
        next "removed" to form spells.
      * If the ticker is currently in the index and the last event is
        an "added" (or there are no events), the spell is left open
        with ``included_until = NaT``.
      * If the ticker is currently in the index but has no addition
        event in the change log, fall back to the "Date added" column
        from the current table; if that is also missing, leave
        ``included_from = NaT`` (meaning "since before the change log
        started").
      * If the ticker is currently in the index but the most recent
        event is a "removed" (data inconsistency — re-added without
        an event), open a fresh spell using the current table's date.
    """
    by_ticker: dict[str, list[dict]] = {}
    for ev in change_events:
        by_ticker.setdefault(ev["ticker"], []).append(ev)
    for evs in by_ticker.values():
        evs.sort(key=lambda e: e["date"])

    if not current_df.empty:
        current_set = set(current_df["ticker"])
        current_dates = dict(zip(current_df["ticker"], current_df["date_added"]))
        current_names = dict(zip(current_df["ticker"], current_df["name"]))
        current_sectors = dict(zip(current_df["ticker"], current_df["sector"]))
    else:
        current_set, current_dates = set(), {}
        current_names, current_sectors = {}, {}

    rows: list[dict] = []

    for ticker, events in by_ticker.items():
        spells: list[tuple] = []
        open_from: Optional[pd.Timestamp] = None
        last_name: Optional[str] = None
        for ev in events:
            if ev.get("name"):
                last_name = ev["name"]
            if ev["action"] == "added":
                if open_from is None:
                    open_from = ev["date"]
                # else duplicate "added" — ignore (data anomaly)
            else:  # removed
                if open_from is not None:
                    spells.append((open_from, ev["date"]))
                    open_from = None
                else:
                    # Removed without prior recorded add → must have
                    # been in the index since before the change log;
                    # leave the start as NaT.
                    spells.append((pd.NaT, ev["date"]))

        is_current = ticker in current_set
        if open_from is not None:
            # Final spell is still open.
            spells.append((open_from, pd.NaT))
        elif is_current:
            # In the current table, but the change log doesn't have
            # an open spell for this ticker. Open one using the
            # current table's date_added, which may itself be NaT.
            spells.append((current_dates.get(ticker, pd.NaT), pd.NaT))

        for inc_from, inc_until in spells:
            rows.append({
                "ticker": ticker,
                "name": current_names.get(ticker) or last_name,
                "sector": current_sectors.get(ticker),
                "included_from": inc_from,
                "included_until": inc_until,
            })

    # Tickers in the current table that the changes log doesn't mention
    # at all — they've been in the index for the entire window.
    for ticker in sorted(current_set - by_ticker.keys()):
        rows.append({
            "ticker": ticker,
            "name": current_names.get(ticker),
            "sector": current_sectors.get(ticker),
            "included_from": current_dates.get(ticker, pd.NaT),
            "included_until": pd.NaT,
        })

    df = pd.DataFrame(rows, columns=MEMBERSHIP_COLUMNS)
    if df.empty:
        return _empty_membership_frame()
    df = df.sort_values(
        ["ticker", "included_from"], na_position="first"
    ).reset_index(drop=True)
    return _coerce_membership_dtypes(df)


# ---------------------------------------------------------------------------
# Membership-frame helpers (pure, exposed for consumers)
# ---------------------------------------------------------------------------
def current_tickers(df: pd.DataFrame) -> list[str]:
    """Tickers whose most recent spell is still open (included_until NaT)."""
    if df.empty:
        return []
    open_spells = df[df["included_until"].isna()]
    return sorted(open_spells["ticker"].unique().tolist())


def active_at(df: pd.DataFrame, as_of: str | pd.Timestamp) -> list[str]:
    """Tickers active on ``as_of``.

    A spell covers ``as_of`` if:
      * ``included_from`` is NaT or ``included_from <= as_of``, AND
      * ``included_until`` is NaT or ``included_until > as_of``.

    The strict-greater on the upper bound matches the convention that
    a removal "on date X" means the ticker is no longer in the index
    on that day.
    """
    if df.empty:
        return []
    as_of_ts = pd.Timestamp(as_of)
    inc_from = df["included_from"]
    inc_until = df["included_until"]
    starts_ok = inc_from.isna() | (inc_from <= as_of_ts)
    ends_ok = inc_until.isna() | (inc_until > as_of_ts)
    mask = starts_ok & ends_ok
    return sorted(df.loc[mask, "ticker"].unique().tolist())


def normalize_ticker(t: Optional[str]) -> str:
    """Trim, uppercase, and strip Wikipedia footnote markers like '[1]'.

    Returns "" for None / empty / sentinel-only inputs.
    """
    if t is None:
        return ""
    s = re.sub(r"\[[^\]]*\]", "", str(t)).strip().upper()
    return s


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------
def _empty_membership_frame() -> pd.DataFrame:
    df = pd.DataFrame({
        "ticker": pd.Series([], dtype="object"),
        "name": pd.Series([], dtype="object"),
        "sector": pd.Series([], dtype="object"),
        "included_from": pd.Series([], dtype="datetime64[ns]"),
        "included_until": pd.Series([], dtype="datetime64[ns]"),
    })
    return df


def _coerce_membership_dtypes(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    for col in ("included_from", "included_until"):
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce")
    for col in ("ticker", "name", "sector"):
        if col in df.columns:
            df[col] = df[col].astype("object")
    return df[MEMBERSHIP_COLUMNS]


def _clean(text: str) -> str:
    """Collapse whitespace and strip, returning '' for None."""
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def _cell_or_none(cells, idx: Optional[int]) -> Optional[str]:
    if idx is None or idx >= len(cells):
        return None
    val = _clean(cells[idx].get_text())
    return val or None


def _header_lookup(headers: list[str], **wanted) -> dict[str, Optional[int]]:
    """Map logical column names to header indices by case-insensitive match.

    ``wanted`` is keyword args of {logical_name: set_of_acceptable_header_strings}.
    Returns {logical_name: index or None}.
    """
    norm = [h.lower() for h in headers]
    out: dict[str, Optional[int]] = {}
    for key, choices in wanted.items():
        choices_lc = {c.lower() for c in choices}
        idx = next(
            (i for i, h in enumerate(norm) if h in choices_lc),
            None,
        )
        out[key] = idx
    return out


def _parse_date(text: Optional[str]) -> Optional[pd.Timestamp]:
    """Parse Wikipedia's varied date formats into a naive Timestamp.

    Returns None if the text can't be coerced. Wikipedia uses a mix of
    "1976-08-09", "August 9, 1976", and occasionally bare years.
    """
    if not text:
        return None
    text = text.strip()
    # Strip footnote markers
    text = re.sub(r"\[[^\]]*\]", "", text).strip()
    if not text:
        return None
    try:
        ts = pd.to_datetime(text, errors="coerce")
    except (ValueError, TypeError):
        return None
    if pd.isna(ts):
        return None
    # Drop any tz info to keep the schema naive (the loader's caller
    # treats these as date-only).
    if getattr(ts, "tz", None) is not None:
        ts = ts.tz_localize(None)
    return ts


def _log(msg: str) -> None:
    """Lightweight logger compatible with the existing data_manager style.

    Routes through ``debug_config`` if available, otherwise stays
    silent. Keeps the module importable in standalone contexts
    (notebooks, isolated tests) without pulling in the wider project's
    debug infrastructure.
    """
    try:
        from debug_config import is_debug_enabled  # type: ignore
        verbose = is_debug_enabled("DATA_MANAGER")
    except Exception:
        verbose = False
    if verbose:
        print(f"[UNIVERSE] {msg}")
