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
    crisis_max_positions: int = 5
    stressed_max_positions: int = 7
    # HMM-confidence floor for risk_scalar damping. confidence=0 (uniform
    # posterior) → risk_scalar *= floor; confidence=1 (concentrated) → *= 1.
    # Set to 1.0 to disable damping entirely.
    hmm_confidence_min_floor: float = 0.6


@dataclass
class HMMConfig:
    """Confidence-aware HMM regime classifier (additive to 5-axis detector).

    Default disabled — enabling adds ~3-5ms per detect_regime call (single
    HMM forward pass on a 7-feature snapshot) and modulates the existing
    advisory.risk_scalar by HMM posterior entropy.
    """
    hmm_enabled: bool = False
    model_path: str = "engines/engine_e_regime/models/hmm_3state_v1.pkl"
    # When confidence (1 - normalized entropy) is low, scale risk down.
    # Linear: scalar = min_confidence_floor + (1 - min_confidence_floor) * confidence.
    # Example: min_confidence_floor=0.6 → uniform-distribution gives 0.6x;
    # concentrated gives 1.0x. Engine B's existing advisory_risk_scalar
    # consumer multiplies this in, no Engine B code change needed.
    min_confidence_floor: float = 0.6
    # If HMM model file is missing, behavior:
    #   "warn"  → log warning, skip HMM augmentation (advisory unchanged)
    #   "raise" → fail RegimeDetector init
    on_model_missing: str = "warn"


@dataclass
class MultiResHMMConfig:
    """Multi-resolution HMM (Workstream C slice 2 — 2026-05).

    Adds weekly + monthly HMM classifiers running in parallel with the
    daily HMM. Outputs are surfaced READ-ONLY in advisory.regime_daily,
    advisory.regime_weekly, advisory.regime_monthly. They do NOT modify
    risk_scalar by default — downstream consumers (Path C compounder,
    future tactical sleeves) opt in by reading the field.

    Default disabled. When enabled adds ~5-8ms per detect_regime call
    (three HMM forward passes on resampled feature snapshots).

    Requires both weekly_path and monthly_path artifacts to exist on
    disk (produced by `scripts/train_multires_hmm.py`).
    """
    multires_enabled: bool = False
    weekly_model_path: str = "engines/engine_e_regime/models/hmm_weekly_v1.pkl"
    monthly_model_path: str = "engines/engine_e_regime/models/hmm_monthly_v1.pkl"
    # Trailing window for windowed posterior smoothing per cadence.
    history_window_daily: int = 60
    history_window_weekly: int = 26
    history_window_monthly: int = 12


@dataclass
class TransitionWarningConfig:
    """Transition-warning detector (Workstream C slice 2 — 2026-05).

    Fires when the daily HMM posterior entropy is high or KL-divergence
    between current and lag posteriors is large — both indicate the
    classifier is in transit between states. Surfaced read-only as
    advisory.regime_transition_warning. Engine B does NOT consume by
    default; this is observability/diagnostic-only.

    Acceptance criterion (per Workstream C deliverables): fire ≥48hr
    ahead of regime changes in ≥80% of historical cases.
    """
    transition_warning_enabled: bool = False
    window: int = 5
    entropy_threshold: float = 0.55
    kl_threshold: float = 0.30
    smoothing_window: int = 3
    min_history: int = 5
    # Trailing buffer of posteriors to maintain in RegimeDetector for
    # streaming detection. Large enough to span multiple windows.
    posterior_buffer_size: int = 20


@dataclass
class RegimeConfig:
    trend: TrendConfig = field(default_factory=TrendConfig)
    volatility: VolatilityConfig = field(default_factory=VolatilityConfig)
    correlation: CorrelationConfig = field(default_factory=CorrelationConfig)
    breadth: BreadthConfig = field(default_factory=BreadthConfig)
    forward_stress: ForwardStressConfig = field(default_factory=ForwardStressConfig)
    advisory: AdvisoryConfig = field(default_factory=AdvisoryConfig)
    hmm: HMMConfig = field(default_factory=HMMConfig)
    multires: MultiResHMMConfig = field(default_factory=MultiResHMMConfig)
    transition_warning: TransitionWarningConfig = field(
        default_factory=TransitionWarningConfig
    )
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
            hmm=HMMConfig(**raw.get("hmm", {})),
            multires=MultiResHMMConfig(**raw.get("multires", {})),
            transition_warning=TransitionWarningConfig(
                **raw.get("transition_warning", {})
            ),
            benchmarks=raw.get("benchmarks", ["SPY"]),
            cross_asset=raw.get("cross_asset", ["TLT", "GLD"]),
            vix_tickers=raw.get("vix_tickers", ["^VIX", "^VIX3M"]),
            exclude_from_breadth=raw.get(
                "exclude_from_breadth", ["SPY", "QQQ", "IWM", "TLT", "GLD"]
            ),
        )
