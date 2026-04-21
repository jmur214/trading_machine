"""
RegimeConfig — typed configuration for Engine E.
Loads from config/regime_settings.json and provides typed access to all parameters.
"""

import json
import os
from dataclasses import dataclass, field
from typing import List

_CONFIG_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "config", "regime_settings.json"
)


@dataclass
class TrendConfig:
    sma_long: int = 200
    sma_short: int = 50
    er_structural_window: int = 60
    er_tactical_window: int = 14
    er_chop_threshold: float = 0.20
    slope_window: int = 20
    hysteresis_bars: int = 5


@dataclass
class VolatilityConfig:
    atr_window: int = 14
    lookback_bars: int = 252
    high_percentile: float = 75
    low_percentile: float = 25
    shock_percentile: float = 90
    shock_vol_threshold: float = 0.30
    vol_short_window: int = 5
    vol_long_window: int = 60
    vol_ratio_shock_threshold: float = 2.0
    hysteresis_bars: int = 3
    crisis_bypass_confidence: float = 0.90


@dataclass
class CorrelationConfig:
    rolling_window: int = 60
    pc1_spike_threshold: float = 0.55
    pc1_elevated_threshold: float = 0.40
    pc1_dispersed_threshold: float = 0.25
    avg_corr_spike_threshold: float = 0.80
    avg_corr_elevated_threshold: float = 0.60
    avg_corr_dispersed_threshold: float = 0.30
    spy_tlt_spike_threshold: float = 0.40
    spy_tlt_elevated_threshold: float = 0.30
    spy_tlt_dispersed_threshold: float = -0.20
    spy_tlt_change_lookback: int = 30
    spy_tlt_change_warning_threshold: float = 0.15
    spy_gld_safe_haven_threshold: float = -0.30
    min_sectors: int = 5
    hysteresis_bars: int = 3
    crisis_bypass_confidence: float = 0.90


@dataclass
class BreadthConfig:
    sma_long: int = 200
    sma_short: int = 50
    strong_sma200_pct: float = 0.70
    strong_sma50_pct: float = 0.60
    narrow_sma200_pct: float = 0.50
    narrow_sma50_pct: float = 0.40
    weak_sma200_pct: float = 0.40
    slope_window: int = 10
    slope_deteriorating_threshold: float = -0.01
    slope_recovering_threshold: float = 0.01
    recovering_floor: float = 0.40
    recovering_ceiling: float = 0.60
    deteriorating_ceiling: float = 0.55
    nh_nl_window: int = 252
    hysteresis_bars: int = 3


@dataclass
class ForwardStressConfig:
    vix_ticker: str = "^VIX"
    vix3m_ticker: str = "^VIX3M"
    vix_lookback: int = 252
    panic_term_spread: float = -5.0
    panic_vix_level: float = 35.0
    panic_vix_z: float = 2.0
    stressed_term_spread: float = -2.0
    stressed_vix_level: float = 25.0
    stressed_vix_z: float = 1.5
    cautious_term_spread: float = 0.0
    cautious_vix_level: float = 20.0
    cautious_vix_z: float = 1.0
    hysteresis_bars: int = 2
    crisis_bypass_confidence: float = 0.85


@dataclass
class AdvisoryConfig:
    duration_ramp_bars: int = 20
    flip_frequency_lookback: int = 30
    flip_frequency_warning_threshold: int = 3
    transition_matrix_min_bars: int = 100


@dataclass
class RegimeConfig:
    trend: TrendConfig = field(default_factory=TrendConfig)
    volatility: VolatilityConfig = field(default_factory=VolatilityConfig)
    correlation: CorrelationConfig = field(default_factory=CorrelationConfig)
    breadth: BreadthConfig = field(default_factory=BreadthConfig)
    forward_stress: ForwardStressConfig = field(default_factory=ForwardStressConfig)
    advisory: AdvisoryConfig = field(default_factory=AdvisoryConfig)
    benchmarks: List[str] = field(default_factory=lambda: ["SPY"])
    cross_asset: List[str] = field(default_factory=lambda: ["TLT", "GLD"])
    vix_tickers: List[str] = field(default_factory=lambda: ["^VIX", "^VIX3M"])
    exclude_from_breadth: List[str] = field(
        default_factory=lambda: ["SPY", "QQQ", "IWM", "TLT", "GLD"]
    )

    @classmethod
    def from_json(cls, path: str = _CONFIG_PATH) -> "RegimeConfig":
        """Load config from JSON file. Falls back to defaults if file missing."""
        resolved = os.path.abspath(path)
        if not os.path.exists(resolved):
            return cls()

        with open(resolved, "r") as f:
            raw = json.load(f)

        return cls(
            trend=TrendConfig(**raw.get("trend", {})),
            volatility=VolatilityConfig(**raw.get("volatility", {})),
            correlation=CorrelationConfig(**raw.get("correlation", {})),
            breadth=BreadthConfig(**raw.get("breadth", {})),
            forward_stress=ForwardStressConfig(**raw.get("forward_stress", {})),
            advisory=AdvisoryConfig(**raw.get("advisory", {})),
            benchmarks=raw.get("benchmarks", ["SPY"]),
            cross_asset=raw.get("cross_asset", ["TLT", "GLD"]),
            vix_tickers=raw.get("vix_tickers", ["^VIX", "^VIX3M"]),
            exclude_from_breadth=raw.get(
                "exclude_from_breadth", ["SPY", "QQQ", "IWM", "TLT", "GLD"]
            ),
        )
