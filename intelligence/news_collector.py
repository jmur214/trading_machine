# intelligence/news_collector.py
from __future__ import annotations

"""
Quant-OSINT Market News Collector
=================================

MVP that aggregates market/finance headlines from multiple sources (RSS/HTML),
deduplicates, adds sentiment (VADER), ranks, and writes a daily snapshot
(JSON + CSV) for:
  1) Research ingestion (Engine D / edge discovery)
  2) Dashboard "Intel" tab (daily market snapshot)

Usage (CLI):
------------
python -m intelligence.news_collector \
  --sources config/intel_sources.json \
  --out-dir data/intel \
  --since-hours 36

Optional:
  --tickers AAPL,MSFT,TSLA    (light keyword filtering, best-effort)
  --top-k 100                  (limit rows in snapshot)
  --date 2025-10-17            (force output filename date; default: today local)

Dependencies:
-------------
pip install requests feedparser beautifulsoup4 vaderSentiment pandas python-dateutil

Notes:
------
- Respects simple backoff and fails closed (skips bad sources, continues).
- Dedup heuristic: normalized(title) + domain + yyyymmdd
- Sentiment: VADER compound in [-1, 1]
- Relevance: simple keyword hit score (MVP; replace with ML model later)
"""

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import pandas as pd

# Optional imports guarded for graceful degradation
try:
    import requests
except Exception:
    requests = None  # type: ignore

try:
    import feedparser  # type: ignore
except Exception:
    feedparser = None  # type: ignore

try:
    from bs4 import BeautifulSoup  # type: ignore
except Exception:
    BeautifulSoup = None  # type: ignore

try:
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # type: ignore
except Exception:
    SentimentIntensityAnalyzer = None  # type: ignore

# Alpaca Imports
try:
    from alpaca.data.historical.news import NewsClient
    from alpaca.data.requests import NewsRequest
    from alpaca.common.enums import Sort
except ImportError:
    NewsClient = None

from dateutil import parser as dateparser
import os
from dotenv import load_dotenv

load_dotenv()


# --------------------------- Data Models --------------------------- #

@dataclass
class SourceSpec:
    name: str
    url: str
    type: str  # "rss" or "html"
    weight: float = 1.0
    enabled: bool = True


@dataclass
class NewsItem:
    source: str
    title: str
    summary: str
    link: str
    published: Optional[pd.Timestamp]
    sentiment: Optional[float]
    relevance: float
    domain: str


# --------------------------- Utilities --------------------------- #

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[NEWS][{ts}] {msg}")


def _safe_ts(x: Any) -> Optional[pd.Timestamp]:
    if x is None:
        return None
    try:
        return pd.to_datetime(x)
    except Exception:
        try:
            return pd.to_datetime(dateparser.parse(str(x)))
        except Exception:
            return None


def _normalize_title(t: str) -> str:
    t = (t or "").strip().lower()
    t = re.sub(r"\s+", " ", t)
    return t


def _domain(u: str) -> str:
    try:
        return urlparse(u).netloc.lower()
    except Exception:
        return ""


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _now_local() -> datetime:
    return datetime.now()


# --------------------------- Collector --------------------------- #

