"""Engine E — Regime Intelligence.

See ``docs/Core/engine_charters.md`` § Engine E for the full charter.
"""
from .regime_detector import RegimeDetector
from .regime_config import RegimeConfig

__version__ = "0.1.0"
__charter_status__ = "drift: HIGH — empirically coincident, not leading; satisfies output contract but fails mission"
__all__ = ["RegimeDetector", "RegimeConfig"]
