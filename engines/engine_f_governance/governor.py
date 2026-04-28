from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
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

    # regime-conditional governance
    regime_conditional_enabled: bool = True
    min_trades_per_regime: int = 8
    regime_weight_blend_alpha: float = 0.7  # 0.7 = 70% regime weight, 30% global

    # learned edge affinity (signal_processor 0.3-1.5x multiplier per category)
    learned_affinity_enabled: bool = True

    # autonomous lifecycle transitions (active → paused → retired, reversible)
    # Default False (defense-first): requires explicit opt-in before edges
    # start retiring themselves. See engines/engine_f_governance/lifecycle_manager.py
    lifecycle_enabled: bool = False
    lifecycle_retirement_margin: float = 0.3  # edge_sharpe must undershoot benchmark by this
    lifecycle_min_trades: int = 100
    lifecycle_min_days: int = 90
    # Read-only: evaluate gates but do not write to registry/history CSV.
    # Set True for OOS backtesting so re-runs of the same window give the same result.
    lifecycle_readonly: bool = False

    # autonomous allocation evaluation (Phase 8)
    allocation_evaluation_enabled: bool = True
    auto_apply_allocation: bool = False


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
        """Clamp each weight independently to [0, 1].

        Weights are independent quality scores (not portfolio allocations),
        so they should NOT be forced to sum to 1.0.  The old sum-to-1
        normalization compressed every weight when many edges existed,
        making the best edge indistinguishable from mediocre ones.
        """
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

        # Regime-conditional performance tracker
        from engines.engine_f_governance.regime_tracker import RegimePerformanceTracker
        self.regime_tracker = RegimePerformanceTracker(
            min_trades=getattr(self.cfg, 'min_trades_per_regime', 8)
        )
        regime_perf_path = self.state_path.parent / "regime_edge_performance.json"
        self.regime_tracker.load(regime_perf_path)

        # Cached regime-conditional weights
        self._regime_weights: Dict[str, Dict[str, float]] = {}
        self._regime_blend_alpha: float = getattr(self.cfg, 'regime_weight_blend_alpha', 0.7)

        # Prime regime weights from the loaded tracker so that regime-conditional
        # blending works during THIS run, not just the next one. Without this,
        # _regime_weights only gets populated inside update_from_trades (end of
        # run) and get_edge_weights falls back to global weights for the entire
        # trade-generation pass.
        if getattr(self.cfg, 'regime_conditional_enabled', True):
            self._rebuild_regime_weights_from_tracker(self._weights.keys())

    # ----------------- public API ----------------- #

    def _rebuild_regime_weights_from_tracker(self, edge_names) -> None:
        """Populate self._regime_weights from self.regime_tracker for every
        regime the tracker has data on. Uses `edge_names` as the edge set to
        evaluate (typically the keys of self._weights)."""
        edge_names = list(edge_names)
        self._regime_weights = {}
        for regime_label in sorted(set(self.regime_tracker._data.keys()) - {"_global"}):
            regime_w = {}
            for edge_name in edge_names:
                rw = self.regime_tracker.get_regime_weight(
                    edge_name, regime_label,
                    sr_floor=self.cfg.sr_weight_floor,
                    sr_ceil=self.cfg.sr_weight_ceil,
                    disable_sr_threshold=self.cfg.disable_sr_threshold,
                    mdd_threshold=self.cfg.disable_mdd_threshold,
                )
                if rw is not None:
                    regime_w[edge_name] = rw
            if regime_w:
                self._regime_weights[regime_label] = regime_w

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
                
                # Sortino Ratio (Penalize only downside volatility)
                # Downside Deviation: std of returns < 0
                downside = ret[ret < 0]
                if downside.empty or downside.std() == 0:
                    # Ideal case: no downside. Cap sortino at a high number to avoid inf
                    sortino = 10.0
                else:
                    sortino = ret.mean() / (downside.std() + 1e-12) * np.sqrt(252.0)

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
                        if np.isfinite(c):
                            # Bensdorp/Parrondo Logic:
                            # High Positive Correlation (>0.7) -> Redundant (Penalty)
                            # Negative Correlation (<0.0) -> Hedge (Bonus implied by NOT penalizing)
                            
                            # We implement "Uncorrelation Bonus" by adjusting the penalty.
                            # If we use a scalar 'corr_penalty', we can make it negative to boost weight.
                            
                            if c > 0.7:
                                # Penalize redundancy
                                corr_penalty = (c - 0.7) * 0.5  # up to 0.15 penalty
                            elif c < 0.0:
                                # Reward hedge (Negative penalty = Bonus)
                                # Boost up to 20% for strong inverse correlation
                                corr_penalty = -min(0.20, abs(c) * 0.5)
                            else:
                                corr_penalty = 0.0

            # Current drawdown (for MDD soft penalty logic)
            current_dd = float(dd_pct.iloc[-1]) if not dd_pct.empty and np.isfinite(dd_pct.iloc[-1]) else 0.0

            # collect diagnostics for this edge
            edge_metrics[edge_name] = {
                "trade_count": int(trade_count),
                "sr": float(sr),
                "sortino": float(sortino),
                "mdd": float(mdd),
                "current_dd": float(current_dd),
                "corr_penalty": float(corr_penalty),
            }

            # --- Weight computation: SR → base weight, MDD → soft penalty ---
            # Kill-switch: negative Sharpe → hard zero (edge is losing on average)
            if sr <= self.cfg.disable_sr_threshold:
                proposed = 0.0
            else:
                # linearly map SR∈[0,1] to [floor,1], clamp SR at 1.0 on the upside
                sr_clamped = float(np.clip(sr, 0.0, 1.0))
                proposed = self.cfg.sr_weight_floor + (self.cfg.sr_weight_ceil - self.cfg.sr_weight_floor) * sr_clamped

                # MDD: soft penalty instead of hard zero.
                # Distinguish current drawdown (still underwater) from historical
                # peak drawdown (may have recovered).
                if mdd <= self.cfg.disable_mdd_threshold:
                    if current_dd <= self.cfg.disable_mdd_threshold:
                        # Currently underwater past threshold — heavy penalty
                        proposed *= 0.25
                    else:
                        # Recovered from historical drawdown — proportional penalty
                        overshoot = abs(mdd) / abs(self.cfg.disable_mdd_threshold)
                        mdd_factor = max(0.3, 1.0 / overshoot)
                        proposed *= mdd_factor

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

        # Feed regime tracker with realized-PnL rows only — entries have NaN PnL
        # and recording them as 0.0 floods the Welford stats with fake zero-PnL
        # trades, destroying the mean/variance signal and suppressing Sharpe.
        regime_enabled = getattr(self.cfg, 'regime_conditional_enabled', True)
        if regime_enabled and "regime_label" in df.columns:
            for _, row in df.iterrows():
                pnl_raw = row.get("pnl")
                if pd.isna(pnl_raw):
                    continue
                edge_name = "Unknown" if pd.isna(row["edge"]) else str(row["edge"])
                pnl_val = float(pnl_raw)
                regime_label = str(row["regime_label"]) if pd.notna(row.get("regime_label")) else "unknown"
                if regime_label and regime_label != "unknown":
                    trigger = str(row["trigger"]) if "trigger" in row and pd.notna(row.get("trigger")) else None
                    self.regime_tracker.record_trade(edge_name, pnl_val, regime_label, trigger=trigger)

            # Build regime-conditional weights for each known regime
            self._rebuild_regime_weights_from_tracker(weights_new.keys())

        # persist diagnostics and log
        try:
            self._save_metrics(edge_metrics)
        except Exception:
            pass
        try:
            log.info(f"[Governor] Updated weights: {self._weights}")
        except Exception:
            pass

    def get_edge_weights(self, regime_meta: Optional[dict] = None) -> Dict[str, float]:
        """Return edge weights, optionally regime-conditional.

        If regime_meta is provided and regime-conditional data is available,
        returns blended weights: alpha * regime_weight + (1-alpha) * global_weight.
        Falls back to global weights when regime data is sparse or unavailable.
        """
        if regime_meta is None or not self._regime_weights:
            return dict(self._weights)

        # Extract regime label
        macro = regime_meta.get("macro_regime")
        if isinstance(macro, dict):
            label = macro.get("label", "")
        elif isinstance(macro, str):
            label = macro
        else:
            return dict(self._weights)

        regime_w = self._regime_weights.get(label)
        if not regime_w:
            return dict(self._weights)

        # Blend: alpha * regime + (1-alpha) * global
        # Kill-switch passthrough: a regime_val of exactly 0.0 means the tracker
        # decided this edge is unprofitable in this regime (Sharpe ≤ disable
        # threshold). Don't dilute that with global weight — respect the kill.
        alpha = self._regime_blend_alpha
        blended = {}
        for edge_name in sorted(set(self._weights) | set(regime_w)):
            global_val = self._weights.get(edge_name, 1.0)
            regime_val = regime_w.get(edge_name)
            if regime_val is None:
                blended[edge_name] = global_val
            elif regime_val <= 1e-9:
                blended[edge_name] = 0.0
            else:
                blended[edge_name] = alpha * regime_val + (1.0 - alpha) * global_val
        return blended

    def set_edge_weights(self, weights: Dict[str, float]) -> None:
        """Directly set edge weights (e.g. after recency decay scaling)."""
        self._weights = {str(k): float(v) for k, v in weights.items()}

    def update_from_trade_log(
        self,
        trade_log_path: str | Path = "data/trade_logs/trades.csv",
        snapshot_path: str | Path | None = "data/trade_logs/snapshots.csv",
    ) -> None:
        """
        End-to-end edge feedback loop: load trade/snapshot CSVs, update weights,
        apply recency decay, merge evaluator recommendations, persist, and log history.

        This is the canonical entry point for post-run edge reweighting.
        """
        trade_log_path = Path(trade_log_path)
        snapshot_path = Path(snapshot_path) if snapshot_path else None

        if not trade_log_path.exists() or trade_log_path.stat().st_size == 0:
            log.info("[Governor] No trades found — skipping weight update.")
            return

        try:
            trades = pd.read_csv(trade_log_path)
            log.info(f"[Governor] Loaded {len(trades)} trades from {trade_log_path}")
        except Exception as e:
            log.info(f"[Governor] Failed to read trade log: {e}")
            return

        snapshots = None
        if snapshot_path and snapshot_path.exists() and snapshot_path.stat().st_size > 0:
            try:
                snapshots = pd.read_csv(snapshot_path)
            except Exception:
                pass

        old_weights = self.get_edge_weights()

        self.update_from_trades(trades, snapshots)

        # Recency decay: downweight stale edges
        if "timestamp" in trades.columns:
            try:
                if not pd.api.types.is_datetime64_any_dtype(trades["timestamp"]):
                    trades["timestamp"] = pd.to_datetime(trades["timestamp"], errors="coerce", utc=True)
                last_trade_time = trades["timestamp"].max()
                if pd.notna(last_trade_time):
                    if isinstance(last_trade_time, pd.Timestamp):
                        last_trade_time = last_trade_time.to_pydatetime()
                    if last_trade_time.tzinfo is None:
                        last_trade_time = last_trade_time.replace(tzinfo=timezone.utc)
                    else:
                        last_trade_time = last_trade_time.astimezone(timezone.utc)
                    days_since = (datetime.now(timezone.utc) - last_trade_time).days
                    decay = np.exp(-days_since / 180)
                    log.info(f"[Governor] Recency decay={decay:.4f} ({days_since} days since last trade)")
                    updated = self.get_edge_weights()
                    if updated:
                        self.set_edge_weights({e: w * decay for e, w in updated.items()})
            except Exception as e:
                log.info(f"[Governor] Could not apply recency decay: {e}")

        self.save_weights()

        # Merge evaluator recommendations
        try:
            self.merge_evaluator_recommendations()
        except Exception:
            pass

        # --- Allocation evaluation (Phase 8: autonomous portfolio tuning) ---
        alloc_eval_enabled = getattr(self.cfg, 'allocation_evaluation_enabled', False)
        if alloc_eval_enabled:
            try:
                from engines.engine_c_portfolio.allocation_evaluator import AllocationEvaluator
                evaluator = AllocationEvaluator()
                evaluator.evaluate(trades, snapshot_df=snapshots)
                recs = evaluator.recommend()
                if recs:
                    evaluator.save_recommendations()
                    log.info(f"[Governor] Allocation evaluator: {len(recs)} recommendation(s) saved")
                    for label, rec in recs.items():
                        log.info(f"   {label}: score={rec.get('score', 0):.3f} params={rec.get('params', {})}")

                    # Auto-apply to portfolio policy config if enabled
                    auto_apply = getattr(self.cfg, 'auto_apply_allocation', False)
                    if auto_apply and "_global" in recs:
                        self._apply_allocation_recommendation(recs["_global"])
            except Exception as e:
                log.info(f"[Governor] Allocation evaluation failed: {e}")

        new_weights = self.get_edge_weights()
        if new_weights:
            log.info("[Governor] Updated edge weights:")
            for edge, w in new_weights.items():
                log.info(f"   {edge:<25s}: {w:.3f}")

        # Gather metrics and write history
        metrics = {}
        try:
            if not trades.empty and "pnl" in trades.columns:
                pnl = trades["pnl"].dropna()
                if not pnl.empty:
                    sharpe = pnl.mean() / (pnl.std() + 1e-9) * (252**0.5) if pnl.std() > 0 else None
                    cum_pnl = pnl.cumsum()
                    max_dd = (cum_pnl.cummax() - cum_pnl).max() if not cum_pnl.empty else None
                    metrics = {"sharpe": sharpe, "max_drawdown": max_dd, "num_trades": len(trades)}
        except Exception:
            pass

        self._write_feedback_history(old_weights, new_weights, metrics)

        # --- Autonomous lifecycle transitions (Phase α) ---
        self.evaluate_lifecycle(trades)

    def evaluate_lifecycle(self, trades) -> None:
        """Run lifecycle gates on active/paused edges using the provided trade
        DataFrame. No-op if `lifecycle_enabled` is False. Callable from both
        the backtest post-run path and the paper/live `update_from_trade_log`
        path so autonomous retirement/pause/revival fires in every mode.

        Wrapped in try/except — lifecycle evaluation must never break the
        feedback loop upstream. Failures are logged and swallowed.
        """
        if not getattr(self.cfg, 'lifecycle_enabled', False):
            return
        try:
            from engines.engine_f_governance.lifecycle_manager import (
                LifecycleConfig, LifecycleManager,
            )
            from core.benchmark import compute_benchmark_metrics

            # Resolve benchmark window from the trade log
            bench_sharpe = 0.0
            if trades is not None and not trades.empty and "timestamp" in trades.columns:
                ts = pd.to_datetime(trades["timestamp"], errors="coerce", utc=True)
                ts = ts.dropna()
                if not ts.empty:
                    start_iso = ts.min().date().isoformat()
                    end_iso = ts.max().date().isoformat()
                    bm = compute_benchmark_metrics(start_iso, end_iso)
                    bench_sharpe = bm.sharpe

            lcfg = LifecycleConfig(
                enabled=True,
                retirement_min_trades=int(getattr(self.cfg, 'lifecycle_min_trades', 100)),
                retirement_min_days=int(getattr(self.cfg, 'lifecycle_min_days', 90)),
                retirement_margin=float(getattr(self.cfg, 'lifecycle_retirement_margin', 0.3)),
                readonly=bool(getattr(self.cfg, 'lifecycle_readonly', False)),
            )
            registry_path = self.state_path.parent / "edges.yml"
            history_path = self.state_path.parent / "lifecycle_history.csv"
            lcm = LifecycleManager(
                cfg=lcfg,
                registry_path=registry_path,
                history_path=history_path,
            )
            events = lcm.evaluate(trades, benchmark_sharpe=bench_sharpe)
            if events:
                log.info(f"[Governor] Lifecycle fired {len(events)} transition(s)")
        except Exception as e:
            log.warning(f"[Governor] Lifecycle evaluation failed: {e}")

    def _apply_allocation_recommendation(self, rec: dict) -> None:
        """Write recommended allocation params to portfolio policy config."""
        config_path = Path("config/portfolio_policy.json")
        try:
            existing = {}
            if config_path.exists():
                with config_path.open() as f:
                    existing = json.load(f)

            params = rec.get("params", {})
            for key in ("mode", "max_weight", "target_volatility", "rebalance_threshold"):
                if key in params:
                    existing[key] = params[key]

            config_path.parent.mkdir(parents=True, exist_ok=True)
            with config_path.open("w") as f:
                json.dump(existing, f, indent=2)
            log.info(f"[Governor] Auto-applied allocation recommendation to {config_path}")
        except Exception as e:
            log.info(f"[Governor] Failed to auto-apply allocation config: {e}")

    def _write_feedback_history(
        self,
        old_weights: dict,
        new_weights: dict,
        metrics: dict,
        history_log_path: str | Path = "data/governor/feedback_history.log",
    ) -> None:
        """Append a structured log entry of the feedback run."""
        path = Path(history_log_path)
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
            "old_weights": old_weights or {},
            "new_weights": new_weights or {},
            "metrics": metrics or {},
        }
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception as e:
            log.debug(f"[Governor] Failed to write feedback history: {e}")

    def save_weights(self) -> None:
        """Persist weights to JSON (data/governor/edge_weights.json by default)."""
        out = {"weights": self._weights}
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with self.state_path.open("w") as f:
            json.dump(out, f, indent=2)
        # Also persist regime tracker
        try:
            regime_perf_path = self.state_path.parent / "regime_edge_performance.json"
            self.regime_tracker.save(regime_perf_path)
        except Exception as e:
            log.debug(f"[Governor] Failed to save regime tracker: {e}")

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
        keys = sorted(set(old) | set(new))
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