class NewsCollector:
    """
    Multi-source news collector with RSS first (fast & robust), HTML fallback (best-effort).
    Produces a ranked, deduped snapshot for downstream use.
    """

    def __init__(
        self,
        sources_path: str | Path,
        out_dir: str | Path = "data/intel",
        since_hours: int = 24,
        top_k: int = 100,
        tickers: Optional[List[str]] = None,
        request_timeout: float = 8.0,
        backoff_seconds: float = 1.5,
    ):
        self.sources_path = Path(sources_path)
        self.out_dir = Path(out_dir)
        self.since_hours = max(1, int(since_hours))
        self.top_k = max(1, int(top_k))
        self.tickers = [t.strip().upper() for t in (tickers or []) if t.strip()]
        self.request_timeout = float(request_timeout)
        self.backoff_seconds = float(backoff_seconds)

        self.sources: List[SourceSpec] = self._load_sources()
        self.analyzer = SentimentIntensityAnalyzer() if SentimentIntensityAnalyzer else None

        if requests is None:
            _log("WARN: 'requests' not available; HTML fallback disabled.")
        if feedparser is None:
            _log("WARN: 'feedparser' not available; RSS collection disabled.")
        if BeautifulSoup is None:
            _log("WARN: 'beautifulsoup4' not available; HTML parsing reduced.")
        if self.analyzer is None:
            _log("WARN: 'vaderSentiment' not available; sentiment will be None.")

    # ----------------------- Source handling ----------------------- #

    def _load_sources(self) -> List[SourceSpec]:
        try:
            with open(self.sources_path, "r") as f:
                raw = json.load(f)
        except Exception as e:
            _log(f"ERROR loading sources JSON: {e}")
            return []

        out: List[SourceSpec] = []
        for item in raw:
            try:
                out.append(
                    SourceSpec(
                        name=item.get("name", "unknown"),
                        url=item["url"],
                        type=item.get("type", "rss"),
                        weight=float(item.get("weight", 1.0)),
                        enabled=bool(item.get("enabled", True)),
                    )
                )
            except Exception:
                continue
        _log(f"Loaded {len(out)} sources from config.")
        return out

    # ----------------------- Fetching logic ------------------------ #

    def _fetch_rss(self, spec: SourceSpec) -> List[NewsItem]:
        if feedparser is None:
            return []
        try:
            parsed = feedparser.parse(spec.url)
        except Exception:
            return []
        items: List[NewsItem] = []
        for e in parsed.get("entries", []):
            title = e.get("title", "").strip()
            link = e.get("link", "").strip()
            summary = (e.get("summary") or e.get("description") or "").strip()
            published = _safe_ts(e.get("published") or e.get("updated") or e.get("published_parsed"))
            # Filter by 'since_hours'
            cutoff = _now_local() - timedelta(hours=self.since_hours)
            if published and published.tzinfo is not None:
                published = published.tz_convert(None) if hasattr(published, "tz_convert") else pd.Timestamp(published).tz_localize(None)
            if published and published < pd.Timestamp(cutoff):
                continue
            items.append(
                NewsItem(
                    source=spec.name,
                    title=title,
                    summary=summary,
                    link=link,
                    published=published,
                    sentiment=None,
                    relevance=0.0,
                    domain=_domain(link),
                )
            )
        return items

    def _fetch_html(self, spec: SourceSpec) -> List[NewsItem]:
        """
        Very simple HTML fallback: reads <title> and meta description if available.
        Meant for sources that don't provide RSS. Rate-limited by backoff.
        """
        if requests is None:
            return []
        try:
            resp = requests.get(spec.url, timeout=self.request_timeout, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code != 200:
                return []
            html = resp.text
            if BeautifulSoup is None:
                # crude title detect
                m = re.search(r"<title>(.*?)</title>", html, flags=re.IGNORECASE | re.DOTALL)
                title = (m.group(1).strip() if m else spec.name)
                return [
                    NewsItem(
                        source=spec.name,
                        title=title,
                        summary="",
                        link=spec.url,
                        published=None,
                        sentiment=None,
                        relevance=0.0,
                        domain=_domain(spec.url),
                    )
                ]
            soup = BeautifulSoup(html, "html.parser")
            title = (soup.title.text.strip() if soup.title else spec.name)
            # meta description or og:description
            meta_desc = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
            summary = meta_desc["content"].strip() if (meta_desc and meta_desc.get("content")) else ""
            return [
                NewsItem(
                    source=spec.name,
                    title=title,
                    summary=summary,
                    link=spec.url,
                    published=None,
                    sentiment=None,
                    relevance=0.0,
                    domain=_domain(spec.url),
                )
            ]
        except Exception:
            return []

    def fetch_history_alpaca(self, tickers: List[str], start_date: datetime, end_date: datetime) -> List[NewsItem]:
        """
        Fetch historical news for specific tickers using Alpaca API.
        """
        if NewsClient is None:
            _log("ERROR: alpaca-py not installed. Cannot fetch history.")
            return []
        
        api_key = os.getenv("ALPACA_API_KEY")
        secret_key = os.getenv("ALPACA_SECRET_KEY")
        if not api_key:
            _log("ERROR: ALPACA_API_KEY not found.")
            return []

        client = NewsClient(api_key=api_key, secret_key=secret_key)
        all_items = []

        # Iterate tickers to manage limits (Alpaca allows 50 items/request typically)
        # We'll do it in chunks or per ticker
        for ticker in tickers:
            _log(f"Fetching history for {ticker} ({start_date.date()} to {end_date.date()})...")
            try:
                req = NewsRequest(
                    symbols=ticker,
                    start=start_date,
                    end=end_date,
                    limit=50, # Page size
                    sort=Sort.ASC
                )
                
                # Handling pagination loop if needed, for MVP just getting first page or iterating
                # For robust backfill we might need a loop, but let's grab a chunk first
                page_token = None
                while True:
                    req.page_token = page_token
                    resp = client.get_news(req)
                    
                    # Handle raw object vs dict
                    data_items = []
                    if hasattr(resp, 'news'):
                        data_items = resp.news
                    elif hasattr(resp, 'data'): # Raw response wrapper
                         d = resp.data
                         data_items = d.get('news', []) if isinstance(d, dict) else d

                    if not data_items:
                        break
                        
                    for it in data_items:
                        # Extract fields
                        headline = getattr(it, 'headline', "")
                        summary = getattr(it, 'summary', "")
                        created_at = getattr(it, 'created_at', None)
                        source = getattr(it, 'source', "alpaca")
                        url = getattr(it, 'url', "")
                        
                        # Convert to pandas timestamp
                        ts = pd.to_datetime(created_at) if created_at else None

                        all_items.append(NewsItem(
                            source=f"alpaca_{source}",
                            title=headline,
                            summary=summary,
                            link=url,
                            published=ts,
                            sentiment=None, # Will be computed later
                            relevance=1.0,  # Explicitly asked for this ticker
                            domain="alpaca.markets"
                        ))
                    
                    _log(f"  Got {len(data_items)} items. Total: {len(all_items)}")
                    
                    page_token = getattr(resp, 'next_page_token', None)
                    if not page_token:
                        break
                    
                    time.sleep(0.5) # Rate limit default
                    
            except Exception as e:
                _log(f"ERROR fetching {ticker}: {e}")
        
        return all_items

    # --------------------- Post-processing ------------------------- #

    def _apply_sentiment(self, items: List[NewsItem]) -> None:
        if not self.analyzer:
            return
        for it in items:
            text = f"{it.title}. {it.summary}".strip()
            if not text:
                it.sentiment = None
                continue
            try:
                score = self.analyzer.polarity_scores(text)["compound"]
                it.sentiment = float(score)
            except Exception:
                it.sentiment = None

    def _apply_relevance(self, items: List[NewsItem]) -> None:
        """
        MVP: simple keyword / ticker hit score.
        - If self.tickers provided, reward mentions in title/summary.
        - Otherwise, mild boost for words like: fed, inflation, guidance, earnings, downgrade, upgrade, strike, lawsuit.
        """
        keywords = set(["fed", "inflation", "guidance", "earnings", "downgrade", "upgrade", "strike", "lawsuit",
                        "acquisition", "merger", "antitrust", "restructuring", "forecast", "profit", "loss",
                        "outlook", "recession", "tariff", "sanction"])
        for it in items:
            text = f"{it.title} {it.summary}".upper()
            score = 0.0
            if self.tickers:
                for t in self.tickers:
                    if t in text:
                        score += 1.0
            else:
                up = text.lower()
                score += sum(1.0 for k in keywords if k in up) * 0.25
            # small boost for top domains
            if it.domain.endswith(("reuters.com", "bloomberg.com", "ft.com", "wsj.com")):
                score += 0.5
            it.relevance = float(score)

    def _dedup(self, items: List[NewsItem]) -> List[NewsItem]:
        seen: set[Tuple[str, str, str]] = set()
        out: List[NewsItem] = []
        for it in items:
            key_date = (it.published or pd.Timestamp(_now_local())).strftime("%Y%m%d")
            key = (_normalize_title(it.title), it.domain, key_date)
            if key in seen:
                continue
            seen.add(key)
            out.append(it)
        return out

    def _rank(self, items: List[NewsItem]) -> List[NewsItem]:
        """
        Simple score = relevance + 0.5*|sentiment| + source_weight
        (source_weight from sources config by domain/name; fallback 1.0)
        """
        weight_by_source = {s.name: s.weight for s in self.sources}
        def score(it: NewsItem) -> float:
            sw = weight_by_source.get(it.source, 1.0)
            sent = abs(it.sentiment) if it.sentiment is not None else 0.0
            return it.relevance + 0.5 * sent + float(sw)
        return sorted(items, key=score, reverse=True)

    # ------------------------ Orchestration ------------------------ #

    def run(self, out_date: Optional[str] = None) -> Path:
        """
        Execute collection pipeline and write JSON + CSV snapshot.
        Returns path to JSON file written.
        """
        _ensure_dir(self.out_dir)

        items = self.fetch_all()
        if not items:
            _log("No items collected.")
            # still write empty snapshot for consistency
            df = pd.DataFrame(columns=[
                "published", "source", "domain", "title", "summary", "link", "sentiment", "relevance"
            ])
        else:
            self._apply_sentiment(items)
            self._apply_relevance(items)
            items = self._dedup(items)
            items = self._rank(items)
            if self.top_k:
                items = items[: self.top_k]

            df = pd.DataFrame([{
                "published": (it.published.isoformat() if it.published else None),
                "source": it.source,
                "domain": it.domain,
                "title": it.title,
                "summary": it.summary,
                "link": it.link,
                "sentiment": it.sentiment,
                "relevance": it.relevance,
            } for it in items])

        # Write outputs
        day = (pd.to_datetime(out_date) if out_date else pd.Timestamp.today()).strftime("%Y%m%d")
        json_path = self.out_dir / f"news_snapshot_{day}.json"
        csv_path = self.out_dir / f"news_snapshot_{day}.csv"

        try:
            df.to_json(json_path, orient="records", indent=2)
            df.to_csv(csv_path, index=False)
        except Exception as e:
            _log(f"ERROR writing snapshot: {e}")

        _log(f"Wrote snapshot: {json_path}")
        return json_path


# --------------------------- CLI Entry ---------------------------- #

def _parse_cli(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Collect market/finance news into a ranked snapshot.")
    p.add_argument("--sources", default="config/intel_sources.json", help="Path to sources JSON.")
    p.add_argument("--out-dir", default="data/intel", help="Output directory for snapshots.")
    p.add_argument("--since-hours", type=int, default=24, help="Collect items no older than N hours.")
    p.add_argument("--top-k", type=int, default=100, help="Limit number of rows in snapshot.")
    p.add_argument("--tickers", default="", help="Comma-separated tickers to boost relevance, e.g., AAPL,MSFT.")
    p.add_argument("--date", default="", help="Force output date (YYYY-MM-DD); default today.")
    p.add_argument("--timeout", type=float, default=8.0, help="HTTP timeout per request (seconds).")
    p.add_argument("--backoff", type=float, default=1.5, help="Polite delay between source fetches (seconds).")
    p.add_argument("--history-start", default="", help="Fetch history start date (YYYY-MM-DD).")
    p.add_argument("--history-end", default="", help="Fetch history end date (YYYY-MM-DD).")
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = _parse_cli(argv)
    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else []
    collector = NewsCollector(
        sources_path=args.sources,
        out_dir=args.out_dir,
        since_hours=args.since_hours,
        top_k=args.top_k,
        tickers=tickers,
        request_timeout=args.timeout,
        backoff_seconds=args.backoff,
    )

    if args.history_start:
        # History Mode
        try:
            start = datetime.strptime(args.history_start, "%Y-%m-%d")
            end = datetime.strptime(args.history_end, "%Y-%m-%d") if args.history_end else datetime.now()
            
            if not tickers:
                print("ERROR: --tickers required for history fetch mode.")
                return 1
                
            items = collector.fetch_history_alpaca(tickers, start, end)
            if items:
                collector._apply_sentiment(items)
                items = collector._dedup(items)
                
                # Flatten and Save per ticker or aggregate
                df = pd.DataFrame([{
                    "published": (it.published.isoformat() if it.published else None),
                    "source": it.source,
                    "title": it.title,
                    "summary": it.summary,
                    "sentiment": it.sentiment,
                    "relevance": it.relevance,
                    "tickers": args.tickers
                } for it in items])
                
                fn = f"news_history_{args.tickers}_{start.strftime('%Y%m')}.csv"
                out_path = Path(args.out_dir) / "history" / fn
                out_path.parent.mkdir(parents=True, exist_ok=True)
                df.to_csv(out_path, index=False)
                print(f"Saved {len(df)} historical items to {out_path}")
            else:
                print("No historical items found.")
                
        except ValueError as e:
            print(f"Date format error: {e}")
            return 1
    else:
        # Live Snapshot Mode
        collector.run(out_date=(args.date or None))
        
    return 0


if __name__ == "__main__":
    sys.exit(main())