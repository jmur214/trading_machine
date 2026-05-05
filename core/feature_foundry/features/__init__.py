"""Foundry feature plugins. Importing this package triggers
self-registration of every shipped feature."""
from . import cot_commercial_net_long  # noqa: F401
from . import mom_12_1  # noqa: F401
from . import mom_6_1  # noqa: F401
from . import reversal_1m  # noqa: F401
from . import realized_vol_60d  # noqa: F401
from . import beta_252d  # noqa: F401
from . import dist_52w_high  # noqa: F401
from . import drawdown_60d  # noqa: F401
from . import vol_regime_5_60  # noqa: F401
from . import ma_cross_50_200  # noqa: F401
from . import skew_60d  # noqa: F401
# Third batch — calendar / event-driven / pairs primitives
from . import days_to_quarter_end  # noqa: F401
from . import month_of_year_dummy  # noqa: F401
from . import pair_zscore_60d  # noqa: F401
from . import earnings_proximity_5d  # noqa: F401
from . import vix_change_5d  # noqa: F401

__all__ = [
    "cot_commercial_net_long",
    "mom_12_1",
    "mom_6_1",
    "reversal_1m",
    "realized_vol_60d",
    "beta_252d",
    "dist_52w_high",
    "drawdown_60d",
    "vol_regime_5_60",
    "ma_cross_50_200",
    "skew_60d",
    "days_to_quarter_end",
    "month_of_year_dummy",
    "pair_zscore_60d",
    "earnings_proximity_5d",
    "vix_change_5d",
]
