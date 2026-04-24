# core/logger.py
from __future__ import annotations
from pathlib import Path
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any
from debug_config import is_debug_enabled
import threading
import time


def is_info_enabled() -> bool:
    from debug_config import DEBUG_LEVELS
    return DEBUG_LEVELS.get("LOGGER_INFO", False)

# Helper: checks if logging is enabled, based on DEBUG_LEVELS
def is_logger_enabled() -> bool:
    try:
        from debug_config import DEBUG_LEVELS
        return DEBUG_LEVELS.get("LOGGER_ENABLED", True)
    except ImportError:
        return True


class CockpitLogger:
    """
    Logs portfolio events (fills, snapshots) for backtests and live simulations.

    Features:
      • Keeps schema stable and self-healing even after engine updates.
      • Tracks 'edge', 'meta', and 'trigger' fields for research attribution.
      • Estimates realized PnL for exit/cover fills using live portfolio reference.
      • Compatible with dashboards expecting trades.csv and portfolio_snapshots.csv.
    """

    TRADE_COLUMNS = [
        "timestamp",
        "ticker",
        "side",
        "qty",
        "fill_price",
        "commission",
        "pnl",
        "edge",
        "edge_group",
        "trigger",
        "meta",
        "edge_id",
        "edge_category",
        "run_id",
        "regime_label",
    ]

    SNAPSHOT_COLUMNS = [
        "timestamp",
        "cash",
        "market_value",
        "realized_pnl",
        "unrealized_pnl",
        "equity",
        "positions",
        "open_pos_by_edge",
        "run_id",
    ]

    def __init__(self, out_dir: str = "data/trade_logs", portfolio: Optional[Any] = None, verbose: bool = True, flush_interval: float = 3.0, flush_each_fill: bool = False):
        from uuid import uuid4
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.run_id = str(uuid4())
        run_subdir = self.out_dir / self.run_id
        run_subdir.mkdir(parents=True, exist_ok=True)
        self.trade_path = run_subdir / "trades.csv"
        self.snap_path = run_subdir / "portfolio_snapshots.csv"

        self.portfolio = portfolio
        self.verbose = verbose

        self._snap_buffer = []
        self._trade_buffer = []
        self._buffer_limit = 500

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._flush_interval = flush_interval
        self._flush_thread = threading.Thread(target=self._auto_flush_loop, daemon=True)

        self.flush_each_fill = flush_each_fill

        self._ensure_csv_headers()
        self._flush_thread.start()

        if is_info_enabled() or is_debug_enabled("LOGGER"):
            print(f"[LOGGER][INIT] CockpitLogger initialized for run_id={self.run_id} at {self.out_dir}")

    def set_portfolio(self, portfolio: Any) -> None:
        """Attach/refresh the portfolio reference so PnL math is accurate."""
        self.portfolio = portfolio

    # -------------------------------------------------------------------- #
    def _ensure_csv_headers(self) -> None:
        """
        Ensure both CSVs exist and match the required schema.
        If headers differ, they are replaced (schema evolution safe).
        """
        for path, cols in [
            (self.trade_path, self.TRADE_COLUMNS),
            (self.snap_path, self.SNAPSHOT_COLUMNS),
        ]:
            if not path.exists() or path.stat().st_size == 0:
                pd.DataFrame(columns=cols).to_csv(path, index=False)
                continue

            try:
                existing = pd.read_csv(path, nrows=0).columns.tolist()
                # Expand if new columns were introduced in code
                if set(existing) != set(cols):
                    # Merge both column sets (so you don’t lose existing logs)
                    all_cols = list(dict.fromkeys(existing + [c for c in cols if c not in existing]))
                    df = pd.read_csv(path)
                    for c in all_cols:
                        if c not in df.columns:
                            df[c] = None
                    df.to_csv(path, index=False)
                    if is_info_enabled() or is_debug_enabled("LOGGER"):
                        print(f"[LOGGER][INFO] Updated schema for {path.name} → {all_cols}")
            except Exception as e:
                print(f"[LOGGER][WARN] Could not read {path.name}, recreating file: {e}")
                pd.DataFrame(columns=cols).to_csv(path, index=False)

    # -------------------------------------------------------------------- #
    def _flush_buffer(self, path: Path, buffer: list) -> None:
        """Flush the buffered rows to disk and clear the buffer."""
        with self._lock:
            if not buffer:
                return
            df = pd.DataFrame(buffer)
            df["run_id"] = self.run_id
            df.to_csv(path, mode="a", header=False, index=False)
            buffer.clear()
            if is_info_enabled() or is_debug_enabled("LOGGER"):
                print(f"[LOGGER][INFO] Auto-flushed {len(df)} rows to {path.name}")

    # -------------------------------------------------------------------- #
    def _append_to_csv(self, path: Path, row_dict: dict) -> None:
        """Append a single dict row to the appropriate buffer and flush if needed."""
        needs_flush = False
        flush_each = False
        path_ref = None
        buffer_ref = None
        with self._lock:
            if path == self.trade_path:
                row_dict["run_id"] = self.run_id
                self._trade_buffer.append(row_dict)
                needs_flush = len(self._trade_buffer) >= self._buffer_limit
                flush_each = self.flush_each_fill
                path_ref = self.trade_path
                buffer_ref = self._trade_buffer
            elif path == self.snap_path:
                row_dict["run_id"] = self.run_id
                self._snap_buffer.append(row_dict)
                needs_flush = len(self._snap_buffer) >= self._buffer_limit
                path_ref = self.snap_path
                buffer_ref = self._snap_buffer
            else:
                df = pd.DataFrame([row_dict])
                df["run_id"] = self.run_id
                df.to_csv(path, mode="a", header=False, index=False)
                return
        if needs_flush:
            self._flush_buffer(path_ref, buffer_ref)
        if flush_each:
            self.flush()

    # -------------------------------------------------------------------- #
    def _calc_realized_pnl(self, fill: dict) -> Optional[float]:
        """
        Return pre-computed PnL from fill dict.
        PnL is computed by PortfolioEngine.apply_fill() — the single source of truth.
        For entry fills (long/short), returns None.
        """
        side = str(fill.get("side", "")).lower()
        if side not in ("exit", "cover"):
            return None
        return fill.get("pnl")

    # -------------------------------------------------------------------- #
    def log_fill(self, fill: Dict[str, Any], timestamp: Any) -> None:
        """
        Logs each fill (entry, exit, or SL/TP trigger) to trades.csv.
        Auto-includes metadata: edge, trigger, meta.
        Ensures PnL is computed and stored in the fill dict for downstream compatibility.
        """
        if not is_logger_enabled():
            return

        if not fill or "ticker" not in fill:
            return

        # Compute and store realized_pnl into fill for downstream
        self._calc_realized_pnl(fill)

        row = {
            "timestamp": pd.to_datetime(timestamp),
            "ticker": fill.get("ticker"),
            "side": fill.get("side"),
            "qty": fill.get("qty"),
            "fill_price": fill.get("price") or fill.get("fill_price"),
            "commission": fill.get("commission", 0.0),
            "pnl": fill.get("pnl"),
            "edge": fill.get("edge", "Unknown"),
            "edge_group": fill.get("edge_group", None),
            "trigger": fill.get("trigger", None),
            # meta is stringified safely
            "meta": str(fill.get("meta", {})) if fill.get("meta") else None,
            "edge_id": fill.get("edge_id"),
            "edge_category": fill.get("edge_category"),
            "run_id": self.run_id or "",
            "regime_label": fill.get("regime_label", ""),
        }

        self._append_to_csv(self.trade_path, row)

        if is_info_enabled() or is_debug_enabled("LOGGER"):
            px = row["fill_price"]
            print(
                f"[LOGGER][INFO] {timestamp}: {row['side'].upper()} {row['ticker']} x{row['qty']} @ {px:.2f} "
                f"(edge={row['edge']}{'/' + row['edge_group'] if row['edge_group'] else ''}, "
                f"trigger={row['trigger'] or 'manual'})"
            )

    # -------------------------------------------------------------------- #
    def log_trade(self, fill: Dict[str, Any], timestamp: Any = None) -> None:
        """
        Backward-compatible alias for log_fill().

        Some modules still call logger.log_trade(fill) instead of logger.log_fill(fill, ts).
        This keeps compatibility across versions.
        """
        if timestamp is None:
            timestamp = datetime.utcnow()
        try:
            self.log_fill(fill, timestamp)
        except Exception as e:
            if is_info_enabled() or is_debug_enabled("LOGGER"):
                print(f"[LOGGER][WARN] log_trade fallback failed: {e}")

    # -------------------------------------------------------------------- #
    def log_snapshot(self, snap: Dict[str, Any]) -> None:
        """Append a portfolio snapshot per bar. Logger records as-is — no recomputation.
        Callers (BacktestController, PaperTradeController) are responsible for providing
        complete snapshots via PortfolioEngine.snapshot()."""
        if not is_logger_enabled():
            return

        if not isinstance(snap, dict):
            return

        snap = dict(snap)
        snap["timestamp"] = pd.to_datetime(snap.get("timestamp", datetime.utcnow()))
        self._append_to_csv(self.snap_path, snap)

        # Clear debug print with timestamp, cash, equity
        if is_info_enabled() or is_debug_enabled("LOGGER"):
            cash = snap.get("cash", 0.0)
            equity = snap.get("equity", 0.0)
            print(
                f"[LOGGER][DEBUG] [SNAPSHOT WRITE] {snap['timestamp']:%Y-%m-%d %H:%M:%S} | Cash={cash:.2f} | Equity={equity:.2f}"
            )

    # -------------------------------------------------------------------- #
    def flush(self) -> None:
        """Force flush any remaining buffered rows to disk."""
        with self._lock:
            # Flush trades
            if self._trade_buffer:
                df_t = pd.DataFrame(self._trade_buffer)
                df_t["run_id"] = self.run_id
                df_t.to_csv(self.trade_path, mode="a", header=False, index=False)
                flushed_t = len(df_t)
                self._trade_buffer.clear()
            else:
                flushed_t = 0

            # Flush snapshots
            if self._snap_buffer:
                df_s = pd.DataFrame(self._snap_buffer)
                df_s["run_id"] = self.run_id
                df_s.to_csv(self.snap_path, mode="a", header=False, index=False)
                flushed_s = len(df_s)
                self._snap_buffer.clear()
            else:
                flushed_s = 0

            if is_info_enabled() or is_debug_enabled("LOGGER"):
                if flushed_t or flushed_s:
                    print(f"[LOGGER][INFO] Flushed trades={flushed_t}, snapshots={flushed_s}")

    # -------------------------------------------------------------------- #
    def summarize_trades(self, n: int = 5) -> None:
        """Quick console summary of the last N trades."""
        if not self.trade_path.exists():
            print("[LOGGER][INFO] No trade log found.")
            return

        df = pd.read_csv(self.trade_path)
        if df.empty:
            print("[LOGGER][INFO] No trades yet.")
            return

        cols = [c for c in ["timestamp", "ticker", "side", "qty", "fill_price", "pnl", "edge", "trigger"] if c in df]
        print("\n--- Recent Trades ---")
        print(df[cols].tail(n).to_string(index=False))

    # -------------------------------------------------------------------- #
    def _auto_flush_loop(self) -> None:
        while not self._stop_event.is_set():
            time.sleep(self._flush_interval)
            if self._stop_event.is_set():
                break
            try:
                self.flush()
            except Exception as e:
                if is_info_enabled() or is_debug_enabled("LOGGER"):
                    print(f"[LOGGER][WARN] Auto-flush error: {e}")

    # -------------------------------------------------------------------- #
    def close(self) -> None:
        """Stop background thread and flush all buffers safely."""
        self._stop_event.set()
        self._flush_thread.join(timeout=5)
        self.flush()
        print(f"[LOGGER][INFO] Closed logger for run_id={self.run_id}")
