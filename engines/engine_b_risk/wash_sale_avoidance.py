"""Wash-sale avoidance — refuse buys within 30 days of a loss-realizing exit.

Why this exists:
    Per `project_tax_drag_kills_after_tax_2026_05_02.md`, the IRS wash-sale
    rule disallowed $17,343 of losses on the prod-109 2025 OOS run because
    the strategy re-trades the same tickers continuously. Disallowed losses
    don't reduce the year's tax bill — gains are still taxed in full while
    losses are deferred into the new lot's basis. For a high-turnover
    retail strategy this is a structural drag bigger than any single
    engineering improvement.

What this module does:
    Maintains a per-ticker ledger of recent loss-realizing exits. When
    Engine B is asked to open a new long position on a ticker that had a
    loss-realizing close within `window_days` (default 30, matching IRS),
    the buy is refused. This prevents the wash-sale loss disallowance at
    the source rather than absorbing it as drag.

Engine boundary: this is a risk constraint on entries (Engine B's
domain). The module is owned by `RiskEngine`; `BacktestController` /
`PaperTradeController` push fills into it via `RiskEngine.record_fill`.

Default: ``enabled=False`` for backward compat. Flag lives in
``config/portfolio_settings.json`` and is threaded through
``ModeController`` into ``RiskEngine``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional

import pandas as pd


@dataclass
class WashSaleAvoidanceConfig:
    enabled: bool = False
    window_days: int = 30  # IRS rule, calendar days
    # Loss threshold below which a closed lot is NOT recorded as a loss
    # (avoids tagging tiny round-trip noise as wash-sale-blocking).
    min_loss_dollars: float = 1.0


class WashSaleAvoidance:
    """Per-ticker recent-loss ledger consulted at order-entry time.

    Public API:
        record_fill(fill, ts) — call after every fill. Closing fills
            (side='exit'|'cover') with pnl < 0 are ledger-recorded.
        should_block_buy(ticker, now) — True if ticker had a loss-realizing
            close within window_days of `now`.
        stats — dict of fire-counts (proposed/blocked) for diagnostics.
        reset() — clear ledger and counters (used by A/B harness).
    """

    def __init__(self, cfg: Optional[WashSaleAvoidanceConfig] = None):
        self.cfg = cfg or WashSaleAvoidanceConfig()
        self._last_loss_exit: Dict[str, pd.Timestamp] = {}
        self._n_proposed: int = 0
        self._n_blocked: int = 0
        self._n_loss_exits_recorded: int = 0

    def reset(self) -> None:
        self._last_loss_exit.clear()
        self._n_proposed = 0
        self._n_blocked = 0
        self._n_loss_exits_recorded = 0

    @property
    def stats(self) -> dict:
        return {
            "enabled": self.cfg.enabled,
            "buys_proposed": self._n_proposed,
            "buys_blocked": self._n_blocked,
            "block_rate": (self._n_blocked / self._n_proposed) if self._n_proposed else 0.0,
            "loss_exits_recorded": self._n_loss_exits_recorded,
        }

    def record_fill(self, fill: dict, ts) -> None:
        """Push a fill into the ledger. Only loss-realizing closes register."""
        if not self.cfg.enabled or fill is None:
            return
        side = str(fill.get("side", "")).lower()
        if side not in ("exit", "cover"):
            return
        try:
            pnl = float(fill.get("pnl", 0.0))
        except Exception:
            return
        if pnl >= -abs(float(self.cfg.min_loss_dollars)):
            return  # not a meaningful loss; don't tag the ticker
        ticker = str(fill.get("ticker", ""))
        if not ticker:
            return
        try:
            t = pd.Timestamp(ts)
        except Exception:
            return
        prev = self._last_loss_exit.get(ticker)
        # Keep the most recent loss-exit timestamp.
        if prev is None or t > prev:
            self._last_loss_exit[ticker] = t
            self._n_loss_exits_recorded += 1

    def should_block_buy(self, ticker: str, now) -> bool:
        """True iff `ticker` had a loss-realizing close within window_days of `now`."""
        if not self.cfg.enabled:
            return False
        self._n_proposed += 1
        last_loss = self._last_loss_exit.get(ticker)
        if last_loss is None:
            return False
        try:
            now_ts = pd.Timestamp(now)
        except Exception:
            return False
        delta_days = (now_ts - last_loss).days
        if 0 <= delta_days <= int(self.cfg.window_days):
            self._n_blocked += 1
            return True
        return False
