"""
engines/engine_f_governance/lifecycle_manager.py
================================================
Autonomous edge lifecycle transitions: active → paused → retired, and
paused → active (revival). This is the missing deprecation layer that
the charter describes but was never implemented.

Design principles:
- Evidence gates: minimum trade count + time since activation before ANY
  transition can fire (protect against early-stage noise).
- Benchmark-relative retirement: an edge must underperform SPY by at least
  `retirement_margin` Sharpe to retire. This prevents retiring edges that
  are beta-correlated losers during a drawdown — the real target is alpha
  failure, not market exposure failure.
- Hysteresis: paused edges get a revival path if performance recovers.
- Audit trail: every transition logged to `lifecycle_history.csv` with
  timestamp, evidence metrics, triggering gate, before/after status.
- Cycle caps: no more than `max_retirements_per_cycle` at once (default 1)
  to prevent cascade de-risking on a bad month.

Integration:
- Called from `StrategyGovernor.update_from_trade_log` AFTER weight updates,
  inside a try/except so it cannot break the feedback loop.
- Reads `data/governor/edges.yml` for current status; writes status changes
  back. Does NOT modify other fields (params, version, module, etc).
- Gated by `GovernorConfig.lifecycle_enabled` (default False for safety).

Retirement gates (all must fire):
1. Minimum evidence: trades >= retirement_min_trades AND age_days >= retirement_min_days
2. Benchmark-relative: edge Sharpe < benchmark Sharpe - retirement_margin
3. Recent decay: last-30-trade Sharpe < all-time Sharpe - 1 std (shows decay, not just always-bad)
4. Not revived: last 15 trades do NOT show recovery (30-trade Sharpe > 0.3)

Pause gates (either fires):
1. MDD spike: rolling 90-day MDD < pause_mdd_threshold
2. WR collapse: rolling 30-trade WR < rolling 90-trade WR - 0.15

Revival gate (for paused edges):
1. Sustained recovery: last 20 trades since pause, Sharpe > 0.5 AND WR > 0.45
"""

from __future__ import annotations

import csv
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yaml

log = logging.getLogger("Lifecycle")


