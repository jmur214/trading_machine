"""Auto-ablation runner.

F3 of the Feature Foundry. Given a baseline backtest result and a set of
features, drop each feature in turn, re-run the deterministic harness,
measure portfolio impact (Δ Sharpe), and persist the contribution table.

This module ships the *runner* — the cron scheduler + integration with
the production backtest pipeline are deliberate follow-ups (see the
architecture doc). The runner is callable, deterministic, and tested
against a synthetic backtest function so the substrate ships without
blocking on the broader gauntlet refactor.

The contract:

    def run_ablation(
        feature_ids: list[str],
        baseline_run_uuid: str,
        backtest_fn: Callable[[set[str]], float],   # returns Sharpe
    ) -> dict[str, AblationResult]

`backtest_fn` accepts the SET of feature_ids to include (the universe
minus the dropped one) and returns the realised harness Sharpe. The
runner computes baseline Sharpe once (full set), then leave-one-out
Sharpe for each feature. The contribution is `baseline - dropped`:
positive ⇒ the feature contributed alpha; negative ⇒ removing the
feature improved the portfolio (90-day archive candidate per the
reviewer's archive rule).

Persisted results land at:

    data/feature_foundry/ablation/<run_uuid>.json
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
import json


ABLATION_ROOT = Path("data/feature_foundry/ablation")


@dataclass
class AblationResult:
    feature_id: str
    baseline_sharpe: float
    dropped_sharpe: float
    contribution_sharpe: float       # baseline - dropped (positive = useful)
    measured_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def run_ablation(
    feature_ids: List[str],
    baseline_run_uuid: str,
    backtest_fn: Callable[[set], float],
    persist: bool = True,
    out_root: Path = ABLATION_ROOT,
) -> Dict[str, AblationResult]:
    """Leave-one-out ablation over `feature_ids`.

    Parameters
    ----------
    feature_ids : list[str]
        The universe of features under test. The baseline includes all of
        them; each dropped run includes (universe - {one}).
    baseline_run_uuid : str
        Identifier for the run cohort — used as the persistence filename.
    backtest_fn : Callable[[set[str]], float]
        Deterministic harness function. Takes a set of included features,
        returns realised Sharpe. The runner does NOT know how this works
        internally — it just calls it once per ablation cell. Production
        integration will pass a closure over the existing backtest entry
        point; for tests, a synthetic linear-contribution function is fine.
    persist : bool
        Write results to JSON at `out_root/<baseline_run_uuid>.json`.
    """
    if not feature_ids:
        return {}

    universe = set(feature_ids)
    baseline_sharpe = backtest_fn(universe)
    measured_at = datetime.now(timezone.utc).isoformat()

    results: Dict[str, AblationResult] = {}
    for fid in feature_ids:
        dropped_sharpe = backtest_fn(universe - {fid})
        results[fid] = AblationResult(
            feature_id=fid,
            baseline_sharpe=baseline_sharpe,
            dropped_sharpe=dropped_sharpe,
            contribution_sharpe=baseline_sharpe - dropped_sharpe,
            measured_at=measured_at,
        )

    if persist:
        out_root.mkdir(parents=True, exist_ok=True)
        out_path = out_root / f"{baseline_run_uuid}.json"
        payload = {
            "baseline_run_uuid": baseline_run_uuid,
            "baseline_sharpe": baseline_sharpe,
            "measured_at": measured_at,
            "results": {fid: r.to_dict() for fid, r in results.items()},
        }
        out_path.write_text(json.dumps(payload, indent=2))

    return results


def load_ablation(baseline_run_uuid: str,
                  out_root: Path = ABLATION_ROOT) -> Optional[dict]:
    """Read back a persisted ablation result, or None if not found."""
    path = out_root / f"{baseline_run_uuid}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text())


def latest_ablation(out_root: Path = ABLATION_ROOT) -> Optional[dict]:
    """Return the most-recently written ablation payload, or None."""
    if not out_root.exists():
        return None
    paths = sorted(out_root.glob("*.json"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    if not paths:
        return None
    return json.loads(paths[0].read_text())


def latest_ablation_for_feature(
    feature_id: str,
    out_root: Path = ABLATION_ROOT,
) -> Optional[float]:
    """Return the most recent contribution_sharpe value for a feature
    across all persisted ablation runs, or None if no run has scored it."""
    if not out_root.exists():
        return None
    paths = sorted(out_root.glob("*.json"), key=lambda p: p.stat().st_mtime,
                   reverse=True)
    for p in paths:
        try:
            payload = json.loads(p.read_text())
        except Exception:
            continue
        results = payload.get("results") or {}
        if feature_id in results:
            row = results[feature_id]
            return float(row["contribution_sharpe"])
    return None
