# research/edge_db.py
from __future__ import annotations
from pathlib import Path
import pandas as pd
from datetime import datetime
import json
from debug_config import is_debug_enabled, is_info_enabled


class EdgeResearchDB:
    """
    Global research database for storing and ranking edge backtest results.

    Features:
    ----------
    • Appends new harness results from CSVs into a unified Parquet database.
    • Computes averaged metrics per (edge, combo_idx) across walk-forward slices.
    • Provides composite score ranking based on Sharpe, CAGR, returns, and drawdown.
    • Exposes a helper to fetch the best combo for a given edge (for promotion).
    """

    def __init__(self, db_path: str = "data/research/edge_results.parquet"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

        # Load if exists, otherwise empty
        if self.db_path.exists() and self.db_path.stat().st_size > 0:
            try:
                self.df = pd.read_parquet(self.db_path)
                if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
                    print(f"[EDGE_DB][INFO] Loaded database from {self.db_path}")
            except Exception:
                try:
                    self.df = pd.read_csv(self.db_path.with_suffix(".csv"))
                    if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
                        print(f"[EDGE_DB][INFO] Loaded CSV database from {self.db_path.with_suffix('.csv')}")
                except Exception:
                    self.df = pd.DataFrame()
                    if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
                        print(f"[EDGE_DB][WARN] Failed to load database, starting with empty DataFrame")
        else:
            self.df = pd.DataFrame()
            if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
                print(f"[EDGE_DB][INFO] Database file not found or empty, starting with empty DataFrame")

    # ------------------------------------------------------------------ #
    # Private Helpers
    # ------------------------------------------------------------------ #

    def _to_native(self, value):
        """Convert numpy and pandas datatypes to Python-native types for JSON safety."""
        if isinstance(value, (pd.Timestamp, datetime)):
            return value.isoformat()
        elif hasattr(value, "item"):
            try:
                return value.item()
            except Exception:
                return value
        elif isinstance(value, dict):
            return {k: self._to_native(v) for k, v in value.items()}
        elif isinstance(value, (list, tuple)):
            return [self._to_native(v) for v in value]
        return value

    def _clean_numeric(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Coerce numeric metrics to float and fill NaNs with 0.0.
        """
        numeric_cols = ["sharpe", "cagr_pct", "total_return_pct", "max_drawdown_pct", "win_rate_pct", "trades"]
        for c in numeric_cols:
            if c in df.columns:
                df[c] = pd.to_numeric(df[c], errors="coerce").replace([float("inf"), float("-inf")], 0.0)
                missing_count = df[c].isna().sum()
                if missing_count > 0 and (is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB")):
                    print(f"[EDGE_DB][DEBUG] Column '{c}' has {missing_count} missing/NaN values after coercion.")
                df[c] = df[c].fillna(0.0)
                if c == "trades":
                    df[c] = df[c].astype(int)
        if is_debug_enabled("EDGE_DB"):
            print(f"[EDGE_DB][DEBUG] Completed numeric cleaning on columns: {numeric_cols}")
        return df

    # ------------------------------------------------------------------ #
    # Core Methods
    # ------------------------------------------------------------------ #

    def append_run(self, results_csv: str) -> None:
        """
        Appends a single research run (from edge_harness.py) into the global DB.
        Adds timestamp column for auditability.
        """
        new = pd.read_csv(results_csv)
        new["timestamp"] = datetime.utcnow().isoformat()
        new["source_run"] = Path(results_csv).stem

        # Ensure combo_idx column exists for grouping later
        if "combo_idx" not in new.columns:
            new["combo_idx"] = 0

        if new.empty or not any(new.columns):
            if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
                print(f"[EDGE_DB][INFO] Skipping append from {results_csv} due to empty or invalid DataFrame.")
            return

        # Filter out empty or all-NaN frames before concatenation
        frames = [f for f in [self.df, new] if not f.empty and not f.isna().all().all()]
        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            frame_sizes = [len(f) for f in [self.df, new]]
            print(f"[EDGE_DB][DEBUG] Concatenating frames with row counts: {frame_sizes}")
        if frames:
            self.df = pd.concat(frames, ignore_index=True)
        else:
            self.df = pd.DataFrame()
        self.df.drop_duplicates(subset=["edge", "combo_idx", "wf_idx"], inplace=True)
        self.save()
        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            key_cols = ["edge", "combo_idx", "wf_idx", "sharpe", "cagr_pct", "total_return_pct"]
            sample = new[key_cols].head(3).to_dict(orient="records") if all(col in new.columns for col in key_cols) else None
            print(f"[EDGE_DB][INFO] Appended {len(new)} rows from {results_csv}. Sample: {sample}")

    def save(self) -> None:
        """Persist to Parquet; fallback to CSV if Parquet engine unavailable."""
        df_to_save = self.df.astype(object)  # convert to native python types to avoid dtype issues
        try:
            df_to_save.to_parquet(self.db_path, index=False)
        except Exception:
            csv_path = self.db_path.with_suffix(".csv")
            df_to_save.to_csv(csv_path, index=False)
        json_path = self.db_path.with_suffix(".json")
        json_path.write_text(json.dumps(self._to_native(df_to_save.to_dict(orient="records")), indent=2))
        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            print(f"[EDGE_DB][DEBUG] Saved database to {self.db_path}")

    # ------------------------------------------------------------------ #
    # Ranking + Selection
    # ------------------------------------------------------------------ #

    def rank_edges(self, min_wf: int = 2) -> pd.DataFrame:
        """
        Rank all edges (and their parameter combos) by averaged metrics.
        Returns a DataFrame with columns:
        ['edge','combo_idx','avg_sharpe','avg_cagr','avg_return','avg_mdd','avg_winrate','score']
        """
        if self.df.empty:
            if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
                print("[EDGE_DB][INFO] No data to rank.")
            return pd.DataFrame()

        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            print(f"[EDGE_DB][INFO] Starting ranking with {len(self.df)} rows in database.")

        df = self.df.copy()
        df = self._clean_numeric(df)

        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            print(f"[EDGE_DB][INFO] After cleaning, {len(df)} rows remain for ranking.")

        # Group by edge + combo
        grouped = (
            df.groupby(["edge", "combo_idx"], dropna=False)
            .agg(
                n_wf=("wf_idx", "nunique"),
                avg_sharpe=("sharpe", "mean"),
                avg_cagr=("cagr_pct", "mean"),
                avg_return=("total_return_pct", "mean"),
                avg_mdd=("max_drawdown_pct", "mean"),
                avg_winrate=("win_rate_pct", "mean"),
                trades=("trades", "sum"),
            )
            .reset_index()
        )

        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            print(f"[EDGE_DB][INFO] Grouped into {len(grouped)} edge/combo combos.")

        # Drop combos where all primary metrics are NaN
        primary_metrics = ["avg_sharpe", "avg_cagr", "avg_return", "avg_mdd"]
        before_drop = len(grouped)
        grouped = grouped.dropna(how="all", subset=primary_metrics)
        dropped = before_drop - len(grouped)
        if is_debug_enabled("EDGE_DB"):
            print(f"[EDGE_DB][DEBUG] Dropped {dropped} combos with all primary metrics NaN.")

        # Require sufficient walk-forward slices
        grouped = grouped[grouped["n_wf"] >= int(min_wf)].copy()
        if grouped.empty:
            if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
                print("[EDGE_DB][INFO] No combos meet minimum walk-forward slices requirement.")
            return grouped

        # Ensure numeric columns are float
        for col in primary_metrics + ["avg_winrate", "trades", "n_wf"]:
            if col in grouped.columns:
                grouped[col] = grouped[col].astype(float)

        # Z-score normalization for metrics before scoring
        norm_summaries = []
        for col in ["avg_sharpe", "avg_cagr", "avg_return", "avg_mdd"]:
            std_val = grouped[col].std()
            mean_val = grouped[col].mean()
            if std_val == 0 or pd.isna(std_val):
                grouped[col + "_z"] = 0.0
                norm_summaries.append(f"{col}: std=0 or NaN, z-scores set to 0")
            else:
                grouped[col + "_z"] = (grouped[col] - mean_val) / (std_val + 1e-9)
                norm_summaries.append(f"{col}: mean={mean_val:.4f}, std={std_val:.4f}")
        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            print(f"[EDGE_DB][INFO] Normalization details: {', '.join(norm_summaries)}")

        grouped["score"] = (
            0.4 * grouped["avg_sharpe_z"] +
            0.3 * grouped["avg_cagr_z"] +
            0.2 * grouped["avg_return_z"] -
            0.1 * grouped["avg_mdd_z"].abs()
        )

        # Fill NaNs in score with -9999 to sort last
        grouped["score"] = grouped["score"].fillna(-9999)

        grouped = grouped.sort_values(
            ["score", "avg_sharpe", "avg_return"],
            ascending=[False, False, False]
        ).reset_index(drop=True)

        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            print(f"[EDGE_DB][INFO] Computed rankings for {len(grouped)} combos")

        return grouped

    def top_combo_for_edge(self, edge_name: str, min_wf: int = 2) -> dict | None:
        """
        Returns the best-performing parameter combo dict for the given edge.
        Used by the promoter to auto-update edge_config.json.
        """
        ranked = self.rank_edges(min_wf=min_wf)
        if ranked.empty:
            return None

        sub = ranked[ranked["edge"] == edge_name]
        if sub.empty:
            return None

        result = sub.iloc[0].to_dict()
        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            result_summary = {k: result[k] for k in ["combo_idx", "score"] if k in result}
            print(f"[EDGE_DB][INFO] Top combo for edge '{edge_name}': {result_summary}")

        return result

    # ------------------------------------------------------------------ #
    # Convenience Utilities
    # ------------------------------------------------------------------ #

    def export_json(self, out_path: str = "data/research/edge_rankings.json") -> Path:
        """
        Export current ranking to JSON for dashboards or governor introspection.
        """
        ranked = self.rank_edges()
        if ranked.empty:
            if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
                print("[EDGE_DB][INFO] No data to export.")
            return Path(out_path)

        payload = {
            "generated_at": datetime.utcnow().isoformat(),
            "count": len(ranked),
            "edges": ranked.to_dict(orient="records"),
        }

        out_p = Path(out_path)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(self._to_native(payload), indent=2))
        if is_debug_enabled("EDGE_DB") or is_info_enabled("EDGE_DB"):
            print(f"[EDGE_DB][INFO] Exported rankings to {out_p}")
        return out_p