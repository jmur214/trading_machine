from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
import logging

log = logging.getLogger("governor")


# ----------------------------- Config ----------------------------- #

@dataclass
class GovernorConfig:
    """
    Configuration for the Strategy Governor (Engine D).

    Notes
    -----
    • All thresholds are *defense-first* defaults. Tune for your book.
    • rolling_window_days: metrics computed over the most recent N calendar days.
    • disable_sr_threshold: if rolling Sharpe < this, weight→0 (after warmup).
    • disable_mdd_threshold: if edge rolling MDD < this negative %, weight→0.
    • max_weight: global cap; useful if you later combine ML/meta-allocations.
    • ema_halflife_days: smooths weight updates to avoid flip-flopping.
    • warmup_days: don’t enforce kill-switches until we have enough data.
    • sr_weight_floor/sr_weight_ceil: SR→weight mapping clamp (soft scaling).
    """
    rolling_window_days: int = 90
    disable_sr_threshold: float = 0.0
    disable_mdd_threshold: float = -0.25   # -25% MDD kill-switch
    max_weight: float = 1.0

    ema_halflife_days: int = 15
    warmup_days: int = 45

    # map Sharpe to soft weight in [sr_weight_floor, 1.0]
    sr_weight_floor: float = 0.25
    sr_weight_ceil: float = 1.0

    # optional defenses
    min_trades_in_window: int = 10
    max_turnover_per_month: float = 100.0  # informational, not enforced by default
    penalize_negative_correlation: bool = False  # set True to downweight negatively corr edges


# ----------------------------- Governor ----------------------------- #

