from __future__ import annotations

from typing import Dict, List, Any
import pandas as pd
import numpy as np

from .base import BaseEdge, Signal
from ..edge_registry import EdgeRegistry, EdgeSpec


EDGE_ID = "rsi_mean_reversion_v1"
MODULE_NAME = "rsi_mean_reversion"
CATEGORY = "technical"


def _rsi(series: pd.Series | pd.DataFrame, window: int = 14) -> pd.Series:
    """Classic RSI implementation (Wilder’s smoothing approximation, guaranteed 1D-safe)."""
    # If given a DataFrame (e.g. from yfinance), extract the first column
    if isinstance(series, pd.DataFrame):
        if "Close" in series.columns:
            series = series["Close"]
        else:
            series = series.iloc[:, 0]

    s = pd.Series(series).astype(float).squeeze()  # ensure 1D
    delta = s.diff()

    up = delta.clip(lower=0).ewm(alpha=1/window, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/window, adjust=False).mean()

    rs = up / down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))

    # ensure 1D output
    if isinstance(rsi, pd.DataFrame):
        rsi = rsi.iloc[:, 0]
    elif isinstance(rsi, np.ndarray) and rsi.ndim > 1:
        rsi = np.ravel(rsi)

    return pd.Series(rsi, index=s.index, dtype=float)



