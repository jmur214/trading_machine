# cockpit/logger.py
from __future__ import annotations
from pathlib import Path
import pandas as pd
from datetime import datetime
from typing import Optional, Dict, Any


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
    ]

    SNAPSHOT_COLUMNS = [
        "timestamp",
        "cash",
        "market_value",
        "realized_pnl",
        "unrealized_pnl",
        "equity",
        "positions",
    ]

    def __init__(self, out_dir: str, portfolio: Optional[Any] = None, verbose: bool = True):
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)

        self.trade_path = self.out_dir / "trades.csv"
        self.snap_path = self.out_dir / "portfolio_snapshots.csv"
        self.portfolio = portfolio
        self.verbose = verbose

        self._ensure_csv_headers()

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
                    if self.verbose:
                        print(f"[LOGGER] Updated schema for {path.name} → {all_cols}")
            except Exception as e:
                print(f"[LOGGER][WARN] Could not read {path.name}, recreating file: {e}")
                pd.DataFrame(columns=cols).to_csv(path, index=False)

    # -------------------------------------------------------------------- #
    def _append_to_csv(self, path: Path, row_dict: dict) -> None:
        """Safely append a single dict row to a CSV file."""
        df = pd.DataFrame([row_dict])
        df.to_csv(path, mode="a", header=False, index=False)

    # -------------------------------------------------------------------- #
    def _calc_realized_pnl(self, fill: dict) -> Optional[float]:
        """
        Estimate realized PnL for exits when portfolio reference exists.
        Uses average price and direction of the position.
        """
        if not self.portfolio:
            return None

        tkr = fill.get("ticker")
        side = str(fill.get("side", "")).lower()
        qty = float(fill.get("qty", 0))
        px = float(fill.get("price", fill.get("fill_price", 0.0)))

        if side not in ("exit", "cover"):
            return None

        pos = self.portfolio.positions.get(tkr)
        if not pos or not getattr(pos, "avg_price", None):
            return None

        avg = float(pos.avg_price)
        sign = 1 if side == "exit" else -1  # exit=long sell, cover=short buy
        pnl = round((px - avg) * qty * sign, 2)
        return pnl

    # -------------------------------------------------------------------- #
    def log_fill(self, fill: Dict[str, Any], timestamp: Any) -> None:
        """
        Logs each fill (entry, exit, or SL/TP trigger) to trades.csv.
        Auto-includes metadata: edge, trigger, meta.
        """
        if not fill or "ticker" not in fill:
            return

        realized_pnl = self._calc_realized_pnl(fill)

        row = {
            "timestamp": pd.to_datetime(timestamp),
            "ticker": fill.get("ticker"),
            "side": fill.get("side"),
            "qty": fill.get("qty"),
            "fill_price": fill.get("price") or fill.get("fill_price"),
            "commission": fill.get("commission", 0.0),
            "pnl": realized_pnl,
            "edge": fill.get("edge", "Unknown"),
            "edge_group": fill.get("edge_group", None),
            "trigger": fill.get("trigger", None),
            # meta is stringified safely
            "meta": str(fill.get("meta", {})) if fill.get("meta") else None,
        }

        self._append_to_csv(self.trade_path, row)

        if self.verbose:
            px = row["fill_price"]
            print(
                f"[LOGGER] {timestamp}: {row['side'].upper()} {row['ticker']} x{row['qty']} @ {px:.2f} "
                f"(edge={row['edge']}{'/' + row['edge_group'] if row['edge_group'] else ''}, "
                f"trigger={row['trigger'] or 'manual'})"
            )

    # -------------------------------------------------------------------- #
    def log_snapshot(self, snap: Dict[str, Any]) -> None:
        """Append a portfolio snapshot per bar (timestamp required)."""
        if not isinstance(snap, dict) or "equity" not in snap:
            return

        snap = dict(snap)
        snap["timestamp"] = pd.to_datetime(snap["timestamp"])
        self._append_to_csv(self.snap_path, snap)

        if self.verbose:
            print(
                f"[LOGGER][SNAPSHOT] {snap['timestamp']:%Y-%m-%d %H:%M} "
                f"Equity={snap['equity']:.2f} | Cash={snap['cash']:.2f} | "
                f"Pos={snap['positions']}"
            )

    # -------------------------------------------------------------------- #
    def summarize_trades(self, n: int = 5) -> None:
        """Quick console summary of the last N trades."""
        if not self.trade_path.exists():
            print("[LOGGER] No trade log found.")
            return

        df = pd.read_csv(self.trade_path)
        if df.empty:
            print("[LOGGER] No trades yet.")
            return

        cols = [c for c in ["timestamp", "ticker", "side", "qty", "fill_price", "pnl", "edge", "trigger"] if c in df]
        print("\n--- Recent Trades ---")
        print(df[cols].tail(n).to_string(index=False))