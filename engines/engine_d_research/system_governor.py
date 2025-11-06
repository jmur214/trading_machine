from __future__ import annotations

"""
System Governor Orchestrator
============================
Coordinates the Trading Machine "intelligence loop":

1) Detects changes in trade logs and portfolio snapshots
2) Computes/refreshes edge metrics (via analytics.edge_feedback if available; otherwise local fallback)
3) Updates governor edge weights (via engines.engine_d_research.governor if available; otherwise local merge)
4) Persists:
   - data/governor/edge_metrics.json
   - data/governor/edge_weights.json
   - data/governor/edge_weights_history.csv (append-only)
   - data/governor/system_state.json (dashboard-friendly cache)

CLI:
    python -m engines.engine_d_research.system_governor --once
    python -m engines.engine_d_research.system_governor --watch --interval 60

This module is deliberately robust and degrades gracefully if certain
dependencies are unavailable. It prefers the project's native edge_feedback
and governor modules when importable.

Author: Trading Machine (System Governor)
"""

import json
import time
import hashlib
import logging
import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict, Any, Tuple

# Soft deps (pandas/numpy used in local fallback computations)
try:
    import pandas as pd
    import numpy as np
except Exception:  # pragma: no cover
    pd = None
    np = None

# Prefer native project modules when available
_EDGE_FB = None
_GOVERNOR_MOD = None
try:
    from analytics import edge_feedback as _EDGE_FB  # type: ignore
except Exception:
    _EDGE_FB = None

try:
    from engines.engine_d_research import governor as _GOVERNOR_MOD  # type: ignore
except Exception:
    _GOVERNOR_MOD = None


# ---------- Paths & Defaults ----------
DATA_DIR = Path("data")
TRADE_LOGS_DIR = DATA_DIR / "trade_logs"
BT_TRADES = TRADE_LOGS_DIR / "trades.csv"
BT_SNAPSHOTS = TRADE_LOGS_DIR / "portfolio_snapshots.csv"

PAPER_DIR = TRADE_LOGS_DIR / "paper"
PAPER_TRADES = PAPER_DIR / "trades.csv"
PAPER_SNAPSHOTS = PAPER_DIR / "portfolio_snapshots.csv"

GOV_DIR = DATA_DIR / "governor"
GOV_DIR.mkdir(parents=True, exist_ok=True)

EDGE_METRICS_PATH = GOV_DIR / "edge_metrics.json"
EDGE_WEIGHTS_PATH = GOV_DIR / "edge_weights.json"
EDGE_WEIGHTS_HISTORY = GOV_DIR / "edge_weights_history.csv"
SYSTEM_STATE_PATH = GOV_DIR / "system_state.json"

LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = LOGS_DIR / "system_governor.log"


# ---------- Logging ----------
logger = logging.getLogger("system_governor")
logger.setLevel(logging.INFO)
if not logger.handlers:
    _fh = logging.FileHandler(LOG_PATH)
    _fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(_fh)
    _sh = logging.StreamHandler()
    _sh.setFormatter(logging.Formatter("%(levelname)s | %(message)s"))
    logger.addHandler(_sh)


# ---------- Helpers ----------
def _file_hash(path: Path) -> Optional[str]:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return None
        h = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(65536), b""):
                h.update(chunk)
        return h.hexdigest()
    except Exception as e:
        logger.warning(f"Hash failed for {path}: {e}")
        return None


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return {}
        return json.loads(path.read_text())
    except Exception as e:
        logger.warning(f"Failed to read JSON {path}: {e}")
        return {}


def _safe_write_json(path: Path, obj: Dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, indent=2))
        tmp.replace(path)
    except Exception as e:
        logger.error(f"Failed to write JSON {path}: {e}")


