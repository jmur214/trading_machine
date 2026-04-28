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

    # Cycle caps
    max_retirements_per_cycle: int = 1
    max_pauses_per_cycle: int = 2


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

        # Filter to closed trades only
        tdf = trades.copy()
        if "pnl" not in tdf.columns or "edge" not in tdf.columns:
            return []
        tdf = tdf[tdf["pnl"].notna() & (tdf["pnl"] != 0)]
        if tdf.empty:
            return []
        if "timestamp" in tdf.columns:
            tdf["timestamp"] = pd.to_datetime(tdf["timestamp"], errors="coerce", utc=True)
            tdf = tdf.dropna(subset=["timestamp"])
        if as_of is None:
            as_of = tdf["timestamp"].max() if "timestamp" in tdf.columns else pd.Timestamp.now(tz="UTC")

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

        # Evaluate each edge. Important: the base-edge registry entries (e.g.
        # atr_breakout_v1) don't have a first-activation timestamp; we treat
        # their "age" as the window span of their trades.
        for edge_spec in edges:
            if retirements_used >= self.cfg.max_retirements_per_cycle and \
               pauses_used >= self.cfg.max_pauses_per_cycle:
                break
            edge_id = edge_spec.get("edge_id", "")
            status = edge_spec.get("status", "unknown")
            if status not in ("active", "paused"):
                continue  # candidate/failed/archived not evaluated here

            sub = tdf[tdf["edge"] == edge_id]
            if sub.empty:
                continue  # No trades — no evidence — no transition

            pnls = sub["pnl"].to_numpy(dtype=float)
            trade_count = len(pnls)
            edge_sharpe = _edge_sharpe_from_pnl(pnls)
            edge_mdd = _edge_loss_fraction(pnls)

            if "timestamp" in sub.columns:
                first_trade = sub["timestamp"].min()
                days_active = int((as_of - first_trade).days)
            else:
                days_active = 0

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

        # Persist registry + history
        if events:
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
        recent = pnls[-self.cfg.revival_window :]
        recent_sharpe = _edge_sharpe_from_pnl(recent)
        recent_wr = (recent > 0).mean()
        if recent_sharpe > self.cfg.revival_sharpe and recent_wr > self.cfg.revival_wr:
            return True, f"sustained_recovery_sharpe_{recent_sharpe:.2f}_wr_{recent_wr:.2f}"
        return False, "no_recovery"

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
