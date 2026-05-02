# backtester/alpaca_fees.py
"""
Alpaca fee model for backtest execution simulation.

Alpaca offers commission-free equity trading, but regulatory pass-through
fees still apply on sells. The fees a retail Alpaca account actually pays:

  1. **SEC Section 31 fee** — assessed on the dollar amount of every
     equity sale (long sells + short sales). The rate is set semi-annually
     by the SEC; the public posted rate as of 2026 is **$27.80 per
     $1,000,000 of principal**, i.e. 0.0000278 (0.278 bps).

  2. **FINRA Trading Activity Fee (TAF)** — assessed per share on every
     equity sale. The published rate is **$0.000166/share** with a maximum
     of **$8.30 per trade**. (That cap kicks in at exactly 50,000 shares
     per trade.)

Buys do not incur SEC or FINRA per-share fees. Long-only buys are free
under Alpaca; short opens (sell-to-open) and long closes (sell-to-close)
both pay both fees.

Sources for the published rates:
  - SEC: https://www.sec.gov/divisions/marketreg/mrfreqreq.htm (Section 31)
  - FINRA TAF: https://www.finra.org/rules-guidance/key-topics/regulatory-fees
  - Alpaca's pass-through model is documented at
    https://alpaca.markets/learn/trading-fees

All values in this module reflect the rates published as of 2026-05.
They change periodically; if you need pinpoint accuracy, override via
the config. (Order of magnitude for any equity backtest: a few tenths
of a basis point per round-trip.)
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class AlpacaFeesConfig:
    """Per-fill fee configuration. Defaults match Alpaca's 2026 published
    pass-through rates."""

    enabled: bool = True
    # SEC Section 31 fee (dollars per dollar of principal on sells).
    # Published rate: $27.80 / $1,000,000 = 0.0000278 of notional.
    sec_fee_per_dollar: float = 27.80 / 1_000_000.0  # 2.78e-5
    # FINRA TAF (dollars per share on sells, capped per trade).
    taf_per_share: float = 0.000166
    taf_max_per_trade: float = 8.30
    # Stocks are commission-free at Alpaca; this knob exists so callers
    # can simulate non-zero commission for cross-broker comparisons or
    # to stress-test cost sensitivity.
    base_commission: float = 0.0
    # Whether buys pay any of these fees. Default False; both SEC and
    # FINRA TAF are sell-side only by rule.
    buy_side_fees: bool = False


_SELL_SIDES = frozenset({"sell", "exit", "short"})
_BUY_SIDES = frozenset({"buy", "long", "cover"})


class AlpacaFees:
    """Compute per-fill regulatory pass-through + commission for Alpaca.

    Use as a fill-time cost model. Wired into ``ExecutionSimulator`` via
    its ``alpaca_fees`` constructor param so commission on every fill
    reflects the regulatory drag actually charged at the broker.

    A separate sweep-style application is available for post-processing
    when only a fill log is on hand (e.g. retroactive cost study).
    """

    def __init__(self, config: Optional[AlpacaFeesConfig] = None):
        self.config = config or AlpacaFeesConfig()

    @staticmethod
    def _is_sell_side(side: str) -> bool:
        return side.lower() in _SELL_SIDES

    @staticmethod
    def _is_buy_side(side: str) -> bool:
        return side.lower() in _BUY_SIDES

    # ------------------------------------------------------------------ #
    # Per-fill computation
    # ------------------------------------------------------------------ #
    def compute_fee(
        self,
        side: str,
        qty: int,
        fill_price: float,
    ) -> float:
        """Return total per-fill cost in dollars (>= 0).

        Components on a sell:
          fee = base_commission + sec_fee + taf
        Components on a buy:
          fee = base_commission (+ optional buy_side_fees)
        """
        if not self.config.enabled:
            return float(self.config.base_commission)

        if qty <= 0 or fill_price <= 0:
            return float(self.config.base_commission)

        cfg = self.config
        notional = float(qty) * float(fill_price)
        fee = float(cfg.base_commission)

        is_sell = self._is_sell_side(side)
        is_buy = self._is_buy_side(side)

        # Defensive: unknown side string → treat as buy (no extra fees)
        # rather than crashing the backtest; the existing ExecutionSimulator
        # already validates side strings upstream.
        if is_sell or (cfg.buy_side_fees and is_buy):
            sec_fee = notional * cfg.sec_fee_per_dollar
            taf_uncapped = float(qty) * cfg.taf_per_share
            taf = min(taf_uncapped, cfg.taf_max_per_trade)
            fee += sec_fee + taf
        return fee

    def compute_fee_breakdown(
        self,
        side: str,
        qty: int,
        fill_price: float,
    ) -> dict:
        """Same as ``compute_fee`` but returns per-component dollars."""
        cfg = self.config
        out = {
            "base_commission": float(cfg.base_commission) if cfg.enabled else 0.0,
            "sec_fee": 0.0,
            "taf": 0.0,
            "total": 0.0,
        }
        if not cfg.enabled or qty <= 0 or fill_price <= 0:
            out["total"] = out["base_commission"]
            return out

        notional = float(qty) * float(fill_price)
        is_sell = self._is_sell_side(side)
        is_buy = self._is_buy_side(side)

        if is_sell or (cfg.buy_side_fees and is_buy):
            out["sec_fee"] = notional * cfg.sec_fee_per_dollar
            taf_uncapped = float(qty) * cfg.taf_per_share
            out["taf"] = min(taf_uncapped, cfg.taf_max_per_trade)
        out["total"] = out["base_commission"] + out["sec_fee"] + out["taf"]
        return out

    # ------------------------------------------------------------------ #
    # Bulk application — for post-hoc fill-log adjustment
    # ------------------------------------------------------------------ #
    def apply_to_fill_log(self, fill_log_df):
        """Compute the per-row fee for a trade-log DataFrame.

        Expects columns: ``side``, ``qty``, ``fill_price``. Returns a
        ``pd.Series`` of dollar fees aligned to the input index.
        """
        import pandas as pd
        if fill_log_df is None or len(fill_log_df) == 0:
            return pd.Series(dtype=float)
        sides = fill_log_df["side"].astype(str)
        qtys = pd.to_numeric(fill_log_df["qty"], errors="coerce").fillna(0).astype(float)
        prices = pd.to_numeric(fill_log_df["fill_price"], errors="coerce").fillna(0).astype(float)
        fees = pd.Series(0.0, index=fill_log_df.index)
        for i in range(len(fill_log_df)):
            fees.iloc[i] = self.compute_fee(
                str(sides.iloc[i]), int(qtys.iloc[i]), float(prices.iloc[i])
            )
        return fees


def get_alpaca_fees(config_dict: Optional[dict] = None) -> AlpacaFees:
    """Factory mirroring the slippage/borrow factories."""
    if not config_dict:
        return AlpacaFees(AlpacaFeesConfig())
    cfg = AlpacaFeesConfig(
        enabled=bool(config_dict.get("enabled", True)),
        sec_fee_per_dollar=float(
            config_dict.get("sec_fee_per_dollar", 27.80 / 1_000_000.0)
        ),
        taf_per_share=float(config_dict.get("taf_per_share", 0.000166)),
        taf_max_per_trade=float(config_dict.get("taf_max_per_trade", 8.30)),
        base_commission=float(config_dict.get("base_commission", 0.0)),
        buy_side_fees=bool(config_dict.get("buy_side_fees", False)),
    )
    return AlpacaFees(cfg)