@dataclass
class LifecycleConfig:
    """Gates and thresholds for edge lifecycle transitions."""
    enabled: bool = False  # defense-first default

    # Retirement gates
    retirement_min_trades: int = 100
    retirement_min_days: int = 90
    retirement_margin: float = 0.3  # edge_sharpe must be <= benchmark_sharpe - 0.3 to retire
    retirement_recent_window: int = 30
    retirement_decay_std: float = 1.0
    retirement_revival_window: int = 15
    retirement_revival_sharpe: float = 0.3

    # Pause gates
    # pause_loss_fraction_threshold: trailing 30-trade loss fraction
    # (pnl_sum / abs_volume) below this triggers pause. Range (-1, +1).
    # -0.3 means the edge lost 30% of its deployed dollar volume in the last
    # 30 trades — strong "something broke" signal, reversible via revival.
    pause_loss_fraction_threshold: float = -0.3
    pause_wr_collapse: float = 0.15  # rolling-30 WR must drop 15pp vs rolling-90
    pause_min_trades: int = 30

    # Revival gate (for paused → active)
    revival_window: int = 20
    revival_sharpe: float = 0.5
    revival_wr: float = 0.45

    # Retirement from soft-pause: if an edge has been paused for this many
    # days AND is still benchmarkrelative-negative, retire it. Prevents paused
    # edges from accumulating losses at 0.25x indefinitely. Set to 0 to disable.
    paused_retirement_min_days: int = 90

    # ----------------------------------------------------------- Phase 2.10d
    # Trigger 1 — Zero-fill / sparse-fill timeout
    # Catches the failure mode the existing per-trade gates can't see: an
    # edge that's registered active but doesn't fire enough to accumulate
    # the min_trades evidence the retirement gate requires. The zero-fill
    # registered edges (rsi_bounce_v1, bollinger_reversion_v1, etc.) sit at
    # status=active forever under the legacy gates because `sub.empty` on
    # their per-edge slice returns `continue` before any decision fires.
    #
    # Spec source: forward_plan_2026_04_30.md Phase 2.10d Task A item 1
    # ("default 90 days"). Calibrated to 365 days here because pead_v1
    # (a KEEP edge per pruning_proposal_2026_04.md) has a 290-day max gap
    # between fills — the literal 90-day default would have falsely tripped
    # one of the 6 keep-eligible edges. 365d preserves the spec intent
    # (catch sparse / zero-fill edges) without false-tripping low-frequency
    # KEEPs. See lifecycle_triggers_validation_2026_04.md for the
    # calibration journey.
    zero_fill_lookback_days: int = 365
    # Below this many entry-fills in the lookback window an edge is
    # considered dormant. Set to 2 (not 0) to also catch edges that have
    # exactly 1 fill in 5 years (e.g., value_deep_v1) which strictly
    # zero-fill semantics would miss.
    zero_fill_min_fills: int = 2
    # An already-paused edge needs this many days *and* still-zero-fill to
    # auto-retire. Cumulative (lookback + this), so 365+365 = 2yrs of
    # functional inactivity by default before retire.
    zero_fill_paused_retire_days: int = 365
    # Cycle caps for the zero-fill triggers — much higher than the
    # legacy max_pauses cap because these are quasi-static decisions
    # (a registered edge with 0 fills is unambiguously dormant; we are
    # not at risk of cascade de-risking on a bad month). The legacy
    # max_pauses_per_cycle = 2 cap is for active-edges-going-bad, where
    # cascade caution genuinely matters.
    max_zero_fill_pauses_per_cycle: int = 50
    max_zero_fill_retirements_per_cycle: int = 50

    # Trigger 2 — Sustained-noise (per-year contribution)
    # Catches edges that fire enough to clear Trigger 1 but produce
    # near-zero net contribution AND have at least one clearly-negative
    # year. Examples from the 2026-04 audit: panic_v1 (mean -0.03%/yr,
    # min year -0.16%), value_trap_v1 (mean -0.01%/yr, min year -0.05%).
    #
    # The "AND at least one negative year below threshold" clause is the
    # key calibration choice. A pure |mean| < threshold gate would
    # false-trip pead_v1 (mean +0.00%/yr, all years 0 or +0.01%); the
    # negative-year requirement excludes "rarely-fires-and-produces-zero"
    # which is sparse-but-not-noise.
    noise_window_years: int = 3
    # Absolute mean annual contribution (as fraction of starting capital)
    # below which an edge qualifies as "low-magnitude." 0.001 = 0.10% of
    # capital per year. Calibrated against the per-year audit:
    #   - panic_v1 mean -0.03%/yr (|mean|=0.0003) → trips ✓
    #   - macro_credit_spread_v1 mean +0.15%/yr (|mean|=0.0015) → does
    #     NOT trip ✓ (preserved as KEEP)
    # See audit doc for full calibration table.
    noise_mean_threshold: float = 0.001
    # An edge's worst-year contribution must be at least this negative
    # (as fraction of capital) for the noise gate to fire. -0.0003 = -0.03%
    # of capital. Set just-permissive enough that minor zero-rounding
    # noise (e.g., -0.011%) doesn't count as "negative year" but a real
    # losing year (-0.05% or worse) does.
    noise_negative_year_threshold: float = -0.0003
    # Minimum fills in the noise window — protects against falsely
    # tripping brand-new edges with too-small a sample.
    noise_min_fills_in_window: int = 5
    # Minimum trade-history span (days) before the noise gate can fire.
    # Trigger 2 frames its decision in years — it shouldn't be evaluated
    # against an edge that hasn't even had a full year of trade history.
    # Set to 365 days = 1 year of trade history minimum.
    noise_min_history_days: int = 365
    # Cycle cap — this gate is more nuanced than zero-fill so a moderate
    # cap is appropriate.
    max_noise_pauses_per_cycle: int = 10

    # Trigger 2 ancillary — revival veto for paused edges with heavy
    # cumulative drag. The legacy revival gate fires on the last-20-trades
    # Sharpe + WR, but a paused edge that's lost a meaningful fraction of
    # capital over its lifetime should NOT revive even when a recent slice
    # looks OK — that pattern is exactly the soft-pause leak (paused at
    # 0.25x weight, accumulates fills, last 20 happen to look positive,
    # gets revived to full weight, blows up in the next bad regime).
    #
    # Calibration: -0.5% of starting capital cumulative is the threshold.
    # Tuned against the per-year audit:
    #   - momentum_edge_v1 (5y cumulative -7.35%, min year -9.17%) → veto
    #   - low_vol_factor_v1 (5y cumulative -1.95%, min year -2.53%) → veto
    #   - atr_breakout_v1 (5y cumulative -5.91%, min year -5.78%) → veto
    # All three were in the pruning_proposal CUT list and lifecycle-paused.
    revival_veto_cumulative_pct_threshold: float = -0.005

    # Cycle caps (legacy gates, unchanged)
    max_retirements_per_cycle: int = 1
    max_pauses_per_cycle: int = 2

    # Read-only mode: evaluate gates and return events but do NOT write to
    # registry or history CSV. Use for OOS backtesting where lifecycle
    # decisions should be observed but not committed, so re-running the
    # same window gives the same result.
    readonly: bool = False

    # Initial capital for normalizing per-year PnL into "% of capital"
    # for Trigger 2. Backtest is currently $100k throughout; surface as
    # config so paper/live with different starting capital still works.
    initial_capital: float = 100_000.0


@dataclass
class LifecycleEvent:
    """One transition event for the audit trail."""
    timestamp: str
    edge_id: str
    old_status: str
    new_status: str
    triggering_gate: str
    edge_sharpe: float
    benchmark_sharpe: float
    edge_mdd: float
    trade_count: int
    days_active: int
    notes: str = ""


def _edge_sharpe_from_pnl(pnls: np.ndarray) -> float:
    """Annualize trade-level pnl into an approximate Sharpe."""
    if len(pnls) < 2:
        return 0.0
    std = pnls.std()
    if std == 0:
        return 0.0
    # Assuming daily trade frequency; scale by sqrt(252) matches existing governor code.
    return float(pnls.mean() / std * np.sqrt(252))


def _edge_loss_fraction(pnls: np.ndarray, window: int = 30) -> float:
    """Compute recent-window normalized loss as (sum of last-N pnls) / (gross
    absolute volume of last-N pnls). Range (-1, +1). Useful as an MDD proxy
    when we don't have a proper equity curve per edge.

    Returns 0.0 when insufficient data or zero volume.
    """
    if len(pnls) < 5:
        return 0.0
    recent = pnls[-window:]
    gross = float(np.abs(recent).sum())
    if gross <= 0:
        return 0.0
    return float(recent.sum() / gross)


