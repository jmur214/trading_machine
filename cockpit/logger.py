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
        if path == self.trade_path:
            row_dict["run_id"] = self.run_id
            self._trade_buffer.append(row_dict)
            if len(self._trade_buffer) >= self._buffer_limit:
                self._flush_buffer(self.trade_path, self._trade_buffer)
            if self.flush_each_fill:
                self.flush()
        elif path == self.snap_path:
            row_dict["run_id"] = self.run_id
            self._snap_buffer.append(row_dict)
            if len(self._snap_buffer) >= self._buffer_limit:
                self._flush_buffer(self.snap_path, self._snap_buffer)
        else:
            # Fallback: write immediately if unknown path
            df = pd.DataFrame([row_dict])
            df["run_id"] = self.run_id
            with self._lock:
                df.to_csv(path, mode="a", header=False, index=False)

    # -------------------------------------------------------------------- #
    def _calc_realized_pnl(self, fill: dict) -> Optional[float]:
        """
        Improved: Compute realized PnL for exits and covers using portfolio reference.
        For entry fills, realized PnL is None.
        If portfolio info is missing, fallback to estimate using prior close or fill meta.
        The computed PnL is also stored directly into the fill dict for downstream compatibility.
        """
        tkr = fill.get("ticker")
        side = str(fill.get("side", "")).lower()
        qty = float(fill.get("qty", 0))
        # accept either key; normalize to float if possible
        px_raw = fill.get("price", fill.get("fill_price", 0.0))
        try:
            px = float(px_raw)
        except Exception:
            px = 0.0

        # Only compute PnL for exit/cover (i.e., closing trades)
        if side not in ("exit", "cover"):
            fill["pnl"] = None
            return None

        # Try to use portfolio for best accuracy
        pnl = None
        if self.portfolio:
            pos = self.portfolio.positions.get(tkr)
            # If position exists and has avg_price and side, compute realized PnL
            if pos and getattr(pos, "avg_price", None) is not None and hasattr(pos, "side"):
                avg = float(pos.avg_price)
                # Figure out what side the position was (long/short)
                pos_side = str(getattr(pos, "side", "")).lower()
                # For exit: closing a long (sell), realized = (fill_px - avg_px) * qty
                # For cover: closing a short (buy), realized = (avg_px - fill_px) * qty
                if side == "exit" and pos_side == "long":
                    pnl = round((px - avg) * qty, 2)
                elif side == "cover" and pos_side == "short":
                    pnl = round((avg - px) * qty, 2)
                else:
                    # Defensive: fallback to sign logic
                    sign = 1 if side == "exit" else -1
                    pnl = round((px - avg) * qty * sign, 2)
        # Fallback: try to estimate from prior close or fill meta
        if pnl is None:
            # Try to use PrevClose if available in fill meta or fill itself
            prev_close = None
            meta = fill.get("meta", {})
            if isinstance(meta, dict):
                prev_close = meta.get("PrevClose")
            if prev_close is None:
                prev_close = fill.get("PrevClose")
            try:
                prev_close = float(prev_close)
            except Exception:
                prev_close = None
            # If both fill price and prev_close are available, estimate
            if prev_close is not None and px:
                if side == "exit":
                    pnl = round((px - prev_close) * qty, 2)
                elif side == "cover":
                    pnl = round((prev_close - px) * qty, 2)
            else:
                # As last resort, set to zero
                pnl = 0.0
        fill["pnl"] = pnl
        return pnl

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
        """Append a portfolio snapshot per bar (timestamp required). Refreshes cash, market_value, realized/unrealized_pnl, equity from live portfolio if available."""
        if not is_logger_enabled():
            return

        if not isinstance(snap, dict):
            return

        # Ensure timestamp and base fields exist
        snap = dict(snap)
        snap["timestamp"] = pd.to_datetime(snap.get("timestamp", datetime.utcnow()))
        # --- NEW: Recompute snapshot fields directly from live portfolio if available ---
        if self.portfolio:
            try:
                live_cash = float(getattr(self.portfolio, "cash", snap.get("cash", 0.0)))
                realized = float(getattr(self.portfolio, "realized_pnl", snap.get("realized_pnl", 0.0)))
                unreal = float(getattr(self.portfolio, "unrealized_pnl", snap.get("unrealized_pnl", 0.0)))

                # Compute market_value from open positions
                mv = 0.0
                for t, pos in getattr(self.portfolio, "positions", {}).items():
                    if hasattr(pos, "qty") and pos.qty != 0:
                        last_px = getattr(pos, "last_price", getattr(pos, "avg_price", 0.0))
                        mv += float(pos.qty) * float(last_px)

                snap["cash"] = float(live_cash)
                snap["realized_pnl"] = float(realized)
                snap["unrealized_pnl"] = float(unreal)
                snap["market_value"] = float(mv)
                snap["equity"] = float(live_cash + mv)
            except Exception:
                pass
        # Note: run_id is injected in _append_to_csv to keep schema consistent
        # DEBUG: see what logger receives and where it's going to write
        try:
            from debug_config import is_debug_enabled
            if is_debug_enabled("COCKPIT_LOGGER"):
                print(f"[DEBUG_LOGGER_SNAPSHOT_INPUT] snap={snap}, snap_path={self.snap_path}")
        except Exception:
            pass
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
            if self._lock.locked():
                continue
            self.flush()

    # -------------------------------------------------------------------- #
    def close(self) -> None:
        """Stop background thread and flush all buffers safely."""
        self._stop_event.set()
        self._flush_thread.join(timeout=5)
        self.flush()
        print(f"[LOGGER][INFO] Closed logger for run_id={self.run_id}")
