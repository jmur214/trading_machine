"""Long-term hold preference — defer signal-driven exits past 365 days
when the tax-rate delta exceeds expected alpha lift.

Why this exists:
    Per `project_tax_drag_kills_after_tax_2026_05_02.md`, federal short-
    term cap-gains rate is ~30% but long-term (≥365 days) is ~15%. For a
    profitable position held 300-364 days, exiting 1+ day early costs an
    extra 15% of the realized gain in tax. Holding past day 365 captures
    the rate delta — often a larger expected dollar value than the next
    rebalance's marginal alpha.

What this module does:
    Tracks per-ticker entry timestamps as fills stream in. When Engine A
    signals a neutral exit on a position currently held in the
    `[defer_window_start_days, long_term_min_days)` window, this module
    compares the dollar value of the long-term tax saving against the
    expected alpha-lift of exiting now. If the tax saving dominates, the
    exit is deferred. A hard cap at `hard_cap_days` prevents indefinite
    deferral — once that age is reached, exits are always allowed
    (long-term treatment is locked in).

Engine boundary: this is an exit-side risk constraint (Engine B). The
module is owned by `RiskEngine` and consulted in `prepare_order` when a
neutral signal arrives on a ticker with an open position. Hard SL/TP
exits bypass this rule — protective exits must always fire.

Defaults: ``enabled=False`` (default-off so behavior on main is
unchanged). Flag in ``config/portfolio_settings.json`` is threaded
through ``ModeController`` into ``RiskEngine``.

Limitations / honest caveats:
- Entry-date tracking is updated on opening fills (long/short). If a
  ticker is partially closed then partially re-added, the entry resets
  on the first fully-closed → reopen cycle (matches FIFO accounting).
- Does not handle multiple tax lots — uses position-level avg entry,
  matching existing PortfolioEngine accounting (single-lot per ticker).
- Does not consider state tax. The federal 30%→15% delta is the dominant
  driver; state delta on top would only strengthen the deferral.
- Does NOT defer hard SL/TP exits. Those are protective and bypass this
  rule (loss/protection magnitude already dominates the tax delta).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional

import pandas as pd


@dataclass
class LTHoldPreferenceConfig:
    enabled: bool = False
    short_term_rate: float = 0.30
    long_term_rate: float = 0.15
    long_term_min_days: int = 365  # IRS rule: more than 1 year
    # Defer entries between this and long_term_min_days.
    defer_window_start_days: int = 300
    # Hard upper bound — once this many days have elapsed, lock in
    # long-term treatment and stop deferring further.
    hard_cap_days: int = 380
    # Don't defer if tax savings are below this many dollars.
    min_hold_savings_threshold: float = 50.0


class LTHoldPreference:
    """Defer signal-driven exits when long-term tax saving > alpha-lift.

    Public API:
        record_fill(fill, ts, post_fill_qty) — call after every fill.
            Maintains internal per-ticker entry-date ledger.
        should_defer_exit(ticker, current_qty, avg_price, current_price,
                          now, exit_alpha_value=0.0) -> bool
        stats — diagnostic counts (proposed/deferred/hard-capped)
        reset() — zero counters and ledger (for A/B harness reproducibility)

    Note: ``exit_alpha_value`` defaults to 0.0 because Engine A's neutral
    signal carries no expected-lift estimate. Callers with a richer alpha
    forecast may pass a non-zero value to override the rule.
    """

    def __init__(self, cfg: Optional[LTHoldPreferenceConfig] = None):
        self.cfg = cfg or LTHoldPreferenceConfig()
        self._entry_dt: Dict[str, pd.Timestamp] = {}
        self._n_proposed: int = 0
        self._n_deferred: int = 0
        self._n_hard_capped: int = 0

    def reset(self) -> None:
        self._entry_dt.clear()
        self._n_proposed = 0
        self._n_deferred = 0
        self._n_hard_capped = 0

    @property
    def stats(self) -> dict:
        return {
            "enabled": self.cfg.enabled,
            "exits_proposed": self._n_proposed,
            "exits_deferred": self._n_deferred,
            "exits_hard_capped": self._n_hard_capped,
            "defer_rate": (self._n_deferred / self._n_proposed) if self._n_proposed else 0.0,
            "tickers_tracked": len(self._entry_dt),
        }

    def record_fill(self, fill: dict, ts, post_fill_qty: Optional[int] = None) -> None:
        """Update the entry-date ledger from a fill.

        - Opening fill (side=long|short): set entry_dt if not already tracked.
        - Closing fill (side=exit|cover): if `post_fill_qty == 0`, clear entry_dt.
          When `post_fill_qty` is None we conservatively clear on any close
          (matches the strategy's full-close convention).
        """
        if not self.cfg.enabled or fill is None:
            return
        side = str(fill.get("side", "")).lower()
        ticker = str(fill.get("ticker", ""))
        if not ticker:
            return
        try:
            t = pd.Timestamp(ts)
        except Exception:
            return
        if side in ("long", "short"):
            self._entry_dt.setdefault(ticker, t)
        elif side in ("exit", "cover"):
            if post_fill_qty is None or int(post_fill_qty) == 0:
                self._entry_dt.pop(ticker, None)

    def get_entry_dt(self, ticker: str) -> Optional[pd.Timestamp]:
        return self._entry_dt.get(ticker)

    def should_defer_exit(
        self,
        ticker: str,
        current_qty: int,
        avg_price: float,
        current_price: float,
        now,
        exit_alpha_value: float = 0.0,
    ) -> bool:
        """Decide whether to defer a signal-driven exit.

        Returns True iff:
            1. Module is enabled.
            2. Position has a tracked entry_dt.
            3. Holding age is in [defer_window_start_days, long_term_min_days).
               (Past long-term, no further benefit; below window start, no rule.)
            4. Holding age is below hard_cap_days.
            5. Position has unrealized gain (tax savings only matter on gains).
            6. Tax saving (gain × rate_delta) exceeds:
                a. min_hold_savings_threshold (in dollars), AND
                b. exit_alpha_value (caller's estimate of value of exiting now).

        The hard-cap branch is recorded in stats — past hard_cap_days we
        always allow the exit (returns False) regardless of tax math.
        """
        if not self.cfg.enabled:
            return False
        try:
            qty = int(current_qty)
        except Exception:
            qty = 0
        if qty == 0:
            return False
        entry_ts = self._entry_dt.get(ticker)
        if entry_ts is None:
            return False
        try:
            now_ts = pd.Timestamp(now)
        except Exception:
            return False
        holding_days = (now_ts - entry_ts).days

        # Hard cap: never defer past this point.
        if holding_days >= int(self.cfg.hard_cap_days):
            self._n_hard_capped += 1
            return False
        if holding_days < int(self.cfg.defer_window_start_days):
            return False
        if holding_days >= int(self.cfg.long_term_min_days):
            return False

        self._n_proposed += 1

        try:
            ap = float(avg_price)
            cp = float(current_price)
        except Exception:
            return False
        if ap <= 0 or cp <= 0:
            return False

        if qty > 0:
            unrealized_gain = (cp - ap) * qty
        else:
            unrealized_gain = (ap - cp) * abs(qty)
        if unrealized_gain <= 0:
            return False

        rate_delta = float(self.cfg.short_term_rate) - float(self.cfg.long_term_rate)
        tax_savings = unrealized_gain * rate_delta

        if tax_savings < float(self.cfg.min_hold_savings_threshold):
            return False
        if tax_savings <= float(exit_alpha_value):
            return False

        self._n_deferred += 1
        return True