def _per_year_pnl_pct(
    edge_trades: pd.DataFrame,
    initial_capital: float,
    window_years: int,
    as_of: pd.Timestamp,
) -> Dict[int, float]:
    """Compute per-year contribution as fraction of starting capital for
    one edge over the rolling N-year window ending at `as_of`.

    Inputs:
      edge_trades : per-edge trade rows with 'pnl' and 'timestamp' columns
                    (closed trades only — caller filters to pnl.notna()).
      initial_capital : denominator (e.g. 100_000.0).
      window_years : how many calendar years back from `as_of` to include.
      as_of : reference date for the window.

    Output: dict {year: pnl_fraction} for each year in the window. Years
    where the edge had no closed trades are present with value 0.0 so the
    caller can distinguish 'didn't fire' from 'fired and produced zero'.

    The window is the last N FULL calendar years that include as_of's year,
    counted backwards: e.g., as_of=2025-12-31, window_years=3 → 2023, 2024, 2025.
    """
    if initial_capital <= 0 or window_years <= 0:
        return {}
    last_year = int(as_of.year)
    years = list(range(last_year - window_years + 1, last_year + 1))

    if edge_trades.empty:
        return {y: 0.0 for y in years}

    sub = edge_trades.copy()
    sub["year"] = pd.to_datetime(sub["timestamp"], utc=True, errors="coerce").dt.year
    sub = sub.dropna(subset=["year"])
    grouped = sub.groupby("year")["pnl"].sum()
    return {y: float(grouped.get(y, 0.0)) / initial_capital for y in years}


