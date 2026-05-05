"""
engines/engine_a_alpha/fill_share_capper.py
===========================================
Phase 2.10d Primitive 1 — per-edge fill-share ceiling.

Problem (from docs/Measurements/2026-04/oos_2025_decomposition_2026_04.md):
    The bottom-three edges in 2025 (momentum_edge_v1, low_vol_factor_v1,
    atr_breakout_v1) consumed 83% of fill share while producing -$5,645
    of realized losses. The two edges with consistent positive contribution
    in 2025 (volume_anomaly_v1, herding_v1) got only 4.3% of fills
    combined. The signal-processor's allocation logic provides no
    structural floor for low-frequency event-driven edges against
    universal-fire edges.

Mechanism:
    Per bar, AlphaEngine produces one signal per ticker, each attributed
    to a single dominant edge (`edge_id`). This module is invoked AFTER
    that attribution and BEFORE downstream position sizing. For any edge
    whose share of the bar's signals exceeds `cap`, the strength of all
    its signals is scaled by `cap / share`. The signal count is preserved
    (no signals are dropped); only the magnitude is reduced.

    Scaling strength is the right knob because RiskEngine's position
    sizing is proportional to it. Reducing strength reduces position size,
    which reduces capital deployed to the dominant edge — the actual goal.

    "Fills will follow strength" — strengths below the entry threshold
    will not produce orders downstream, so the fill-count effect of
    capping is downstream-organic rather than enforced here.

Design decisions:
    - X (cap fraction) default = 0.25 (no edge gets more than 1/4 of the
      bar's signal budget). Below the bottom-three's 83% by 3.3x; above
      the natural 1/N share when N=14 active edges (~7%) so it doesn't
      bind in the well-distributed case.
    - Per-bar measurement (not rolling). Per-bar is the natural unit of
      "current rivalry" — different bars have different signal mixes
      and rolling windows would create spurious cross-bar coupling.
    - Proportional scale-down (NOT drop). Preserves the directional
      information; treats the cap as a budget constraint not a hard
      veto. Aligns with the director's "preserve all signals at smaller
      magnitude" spec.
    - Cap applies only when there are >= N_min signals on the bar.
      Skipping low-volume bars avoids degenerate cases (e.g. 1 signal
      with 100% share is unavoidable; 2 signals where one dominates is
      noise).
    - Cap is applied per side independently? **No** — the diagnosis is
      *capital allocation across edges*, not direction. A bar where
      momentum_edge attributes 30 longs and 5 shorts has a single edge
      consuming 35/100 share even if the directions are mixed. The
      capital allocator doesn't care about side parity; it cares about
      single-edge dominance.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, List


@dataclass
class FillShareCapSettings:
    """Configuration for the per-bar fill-share ceiling.

    Attributes:
        cap: Maximum share of per-bar signals that any single edge may
            attribute. Strengths of over-budget edges are scaled by
            cap / actual_share. Default 0.25.
        min_signals_for_cap: Below this signal count per bar the cap is
            inactive. Avoids degenerate "1 signal = 100% share" cases.
            Default 4 (cap binds at >= 4 signals when one edge has 25%+).
        enabled: Master switch. When False, this module is a no-op and
            signals pass through unchanged. Default True.
    """
    cap: float = 0.25
    min_signals_for_cap: int = 4
    enabled: bool = True


class FillShareCapper:
    """Apply per-bar single-edge attribution share ceiling.

    Statelessly transforms a list of signal dicts. Each dict must have
    `edge_id` (str) and `strength` (float). Other keys are passed through
    unchanged.

    Example:
        capper = FillShareCapper(FillShareCapSettings(cap=0.25))
        capped = capper.apply(signals)
    """

    def __init__(self, settings: FillShareCapSettings | None = None):
        self.settings = settings or FillShareCapSettings()
        if not 0.0 < self.settings.cap <= 1.0:
            raise ValueError(
                f"cap must be in (0, 1], got {self.settings.cap}"
            )

    def apply(self, signals: List[dict]) -> List[dict]:
        """Scale strength of over-budget edges' signals in-place; return
        the same list. Returns immediately if disabled or below
        min_signals_for_cap. Mutates the dicts in `signals`.
        """
        if not self.settings.enabled:
            return signals
        n = len(signals)
        if n < self.settings.min_signals_for_cap:
            return signals

        # Count attribution per edge_id. Signals without an edge_id
        # (defensive) are bucketed under "_unknown" and follow the same
        # rule.
        edge_counts: Counter = Counter(
            (s.get("edge_id") or "_unknown") for s in signals
        )

        # For each over-budget edge, compute the scale factor.
        budget_count = self.settings.cap * n
        scale_factors: dict[str, float] = {}
        for edge_id, count in edge_counts.items():
            if count > budget_count:
                # Scale = cap * n / count → exact share of `cap` post-scale.
                scale_factors[edge_id] = budget_count / float(count)

        if not scale_factors:
            return signals

        # Apply in-place. Strength is clamped non-negative (defensive)
        # and the original strength is recorded under meta.fill_share_cap_pre
        # so downstream attribution / debugging can trace what happened.
        for s in signals:
            edge_id = s.get("edge_id") or "_unknown"
            sf = scale_factors.get(edge_id)
            if sf is None:
                continue
            pre = float(s.get("strength", 0.0))
            post = max(0.0, pre * sf)
            s["strength"] = post
            meta = s.get("meta") or {}
            meta["fill_share_cap"] = {
                "edge_id": edge_id,
                "share_pre": edge_counts[edge_id] / float(n),
                "scale": sf,
                "strength_pre": pre,
            }
            s["meta"] = meta

        return signals

    def diagnose(self, signals: Iterable[dict]) -> dict:
        """Return per-edge share + would-trigger-cap diagnostic dict.
        Read-only; useful for tests and audit doc reconstruction."""
        signals = list(signals)
        n = len(signals)
        if n == 0:
            return {"n": 0, "shares": {}, "binds": {}}
        edge_counts: Counter = Counter(
            (s.get("edge_id") or "_unknown") for s in signals
        )
        shares = {e: c / n for e, c in edge_counts.items()}
        binds = {e: s for e, s in shares.items() if s > self.settings.cap}
        return {"n": n, "shares": shares, "binds": binds}
