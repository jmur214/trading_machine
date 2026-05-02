"""Foundry feature plugins. Importing this package triggers
self-registration of every shipped feature."""
from . import cot_commercial_net_long  # noqa: F401

__all__ = ["cot_commercial_net_long"]