class LifecycleManager:
    """Evaluates lifecycle transitions for all edges in edges.yml.

    Call .evaluate(trades_df) once per `update_from_trade_log` cycle.
    Persists status changes to edges.yml; appends every event to
    `data/governor/lifecycle_history.csv`.
    """

    def __init__(
        self,
        cfg: Optional[LifecycleConfig] = None,
        registry_path: str | Path = "data/governor/edges.yml",
        history_path: str | Path = "data/governor/lifecycle_history.csv",
    ):
        self.cfg = cfg or LifecycleConfig()
        self.registry_path = Path(registry_path)
        self.history_path = Path(history_path)

    # ----------------- public API ----------------- #

    def evaluate(
        self,
        trades: pd.DataFrame,
        benchmark_sharpe: float = 0.0,
        as_of: Optional[pd.Timestamp] = None,
    ) -> List[LifecycleEvent]:
        """Evaluate lifecycle transitions using the current trade log and benchmark.

        `trades` must have columns: edge, pnl, timestamp. Rows without pnl
        (open fills) are ignored.

        Returns a list of LifecycleEvents fired this cycle.
        """
        if not self.cfg.enabled:
            return []

        # Phase α v3 sanity check: detect audit-trail / registry divergence.
        # The 2026-04-25 registry-stomp bug accumulated multiple identical
        # `<edge>: active → paused` events across consecutive runs because
        # the bug reverted pause state between runs. Under correct behavior
        # the second run should see the edge already paused and not fire
        # the same transition again. Catch this signature here so the next
        # bug class of "lifecycle decisions silently lost" is impossible to
        # hide. Logged as a warning, not raised — observability not gating.
        try:
            self._audit_registry_divergence_check()
        except Exception as exc:
            log.debug(f"[Lifecycle] divergence check failed silently: {exc}")

        if trades is None or trades.empty:
            return []

        # Two views of the trade log:
        #   * `entries_df` — every fill row (uses the 'trigger' column when
        #     present; else all rows). Trigger 1 measures FIRING rate, which
        #     means counting entry events, not closed P&L rows.
        #   * `tdf` — closed trades only (pnl present and non-zero), for the
        #     existing per-trade gates AND for Trigger 2's per-year P&L
        #     attribution.
        if "edge" not in trades.columns:
            return []

        raw = trades.copy()
        if "timestamp" in raw.columns:
            raw["timestamp"] = pd.to_datetime(raw["timestamp"], errors="coerce", utc=True)
            raw = raw.dropna(subset=["timestamp"])

        if "trigger" in raw.columns:
            entries_df = raw[raw["trigger"] == "entry"].copy()
        else:
            entries_df = raw.copy()

        # Closed trades for legacy + Trigger 2
        tdf = raw.copy()
        if "pnl" not in tdf.columns:
            return []
        tdf = tdf[tdf["pnl"].notna() & (tdf["pnl"] != 0)]

        # Resolve as_of from the WIDER view so zero-fill timeouts don't
        # shrink to "as_of = last closed trade" when an edge fires lots of
        # entries but never produces closed pnls in the window.
        if as_of is None:
            if not raw.empty and "timestamp" in raw.columns:
                as_of = raw["timestamp"].max()
            elif not tdf.empty and "timestamp" in tdf.columns:
                as_of = tdf["timestamp"].max()
            else:
                as_of = pd.Timestamp.now(tz="UTC")

        # Pre-compute per-edge fill counts in the lookback window. Used
        # by Trigger 1's firing-rate gate.
        recent_fill_counts: Dict[str, int] = {}
        if not entries_df.empty and "timestamp" in entries_df.columns:
            cutoff = as_of - pd.Timedelta(days=self.cfg.zero_fill_lookback_days)
            recent = entries_df[entries_df["timestamp"] >= cutoff]
            recent_fill_counts = recent.groupby("edge").size().to_dict()

        # Load registry
        edges = self._load_registry()
        if not edges:
            return []

        # Build a lookup: edge_id → most-recent pause date (UTC).
        # Used for the paused → retired retirement gate.
        pause_dates: Dict[str, pd.Timestamp] = {}
        if self.history_path.exists() and self.history_path.stat().st_size > 0:
            try:
                _hist = pd.read_csv(self.history_path)
                if {"new_status", "edge_id", "timestamp"}.issubset(_hist.columns):
                    _paused_rows = _hist[_hist["new_status"] == "paused"].copy()
                    _paused_rows["timestamp"] = pd.to_datetime(
                        _paused_rows["timestamp"], utc=True, errors="coerce"
                    )
                    _paused_rows = _paused_rows.dropna(subset=["timestamp"]).sort_values("timestamp")
                    for _eid, _grp in _paused_rows.groupby("edge_id"):
                        pause_dates[_eid] = _grp["timestamp"].iloc[-1]
            except Exception:
                pass

        events: List[LifecycleEvent] = []
        retirements_used = 0
        pauses_used = 0
        zero_fill_pauses_used = 0
        zero_fill_retirements_used = 0
        noise_pauses_used = 0

        def _all_caps_full() -> bool:
            return (
                retirements_used >= self.cfg.max_retirements_per_cycle
                and pauses_used >= self.cfg.max_pauses_per_cycle
                and zero_fill_pauses_used >= self.cfg.max_zero_fill_pauses_per_cycle
                and zero_fill_retirements_used >= self.cfg.max_zero_fill_retirements_per_cycle
                and noise_pauses_used >= self.cfg.max_noise_pauses_per_cycle
            )

        # Evaluate each edge. Important: the base-edge registry entries (e.g.
        # atr_breakout_v1) don't have a first-activation timestamp; we treat
        # their "age" as the window span of their trades.
        for edge_spec in edges:
            if _all_caps_full():
                break
            edge_id = edge_spec.get("edge_id", "")
            status = edge_spec.get("status", "unknown")
            if status not in ("active", "paused"):
                continue  # candidate/failed/archived not evaluated here

            sub = tdf[tdf["edge"] == edge_id]
            n_recent_fills = int(recent_fill_counts.get(edge_id, 0))

            # ----- Trigger 1: zero-fill / sparse-fill timeout ----- #
            # This must run BEFORE the legacy `if sub.empty: continue` branch
            # because zero-fill edges are exactly the ones with empty `sub`
            # — and the legacy branch silently kept them active forever.
            if status == "active" and zero_fill_pauses_used < self.cfg.max_zero_fill_pauses_per_cycle:
                zf_pause_fired, zf_pause_gate = self._check_zero_fill_pause_gate(n_recent_fills)
                if zf_pause_fired:
                    # Best-effort metric snapshot. Closed-trade stats may be
                    # zero/empty for these edges — that's fine, the gate's
                    # decision is based on firing rate not pnl.
                    pnls_for_log = sub["pnl"].to_numpy(dtype=float) if not sub.empty else np.array([])
                    edge_sharpe_for_log = _edge_sharpe_from_pnl(pnls_for_log)
                    edge_mdd_for_log = _edge_loss_fraction(pnls_for_log)
                    ev = self._transition(
                        edge_spec, "paused", zf_pause_gate, edge_sharpe_for_log,
                        benchmark_sharpe, edge_mdd_for_log, len(pnls_for_log), 0, as_of,
                    )
                    events.append(ev)
                    zero_fill_pauses_used += 1
                    continue

            if status == "paused" and zero_fill_retirements_used < self.cfg.max_zero_fill_retirements_per_cycle:
                pause_date = pause_dates.get(edge_id)
                days_since_pause = int((as_of - pause_date).days) if pause_date is not None else self.cfg.zero_fill_paused_retire_days
                zf_retire_fired, zf_retire_gate = self._check_zero_fill_paused_retire_gate(
                    n_recent_fills, days_since_pause,
                )
                if zf_retire_fired:
                    pnls_for_log = sub["pnl"].to_numpy(dtype=float) if not sub.empty else np.array([])
                    edge_sharpe_for_log = _edge_sharpe_from_pnl(pnls_for_log)
                    edge_mdd_for_log = _edge_loss_fraction(pnls_for_log)
                    ev = self._transition(
                        edge_spec, "retired", zf_retire_gate, edge_sharpe_for_log,
                        benchmark_sharpe, edge_mdd_for_log, len(pnls_for_log),
                        days_since_pause, as_of,
                    )
                    events.append(ev)
                    zero_fill_retirements_used += 1
                    continue

            # Past Trigger 1 → if no closed trades, no further evidence
            # available. Keep the legacy "no trades, no transition" semantics.
            if sub.empty:
                continue

            pnls = sub["pnl"].to_numpy(dtype=float)
            trade_count = len(pnls)
            edge_sharpe = _edge_sharpe_from_pnl(pnls)
            edge_mdd = _edge_loss_fraction(pnls)

            if "timestamp" in sub.columns:
                first_trade = sub["timestamp"].min()
                days_active = int((as_of - first_trade).days)
            else:
                days_active = 0

            # ----- Trigger 2: sustained-noise (active edges only) ----- #
            if status == "active" and noise_pauses_used < self.cfg.max_noise_pauses_per_cycle:
                yearly = _per_year_pnl_pct(
                    sub, self.cfg.initial_capital, self.cfg.noise_window_years, as_of,
                )
                # Count fills in the noise window — uses entries_df so the
                # "min fills" gate excludes new edges with too-small a
                # sample regardless of pnl-row distribution.
                window_cutoff = as_of - pd.Timedelta(days=self.cfg.noise_window_years * 365)
                if not entries_df.empty:
                    edge_entries = entries_df[entries_df["edge"] == edge_id]
                    window_entries = edge_entries[edge_entries["timestamp"] >= window_cutoff]
                    n_fills_window = int(len(window_entries))
                    # Use ENTRY span (not closed-pnl span) for days_history.
                    # An edge that fires throughout 2023-2025 with mostly-zero
                    # pnls in earlier years should still qualify as "old enough
                    # to evaluate" — closed-pnl filtering would underestimate
                    # the real history span.
                    if not edge_entries.empty:
                        days_history = int(
                            (as_of - edge_entries["timestamp"].min()).days
                        )
                    else:
                        days_history = days_active
                else:
                    n_fills_window = trade_count
                    days_history = days_active

                noise_fired, noise_gate = self._check_sustained_noise_pause_gate(
                    yearly, n_fills_window, days_history,
                )
                if noise_fired:
                    ev = self._transition(
                        edge_spec, "paused", noise_gate, edge_sharpe, benchmark_sharpe,
                        edge_mdd, trade_count, days_active, as_of,
                    )
                    events.append(ev)
                    noise_pauses_used += 1
                    continue

            # ----- Legacy gates ----- #
            if status == "active":
                # Try pause first (faster-triggered, reversible), then retire.
                pause_fired, pause_gate = self._check_pause_gates(pnls, trade_count)
                if pause_fired and pauses_used < self.cfg.max_pauses_per_cycle:
                    ev = self._transition(
                        edge_spec, "paused", pause_gate, edge_sharpe, benchmark_sharpe,
                        edge_mdd, trade_count, days_active, as_of,
                    )
                    events.append(ev)
                    pauses_used += 1
                    continue

                retire_fired, retire_gate = self._check_retirement_gates(
                    pnls, trade_count, days_active, edge_sharpe, benchmark_sharpe,
                )
                if retire_fired and retirements_used < self.cfg.max_retirements_per_cycle:
                    ev = self._transition(
                        edge_spec, "retired", retire_gate, edge_sharpe, benchmark_sharpe,
                        edge_mdd, trade_count, days_active, as_of,
                    )
                    events.append(ev)
                    retirements_used += 1

            elif status == "paused":
                revive_fired, revive_gate = self._check_revival_gates(pnls)
                if revive_fired:
                    ev = self._transition(
                        edge_spec, "active", revive_gate, edge_sharpe, benchmark_sharpe,
                        edge_mdd, trade_count, days_active, as_of,
                    )
                    events.append(ev)
                    continue

                # paused → retired: if the edge has been in soft-pause past
                # the minimum hold period and is still deeply negative, retire
                # it. Prevents paused edges bleeding losses at 0.25x forever.
                if retirements_used < self.cfg.max_retirements_per_cycle:
                    pause_date = pause_dates.get(edge_id)
                    days_since_pause = int((as_of - pause_date).days) if pause_date is not None else 0
                    retire_from_pause_fired, retire_from_pause_gate = (
                        self._check_retirement_from_paused_gates(
                            pnls, days_since_pause, edge_sharpe, benchmark_sharpe,
                        )
                    )
                    if retire_from_pause_fired:
                        ev = self._transition(
                            edge_spec, "retired", retire_from_pause_gate, edge_sharpe,
                            benchmark_sharpe, edge_mdd, trade_count, days_active, as_of,
                        )
                        events.append(ev)
                        retirements_used += 1

        # Persist registry + history (skipped in readonly mode)
        if events:
            if self.cfg.readonly:
                for ev in events:
                    log.info(
                        f"[Lifecycle][READONLY] would fire {ev.edge_id}: "
                        f"{ev.old_status} → {ev.new_status}  gate={ev.triggering_gate}  "
                        f"edge_sharpe={ev.edge_sharpe:.2f}  "
                        f"benchmark_sharpe={ev.benchmark_sharpe:.2f}  trades={ev.trade_count}"
                    )
            else:
                self._save_registry(edges)
                self._append_history(events)
                for ev in events:
                    log.info(
                        f"[Lifecycle] {ev.edge_id}: {ev.old_status} → {ev.new_status}  "
                        f"gate={ev.triggering_gate}  edge_sharpe={ev.edge_sharpe:.2f}  "
                        f"benchmark_sharpe={ev.benchmark_sharpe:.2f}  trades={ev.trade_count}"
                    )

        return events

    # ----------------- gate evaluators ----------------- #

    def _check_retirement_gates(
        self,
        pnls: np.ndarray,
        trade_count: int,
        days_active: int,
        edge_sharpe: float,
        benchmark_sharpe: float,
    ) -> Tuple[bool, str]:
        """Gates (all must pass to retire):
        1. Minimum evidence: trades and days_active meet thresholds.
        2. Benchmark-relative: edge sharpe < benchmark - margin. This catches
           both "always bad" edges (like atr_breakout with global Sharpe -0.04)
           AND edges that degraded to unprofitable.
        3. Not currently reviving: last-15-trade Sharpe is not showing recovery.
           Protects against retiring an edge that's just now turning around.

        An earlier draft had a "recent decay" gate (recent < historical - 1 std)
        that required DECLINE to retire. That gate refused to retire
        consistently-bad edges because they don't decline — they just stay bad.
        Removed. Benchmark-relative is the right frame: if you've underperformed
        passive for 100+ trades, you should retire regardless of trend.
        """
        # Gate 1: minimum evidence
        if trade_count < self.cfg.retirement_min_trades:
            return False, "insufficient_trades"
        if days_active < self.cfg.retirement_min_days:
            return False, "insufficient_age"
        # Gate 2: benchmark-relative underperformance
        threshold = benchmark_sharpe - self.cfg.retirement_margin
        if edge_sharpe >= threshold:
            return False, "benchmark_ok"
        # Gate 3: not currently reviving — don't retire an edge that's turning around
        revival_slice = pnls[-self.cfg.retirement_revival_window :]
        if len(revival_slice) >= 5:
            revival_sharpe = _edge_sharpe_from_pnl(revival_slice)
            if revival_sharpe > self.cfg.retirement_revival_sharpe:
                return False, f"currently_reviving_sharpe_{revival_sharpe:.2f}"
        return True, f"benchmark_under_{edge_sharpe:.2f}_vs_{benchmark_sharpe:.2f}_margin_{self.cfg.retirement_margin}"

    def _check_pause_gates(
        self,
        pnls: np.ndarray,
        trade_count: int,
    ) -> Tuple[bool, str]:
        if trade_count < self.cfg.pause_min_trades:
            return False, "insufficient_trades"
        # Recent loss fraction (proxy for MDD without a proper equity curve)
        loss_frac = _edge_loss_fraction(pnls, window=30)
        if loss_frac < self.cfg.pause_loss_fraction_threshold:
            return True, f"loss_fraction_{loss_frac:.2f}"
        # WR collapse
        if trade_count >= 90:
            recent_30 = pnls[-30:]
            all_90 = pnls[-90:]
            wr_recent = (recent_30 > 0).mean()
            wr_90 = (all_90 > 0).mean()
            if wr_recent < wr_90 - self.cfg.pause_wr_collapse:
                return True, f"wr_collapse_{wr_recent:.2f}_vs_{wr_90:.2f}"
        return False, "no_trigger"

    def _check_revival_gates(
        self,
        pnls: np.ndarray,
    ) -> Tuple[bool, str]:
        if len(pnls) < self.cfg.revival_window:
            return False, "insufficient_recent"

        # Phase 2.10d revival veto: an edge whose lifetime cumulative loss
        # exceeds the threshold cannot revive even with a strong-looking
        # recent window. The recent slice on a soft-paused edge is biased —
        # 0.25x sizing happens to look positive over a benign stretch but
        # the edge's structural pattern is a heavy loser. See
        # revival_veto_cumulative_pct_threshold for calibration journey.
        cum_pct = float(pnls.sum()) / max(self.cfg.initial_capital, 1.0)
        if cum_pct < self.cfg.revival_veto_cumulative_pct_threshold:
            return False, (
                f"veto_lifetime_cumulative_{cum_pct:+.4f}_below_"
                f"{self.cfg.revival_veto_cumulative_pct_threshold:+.4f}"
            )

        recent = pnls[-self.cfg.revival_window :]
        recent_sharpe = _edge_sharpe_from_pnl(recent)
        recent_wr = (recent > 0).mean()
        if recent_sharpe > self.cfg.revival_sharpe and recent_wr > self.cfg.revival_wr:
            return True, f"sustained_recovery_sharpe_{recent_sharpe:.2f}_wr_{recent_wr:.2f}"
        return False, "no_recovery"

    # ----------------- Phase 2.10d new triggers ----------------- #

    def _check_zero_fill_pause_gate(
        self,
        n_recent_fills: int,
    ) -> Tuple[bool, str]:
        """Trigger 1 (active → paused). Fires when an edge had fewer than
        `zero_fill_min_fills` entry events in the last `zero_fill_lookback_days`.

        The gate is **firing-rate**, not pnl-conditional — a registered-active
        edge that doesn't fire is dormant regardless of how its rare fills
        performed. Pruning_proposal_2026_04.md cited 5 such registered-active
        but never-firing edges (rsi_bounce_v1, bollinger_reversion_v1,
        earnings_vol_v1, insider_cluster_v1, macro_real_rate_v1) plus 3
        sparse-firing edges (value_deep_v1, pead_short_v1, growth_sales_v1
        partial). All but growth_sales_v1 should trip this gate.
        """
        if n_recent_fills >= self.cfg.zero_fill_min_fills:
            return False, f"alive_fills_{n_recent_fills}"
        return True, (
            f"zero_fill_n_{n_recent_fills}_in_{self.cfg.zero_fill_lookback_days}d"
        )

    def _check_zero_fill_paused_retire_gate(
        self,
        n_recent_fills: int,
        days_since_pause: int,
    ) -> Tuple[bool, str]:
        """Trigger 1 (paused → retired). Fires when an already-paused edge
        has continued to not fire (still below `zero_fill_min_fills`) AND
        has been paused at least `zero_fill_paused_retire_days`.
        """
        if n_recent_fills >= self.cfg.zero_fill_min_fills:
            return False, "paused_revived_via_fills"
        if days_since_pause < self.cfg.zero_fill_paused_retire_days:
            return False, (
                f"paused_only_{days_since_pause}d_of_"
                f"{self.cfg.zero_fill_paused_retire_days}d_required_for_zero_fill_retire"
            )
        return True, (
            f"zero_fill_paused_{days_since_pause}d_n_{n_recent_fills}"
        )

    def _check_sustained_noise_pause_gate(
        self,
        yearly_contributions: Dict[int, float],
        n_fills_in_window: int,
        days_history: int,
    ) -> Tuple[bool, str]:
        """Trigger 2. Fires on edges whose net contribution over the
        rolling N-year window is small in absolute terms AND has at
        least one clearly-negative year.

        Required predicates (all must hold):
          1. Edge has at least `noise_min_fills_in_window` fills in the
             window — so the gate doesn't false-trip on brand-new edges
             with too-small a sample.
          2. |mean per-year contribution| < `noise_mean_threshold` —
             low-magnitude over the window.
          3. min per-year contribution < `noise_negative_year_threshold` —
             at least one clearly-negative year (rules out pead_v1-style
             "rarely fires, all years 0-or-positive").
        """
        if days_history < self.cfg.noise_min_history_days:
            return False, (
                f"insufficient_history_{days_history}d_of_"
                f"{self.cfg.noise_min_history_days}d_required"
            )
        if n_fills_in_window < self.cfg.noise_min_fills_in_window:
            return False, f"insufficient_fills_{n_fills_in_window}"
        if not yearly_contributions:
            return False, "no_yearly_data"

        contributions = list(yearly_contributions.values())
        mean_contrib = float(np.mean(contributions))
        min_contrib = float(np.min(contributions))

        if abs(mean_contrib) >= self.cfg.noise_mean_threshold:
            return False, (
                f"meaningful_mean_{mean_contrib:+.4f}_vs_"
                f"threshold_{self.cfg.noise_mean_threshold:+.4f}"
            )
        if min_contrib >= self.cfg.noise_negative_year_threshold:
            return False, (
                f"no_clearly_negative_year_min_{min_contrib:+.4f}_vs_"
                f"threshold_{self.cfg.noise_negative_year_threshold:+.4f}"
            )

        return True, (
            f"sustained_noise_mean_{mean_contrib:+.4f}_min_year_{min_contrib:+.4f}"
        )

    def _check_retirement_from_paused_gates(
        self,
        pnls: np.ndarray,
        days_since_pause: int,
        edge_sharpe: float,
        benchmark_sharpe: float,
    ) -> Tuple[bool, str]:
        """Gates for retiring an edge that is already in soft-pause.

        An edge can be retired from paused state when all of:
        1. Minimum hold period met: has been soft-paused for at least
           `paused_retirement_min_days` (default 90). Prevents snap-retiring
           an edge that was paused yesterday — give the revival gate time.
        2. Benchmark-relative underperformance: edge_sharpe still below the
           retirement threshold (same margin as active → retire). If an edge
           is recovering toward benchmark, don't retire it.
        3. Not currently reviving: last 20 trades don't show recovery.
           Protects against retiring an edge whose soft-pause data shows
           it turning the corner.

        Returns (fired, gate_label).
        """
        min_days = self.cfg.paused_retirement_min_days
        if min_days <= 0:
            return False, "paused_retirement_disabled"

        if days_since_pause < min_days:
            return False, f"paused_only_{days_since_pause}d_of_{min_days}d_required"

        threshold = benchmark_sharpe - self.cfg.retirement_margin
        if edge_sharpe >= threshold:
            return False, "paused_benchmark_ok"

        revival_slice = pnls[-self.cfg.retirement_revival_window :]
        if len(revival_slice) >= 5:
            revival_sharpe = _edge_sharpe_from_pnl(revival_slice)
            if revival_sharpe > self.cfg.retirement_revival_sharpe:
                return False, f"paused_currently_reviving_sharpe_{revival_sharpe:.2f}"

        return True, (
            f"paused_{days_since_pause}d_benchmark_under_"
            f"{edge_sharpe:.2f}_vs_{benchmark_sharpe:.2f}_margin_{self.cfg.retirement_margin}"
        )

    # ----------------- divergence-detection (Phase α v3) ----------------- #

    def _audit_registry_divergence_check(self) -> List[Dict]:
        """Cross-check audit-trail history against current registry status.

        For each edge that has at least one row in `lifecycle_history.csv`,
        the most recent `new_status` should equal that edge's current
        status in `edges.yml`. If they disagree, something between cycles
        (a config restore, a manual edit, a bug like the 2026-04-25
        EdgeRegistry.ensure() stomp) reverted the lifecycle's decision
        without an audit trail.

        Returns a list of divergence records (also logged). Empty list when
        the audit trail and registry agree, or when either is empty (no
        data to compare yet).

        This is observability, not gating — the lifecycle still proceeds
        with whatever the registry currently says. The point is to make
        silent-revert bugs impossible to hide.
        """
        # Bail cleanly when either side has no data yet
        if not self.history_path.exists() or self.history_path.stat().st_size == 0:
            return []
        registry_specs = self._load_registry()
        if not registry_specs:
            return []

        try:
            history = pd.read_csv(self.history_path)
        except Exception as exc:
            log.debug(f"[Lifecycle] could not read history for divergence check: {exc}")
            return []

        if history.empty or "edge_id" not in history.columns or "new_status" not in history.columns:
            return []

        # Most recent transition per edge_id. Sort by timestamp ascending
        # then keep last per group → that's the latest event the lifecycle
        # ever recorded for that edge.
        try:
            history = history.copy()
            history["timestamp"] = pd.to_datetime(history["timestamp"], errors="coerce")
            history = history.dropna(subset=["timestamp"]).sort_values("timestamp")
            latest_per_edge = (
                history.groupby("edge_id")[["timestamp", "new_status"]]
                .last()
                .to_dict("index")
            )
        except Exception as exc:
            log.debug(f"[Lifecycle] divergence check parse failed: {exc}")
            return []

        registry_status = {
            spec.get("edge_id"): spec.get("status")
            for spec in registry_specs
            if spec.get("edge_id")
        }

        divergences: List[Dict] = []
        for edge_id, info in latest_per_edge.items():
            recorded_status = info.get("new_status")
            current_status = registry_status.get(edge_id)
            if current_status is None:
                # Edge in audit trail but not in registry — could be a
                # rename/removal. Worth flagging but lower-severity.
                divergences.append({
                    "edge_id": edge_id,
                    "audit_says": recorded_status,
                    "registry_says": "<missing>",
                    "kind": "missing_from_registry",
                })
                continue
            if str(recorded_status) != str(current_status):
                divergences.append({
                    "edge_id": edge_id,
                    "audit_says": recorded_status,
                    "registry_says": current_status,
                    "kind": "status_reverted",
                })

        if divergences:
            log.warning(
                "[Lifecycle] DIVERGENCE DETECTED — audit trail and registry disagree "
                "on edge status. This is the signature of the 2026-04-25 "
                "registry-stomp bug class (or a manual edit between cycles). "
                "Investigate before trusting subsequent lifecycle decisions."
            )
            for d in divergences:
                log.warning(
                    f"[Lifecycle]   {d['edge_id']}: audit_trail says "
                    f"{d['audit_says']!r}, registry says {d['registry_says']!r} "
                    f"({d['kind']})"
                )

        return divergences

    # ----------------- persistence ----------------- #

    def _transition(
        self,
        edge_spec: Dict,
        new_status: str,
        gate: str,
        edge_sharpe: float,
        benchmark_sharpe: float,
        edge_mdd: float,
        trade_count: int,
        days_active: int,
        as_of: pd.Timestamp,
    ) -> LifecycleEvent:
        old_status = edge_spec.get("status", "unknown")
        edge_spec["status"] = new_status
        return LifecycleEvent(
            timestamp=as_of.isoformat() if hasattr(as_of, "isoformat") else str(as_of),
            edge_id=edge_spec.get("edge_id", ""),
            old_status=old_status,
            new_status=new_status,
            triggering_gate=gate,
            edge_sharpe=float(edge_sharpe),
            benchmark_sharpe=float(benchmark_sharpe),
            edge_mdd=float(edge_mdd),
            trade_count=int(trade_count),
            days_active=int(days_active),
        )

    def _load_registry(self) -> List[Dict]:
        if not self.registry_path.exists():
            return []
        try:
            data = yaml.safe_load(self.registry_path.read_text()) or {}
            return list(data.get("edges", []))
        except Exception as e:
            log.warning(f"[Lifecycle] Could not load registry: {e}")
            return []

    def _save_registry(self, edges: List[Dict]) -> None:
        try:
            self.registry_path.parent.mkdir(parents=True, exist_ok=True)
            with self.registry_path.open("w") as f:
                yaml.dump({"edges": edges}, f, sort_keys=False)
        except Exception as e:
            log.warning(f"[Lifecycle] Could not save registry: {e}")

    def _append_history(self, events: List[LifecycleEvent]) -> None:
        try:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            write_header = not self.history_path.exists() or self.history_path.stat().st_size == 0
            with self.history_path.open("a", newline="") as f:
                writer = csv.writer(f)
                if write_header:
                    writer.writerow([
                        "timestamp", "edge_id", "old_status", "new_status",
                        "triggering_gate", "edge_sharpe", "benchmark_sharpe",
                        "edge_mdd", "trade_count", "days_active", "notes",
                    ])
                for ev in events:
                    writer.writerow([
                        ev.timestamp, ev.edge_id, ev.old_status, ev.new_status,
                        ev.triggering_gate, f"{ev.edge_sharpe:.4f}",
                        f"{ev.benchmark_sharpe:.4f}", f"{ev.edge_mdd:.4f}",
                        ev.trade_count, ev.days_active, ev.notes,
                    ])
        except Exception as e:
            log.warning(f"[Lifecycle] Could not append history: {e}")


__all__ = ["LifecycleConfig", "LifecycleEvent", "LifecycleManager"]
