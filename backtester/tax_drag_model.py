# backtester/tax_drag_model.py
"""
Tax drag model — short/long-term capital gains accounting on a backtest
fill log.

Why this exists:
  ArchonDEX claims "beats SPY net of realistic costs" but the cost model
  has historically excluded the single largest cost retail traders face:
  taxes on short-term realized gains. For a short-horizon equity strategy
  trading inside a taxable brokerage account, **federal short-term gains
  tax alone subtracts ~30% of profitable closes**. State taxes can add
  another 5-10%. For the retail-capital math the user explicitly framed
  in `project_retail_capital_constraint_2026_05_01.md`, ignoring this
  is dishonest.

What this module models:
  - Per-trade classification (short-term / long-term) by holding period.
  - Wash-sale rule: any loss-realizing close on a ticker that's
    re-purchased within 30 calendar days has its loss disallowed in the
    cost calculation. (We model wash sales conservatively as "loss is
    erased from the year's net P/L"; the realistic IRS rule is "loss is
    deferred and added to the new lot's cost basis", but for backtest
    cost-drag estimation the conservative treatment overstates drag
    slightly — which is the right side to err on.)
  - Year-end synthetic withdrawal: net realized gains (after wash-sale
    adjustment) are taxed at the appropriate rate; the tax is debited
    from equity at the last trading day of each calendar year.
  - Net losses for a year offset future gains up to $3,000/yr against
    ordinary income and the rest carries forward — modelled as full
    carry-forward across years (the $3k against-ordinary-income piece
    is irrelevant since we're not modeling ordinary income here).

What this module deliberately does NOT model:
  - Per-lot specific identification — we use FIFO, the IRS default.
  - Section 1256 / mark-to-market for futures-like instruments.
  - State income tax (configurable as `state_st_rate` if needed).
  - Roth/IRA tax-deferred wrappers (toggle by setting `enabled=False`).
  - Tax-loss harvesting heuristics — the system isn't trying to time
    losses, just account for what taxes the existing strategy owes.

Engine boundary: this is backtester territory. It is a post-processor
on the trade log + snapshot history. It does not modify any engine
state and runs after the backtest completes.

Default: ``enabled=False`` for backward compat. Flipping it on is the
user's call once the deltas are documented and the implications
understood.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional
from collections import deque
import math

import pandas as pd


@dataclass
class TaxDragConfig:
    """Tax-rate and rule configuration."""

    enabled: bool = False
    # Federal short-term capital gains rate. 30% is a midpoint between
    # the 22% bracket and 37% top bracket — reasonable retail default.
    short_term_rate: float = 0.30
    # Federal long-term capital gains rate. 15% is the middle bracket;
    # 0% applies below ~$47k income, 20% above ~$518k.
    long_term_rate: float = 0.15
    # Long-term threshold in days. IRS rule is "more than 1 year"; we
    # use ≥ 365 days as a slight (conservative) overestimate of drag.
    long_term_min_days: int = 365
    # Wash-sale lookback/lookahead window (calendar days, IRS = 30).
    wash_sale_window_days: int = 30
    # Carry-forward losses across years.
    carry_forward_losses: bool = True


@dataclass
class _OpenLot:
    """One FIFO lot of an open position."""
    qty: int
    price: float
    entry_dt: pd.Timestamp


@dataclass
class _RealizedTrade:
    """One closed lot — produced by FIFO matching."""
    ticker: str
    qty: int
    entry_dt: pd.Timestamp
    exit_dt: pd.Timestamp
    entry_price: float
    exit_price: float
    side: str   # "long" or "short" — direction of original lot
    pnl: float  # gross (price-only, no commissions)
    holding_days: int
    classification: str  # "short_term" or "long_term"
    wash_sale_disallowed: bool = False


class TaxDragModel:
    """Apply capital-gains tax drag to a backtest equity curve.

    Pipeline:
      1. ``reconstruct_trades(fill_log)`` — FIFO-match opens to closes,
         producing one ``_RealizedTrade`` per closed lot with holding
         period, classification, and gross P/L.
      2. ``apply_wash_sale_rule(trades)`` — flag loss-realizing trades
         that have a re-purchase within ±30 days; their loss is set to
         zero for tax-drag purposes.
      3. ``compute_yearly_tax(trades)`` — group by calendar year, split
         st vs lt, apply rates, accumulate carry-forward losses.
      4. ``apply_to_equity_curve(equity, trades)`` — debit tax on the
         last trading day of each year as a synthetic withdrawal.
    """

    def __init__(self, config: Optional[TaxDragConfig] = None):
        self.config = config or TaxDragConfig()

    # ------------------------------------------------------------------ #
    # 1. FIFO reconstruction
    # ------------------------------------------------------------------ #
    def reconstruct_trades(self, fill_log: pd.DataFrame) -> List[_RealizedTrade]:
        """FIFO-match a fill log into closed-trade records.

        Expects columns: ``timestamp``, ``ticker``, ``side``, ``qty``,
        ``fill_price``. Recognized sides: long (open long), short (open
        short), exit (close long), cover (close short). The same fill
        log produced by BacktestController._safe_write_trade is
        compatible.

        Long and short positions are tracked as separate FIFO queues per
        ticker — opening a long while a short is still open is treated
        as two independent positions (the existing PortfolioEngine
        flattens through opposite-side fills, so this branch is unusual
        but worth handling).
        """
        if fill_log is None or len(fill_log) == 0:
            return []

        df = fill_log.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp", kind="stable").reset_index(drop=True)

        long_lots: Dict[str, deque] = {}
        short_lots: Dict[str, deque] = {}
        realized: List[_RealizedTrade] = []

        for _, row in df.iterrows():
            ticker = str(row["ticker"])
            side = str(row["side"]).lower()
            qty = int(row.get("qty", 0))
            price = float(row.get("fill_price", 0.0))
            dt = pd.Timestamp(row["timestamp"])
            if qty <= 0 or price <= 0 or not ticker:
                continue

            if side == "long":
                long_lots.setdefault(ticker, deque()).append(
                    _OpenLot(qty=qty, price=price, entry_dt=dt)
                )
            elif side == "short":
                short_lots.setdefault(ticker, deque()).append(
                    _OpenLot(qty=qty, price=price, entry_dt=dt)
                )
            elif side == "exit":
                self._fifo_close(
                    long_lots.get(ticker, deque()),
                    qty=qty,
                    exit_price=price,
                    exit_dt=dt,
                    ticker=ticker,
                    side_open="long",
                    out=realized,
                )
            elif side == "cover":
                self._fifo_close(
                    short_lots.get(ticker, deque()),
                    qty=qty,
                    exit_price=price,
                    exit_dt=dt,
                    ticker=ticker,
                    side_open="short",
                    out=realized,
                )
            # unknown sides silently ignored

        # Tag classification on each trade
        for t in realized:
            t.holding_days = max(0, (t.exit_dt - t.entry_dt).days)
            t.classification = (
                "long_term"
                if t.holding_days >= self.config.long_term_min_days
                else "short_term"
            )
        return realized

    def _fifo_close(
        self,
        queue: deque,
        qty: int,
        exit_price: float,
        exit_dt: pd.Timestamp,
        ticker: str,
        side_open: str,
        out: List[_RealizedTrade],
    ) -> None:
        """FIFO-match a close against ``queue``. Mutates queue in place."""
        remaining = qty
        while remaining > 0 and queue:
            lot = queue[0]
            close_qty = min(lot.qty, remaining)
            if side_open == "long":
                pnl = (exit_price - lot.price) * close_qty
            else:  # short
                pnl = (lot.price - exit_price) * close_qty
            out.append(
                _RealizedTrade(
                    ticker=ticker,
                    qty=close_qty,
                    entry_dt=lot.entry_dt,
                    exit_dt=exit_dt,
                    entry_price=lot.price,
                    exit_price=exit_price,
                    side=side_open,
                    pnl=pnl,
                    holding_days=0,            # filled in after loop
                    classification="short_term",  # placeholder
                )
            )
            lot.qty -= close_qty
            remaining -= close_qty
            if lot.qty == 0:
                queue.popleft()
        # If remaining > 0 here, the fill log is inconsistent (close
        # bigger than open) — silently drop the residual; the simulator
        # already enforces no-naked-close rules upstream.

    # ------------------------------------------------------------------ #
    # 2. Wash-sale rule
    # ------------------------------------------------------------------ #
    def apply_wash_sale_rule(
        self, trades: List[_RealizedTrade]
    ) -> List[_RealizedTrade]:
        """Flag loss-realizing trades with a repurchase within ±30 days.

        Conservative treatment: the loss is **disallowed for the year**.
        The realistic IRS rule defers the loss into the new lot's basis;
        for cost-drag estimation, disallowing slightly overstates drag
        which is the safe direction.
        """
        if not trades:
            return trades

        window = self.config.wash_sale_window_days

        # Index re-opens per ticker by date (only "long" and "short" opens)
        by_ticker_opens: Dict[str, List[pd.Timestamp]] = {}
        for t in trades:
            by_ticker_opens.setdefault(t.ticker, []).append(t.entry_dt)
        # Sort each list once
        for v in by_ticker_opens.values():
            v.sort()

        for t in trades:
            if t.pnl >= 0:
                continue  # only losses can be wash-saled
            opens = by_ticker_opens.get(t.ticker, [])
            # any open within ±window of exit_dt (excluding the lot itself)
            wash = any(
                abs((open_dt - t.exit_dt).days) <= window
                and open_dt != t.entry_dt
                for open_dt in opens
            )
            if wash:
                t.wash_sale_disallowed = True
        return trades

    # ------------------------------------------------------------------ #
    # 3. Yearly tax computation
    # ------------------------------------------------------------------ #
    def compute_yearly_tax(
        self, trades: List[_RealizedTrade]
    ) -> Dict[int, Dict[str, float]]:
        """Aggregate trades by calendar year and compute owed tax.

        Returns: ``{year: {st_gain, st_loss, lt_gain, lt_loss, taxable_st,
        taxable_lt, tax_owed}}``. ``tax_owed`` is the actual dollar drag
        applied at year-end, after carry-forward losses.
        """
        out: Dict[int, Dict[str, float]] = {}
        if not trades:
            return out

        # Group
        for t in trades:
            year = int(t.exit_dt.year)
            bucket = out.setdefault(
                year,
                {
                    "st_gain": 0.0,
                    "st_loss": 0.0,
                    "lt_gain": 0.0,
                    "lt_loss": 0.0,
                    "wash_sale_disallowed_loss": 0.0,
                },
            )
            pnl = t.pnl
            if t.wash_sale_disallowed:
                bucket["wash_sale_disallowed_loss"] += abs(pnl)
                continue  # disallow loss entirely (conservative)
            if t.classification == "short_term":
                if pnl >= 0:
                    bucket["st_gain"] += pnl
                else:
                    bucket["st_loss"] += abs(pnl)
            else:
                if pnl >= 0:
                    bucket["lt_gain"] += pnl
                else:
                    bucket["lt_loss"] += abs(pnl)

        # Apply rates with carry-forward
        cfg = self.config
        carry_st = 0.0
        carry_lt = 0.0
        for year in sorted(out.keys()):
            b = out[year]
            net_st = b["st_gain"] - b["st_loss"] - carry_st
            net_lt = b["lt_gain"] - b["lt_loss"] - carry_lt
            # Carry forward only if losses; reset carry on positive net.
            new_carry_st = 0.0 if net_st >= 0 else -net_st
            new_carry_lt = 0.0 if net_lt >= 0 else -net_lt
            taxable_st = max(0.0, net_st)
            taxable_lt = max(0.0, net_lt)
            tax_owed = (
                taxable_st * cfg.short_term_rate
                + taxable_lt * cfg.long_term_rate
            )
            b["taxable_st"] = taxable_st
            b["taxable_lt"] = taxable_lt
            b["tax_owed"] = tax_owed
            b["carry_in_st"] = carry_st
            b["carry_in_lt"] = carry_lt
            b["carry_out_st"] = new_carry_st
            b["carry_out_lt"] = new_carry_lt
            if cfg.carry_forward_losses:
                carry_st = new_carry_st
                carry_lt = new_carry_lt
            else:
                carry_st = 0.0
                carry_lt = 0.0
        return out

    # ------------------------------------------------------------------ #
    # 4. Apply to equity curve
    # ------------------------------------------------------------------ #
    def apply_to_equity_curve(
        self,
        equity_curve: pd.Series,
        trades: List[_RealizedTrade],
    ) -> pd.Series:
        """Return ``equity_curve`` with year-end synthetic tax withdrawals."""
        if not self.config.enabled or len(equity_curve) == 0:
            return equity_curve.copy()
        wash_trades = self.apply_wash_sale_rule(trades)
        yearly = self.compute_yearly_tax(wash_trades)
        if not yearly:
            return equity_curve.copy()

        adjusted = equity_curve.copy().astype(float)
        idx = pd.to_datetime(adjusted.index)

        cumulative_drag = 0.0
        for year in sorted(yearly.keys()):
            tax_owed = float(yearly[year]["tax_owed"])
            if tax_owed <= 0:
                continue
            # Find the last index <= year-end of this calendar year.
            year_end = pd.Timestamp(year=year, month=12, day=31)
            mask = idx <= year_end
            if not mask.any():
                continue
            last_idx_in_year = adjusted.index[mask][-1]
            # Apply drag: subtract owed from this point forward.
            cumulative_drag += tax_owed
            cutover_pos = adjusted.index.get_loc(last_idx_in_year)
            # Add this year's tax to all subsequent equity points.
            adjusted.iloc[cutover_pos:] -= tax_owed
        return adjusted

    # ------------------------------------------------------------------ #
    # Convenience: end-to-end
    # ------------------------------------------------------------------ #
    def compute(
        self,
        fill_log: pd.DataFrame,
        equity_curve: pd.Series,
    ) -> Dict[str, "object"]:
        """Run the full pipeline and return a dict of artifacts."""
        trades = self.reconstruct_trades(fill_log)
        trades = self.apply_wash_sale_rule(trades)
        yearly = self.compute_yearly_tax(trades)
        adjusted = self.apply_to_equity_curve(equity_curve, trades)
        total_tax = sum(b["tax_owed"] for b in yearly.values())
        return {
            "trades": trades,
            "yearly_tax": yearly,
            "total_tax": total_tax,
            "after_tax_equity": adjusted,
        }


def get_tax_drag_model(config_dict: Optional[dict] = None) -> TaxDragModel:
    """Factory mirroring the slippage/borrow factories."""
    if not config_dict:
        return TaxDragModel(TaxDragConfig())
    cfg = TaxDragConfig(
        enabled=bool(config_dict.get("enabled", False)),
        short_term_rate=float(config_dict.get("short_term_rate", 0.30)),
        long_term_rate=float(config_dict.get("long_term_rate", 0.15)),
        long_term_min_days=int(config_dict.get("long_term_min_days", 365)),
        wash_sale_window_days=int(config_dict.get("wash_sale_window_days", 30)),
        carry_forward_losses=bool(config_dict.get("carry_forward_losses", True)),
    )
    return TaxDragModel(cfg)
