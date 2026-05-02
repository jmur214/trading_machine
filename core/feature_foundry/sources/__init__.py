"""Foundry DataSource plugins. Importing this package triggers
self-registration of every shipped source."""
from . import cftc_cot  # noqa: F401  (registers CFTCCommitmentsOfTraders)
from . import local_ohlcv  # noqa: F401  (registers LocalOHLCV)

__all__ = ["cftc_cot", "local_ohlcv"]
