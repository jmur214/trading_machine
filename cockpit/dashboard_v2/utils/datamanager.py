from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Any, Optional, Tuple

import pandas as pd

DATA_DIR = Path("data")
GOV_DIR = DATA_DIR / "governor"
STATE_PATH = GOV_DIR / "system_state.json"
EDGE_METRICS_PATH = GOV_DIR / "edge_metrics.json"
EDGE_WEIGHTS_PATH = GOV_DIR / "edge_weights.json"
EDGE_WEIGHTS_HISTORY = GOV_DIR / "edge_weights_history.csv"
TRADE_LOGS_DIR = DATA_DIR / "trade_logs"
BT_TRADES = TRADE_LOGS_DIR / "trades.csv"
BT_SNAPSHOTS = TRADE_LOGS_DIR / "portfolio_snapshots.csv"
PAPER_DIR = TRADE_LOGS_DIR / "paper"
PAPER_TRADES = PAPER_DIR / "trades.csv"
PAPER_SNAPSHOTS = PAPER_DIR / "portfolio_snapshots.csv"
BT_POSITIONS = TRADE_LOGS_DIR / "positions.csv"
PAPER_POSITIONS = PAPER_DIR / "positions.csv"


def _safe_read_json(path: Path) -> Dict[str, Any]:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return {}
        return json.loads(path.read_text())
    except Exception:
        return {}


def _safe_read_csv(path: Path) -> pd.DataFrame:
    try:
        if not path.exists() or path.stat().st_size == 0:
            return pd.DataFrame()
        df = pd.read_csv(path)
        if "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df
    except Exception:
        return pd.DataFrame()


class DataManager:
    """Unified reader for governor + analytics state.

    Prefers system_state.json; falls back to separate files when missing.
    """

    def __init__(self, prefer_backtest: bool = True):
        self.prefer_backtest = prefer_backtest

    # --------- State JSON ---------
    def load_state(self) -> Dict[str, Any]:
        st = _safe_read_json(STATE_PATH)
        if st:
            return st
        # Fallback: compose from legacy files
        metrics = _safe_read_json(EDGE_METRICS_PATH).get("metrics", {})
        weights = _safe_read_json(EDGE_WEIGHTS_PATH).get("weights", {})
        return {
            "timestamp": None,
            "summary": {},
            "metrics": metrics,
            "weights": weights,
            "recommendations": {},
        }

    def get_summary(self) -> Dict[str, Any]:
        return self.load_state().get("summary", {})

    def get_metrics(self) -> Dict[str, Any]:
        return self.load_state().get("metrics", {})

    def get_weights(self) -> Dict[str, float]:
        w = self.load_state().get("weights", {})
        # ensure floats
        return {k: float(v) for k, v in w.items() if self._is_number(v)}

    def get_recommendations(self) -> Dict[str, Any]:
        return self.load_state().get("recommendations", {})

    def get_last_update(self) -> Optional[str]:
        return self.load_state().get("timestamp")

    # --------- History CSV ---------
    def get_weight_history(self) -> pd.DataFrame:
        df = _safe_read_csv(EDGE_WEIGHTS_HISTORY)
        # History file likely does not have timezone info; enforce UTC
        if not df.empty and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df

    # --------- Trades / Snapshots ---------
    def get_trades_and_snapshots(self) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """Return preferred (backtest or paper) trades and snapshots DataFrames."""
        bt_trades = _safe_read_csv(BT_TRADES)
        bt_snaps = _safe_read_csv(BT_SNAPSHOTS)
        paper_trades = _safe_read_csv(PAPER_TRADES)
        paper_snaps = _safe_read_csv(PAPER_SNAPSHOTS)

        if self.prefer_backtest:
            trades = bt_trades if not bt_trades.empty else paper_trades
            snaps = bt_snaps if not bt_snaps.empty else paper_snaps
        else:
            trades = paper_trades if not paper_trades.empty else bt_trades
            snaps = paper_snaps if not paper_snaps.empty else bt_snaps
        return trades, snaps

    def get_trades(self, mode: str = "backtest") -> pd.DataFrame:
        """Return trades DataFrame for specified mode."""
        path = PAPER_TRADES if mode.lower() == "paper" else BT_TRADES
        df = _safe_read_csv(path)
        if not df.empty and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df

    def get_positions(self, mode: str = "backtest") -> pd.DataFrame:
        """Return positions DataFrame for specified mode (if present)."""
        path = PAPER_POSITIONS if mode.lower() == "paper" else BT_POSITIONS
        df = _safe_read_csv(path)
        if not df.empty and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df

    # --------- Helpers ---------
    @staticmethod
    def _is_number(x: Any) -> bool:
        try:
            float(x)
            return True
        except Exception:
            return False

    # --------- Legacy Compatibility Methods ---------
    def _safe_read_csv(self, path: Path):
        """Legacy wrapper for backward compatibility with older dashboard callbacks."""
        return _safe_read_csv(path)

    def get_equity_curve(self, mode: str = "backtest") -> pd.DataFrame:
        """Return equity curve (portfolio snapshots) for specified mode."""
        if mode.lower() == "paper":
            snaps_path = PAPER_SNAPSHOTS
        else:
            snaps_path = BT_SNAPSHOTS
        df = _safe_read_csv(snaps_path)
        if not df.empty and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df

    def get_trades(self, mode: str = "backtest") -> pd.DataFrame:
        """Return trades DataFrame for specified mode."""
        path = PAPER_TRADES if mode.lower() == "paper" else BT_TRADES
        df = _safe_read_csv(path)
        if not df.empty and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df

    def get_positions(self, mode: str = "backtest") -> pd.DataFrame:
        """Return positions DataFrame for specified mode (if present)."""
        path = PAPER_POSITIONS if mode.lower() == "paper" else BT_POSITIONS
        df = _safe_read_csv(path)
        if not df.empty and "timestamp" in df.columns:
            df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
            df = df.dropna(subset=["timestamp"]).sort_values("timestamp")
        return df