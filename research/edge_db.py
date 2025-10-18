# research/edge_db.py
from pathlib import Path
import pandas as pd
import json
from datetime import datetime

class EdgeResearchDB:
    def __init__(self, db_path="data/research/edge_results.parquet"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.df = pd.read_parquet(self.db_path) if self.db_path.exists() else pd.DataFrame()

    def append_run(self, results_csv: str):
        new = pd.read_csv(results_csv)
        new["timestamp"] = datetime.utcnow().isoformat()
        self.df = pd.concat([self.df, new], ignore_index=True)
        self.save()

    def save(self):
        self.df.to_parquet(self.db_path, index=False)

    def rank_edges(self):
        if self.df.empty:
            return pd.DataFrame()
        grouped = (
            self.df.groupby("edge")[["sharpe", "cagr_pct", "max_drawdown_pct"]]
            .mean()
            .reset_index()
        )
        grouped["score"] = (
            0.5 * grouped["sharpe"].fillna(0)
            + 0.3 * (grouped["cagr_pct"].fillna(0) / 10)
            - 0.2 * grouped["max_drawdown_pct"].abs()
        )
        grouped = grouped.sort_values("score", ascending=False)
        return grouped