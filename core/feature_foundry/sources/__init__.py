"""Foundry DataSource plugins. Importing this package triggers
self-registration of every shipped source."""
from . import cftc_cot  # noqa: F401  (registers CFTCCommitmentsOfTraders)

__all__ = ["cftc_cot"]
