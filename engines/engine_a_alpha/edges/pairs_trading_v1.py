"""
engines/engine_a_alpha/edges/pairs_trading_v1.py
================================================

Cointegration-based pairs-trading edge framework (T-2026-05-09-017).

Mechanism (per pair P = (X, Y)):
- Spread:   s_t = log(Y_t) - β · log(X_t)
            β is the cointegration coefficient estimated by the
            substrate-honest screen (`scripts/cointegration_pair_screen.py`).
- z-score:  z_t = (s_t - mean(s)) / std(s)  over a rolling lookback.
- Entry:    z_t <= -z_entry  →  long Y, short X  (Y is cheap on the spread)
            z_t >= +z_entry  →  short Y, long X  (Y is rich)
- Stop:     |z_t| >= z_stop  →  flat (spread broken — exit)
- Exit:     |z_t| <= z_exit  →  flat (mean-reverted)
- Otherwise (between bands)  →  flat (stateless v1; the entry threshold
            is wide enough that the market spends most of its time
            in the inactive zone). Stateful hysteresis is a follow-up.

The edge maps to the project's signal contract (`{ticker: float in [-1, 1]}`):
- The "long Y / short X" side becomes Y=+1.0, X=-1.0.
- The "short Y / long X" side becomes Y=-1.0, X=+1.0.
- Tickers outside the pair receive abstain (0.0).

WHY ONE FILE FOR ALL PAIRS:
- Same statistical machinery (rolling z, threshold logic) for every
  pair; only β + (ticker_x, ticker_y) vary.
- Implementing 10 separate edge files would copy-paste the same body.
- Per-instance config is delivered via the registry's `params` dict
  (mode_controller calls `edge_class(params=params)` per spec).

THE BETA IS NOT TUNED PER-PAIR:
- β is the OUTPUT of the cointegration screen on the in-sample window.
  It's a fitted estimate, not a tuned hyper-parameter. Tuning would
  be flipping z_entry, z_exit, z_stop per pair — we DELIBERATELY share
  those across the full pair inventory (the brief's hard constraint
  against per-pair tuning).

REGISTRATION:
- Auto-registers one EdgeSpec per surviving pair from
  `data/research/cointegrated_pairs_2026_05_09.json`.
- Each spec uses the same `module=__name__` and class
  `PairsTradingEdge`; per-instance config (ticker_x, ticker_y, beta,
  pair_id) lives in the spec's `params` field.
- All specs auto-register at `status='paused' tier='feature'`. They
  feed the meta-learner / lifecycle gauntlet at 0.25× weight (per
  project_soft_pause_win_2026_04_24); they do NOT trade in production
  until the gauntlet validates them.

BEHAVIOR WHEN MANIFEST IS MISSING:
- The screen's output is read at module-import time. If the file is
  missing (e.g., fresh checkout before the screen has been run), the
  module imports cleanly without registering any pair instances —
  no crash, but also no pair edges in inventory. Run the screen
  (`python scripts/cointegration_pair_screen.py`) to populate.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("PairsTradingEdge")


# ---------------------------------------------------------------------------
# Default thresholds — SHARED across the whole pair inventory by design.
# Per-pair tuning is overfitting; the brief explicitly forbids it.
# ---------------------------------------------------------------------------
SHARED_DEFAULTS: Dict[str, Any] = {
    # Pair-specific (filled in per-instance from the screen manifest).
    "ticker_x": "",
    "ticker_y": "",
    "beta": 1.0,         # cointegration coefficient (log_y on log_x)
    "pair_id": "",       # short label, e.g. "MA_V"

    # Shared signal logic — DO NOT tune per pair.
    "lookback_days": 60,   # rolling window for spread mean/std (z-score basis)
    "z_entry": 2.0,        # enter when |z| >= this
    "z_exit": 0.5,         # mean-reverted; flatten
    "z_stop": 4.0,         # blow-out stop; flatten
    "min_history_bars": 60,  # need at least lookback bars of aligned history

    # Signal magnitudes. Symmetric long/short by construction.
    "long_score": 1.0,
    "short_score": -1.0,
}

MANIFEST_PATH = Path("data/research/cointegrated_pairs_2026_05_09.json")


class PairsTradingEdge(EdgeBase):
    """Single-pair cointegration mean-reversion edge.

    Each instance is bound to a (ticker_x, ticker_y, beta) triple via
    the params dict supplied by the EdgeRegistry at load time. The
    same class powers all surviving pairs; per-pair config is the
    only difference between instances.
    """

    EDGE_ID = "pairs_trading_v1"  # base id; per-instance overrides via spec
    CATEGORY = "pairs_trading"
    DESCRIPTION = (
        "Cointegration-based pairs trading. Spread z-score with shared "
        "entry/exit/stop bands across the surviving pair inventory. "
        "β estimated offline by scripts/cointegration_pair_screen.py."
    )

    DEFAULT_PARAMS = dict(SHARED_DEFAULTS)

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__()
        self.params = dict(self.DEFAULT_PARAMS)
        if params:
            self.params.update(params)

    @classmethod
    def sample_params(cls) -> Dict[str, Any]:
        return dict(cls.DEFAULT_PARAMS)

    # ----------------------------- core math ----------------------------- #
    def _aligned_log_closes(
        self,
        df_x: pd.DataFrame,
        df_y: pd.DataFrame,
        now: pd.Timestamp,
        lookback: int,
    ) -> Optional[tuple[np.ndarray, np.ndarray]]:
        """Return (log_x, log_y) numpy arrays aligned on common dates,
        ending at or before ``now``, with at least ``lookback`` bars.
        Returns None if either leg lacks Close, the ticker dataframes
        have insufficient overlap, or any non-finite log emerges.
        """
        if (
            df_x is None
            or df_y is None
            or "Close" not in df_x.columns
            or "Close" not in df_y.columns
        ):
            return None

        cx = pd.to_numeric(df_x["Close"], errors="coerce").dropna()
        cy = pd.to_numeric(df_y["Close"], errors="coerce").dropna()
        cx = cx[cx > 0]
        cy = cy[cy > 0]
        if cx.empty or cy.empty:
            return None

        # Cap at the as-of timestamp on each side.
        cx = cx[cx.index <= now]
        cy = cy[cy.index <= now]
        if cx.empty or cy.empty:
            return None

        common = cx.index.intersection(cy.index)
        if len(common) < lookback:
            return None
        # Take the trailing `lookback` bars of aligned data.
        common_tail = common[-lookback:]
        log_x = np.log(cx.loc[common_tail].values)
        log_y = np.log(cy.loc[common_tail].values)
        if not (np.all(np.isfinite(log_x)) and np.all(np.isfinite(log_y))):
            return None
        return log_x, log_y

    def _zscore_now(
        self, log_x: np.ndarray, log_y: np.ndarray, beta: float,
    ) -> Optional[float]:
        """Compute z-score of the most recent spread observation
        relative to the rolling-window mean/std. Returns None if std
        is degenerate.
        """
        spread = log_y - beta * log_x
        mu = float(np.mean(spread))
        sd = float(np.std(spread, ddof=1))
        if not np.isfinite(sd) or sd <= 0:
            return None
        return float((spread[-1] - mu) / sd)

    # ----------------------------- contract ------------------------------ #
    def compute_signals(
        self, data_map: Dict[str, pd.DataFrame], now: pd.Timestamp,
    ) -> Dict[str, float]:
        ticker_x = str(self.params.get("ticker_x") or "")
        ticker_y = str(self.params.get("ticker_y") or "")
        beta = float(self.params.get("beta", 1.0))
        lookback = int(self.params.get("lookback_days", 60))
        z_entry = float(self.params.get("z_entry", 2.0))
        z_exit = float(self.params.get("z_exit", 0.5))
        z_stop = float(self.params.get("z_stop", 4.0))
        long_score = float(self.params.get("long_score", 1.0))
        short_score = float(self.params.get("short_score", -1.0))

        # Default: abstain on every ticker in the data_map.
        out: Dict[str, float] = {ticker: 0.0 for ticker in data_map}

        if not ticker_x or not ticker_y:
            return out  # mis-configured spec; abstain

        df_x = data_map.get(ticker_x)
        df_y = data_map.get(ticker_y)
        if df_x is None or df_y is None:
            # One leg missing from the data_map (universe doesn't cover it).
            # Pairs trading requires BOTH legs simultaneously; abstain on
            # the entire universe — emitting half a pair is structurally
            # incoherent.
            return out

        aligned = self._aligned_log_closes(df_x, df_y, now, lookback)
        if aligned is None:
            return out
        log_x, log_y = aligned

        z = self._zscore_now(log_x, log_y, beta)
        if z is None:
            return out

        # Stop overrides everything else.
        if abs(z) >= z_stop:
            return out  # already 0/abstain

        if z <= -z_entry:
            # Y is cheap on the spread (log_y is below its β · log_x line).
            # Long Y, short X.
            out[ticker_y] = long_score
            out[ticker_x] = short_score
        elif z >= +z_entry:
            # Y is rich; short Y, long X.
            out[ticker_y] = short_score
            out[ticker_x] = long_score
        # Between -z_entry and +z_entry (including the |z|<z_exit region):
        # stateless abstain. Stateful "hold-while-in-trade" is a follow-up.

        return out


# ---------------------------------------------------------------------------
# Auto-register one EdgeSpec per surviving pair, all using the same
# `PairsTradingEdge` class. Per-instance config is in `spec.params`.
# Mode_controller's loader reads `spec.params` and passes them to
# `PairsTradingEdge(params=...)` at instantiation time.
# ---------------------------------------------------------------------------
def _load_survivor_specs() -> List[Dict[str, Any]]:
    """Read the cointegration screen manifest and return one config
    dict per surviving pair. Returns [] if the manifest is missing
    (fresh checkout, or screen never run).
    """
    if not MANIFEST_PATH.exists():
        log.warning(
            "Pairs cointegration manifest not found at %s — no pair edges "
            "will be registered. Run scripts/cointegration_pair_screen.py "
            "to populate.",
            MANIFEST_PATH,
        )
        return []
    try:
        payload = json.loads(MANIFEST_PATH.read_text())
    except json.JSONDecodeError as e:
        log.error("Pairs cointegration manifest at %s is malformed: %s", MANIFEST_PATH, e)
        return []
    candidates = payload.get("candidates") or []
    return [c for c in candidates if c.get("survives")]


def _build_pair_spec(survivor: Dict[str, Any]):
    """Build an EdgeSpec for one surviving pair. Imports lazily so
    test/sandbox imports of this module don't trigger registry I/O.
    """
    from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

    tx = str(survivor["ticker_x"])
    ty = str(survivor["ticker_y"])
    pair_id = f"{tx}_{ty}"
    edge_id = f"pairs_trading_{pair_id}_v1"

    params = dict(SHARED_DEFAULTS)
    params["ticker_x"] = tx
    params["ticker_y"] = ty
    params["beta"] = float(survivor["beta"])
    params["pair_id"] = pair_id

    return EdgeRegistry, EdgeSpec(
        edge_id=edge_id,
        category=PairsTradingEdge.CATEGORY,
        module=__name__,
        version="1.0.0",
        params=params,
        status="paused",
        tier="feature",
    )


# Module-import side-effect: ensure registration. Wrapped in try/except
# matching the pattern in calendar_anomaly_edge.py / momentum_12_1_v1.py
# so a registry I/O hiccup never breaks edge-module import.
try:
    _survivors = _load_survivor_specs()
    for _surv in _survivors:
        _Reg, _spec = _build_pair_spec(_surv)
        _Reg().ensure(_spec)
        log.debug("Registered pair edge %s", _spec.edge_id)
except Exception as e:  # pragma: no cover — defensive, mirrors peers
    log.warning("Pair-edge auto-registration skipped: %s: %s", type(e).__name__, e)