def _safe_read_csv(path: Path) -> "pd.DataFrame":
    if pd is None:
        return None  # type: ignore
    try:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        df = pd.read_csv(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df
    except Exception as e:
        logger.warning(f"Failed to read CSV {path}: {e}")
        return pd.DataFrame()


def _append_weights_history(ts_iso: str, weights: Dict[str, float],
                            metrics: Optional[Dict[str, Any]] = None) -> None:
    """
    Append current weights (and a few metric fields if available) into history CSV.
    """
    try:
        EDGE_WEIGHTS_HISTORY.parent.mkdir(parents=True, exist_ok=True)
        header_needed = not EDGE_WEIGHTS_HISTORY.exists() or EDGE_WEIGHTS_HISTORY.stat().st_size == 0
        with EDGE_WEIGHTS_HISTORY.open("a") as f:
            if header_needed:
                f.write("timestamp,edge,weight,category,sharpe,mdd,trade_count\n")
            for edge, w in weights.items():
                cat = sr = mdd = tc = ""
                if metrics and isinstance(metrics.get(edge), dict):
                    cat = metrics[edge].get("category", "")
                    sr = metrics[edge].get("sr", "")
                    mdd = metrics[edge].get("mdd", "")
                    tc = metrics[edge].get("trade_count", "")
                f.write(f"{ts_iso},{edge},{w},{cat},{sr},{mdd},{tc}\n")
    except Exception as e:
        logger.warning(f"Failed to append weights history: {e}")


@dataclass
class SourceFiles:
    trades: Path
    snapshots: Path

    def state_fingerprint(self) -> str:
        th = _file_hash(self.trades) or "NA"
        sh = _file_hash(self.snapshots) or "NA"
        return f"{th}|{sh}|{int(self.trades.exists())}|{int(self.snapshots.exists())}"


class SystemGovernor:
    """
    Watches trade/snapshot files, refreshes metrics & weights, and writes a single
    dashboard-friendly state cache. Designed to be importable or runnable as a script.
    """

    def __init__(self,
                 backtest_sources: SourceFiles | None = None,
                 paper_sources: SourceFiles | None = None,
                 prefer_backtest: bool = True):
        self.backtest = backtest_sources or SourceFiles(BT_TRADES, BT_SNAPSHOTS)
        self.paper = paper_sources or SourceFiles(PAPER_TRADES, PAPER_SNAPSHOTS)
        self.prefer_backtest = prefer_backtest

        # last processed fingerprints (so we can avoid redundant work)
        self._last_fp: Optional[str] = None

    # ----- Public API -----
    def process_once(self) -> bool:
        """
        Process current state once. Returns True if an update was performed.
        """
        src = self._choose_sources()
        fp = src.state_fingerprint()
        if fp == self._last_fp:
            logger.info("No changes detected; skipping update.")
            return False

        logger.info(f"Detected changes. Updating system intelligence from: {src}")
        ok = self._update_intelligence(src)
        if ok:
            self._last_fp = fp
        return ok

    def watch(self, interval: int = 60) -> None:
        """
        Loop forever, refreshing as files change.
        """
        logger.info(f"Watching for changes (interval={interval}s). Press Ctrl+C to stop.")
        try:
            while True:
                try:
                    self.process_once()
                except Exception as e:
                    logger.error(f"Uncaught error in process_once: {e}")
                time.sleep(interval)
        except KeyboardInterrupt:
            logger.info("Stopped watching.")

    # ----- Internal -----
    def _choose_sources(self) -> SourceFiles:
        """
        Choose between paper or backtest sources. If prefer_backtest is True,
        use backtest when present; else use paper when present; fall back to whichever exists.
        """
        bt_present = self.backtest.trades.exists() or self.backtest.snapshots.exists()
        pr_present = self.paper.trades.exists() or self.paper.snapshots.exists()

        if self.prefer_backtest:
            if bt_present:
                return self.backtest
            if pr_present:
                return self.paper
        else:
            if pr_present:
                return self.paper
            if bt_present:
                return self.backtest
        # neither available; return backtest (will error gracefully)
        return self.backtest

    def _update_intelligence(self, src: SourceFiles) -> bool:
        """
        Orchestrate: compute metrics -> update weights -> write caches.
        """
        # 1) Compute or refresh edge metrics
        metrics_obj = self._compute_edge_metrics(src)

        # 2) Update governor weights (using governor module if available)
        weights_obj = self._update_edge_weights(metrics_obj)

        # 3) Persist system_state.json (single cache for dashboard)
        self._write_system_state(metrics=metrics_obj, weights=weights_obj, src=src)

        # 4) Append weights history for longitudinal charts
        ts_iso = _utc_now_iso()
        if weights_obj.get("weights"):
            _append_weights_history(ts_iso, weights_obj["weights"], metrics_obj.get("metrics"))

        # 5) Log human summary
        self._log_summary(metrics_obj, weights_obj)

        return True

    def _compute_edge_metrics(self, src: SourceFiles) -> Dict[str, Any]:
        """
        Prefer analytics.edge_feedback if present; fallback to minimal local computation.
        Returns dict like: {"metrics": {edge: {...}}, "timestamp": "..."}
        """
        ts_iso = _utc_now_iso()

        if _EDGE_FB and hasattr(_EDGE_FB, "compute_metrics"):
            try:
                # Preferred: call project's analytics function (if it exists)
                logger.info("Computing metrics via analytics.edge_feedback.compute_metrics(...)")
                # The project's signature may differ; handle common forms:
                try:
                    # common signature: compute_metrics(trades_csv, snapshots_csv) -> metrics dict
                    metrics_map = _EDGE_FB.compute_metrics(str(src.trades), str(src.snapshots))  # type: ignore
                except TypeError:
                    # Alternate: compute_metrics(trades_df, snapshots_df)
                    tdf = _safe_read_csv(src.trades)
                    sdf = _safe_read_csv(src.snapshots)
                    metrics_map = _EDGE_FB.compute_metrics(tdf, sdf)  # type: ignore
                out = {"metrics": metrics_map or {}, "timestamp": ts_iso}
                _safe_write_json(EDGE_METRICS_PATH, out)
                return out
            except Exception as e:
                logger.warning(f"analytics.edge_feedback.compute_metrics failed; falling back. Err={e}")

        # Fallback: minimal local computation
        logger.info("Computing metrics via local fallback.")
        metrics_map = _fallback_compute_metrics(src)
        out = {"metrics": metrics_map, "timestamp": ts_iso}
        _safe_write_json(EDGE_METRICS_PATH, out)
        return out

    def _update_edge_weights(self, metrics_obj: Dict[str, Any]) -> Dict[str, Any]:
        """
        Prefer governor module if present; fallback to simple normalization of SR with clamping.
        Returns dict like: {"weights": {edge: float}, "timestamp": "..."}
        """
        ts_iso = _utc_now_iso()
        metrics_map = metrics_obj.get("metrics", {})

        if _GOVERNOR_MOD and hasattr(_GOVERNOR_MOD, "update_weights"):
            try:
                logger.info("Updating weights via engines.engine_d_research.governor.update_weights(...)")
                # Common forms:
                try:
                    weights_map = _GOVERNOR_MOD.update_weights(metrics_map)  # type: ignore
                except TypeError:
                    # maybe expects path(s)
                    weights_map = _GOVERNOR_MOD.update_weights(str(EDGE_METRICS_PATH))  # type: ignore
                out = {"weights": weights_map or {}, "timestamp": ts_iso}
                _safe_write_json(EDGE_WEIGHTS_PATH, out)
                return out
            except Exception as e:
                logger.warning(f"Governor.update_weights failed; falling back. Err={e}")

        # Fallback: derive weights from Sharpe-like metric, clamp, normalize
        logger.info("Updating weights via local fallback.")
        weights_map = _fallback_compute_weights(metrics_map)
        out = {"weights": weights_map, "timestamp": ts_iso}
        _safe_write_json(EDGE_WEIGHTS_PATH, out)
        return out

    def _write_system_state(self,
                            metrics: Dict[str, Any],
                            weights: Dict[str, Any],
                            src: SourceFiles) -> None:
        """
        Compose a small dashboard-friendly cache describing the current state.
        """
        tdf = _safe_read_csv(src.trades)
        sdf = _safe_read_csv(src.snapshots)
        eq_summary = _equity_summary(sdf)

        # Try to include external recommendations if present
        rec_path = DATA_DIR / "research" / "edge_recommendations.json"
        recommendations = _safe_read_json(rec_path)

        state = {
            "timestamp": _utc_now_iso(),
            "last_update_tz": "UTC",
            "source": {
                "trades": str(src.trades),
                "snapshots": str(src.snapshots),
            },
            "summary": eq_summary,
            "metrics": metrics.get("metrics", {}),
            "weights": weights.get("weights", {}),
            "categories": {k: v.get("category") for k, v in metrics.get("metrics", {}).items()},
            "recommendations": recommendations or {},
        }
        _safe_write_json(SYSTEM_STATE_PATH, state)


    def _log_summary(self, metrics_obj: dict, weights_obj: dict) -> None:
        """Print a concise update summary to the logger."""
        try:
            metrics = metrics_obj.get("metrics", {})
            weights = weights_obj.get("weights", {})
            logger.info("----- Intelligence Update Summary -----")
            logger.info(f"Edges analyzed: {len(metrics)}")
            for edge, val in weights.items():
                m = metrics.get(edge, {})
                sr = m.get("sr", "-")
                mdd = m.get("mdd", "-")
                tc = m.get("trade_count", "-")
                logger.info(f"  • {edge:<22} | cat={m.get('category','-'):<10} | weight={val:.3f} | SR={sr} | MDD={mdd} | trades={tc}")
            logger.info("----------------------------------------")
        except Exception as e:
            logger.warning(f"Could not log summary: {e}")


# ---------- Local Fallback Implementations ----------
def _fallback_compute_metrics(src: SourceFiles) -> Dict[str, Dict[str, float]]:
    """
    Very simple per-edge metrics using realized PnL and daily equity stats.
    This is a fallback when analytics.edge_feedback is unavailable.
    """
    results: Dict[str, Dict[str, float]] = {}
    if pd is None or np is None:
        return results

    trades = _safe_read_csv(src.trades)
    snaps = _safe_read_csv(src.snapshots)

    # Edge grouping
    if trades is None or trades.empty:
        return results

    # Ensure numeric PnL and edge column
    if "pnl" not in trades.columns or trades["pnl"].isna().all():
        trades = _fifo_realized_pnl(trades)

    if "edge" not in trades.columns:
        trades["edge"] = "Unknown"

    # Compute basic SR & MDD proxies per edge (prefer edge_id when present)
    edge_col = "edge_id" if "edge_id" in trades.columns else "edge"
    cat_col = "edge_category" if "edge_category" in trades.columns else None

    for edge, tdf in trades.groupby(edge_col, dropna=False):
        # derive category (last non-null) if available
        category = None
        if cat_col and cat_col in tdf.columns:
            non_null = tdf[cat_col].dropna()
            if not non_null.empty:
                category = str(non_null.iloc[-1])
            else:
                category = "unknown"
        tdf = tdf.sort_values("timestamp")
        realized = tdf.dropna(subset=["pnl"])["pnl"]
        trade_count = int(len(tdf))
        win_rate = float(np.nan) if realized.empty else 100.0 * (realized > 0).sum() / len(realized)
        pnl_sum = float(np.nansum(realized)) if not realized.empty else 0.0

        # Sharpe proxy from daily equity (if available); else from trade returns as proxy
        sr = float("nan")
        mdd = float("nan")

        if snaps is not None and not snaps.empty and "equity" in snaps.columns:
            rets = snaps["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
            if not rets.empty and rets.std() > 0:
                sr = (rets.mean() / rets.std()) * np.sqrt(252)
            roll_max = snaps["equity"].cummax()
            dd = (snaps["equity"] - roll_max) / roll_max
            mdd = float(dd.min() * 100.0) if not dd.empty else float("nan")

        # naive correlation penalty: none (0) in fallback
        results[str(edge)] = {
            "trade_count": trade_count,
            "category": category if category else "unknown",
            "win_rate": None if np.isnan(win_rate) else round(win_rate, 2),
            "total_realized_pnl": round(pnl_sum, 2),
            "sr": None if _isnan(sr) else round(sr, 3),
            "mdd": None if _isnan(mdd) else round(mdd, 2),
            "corr_penalty": 0.0,
        }

    return results


def _fifo_realized_pnl(trades_df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Minimal FIFO realized PnL matcher (long/short/exit). Leaves NaN for open legs.
    """
    if pd is None or np is None or trades_df is None or trades_df.empty:
        return trades_df

    df = trades_df.copy()
    for col in ("qty", "fill_price"):
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    if "commission" not in df.columns:
        df["commission"] = 0.0
    if "pnl" not in df.columns:
        df["pnl"] = np.nan

    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    df = df.dropna(subset=["timestamp"])
    df = df.sort_values(["ticker", "timestamp"])

    stacks: Dict[str, list[dict]] = {}

    def sign_for(side: str) -> int:
        s = str(side).lower()
        return +1 if s == "long" else (-1 if s == "short" else 0)

    def closes(prev_sign: int, now_side: str) -> bool:
        s = str(now_side).lower()
        if s in ("exit", "cover"):
            return True
        now_sign = sign_for(s)
        return prev_sign != 0 and now_sign != 0 and np.sign(prev_sign) != np.sign(now_sign)

    for tkr, tdf in df.groupby("ticker", sort=False):
        stack: list[dict] = stacks.setdefault(tkr, [])

        def current_net_sign() -> int:
            if not stack:
                return 0
            net = sum(leg["sign"] * leg["qty"] for leg in stack)
            return int(np.sign(net)) if net != 0 else 0

        prev_net_sign = 0
        for idx, row in tdf.iterrows():
            side = str(row.get("side", "")).lower()
            qty = int(row.get("qty", 0))
            px = float(row.get("fill_price", np.nan))
            if qty <= 0 or not np.isfinite(px):
                continue

            if side in ("long", "short"):
                now_sign = sign_for(side)
                if prev_net_sign == 0 or prev_net_sign == now_sign:
                    stack.append({"sign": now_sign, "price": px, "qty": qty})
                else:
                    # flip: close FIFO then open remainder
                    remaining = qty
                    realized = 0.0
                    while remaining > 0 and stack and np.sign(stack[0]["sign"]) != np.sign(now_sign):
                        leg = stack[0]
                        m = min(remaining, leg["qty"])
                        direction = leg["sign"]
                        realized += (px - leg["price"]) * (m * direction)
                        leg["qty"] -= m
                        remaining -= m
                        if leg["qty"] == 0:
                            stack.pop(0)
                    if remaining > 0:
                        stack.append({"sign": now_sign, "price": px, "qty": remaining})
                    df.loc[idx, "pnl"] = round(realized, 2)
            elif closes(prev_net_sign, side):
                remaining = qty
                realized = 0.0
                while remaining > 0 and stack:
                    leg = stack[0]
                    m = min(remaining, leg["qty"])
                    direction = leg["sign"]
                    realized += (px - leg["price"]) * (m * direction)
                    leg["qty"] -= m
                    remaining -= m
                    if leg["qty"] == 0:
                        stack.pop(0)
                df.loc[idx, "pnl"] = round(realized, 2)

            prev_net_sign = current_net_sign()

    return df


def _fallback_compute_weights(metrics_map: Dict[str, Dict[str, float]]) -> Dict[str, float]:
    """
    Simple heuristic:
      - base score = max(sr, 0)
      - apply (1 + 0.01 * win_rate) bonus if available
      - apply penalty for large MDD (e.g., -|mdd| * 0.01)
      - clamp to [0, None), normalize to sum=1 (unless all zeros)
    """
    if not metrics_map:
        return {}
    scores: Dict[str, float] = {}
    for edge, m in metrics_map.items():
        try:
            sr = float(m.get("sr", 0) or 0)
            wr = float(m.get("win_rate", 0) or 0)
            mdd = float(m.get("mdd", 0) or 0)  # mdd in percent (negative)
            cp = float(m.get("corr_penalty", 0) or 0)

            base = max(sr, 0.0)
            bonus = 1.0 + max(wr, 0.0) * 0.01
            penalty = 1.0 - (abs(min(mdd, 0.0)) * 0.01) - max(cp, 0.0)
            # small diversity bonus for known categories
            cat_bonus = 1.0
            if isinstance(m, dict) and m.get("category") and m.get("category") != "unknown":
                cat_bonus = 1.05
            score = max(base * bonus * penalty * cat_bonus, 0.0)
        except Exception:
            score = 0.0
        scores[str(edge)] = score

    total = sum(scores.values())
    if total <= 0:
        # uniform weights if all zero
        n = len(scores)
        return {k: (1.0 / n) for k in scores} if n > 0 else {}
    return {k: v / total for k, v in scores.items()}


def _equity_summary(snapshots_df: "pd.DataFrame") -> Dict[str, Any]:
    if pd is None or snapshots_df is None or snapshots_df.empty:
        return {}
    try:
        eq = snapshots_df["equity"].astype(float)
        start = float(eq.iloc[0])
        end = float(eq.iloc[-1])
        total_ret = (end - start) / start if start > 0 else float("nan")
        days = (snapshots_df["timestamp"].iloc[-1] - snapshots_df["timestamp"].iloc[0]).days
        cagr = (1 + total_ret) ** (365.0 / days) - 1 if (days > 0 and np.isfinite(total_ret)) else float("nan")
        rets = snapshots_df["equity"].pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        vol = rets.std() * np.sqrt(252) if not rets.empty else float("nan")
        sharpe = (rets.mean() / rets.std()) * np.sqrt(252) if (not rets.empty and rets.std() > 0) else float("nan")

        roll_max = snapshots_df["equity"].cummax()
        dd = (snapshots_df["equity"] - roll_max) / roll_max
        dd = dd.replace([np.inf, -np.inf], np.nan).fillna(0.0)
        mdd = dd.min()

        return {
            "starting_equity": round(start, 2),
            "ending_equity": round(end, 2),
            "total_return_pct": None if _isnan(total_ret) else round(100 * total_ret, 2),
            "cagr_pct": None if _isnan(cagr) else round(100 * cagr, 2),
            "vol_ann_pct": None if _isnan(vol) else round(100 * vol, 2),
            "sharpe": None if _isnan(sharpe) else round(sharpe, 3),
            "max_drawdown_pct": None if _isnan(mdd) else round(100 * float(mdd), 2),
        }
    except Exception:
        return {}


def _utc_now_iso() -> str:
    # Avoid deprecated datetime.utcnow() warnings; use timezone-aware then iso Z
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def _isnan(x: Any) -> bool:
    try:
        return bool(np.isnan(x))  # type: ignore
    except Exception:
        return False


# ---------- CLI ----------
def main() -> None:
    p = argparse.ArgumentParser(description="Trading Machine — System Governor Orchestrator")
    p.add_argument("--once", action="store_true", help="Run a single refresh pass and exit.")
    p.add_argument("--watch", action="store_true", help="Continuously watch files and refresh on change.")
    p.add_argument("--interval", type=int, default=60, help="Watch interval in seconds (default: 60).")
    p.add_argument("--prefer", choices=["backtest", "paper"], default="backtest",
                   help="Preferred source set if both present (default: backtest).")
    args = p.parse_args()

    gov = SystemGovernor(
        prefer_backtest=(args.prefer == "backtest"),
    )

    if args.once and args.watch:
        logger.error("Choose either --once or --watch, not both.")
        return

    if args.once:
        updated = gov.process_once()
        logger.info("Update performed." if updated else "No update necessary.")
        return

    if args.watch or (not args.once):
        gov.watch(interval=args.interval)


if __name__ == "__main__":
    main()