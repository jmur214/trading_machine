# intelligence/news_summarizer.py
from __future__ import annotations
import pandas as pd
from pathlib import Path
from textwrap import fill
from datetime import datetime


class NewsSummarizer:
    """
    Summarizes a daily news snapshot from news_collector into a concise institutional-style
    market brief. Uses simple keyword grouping and sentiment averaging for now.
    """

    def __init__(self, intel_dir: str = "data/intel"):
        self.intel_dir = Path(intel_dir)

    def _latest_snapshot(self) -> Path | None:
        files = sorted(self.intel_dir.glob("news_snapshot_*.json"))
        return files[-1] if files else None

    def summarize(self, snapshot_path: str | None = None, max_len: int = 5) -> str:
        path = Path(snapshot_path) if snapshot_path else self._latest_snapshot()
        if not path or not path.exists():
            return "No recent market intelligence snapshot available."

        df = pd.read_json(path)
        if df.empty:
            return "No news data to summarize."

        # --- Sentiment overview ---
        avg_sent = df["sentiment"].mean(skipna=True)
        if abs(avg_sent) < 0.05:
            sent_text = "Neutral"
        elif avg_sent > 0:
            sent_text = "Mildly Positive"
        else:
            sent_text = "Mildly Negative"

        # --- Topic detection (macro / sector / finance / energy) ---
        text_all = " ".join(df["title"].fillna("").tolist()).lower()
        macro_triggers = ["fed", "inflation", "rates", "economy", "recession", "growth"]
        tech_triggers = ["apple", "microsoft", "nvidia", "ai", "google", "tesla"]
        energy_triggers = ["oil", "gas", "energy", "opec"]
        finance_triggers = ["bank", "goldman", "morgan", "jpmorgan", "credit", "yield"]

        topics = []
        for kw_group, label in [
            (macro_triggers, "macro and monetary policy"),
            (tech_triggers, "technology sector"),
            (energy_triggers, "energy sector"),
            (finance_triggers, "financial sector"),
        ]:
            if any(k in text_all for k in kw_group):
                topics.append(label)

        # --- Build sections ---
        date_str = datetime.now().strftime("%A, %B %d, %Y")
        header = f"DAILY MARKET BRIEF — {date_str}\n"
        divider = "=" * 90 + "\n"

        overview_parts = []
        if "macro and monetary policy" in topics:
            overview_parts.append("Macroeconomic headlines focused on central banks, inflation, and interest rates.")
        if "technology sector" in topics:
            overview_parts.append("Technology shares were active, with attention on AI, semiconductors, and key product news.")
        if "energy sector" in topics:
            overview_parts.append("Energy markets reflected movements in oil and gas prices and OPEC commentary.")
        if "financial sector" in topics:
            overview_parts.append("Financial coverage centered on bank earnings and shifts in bond yields.")
        if not overview_parts:
            overview_parts.append("Market coverage was mixed with no single dominant theme across sectors.")

        overview = " ".join(overview_parts)

        # --- Sentiment and source section ---
        sentiment_section = f"\nOverall Sentiment: {sent_text}  (average score: {avg_sent:.2f})\n"
        if "source" in df.columns:
            top_sources = df["source"].value_counts().head(3).index.tolist()
            if top_sources:
                sentiment_section += f"Primary Sources: {', '.join(top_sources)}\n"

        # --- Optional highlights (top 3 headlines) ---
        highlights = ""
        try:
            sample_headlines = df["title"].dropna().head(3).tolist()
            if sample_headlines:
                highlights = "\nKey Headlines:\n"
                for i, h in enumerate(sample_headlines, 1):
                    clean_h = h.strip().rstrip(".")
                    highlights += f"  {i}. {clean_h}.\n"
        except Exception:
            pass

        # --- Combine into final formatted summary ---
        summary = (
            header
            + divider
            + fill(overview, width=90)
            + "\n"
            + sentiment_section
            + highlights
            + divider
        )

        return summary