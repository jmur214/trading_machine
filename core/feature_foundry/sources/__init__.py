"""Foundry DataSource plugins. Importing this package triggers
self-registration of every shipped source."""
from . import cftc_cot  # noqa: F401  (registers CFTCCommitmentsOfTraders)
from . import local_ohlcv  # noqa: F401  (registers LocalOHLCV)
from . import earnings_calendar  # noqa: F401  (registers EarningsCalendar)
from . import fred_macro  # noqa: F401  (registers FREDMacro)

__all__ = ["cftc_cot", "local_ohlcv", "earnings_calendar", "fred_macro"]
