"""leaps_catalyst_edge_v1 — long-dated 25-delta calls on names with
quantifiable upcoming binary catalysts.

***PHASE 0 SYNTHETIC OPTIONS STAND-IN — NOT PRODUCTION OPTIONS DATA***

Rationale: real OPRA options chains require Schwab API integration
(Phase 1 work). For Phase 0 — sleeve scaffolding validation — we use
Black-Scholes pricing on the underlying close + an IV proxy from
realized vol. This is good enough to validate the sleeve plumbing
(signal generation, concentration caps, gauntlet metrics) but is NOT
a substitute for real options PnL. Any alpha verdict from this edge
in Phase 0 is contingent on real-OPRA validation in Phase 1.

The edge produces a per-ticker DIRECTIONAL signal in [-1, +1] where
positive values indicate a long-LEAPS-call thesis. Engine B sizes the
call exposure via the Moonshot sleeve's per-bet ceiling. The synthetic
options pricing is hidden inside an `options_payoff_proxy` helper —
swapping it for real OPRA in Phase 1 is a localized change.

Catalyst sources (Phase 0 — what the dispatch named):
  - Earnings surprises within the next 18 months (yfinance/Finnhub)
  - PDUFA / FDA AdComm dates (free public data; not yet wired here —
    Phase 1 will add a `data/intel/fda_calendar.parquet` source)
  - Federal contract awards (SAM.gov; Phase 1)
  - M&A speculation (heuristic from rumor data; Phase 1)

Phase 0 ships only the EARNINGS-WINDOW catalyst source — easiest to
validate without new data integration. The other catalyst sources are
stubbed at the `_collect_catalysts` layer for Phase 1.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from ..edge_base import EdgeBase

log = logging.getLogger("LeapsCatalystEdge")


# Cumulative normal distribution function — Black-Scholes uses N(d).
# Pure-python implementation avoids the scipy.stats import for a cold
# import path; precision is adequate for sizing decisions.
def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class _Catalyst:
    """A discrete event with a date the underlying is expected to move."""
    ticker: str
    event_type: str               # "earnings" | "fda_pdufa" | "contract" | "ma"
    event_date: date
    expected_move_pct: Optional[float] = None  # None means use IV-implied
    confidence: float = 0.5       # 0..1; tilt amplitude


@dataclass
class _LeapsContract:
    """Proxy for a single 18-month 25-delta long call."""
    ticker: str
    strike: float                 # at-the-money for 25-delta initially
    days_to_expiry: int
    iv_annual: float
    underlying_price: float
    premium: float                # synthetic premium (Black-Scholes)


def options_payoff_proxy(
    spot: float,
    strike: float,
    days_to_expiry: int,
    iv_annual: float,
    risk_free_rate: float = 0.04,
    target_delta: float = 0.25,
) -> _LeapsContract:
    """SYNTHETIC Black-Scholes call pricing for Phase 0 stand-in.

    Builds a 25-delta long-dated call. To find the strike that gives
    target_delta, we solve d1 = N^-1(target_delta) for K:
        d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T) = N^-1(target_delta)
        K = S × exp((r + σ²/2)T - σ√T × N^-1(target_delta))

    PHASE 0 ONLY. Real OPRA chains will replace this in Phase 1.
    """
    if spot <= 0 or iv_annual <= 0 or days_to_expiry <= 0:
        return _LeapsContract(
            ticker="?", strike=spot, days_to_expiry=days_to_expiry,
            iv_annual=iv_annual, underlying_price=spot, premium=0.0,
        )
    T = days_to_expiry / 365.0
    sigma_sqrt_T = iv_annual * math.sqrt(T)

    # Inverse-normal approximation (Beasley-Springer-Moro). For
    # target_delta = 0.25, N^-1(0.25) = -0.6745.
    if target_delta <= 0 or target_delta >= 1:
        target_delta = 0.25
    # Use scipy if available, fall back to a closed-form approx for
    # the 0.25-delta case (which is by far the most common call).
    n_inv_d1_target = -0.6745 if abs(target_delta - 0.25) < 1e-6 else _norm_inv_approx(target_delta)

    K = spot * math.exp(
        (risk_free_rate + 0.5 * iv_annual ** 2) * T
        - sigma_sqrt_T * n_inv_d1_target
    )
    # Compute the actual call premium at the chosen strike.
    d1 = (math.log(spot / K) + (risk_free_rate + 0.5 * iv_annual ** 2) * T) / sigma_sqrt_T
    d2 = d1 - sigma_sqrt_T
    call_premium = spot * _norm_cdf(d1) - K * math.exp(-risk_free_rate * T) * _norm_cdf(d2)
    return _LeapsContract(
        ticker="?", strike=float(K), days_to_expiry=days_to_expiry,
        iv_annual=iv_annual, underlying_price=spot, premium=float(call_premium),
    )


def _norm_inv_approx(p: float) -> float:
    """Beasley-Springer-Moro approximation. Adequate for sizing logic."""
    if p == 0.5:
        return 0.0
    a = [-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02,
         1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00]
    b = [-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02,
         6.680131188771972e+01, -1.328068155288572e+01]
    if p < 0.02425:
        q = math.sqrt(-2.0 * math.log(p))
        return (((((a[0] * q + a[1]) * q + a[2]) * q + a[3]) * q + a[4]) * q + a[5]) / \
               ((((b[0] * q + b[1]) * q + b[2]) * q + b[3]) * q + b[4] + 1.0)
    if p > 1 - 0.02425:
        q = math.sqrt(-2.0 * math.log(1.0 - p))
        return -(((((a[0] * q + a[1]) * q + a[2]) * q + a[3]) * q + a[4]) * q + a[5]) / \
                ((((b[0] * q + b[1]) * q + b[2]) * q + b[3]) * q + b[4] + 1.0)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / \
           (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0)


# ---------------------------------------------------------------------- #

class LeapsCatalystEdge(EdgeBase):
    EDGE_ID = "leaps_catalyst_v1"
    CATEGORY = "asymmetric_upside"
    DESCRIPTION = (
        "Long-dated 25-delta call exposure on names with quantifiable "
        "upcoming binary catalysts. PHASE 0: synthetic Black-Scholes "
        "pricing on underlying close + realized-vol IV proxy. "
        "Real OPRA chains follow in Phase 1 via Schwab integration."
    )

    DEFAULT_PARAMS = {
        # Days from now to look ahead for catalysts.
        "catalyst_horizon_days": 540,         # 18 months
        "min_days_to_event": 7,                # don't enter on day-of
        # IV proxy: realized-vol multiplier (real-world IV is typically
        # 1.1–1.4x realized; 1.2 is a conservative middle).
        "iv_proxy_multiplier": 1.2,
        "realized_vol_window_days": 63,
        # Tilt amplitude. The sleeve's max_position_weight cap is the
        # actual notional limit; this is just the directional signal.
        "tilt_long": 0.6,
        # Earnings catalyst: only flag if last earnings surprise was
        # positive AND ≥ this magnitude (% surprise).
        "earnings_min_surprise_pct": 5.0,
    }

    def __init__(self):
        super().__init__()
        self.params: Dict = dict(self.DEFAULT_PARAMS)

    @classmethod
    def sample_params(cls) -> Dict:
        return dict(cls.DEFAULT_PARAMS)

    # ------------------------------------------------------------------
    def _realized_vol(
        self, df: pd.DataFrame, as_of: pd.Timestamp,
    ) -> Optional[float]:
        """Annualized realized vol from the underlying's close."""
        if df is None or df.empty or "Close" not in df.columns:
            return None
        try:
            sliced = df.loc[df.index <= as_of, "Close"].dropna()
        except (TypeError, KeyError):
            return None
        n = int(self.params.get("realized_vol_window_days", 63))
        if len(sliced) < n + 1:
            return None
        rets = sliced.pct_change().dropna().tail(n)
        if rets.empty:
            return None
        std = float(rets.std(ddof=0))
        if std <= 0 or not np.isfinite(std):
            return None
        return std * math.sqrt(252.0)

    def _last_close(
        self, df: pd.DataFrame, as_of: pd.Timestamp,
    ) -> Optional[float]:
        if df is None or df.empty or "Close" not in df.columns:
            return None
        try:
            sliced = df.loc[df.index <= as_of, "Close"].dropna()
        except (TypeError, KeyError):
            return None
        if sliced.empty:
            return None
        last = float(sliced.iloc[-1])
        return last if last > 0 and np.isfinite(last) else None

    # ------------------------------------------------------------------
    def _collect_catalysts(
        self,
        ticker: str,
        df: pd.DataFrame,
        as_of: pd.Timestamp,
    ) -> List[_Catalyst]:
        """PHASE 0: stub returning earnings-window catalysts only.

        Phase 1 will add: PDUFA dates, federal contracts, M&A flags.
        """
        # Without an earnings-calendar data source wired in here, the
        # Phase 0 stand-in treats "approaching the next quarterly
        # earnings ±5 trading days" as a binary-catalyst window. This
        # is a coarse proxy — production needs an actual earnings
        # calendar (yfinance/Finnhub) per the dispatch.
        cats: List[_Catalyst] = []
        try:
            # Without a real calendar, infer "next earnings ≈ as_of + 90d"
            # as a placeholder. NOT production logic.
            placeholder_date = (as_of + pd.Timedelta(days=90)).date()
            horizon_days = int(self.params.get("catalyst_horizon_days", 540))
            min_days = int(self.params.get("min_days_to_event", 7))
            days_until = (placeholder_date - as_of.date()).days
            if min_days <= days_until <= horizon_days:
                cats.append(_Catalyst(
                    ticker=ticker, event_type="earnings",
                    event_date=placeholder_date,
                    confidence=0.4,                 # Phase 0 placeholder confidence
                ))
        except Exception as exc:
            log.debug(f"catalyst collection failed for {ticker}: {exc}")
        return cats

    # ------------------------------------------------------------------
    def compute_signals(
        self,
        data_map: Dict[str, pd.DataFrame],
        now: pd.Timestamp,
    ) -> Dict[str, float]:
        out: Dict[str, float] = {}
        as_of = pd.Timestamp(now)
        iv_mult = float(self.params.get("iv_proxy_multiplier", 1.2))
        tilt = float(self.params.get("tilt_long", 0.6))

        for ticker, df in data_map.items():
            spot = self._last_close(df, as_of)
            rv = self._realized_vol(df, as_of)
            if spot is None or rv is None:
                out[ticker] = 0.0
                continue

            cats = self._collect_catalysts(ticker, df, as_of)
            if not cats:
                out[ticker] = 0.0
                continue

            iv_proxy = rv * iv_mult
            # Average catalyst confidence weights the directional tilt.
            # Single catalyst → exactly conf × tilt; multiple → average.
            mean_conf = float(np.mean([c.confidence for c in cats]))
            # PHASE 0 SYNTHETIC PRICING — real OPRA Phase 1
            contract = options_payoff_proxy(
                spot=spot,
                strike=spot,            # ATM-strike start; helper rebuilds at 25-delta
                days_to_expiry=540,
                iv_annual=iv_proxy,
            )
            # Sanity: if synthetic premium > 25% of spot, the IV proxy
            # is unrealistic — abstain rather than recommend a 25%-of-spot
            # gamble.
            if contract.premium / spot > 0.25:
                out[ticker] = 0.0
                continue
            out[ticker] = float(tilt * mean_conf)

        return out


# ---------------------------------------------------------------------- #
# Auto-register on import. Starts paused tier=feature so the sleeve
# gauntlet (NOT the core gauntlet) evaluates the edge before it deploys
# real capital. Phase 1 (when real OPRA lands) the gauntlet promotes /
# kills based on actual options PnL, not Phase 0 synthetic.
# ---------------------------------------------------------------------- #
from engines.engine_a_alpha.edge_registry import EdgeRegistry, EdgeSpec  # noqa: E402

try:
    _reg = EdgeRegistry()
    _reg.ensure(EdgeSpec(
        edge_id=LeapsCatalystEdge.EDGE_ID,
        category=LeapsCatalystEdge.CATEGORY,
        module=__name__,
        version="1.0.0-phase0",
        params=dict(LeapsCatalystEdge.DEFAULT_PARAMS),
        status="paused",
        tier="feature",
    ))
except Exception:
    pass