class RSIMeanReversionEdge(BaseEdge):
    """
    RSI Mean Reversion (v1):
      - Entry (long): RSI < buy_threshold AND Close > MA(200)  (buy dips in uptrend)
      - Exit: RSI > exit_threshold

    Signals are generated bar-by-bar, using only history up to `ts`.
    Risk sizing/SL/TP handled downstream in RiskEngine.
    """

    EDGE_ID = EDGE_ID
    CATEGORY = CATEGORY

    def __init__(self, params: Dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        # Reasonable defaults; can be overridden via edge_config.json in future
        p = self.params
        self.rsi_window = int(p.get("rsi_window", 14))
        self.ma_window = int(p.get("ma_window", 200))
        self.buy_threshold = float(p.get("rsi_buy", 30.0))
        self.exit_threshold = float(p.get("rsi_exit", 50.0))
        self.min_price = float(p.get("min_price", 5.0))  # ignore penny stocks
        self.conf_base = float(p.get("confidence_base", 0.7))

    def _confidence(self, rsi_val: float) -> float:
        # Simple mapping: deeper oversold → higher confidence up to 0.95
        try:
            depth = max(0.0, min(1.0, (self.buy_threshold - rsi_val) / max(1.0, self.buy_threshold)))
            return float(min(0.95, self.conf_base + 0.25 * depth))
        except Exception:
            return float(self.conf_base)

    def _build_meta(self, tkr: str, rsi_val: float, ma_val: float, price: float) -> Dict[str, Any]:
        return {
            "explain": f"RSI({self.rsi_window})={rsi_val:.1f}, MA({self.ma_window})={ma_val:.2f}, Price={price:.2f}",
            "edges_triggered": [
                {"edge": self.EDGE_ID, "signal": float(max(0.0, self.buy_threshold - rsi_val)), "weight": 1.0}
            ],
            "params": {
                "rsi_window": self.rsi_window,
                "ma_window": self.ma_window,
                "buy_threshold": self.buy_threshold,
                "exit_threshold": self.exit_threshold,
            },
        }

    def generate_signals(self, slice_map: Dict[str, pd.DataFrame], ts) -> List[Dict[str, Any]]:
        if not slice_map:
            return []

        signals: List[Dict[str, Any]] = []

        # Normalize ts to naive for safe indexing (BacktestController already uses naive)
        ts = pd.to_datetime(ts)
        ts = ts.normalize()

        for tkr, df in slice_map.items():
            try:
                if df is None or df.empty or "Close" not in df.columns:
                    continue

                df.index = pd.to_datetime(df.index)
                df.index = df.index.normalize()

                # Work with full history up to ts
                if ts not in df.index:
                    # Use the latest bar <= ts
                    df_hist = df.loc[:ts]
                    if df_hist.empty:
                        continue
                else:
                    # Slice inclusive
                    df_hist = df.loc[:ts]

                closes = df_hist["Close"].astype(float)
                if closes.iloc[-1] < self.min_price:
                    continue

                rsi = _rsi(closes, self.rsi_window)
                ma = closes.rolling(self.ma_window, min_periods=1).mean()

                rsi_now = float(rsi.iloc[-1])
                ma_now = float(ma.iloc[-1])
                price_now = float(closes.iloc[-1])

                # Entry: oversold in uptrend
                if rsi_now < self.buy_threshold and price_now > ma_now:
                    conf = self._confidence(rsi_now)
                    sig = Signal(
                        ticker=tkr,
                        side="long",
                        confidence=conf,
                        edge_id=self.EDGE_ID,
                        category=self.CATEGORY,
                        price_hint=price_now,
                        meta=self._build_meta(tkr, rsi_now, ma_now, price_now),
                    ).to_dict()
                    sig["edge"] = self.EDGE_ID
                    sig["edge_id"] = self.EDGE_ID
                    sig["category"] = self.CATEGORY
                    signals.append(sig)
                    continue

                # Exit: momentum restored
                if rsi_now > self.exit_threshold:
                    sig = Signal(
                        ticker=tkr,
                        side="exit",
                        confidence=0.6,
                        edge_id=self.EDGE_ID,
                        category=self.CATEGORY,
                        price_hint=price_now,
                        meta={"explain": f"Exit: RSI({self.rsi_window})={rsi_now:.1f} > {self.exit_threshold}"},
                    ).to_dict()
                    sig["edge"] = self.EDGE_ID
                    sig["edge_id"] = self.EDGE_ID
                    sig["category"] = self.CATEGORY
                    signals.append(sig)

            except Exception:
                continue

        return signals

    # Optional: nicer explanation for dashboards
    def explain(self, signal: Dict[str, Any]) -> str:
        t = signal.get("ticker", "?")
        side = signal.get("side", "?")
        meta = signal.get("meta", {}) or {}
        ex = meta.get("explain", "")
        return f"[{self.EDGE_ID}] {t}: {side} — {ex}"


# ----------------- Module-level API (backward compatible) ----------------- #

# Singleton instance used by module-level function
_EDGE = RSIMeanReversionEdge(params=None)

def generate_signals(slice_map: Dict[str, pd.DataFrame], ts) -> List[Dict[str, Any]]:
    """
    Backward-compatible entry point expected by AlphaEngine.
    """
    return _EDGE.generate_signals(slice_map, ts)

def compute_signals(data_map: Dict[str, pd.DataFrame], now: pd.Timestamp) -> Dict[str, float]:
    """
    Simplified compute_signals interface for AlphaEngine compatibility.
    Returns dict[ticker -> raw_score] where positive = long bias, negative = short bias.
    """
    results = {}
    for tkr, df in data_map.items():
        if df is None or df.empty or "Close" not in df.columns:
            continue

        closes = df["Close"].astype(float)
        if len(closes) < 15:
            continue

        rsi = _rsi(closes)
        if rsi.empty:
            continue

        val = float(rsi.iloc[-1])
        # Normalize RSI: oversold→positive bias, overbought→negative bias
        score = (50 - val) / 50.0  # +1 when RSI=0, -1 when RSI=100
        results[tkr] = max(-1.0, min(1.0, score))
    return results

# Ensure the registry knows about this edge (idempotent on import)
try:
    reg = EdgeRegistry()
    reg.ensure(EdgeSpec(
        edge_id=EDGE_ID,
        category=CATEGORY,
        module=MODULE_NAME,
        version="1.0.0",
        params=_EDGE.params,
        status="active",  # default active; can be changed by governor later
    ))
except Exception:
    # Registry is optional if file is not writable; edge still works by module import.
    pass