class StrategyGovernor:
    """
    Engine D: Governance & Meta-Allocation (non-ML MVP).

    Responsibilities
    ----------------
    • Ingest realized trades (with `edge` column) and/or daily snapshots.
    • Compute rolling, defense-first edge diagnostics (Sharpe, MDD, turnover, corr).
    • Produce stable edge weights in [0,1] with kill-switches and EMA smoothing.
    • Persist & load weights to/from JSON for continuity across sessions.

    How to use
    ----------
    >>> gov = StrategyGovernor(config_path="config/governor_settings.json",
    ...                        state_path="data/governor/edge_weights.json")
    >>> gov.update_from_trades(trades_df, snapshots_df)   # safe if either is None
    >>> live_weights = gov.get_edge_weights()
    >>> gov.save_weights()  # optional
    """

    def _normalize(self, w: Dict[str, float]) -> Dict[str, float]:
        """Soft normalize weights so their sum does not exceed 1.0."""
        try:
            total = float(sum(max(0.0, float(v)) for v in w.values()))
        except Exception:
            return dict(w)
        if total > 1.0 and total > 0:
            return {k: (max(0.0, float(v)) / total) for k, v in w.items()}
        # also clamp to [0,1]
        return {k: float(np.clip(v, 0.0, 1.0)) for k, v in w.items()}

    def normalize_weights(self) -> None:
        """
        Safeguard: Ensure internal weights sum to 1.0 (clamped in [0,1]).
        Call after any weight update to enforce proper normalization.
        """
        self._weights = self._normalize(self._weights)

    def _save_metrics(self, metrics: Dict[str, dict]) -> None:
        """Persist per-edge diagnostics next to weights, for dashboards/analytics."""
        try:
            metrics_path = self.state_path.parent / "edge_metrics.json"
            metrics_path.parent.mkdir(parents=True, exist_ok=True)
            with metrics_path.open("w") as f:
                json.dump({"metrics": metrics}, f, indent=2)
        except Exception as e:
            # Non-fatal
            log.debug(f"[Governor] Failed to save edge metrics: {e}")

    def __init__(self,
                 config_path: str | Path = "config/governor_settings.json",
                 state_path: str | Path = "data/governor/edge_weights.json") -> None:
        self.cfg = self._load_config(config_path)
        self.state_path = Path(state_path)
        self.state_path.parent.mkdir(parents=True, exist_ok=True)

        # persistent weights (EMA-smoothed)
        self._weights: Dict[str, float] = self._load_weights()

    # ----------------- public API ----------------- #

    def update_from_trades(
        self,
        trades: Optional[pd.DataFrame],
        snapshots: Optional[pd.DataFrame] = None
    ) -> None:
        """
        Update internal weights using most-recent data window.

        trades must contain:
          ['timestamp','edge','pnl'] where pnl is *realized* per-closure (FIFO acceptable).

        snapshots (optional, for corr-to-equity calc) should contain:
          ['timestamp','equity'] daily or bar-level. We auto-resample to daily.
        """
        if trades is None or trades.empty:
            return

        # sanitize
        df = trades.copy()
        if "timestamp" not in df.columns or "edge" not in df.columns:
            return
        df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
        df = df.dropna(subset=["timestamp"])
        if "pnl" not in df.columns:
            # If no realized pnl, nothing we can do defensively
            return

        # restrict to rolling window
        end = df["timestamp"].max().normalize()
        start = end - pd.Timedelta(days=int(self.cfg.rolling_window_days))
        dfw = df[(df["timestamp"] >= start) & (df["timestamp"] <= end)].copy()
        if dfw.empty:
            return

        # daily agg per edge
        dfw["date"] = dfw["timestamp"].dt.date
        daily_edge = (
            dfw.groupby(["edge", "date"], dropna=False)["pnl"].sum().reset_index()
        )
        if daily_edge.empty:
            return

        # overall daily strategy pnl for correlation
        daily_total = daily_edge.groupby("date")["pnl"].sum().rename("pnl_total").reset_index()

        # if snapshots provided, build daily returns; else use total daily pnl as proxy
        strat_daily_ret = None
        if snapshots is not None and not snapshots.empty and "equity" in snapshots.columns:
            snaps = snapshots.copy()
            snaps["timestamp"] = pd.to_datetime(snaps["timestamp"], errors="coerce")
            snaps = snaps.dropna(subset=["timestamp", "equity"])
            # daily equity last
            eq_daily = snaps.set_index("timestamp")["equity"].resample("1D").last().dropna()
            strat_daily_ret = eq_daily.pct_change().dropna()

        weights_new: Dict[str, float] = {}
        edge_metrics: Dict[str, dict] = {}
        for edge, sub in daily_edge.groupby("edge", dropna=False):
            edge_name = "Unknown" if pd.isna(edge) else str(edge)
            sub = sub.sort_values("date")

            # Basic defenses
            trade_count = (dfw["edge"] == edge).sum()
            if trade_count < self.cfg.min_trades_in_window:
                # Not enough data: keep previous weight but decay toward floor
                base = self._weights.get(edge_name, 1.0)
                weights_new[edge_name] = max(self.cfg.sr_weight_floor, 0.5 * base)
                continue

            # Build daily returns for this edge — we normalize by abs total to avoid runaway scaling
            # If you track per-edge capital, replace with true returns; pnl proxy works as a defense MVP.
            pnl_series = sub.set_index(pd.to_datetime(sub["date"]))["pnl"].astype(float)
            if pnl_series.abs().sum() == 0:
                sr = 0.0
            else:
                # pseudo-return: pnl / MAD(pnl) to scale; robust to outliers
                scale = pnl_series.abs().median()
                scale = scale if scale and np.isfinite(scale) else max(1.0, pnl_series.abs().mean())
                ret = pnl_series / float(scale)
                sr = ret.mean() / (ret.std() + 1e-12) * np.sqrt(252.0)

            # Rolling MDD on cumulative pnl
            cum = pnl_series.cumsum()
            roll_max = cum.cummax()
            dd = (cum - roll_max)
            # convert to *percentage-like* by scaling vs cum max magnitude if non-zero
            denom = roll_max.replace(0, np.nan).abs()
            dd_pct = (cum - roll_max) / denom
            mdd = float(dd_pct.min()) if np.isfinite(dd_pct.min()) else 0.0  # ≤ 0

            # correlation to strategy (optional)
            corr_penalty = 0.0
            if self.cfg.penalize_negative_correlation:
                if strat_daily_ret is not None:
                    # align dates
                    eg = pnl_series.index
                    st = strat_daily_ret.index
                    common = np.intersect1d(eg, st)
                    if len(common) > 10:
                        eg_ret = (pnl_series.loc[common] / (pnl_series.loc[common].abs().median() or 1.0)).fillna(0.0)
                        st_ret = strat_daily_ret.loc[common].fillna(0.0)
                        c = np.corrcoef(eg_ret.values, st_ret.values)[0, 1]
                        if np.isfinite(c) and c < 0:
                            corr_penalty = min(0.25, abs(c))  # up to 25% penalty for strong negative corr

            # collect diagnostics for this edge
            edge_metrics[edge_name] = {
                "trade_count": int(trade_count),
                "sr": float(sr),
                "mdd": float(mdd),
                "corr_penalty": float(corr_penalty),
            }

            # soft map SR→weight in [floor, 1]
            if sr <= self.cfg.disable_sr_threshold or mdd <= self.cfg.disable_mdd_threshold:
                proposed = 0.0
            else:
                # linearly map SR∈[0,1] to [floor,1], clamp SR at 1.0 on the upside
                sr_clamped = float(np.clip(sr, 0.0, 1.0))
                proposed = self.cfg.sr_weight_floor + (self.cfg.sr_weight_ceil - self.cfg.sr_weight_floor) * sr_clamped

                # apply corr penalty
                if corr_penalty > 0:
                    proposed *= (1.0 - corr_penalty)

            # warmup: avoid hard zeros too early
            # Warmup period measured on the actual filtered window
            try:
                total_days_covered = int((dfw["timestamp"].max().normalize() - dfw["timestamp"].min().normalize()).days)
            except Exception:
                total_days_covered = int(self.cfg.rolling_window_days)
            if total_days_covered < self.cfg.warmup_days and proposed == 0.0:
                proposed = max(self.cfg.sr_weight_floor, 0.5)

            weights_new[edge_name] = float(np.clip(proposed, 0.0, self.cfg.max_weight))

        # EMA smoothing vs previous weights, then soft normalization
        merged = self._ema_merge(self._weights, weights_new, halflife_days=self.cfg.ema_halflife_days)
        self._weights = self._normalize(merged)
        self.normalize_weights()

        # persist diagnostics and log
        try:
            self._save_metrics(edge_metrics)
        except Exception:
            pass
        try:
            log.info(f"[Governor] Updated weights: {self._weights}")
        except Exception:
            pass

    def get_edge_weights(self) -> Dict[str, float]:
        """Return the current smoothed weights for edges."""
        return dict(self._weights)

    def save_weights(self) -> None:
        """Persist weights to JSON (data/governor/edge_weights.json by default)."""
        out = {"weights": self._weights}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w") as f:
            json.dump(out, f, indent=2)

    def merge_evaluator_recommendations(self, rec_path: str | Path = "data/research/edge_recommendations.json") -> None:
        """
        Optionally blend in evaluator-produced edge weights (e.g., from research runs).
        The file format is expected to be a JSON with a top-level key `recommended_weights` mapping
        edge name -> weight in [0,1]. Missing file is a no-op.
        """
        p = Path(rec_path)
        if not p.exists():
            return
        try:
            blob = json.loads(p.read_text())
            recs = blob.get("recommended_weights", {})
            # ensure numeric floats and sensible range
            recs = {str(k): float(np.clip(v, 0.0, 1.0)) for k, v in recs.items()}
            merged = self._ema_merge(self._weights, recs, halflife_days=self.cfg.ema_halflife_days)
            self._weights = self._normalize(merged)
            self.normalize_weights()
            self.save_weights()
            log.info(f"[Governor] Merged evaluator recommendations from {p} -> {self._weights}")
        except Exception as e:
            log.debug(f"[Governor] Failed to merge evaluator recommendations: {e}")

    # ----------------- private helpers ----------------- #

    def _ema_merge(self, old: Dict[str, float], new: Dict[str, float], halflife_days: int) -> Dict[str, float]:
        if halflife_days <= 0:
            return dict(new)
        # Convert halflife to alpha (EMA): alpha = 1 - 0.5**(1/halflife)
        alpha = 1.0 - 0.5 ** (1.0 / max(1.0, float(halflife_days)))
        out: Dict[str, float] = {}
        keys = set(old) | set(new)
        for k in keys:
            prev = float(old.get(k, 1.0))
            nxt = float(new.get(k, prev))
            out[k] = (1.0 - alpha) * prev + alpha * nxt
        return out

    def _load_config(self, p: str | Path) -> GovernorConfig:
        path = Path(p)
        if not path.exists():
            # sensible defense-first defaults
            return GovernorConfig()
        try:
            cfg = json.loads(path.read_text())
            return GovernorConfig(**{k: v for k, v in cfg.items() if k in GovernorConfig.__annotations__})
        except Exception:
            return GovernorConfig()

    def _load_weights(self) -> Dict[str, float]:
        if not self.state_path.exists():
            return {}
        try:
            blob = json.loads(self.state_path.read_text())
            w = blob.get("weights", {})
            return {str(k): float(v) for k, v in w.items()}
        except Exception:
            return {}