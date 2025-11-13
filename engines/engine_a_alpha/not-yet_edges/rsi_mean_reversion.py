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
    if isinstance(series, pd.DataFrame):
        if "Close" in series.columns:
            series = series["Close"]
        else:
            series = series.iloc[:, 0]

    s = pd.Series(series).astype(float).squeeze()
    delta = s.diff()

    up = delta.clip(lower=0).ewm(alpha=1/window, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1/window, adjust=False).mean()

    rs = up / down.replace(0, np.nan)
    rsi = 100 - (100 / (1 + rs))
    return pd.Series(rsi, index=s.index, dtype=float)


class RSIMeanReversionEdge(BaseEdge):
    EDGE_ID = EDGE_ID
    CATEGORY = CATEGORY

    def __init__(self, params: Dict[str, Any] | None = None) -> None:
        super().__init__(params or {})
        p = self.params
        self.rsi_window = int(p.get("rsi_window", 14))
        self.ma_window = int(p.get("ma_window", 200))
        self.lower_band = float(p.get("rsi_lower", 45.0))
        self.upper_band = float(p.get("rsi_upper", 55.0))
        self.min_price = float(p.get("min_price", 5.0))
        self.conf_base = float(p.get("confidence_base", 0.7))

    def _confidence(self, rsi_val: float) -> float:
        depth = abs(50 - rsi_val) / 50.0
        return float(min(0.95, self.conf_base + 0.25 * depth))

    def _build_meta(self, tkr: str, rsi_val: float, ma_val: float, price: float) -> Dict[str, Any]:
        return {
            "explain": f"RSI({self.rsi_window})={rsi_val:.1f}, MA({self.ma_window})={ma_val:.2f}, Price={price:.2f}",
            "edges_triggered": [
                {"edge": self.EDGE_ID, "signal": float(abs(50 - rsi_val)), "weight": 1.0}
            ],
            "params": {
                "rsi_window": self.rsi_window,
                "ma_window": self.ma_window,
                "lower_band": self.lower_band,
                "upper_band": self.upper_band,
            },
        }

    def generate_signals(self, slice_map: Dict[str, pd.DataFrame], ts) -> List[Dict[str, Any]]:
        if not slice_map:
            return []

        import os
        signals: List[Dict[str, Any]] = []
        ts = pd.to_datetime(ts).normalize()

        for tkr, df in slice_map.items():
            try:
                if df is None or df.empty or "Close" not in df.columns:
                    continue

                df.index = pd.to_datetime(df.index).normalize()
                df_hist = df.loc[:ts]
                if df_hist.empty:
                    continue

                closes = df_hist["Close"].astype(float)
                if closes.iloc[-1] < self.min_price:
                    continue

                rsi = _rsi(closes, self.rsi_window)
                ma = closes.rolling(self.ma_window, min_periods=1).mean()

                rsi_now = float(rsi.iloc[-1])
                ma_now = float(ma.iloc[-1])
                price_now = float(closes.iloc[-1])

                if os.getenv("ALPHA_DEBUG") == "1":
                    print(f"[EDGE][DEBUG][{self.EDGE_ID}] {tkr}: rsi_now={rsi_now:.2f}, ma_now={ma_now:.2f}, price_now={price_now:.2f}")

                # Mean reversion logic (balanced mode)
                if rsi_now < self.lower_band and price_now > ma_now:
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
                    signals.append(sig)
                elif rsi_now > self.upper_band and price_now < ma_now:
                    conf = self._confidence(rsi_now)
                    sig = Signal(
                        ticker=tkr,
                        side="short",
                        confidence=conf,
                        edge_id=self.EDGE_ID,
                        category=self.CATEGORY,
                        price_hint=price_now,
                        meta=self._build_meta(tkr, rsi_now, ma_now, price_now),
                    ).to_dict()
                    sig["edge"] = self.EDGE_ID
                    signals.append(sig)
                elif rsi_now > self.upper_band and price_now > ma_now:
                    # Exit from long if RSI high in uptrend
                    sig = Signal(
                        ticker=tkr,
                        side="exit",
                        confidence=0.6,
                        edge_id=self.EDGE_ID,
                        category=self.CATEGORY,
                        price_hint=price_now,
                        meta={"explain": f"Exit long: RSI={rsi_now:.1f} > {self.upper_band}"},
                    ).to_dict()
                    sig["edge"] = self.EDGE_ID
                    signals.append(sig)

            except Exception as e:
                if os.getenv("ALPHA_DEBUG") == "1":
                    print(f"[EDGE][ERROR][{self.EDGE_ID}] {tkr}: {e}")
                continue

        if os.getenv("ALPHA_DEBUG") == "1":
            sides = [s["side"] for s in signals]
            print(f"[EDGE][DEBUG][{self.EDGE_ID}] Generated {len(signals)} signals ({sides}) at {ts}")

        return signals

    def explain(self, signal: Dict[str, Any]) -> str:
        t = signal.get("ticker", "?")
        side = signal.get("side", "?")
        meta = signal.get("meta", {}) or {}
        ex = meta.get("explain", "")
        return f"[{self.EDGE_ID}] {t}: {side} — {ex}"


_EDGE = RSIMeanReversionEdge(params=None)

def generate_signals(slice_map: Dict[str, pd.DataFrame], ts) -> List[Dict[str, Any]]:
    return _EDGE.generate_signals(slice_map, ts)

def compute_signals(data_map: Dict[str, pd.DataFrame], now: pd.Timestamp) -> Dict[str, float]:
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
        score = (50 - val) / 50.0
        results[tkr] = max(-1.0, min(1.0, score))
    return results

try:
    reg = EdgeRegistry()
    reg.ensure(EdgeSpec(
        edge_id=EDGE_ID,
        category=CATEGORY,
        module=MODULE_NAME,
        version="1.0.0",
        params=_EDGE.params,
        status="active",
    ))
except Exception:
    pass