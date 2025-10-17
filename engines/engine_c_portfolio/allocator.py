# engines/engine_c_portfolio/allocator.py
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Iterable, List, Tuple
import math
import pandas as pd


@dataclass
class AllocatorConfig:
    max_names_long: int = 5
    max_names_short: int = 5
    per_name_cap: float = 0.25   # cap within each bucket
    min_abs_score: float = 0.03  # must exceed alpha threshold
    use_inverse_atr: bool = True


class EngineCAllocator:
    """
    Portfolio-level selection & diversification.
    Inputs: per-ticker alpha scores + last row (with ATR)
    Output: subset of tickers to trade (and weights, if desired for future sizing)
    """

    def __init__(self, cfg: Dict | None = None):
        c = cfg or {}
        self.cfg = AllocatorConfig(
            max_names_long=int(c.get("max_names_long", 5)),
            max_names_short=int(c.get("max_names_short", 5)),
            per_name_cap=float(c.get("per_name_cap", 0.25)),
            min_abs_score=float(c.get("min_abs_score", 0.03)),
            use_inverse_atr=bool(c.get("use_inverse_atr", True)),
        )

    def _score_with_vol_penalty(self, score: float, atr: float) -> float:
        if not self.cfg.use_inverse_atr:
            return score
        # small epsilon to avoid div-by-zero
        return score / max(atr, 1e-9)

    def select(self, scored: Dict[str, Dict], last_rows: Dict[str, pd.Series]) -> Tuple[List[str], List[str], Dict[str, float]]:
        """
        scored:  {ticker: {"score": float, "side": "long|short|none", "contrib":[...]}}
        last_rows: {ticker: last_row_series_with_ATR}
        returns: (long_list, short_list, weights_dict)
                 weights_dict is normalized within each bucket (optional use later)
        """
        longs: List[Tuple[str, float]] = []
        shorts: List[Tuple[str, float]] = []

        for tkr, d in scored.items():
            side = d.get("side", "none")
            score = float(d.get("score", 0.0))
            if side == "none" or abs(score) < self.cfg.min_abs_score:
                continue
            atr = float(last_rows.get(tkr, {}).get("ATR", 0.0))
            eff = self._score_with_vol_penalty(abs(score), atr)

            if side == "long":
                longs.append((tkr, eff))
            else:
                shorts.append((tkr, eff))

        # rank & cap count
        longs.sort(key=lambda x: x[1], reverse=True)
        shorts.sort(key=lambda x: x[1], reverse=True)
        longs = longs[: self.cfg.max_names_long]
        shorts = shorts[: self.cfg.max_names_short]

        def norm_and_cap(items: List[Tuple[str, float]]) -> Dict[str, float]:
            total = sum(w for _, w in items) or 1.0
            raw = {t: w / total for t, w in items}
            # per-name cap then renormalize
            capped = {t: min(w, self.cfg.per_name_cap) for t, w in raw.items()}
            csum = sum(capped.values()) or 1.0
            return {t: w / csum for t, w in capped.items()}

        w_long = norm_and_cap(longs)
        w_short = norm_and_cap(shorts)

        selected_longs = list(w_long.keys())
        selected_shorts = list(w_short.keys())
        weights = {**w_long, **w_short}  # handy later if we teach B to hit target weights

        return selected_longs, selected_shorts, weights