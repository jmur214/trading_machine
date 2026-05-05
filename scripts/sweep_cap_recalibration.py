"""
scripts/sweep_cap_recalibration.py
==================================
Phase 2.10d follow-up: cap-recalibration sweep.

Runs a single 2025 OOS Q1 backtest under specified cap values by
temporarily patching:
  - config/alpha_settings.prod.json -> fill_share_cap
  - config/regime_settings.json    -> advisory.crisis_max_positions
                                    -> advisory.stressed_max_positions

Files are restored on exit (success or exception).

Run labels:
  a0 — cap=0.25, crisis=5, stressed=7 (task C baseline reproduction)
  a1 — cap=0.35, crisis=5, stressed=7 (mild loosen, fill-share only)
  a2 — cap=0.45, crisis=7, stressed=9 (medium loosen, coordinated)
  a3 — cap=0.20, crisis=5, stressed=7 (tighter sanity check)

Usage:
  PYTHONHASHSEED=0 python -m scripts.sweep_cap_recalibration --run a0
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

ROOT = Path(__file__).resolve().parents[1]
ALPHA_PROD = ROOT / "config" / "alpha_settings.prod.json"
REGIME = ROOT / "config" / "regime_settings.json"
RESEARCH_DIR = ROOT / "data" / "research"
TRADES_DIR = ROOT / "data" / "trade_logs"

# Lifecycle state files. The autonomous lifecycle (Engine F) mutates
# edges.yml at the END of every backtest, so a naive sweep would test
# each subsequent cap value under a progressively more-pruned edge
# stack. To isolate the cap-value-only effect, snapshot these once and
# restore them before each run.
#
# 2026-05-01 update: list synced with scripts/run_isolated.py
# (lifecycle_history.csv added). Per
# docs/Measurements/2026-05/determinism_floor_restore_2026_05.md the bisect found
# `edges.yml` is the exclusive drift source, but lifecycle_history.csv
# is in the harness for divergence-check observability.
GOVERNOR_DIR = ROOT / "data" / "governor"
LIFECYCLE_FILES = [
    GOVERNOR_DIR / "edges.yml",
    GOVERNOR_DIR / "edge_weights.json",
    GOVERNOR_DIR / "regime_edge_performance.json",
    GOVERNOR_DIR / "lifecycle_history.csv",
]
SWEEP_ANCHOR_DIR = GOVERNOR_DIR / "_cap_recal_anchor"


PRESETS = {
    "a0": {"fill_share_cap": 0.25, "crisis_max_positions": 5,
           "stressed_max_positions": 7,
           "start": "2025-01-01", "end": "2025-12-31",
           "label": "baseline (task C reproduction)"},
    "a1": {"fill_share_cap": 0.35, "crisis_max_positions": 5,
           "stressed_max_positions": 7,
           "start": "2025-01-01", "end": "2025-12-31",
           "label": "mild loosen — fill-share only"},
    "a2": {"fill_share_cap": 0.45, "crisis_max_positions": 7,
           "stressed_max_positions": 9,
           "start": "2025-01-01", "end": "2025-12-31",
           "label": "medium loosen — coordinated"},
    "a3": {"fill_share_cap": 0.20, "crisis_max_positions": 5,
           "stressed_max_positions": 7,
           "start": "2025-01-01", "end": "2025-12-31",
           "label": "tighter sanity check"},
    # Phase 2.10d round-2 bracket sweep below 0.20 on 2025 OOS:
    "b1": {"fill_share_cap": 0.10, "crisis_max_positions": 5,
           "stressed_max_positions": 7,
           "start": "2025-01-01", "end": "2025-12-31",
           "label": "bracket — very tight (0.10) on 2025 OOS"},
    "b2": {"fill_share_cap": 0.15, "crisis_max_positions": 5,
           "stressed_max_positions": 7,
           "start": "2025-01-01", "end": "2025-12-31",
           "label": "bracket — tight (0.15) on 2025 OOS"},
    "b3": {"fill_share_cap": 0.20, "crisis_max_positions": 5,
           "stressed_max_positions": 7,
           "start": "2025-01-01", "end": "2025-12-31",
           "label": "bracket — A3 reproduction (0.20) on 2025 OOS"},
    # Multi-year robustness check on the chosen optimum (window = task C
    # in-sample anchor that produced the original 1.063 Sharpe):
    "is_optimum": {"fill_share_cap": 0.20, "crisis_max_positions": 5,
                   "stressed_max_positions": 7,
                   "start": "2021-01-01", "end": "2024-12-31",
                   "label": "in-sample 2021-2024 robustness — chosen optimum"},
}


def snapshot_lifecycle_state() -> None:
    """Copy lifecycle/governor files into _cap_recal_anchor/. Idempotent."""
    SWEEP_ANCHOR_DIR.mkdir(parents=True, exist_ok=True)
    for src in LIFECYCLE_FILES:
        if src.exists():
            shutil.copy(src, SWEEP_ANCHOR_DIR / src.name)
    print(f"[SWEEP] Snapshotted lifecycle state to {SWEEP_ANCHOR_DIR}")


def restore_lifecycle_state() -> None:
    """Restore lifecycle/governor files from _cap_recal_anchor/.

    For files absent in the anchor (e.g. lifecycle_history.csv when
    snapshotted from an empty-history state), DELETE the live copy so
    the run starts from the same empty-history state. Mirrors the
    semantics of `scripts.run_isolated.restore_anchor`.
    """
    if not SWEEP_ANCHOR_DIR.exists():
        raise RuntimeError(
            f"No anchor at {SWEEP_ANCHOR_DIR}; run with --snapshot first"
        )
    for dst in LIFECYCLE_FILES:
        src = SWEEP_ANCHOR_DIR / dst.name
        if src.exists():
            shutil.copy(src, dst)
        elif dst.exists():
            dst.unlink()
    print(f"[SWEEP] Restored lifecycle state from {SWEEP_ANCHOR_DIR}")


@contextmanager
def patched_configs(fill_share_cap: float, crisis_max: int,
                    stressed_max: int) -> Iterator[None]:
    """Patch alpha_settings.prod.json + regime_settings.json with the
    target cap values. Restore both files on exit."""
    alpha_bak = ALPHA_PROD.with_suffix(".json.cap_recal_bak")
    regime_bak = REGIME.with_suffix(".json.cap_recal_bak")
    shutil.copy(ALPHA_PROD, alpha_bak)
    shutil.copy(REGIME, regime_bak)

    with open(ALPHA_PROD) as f:
        alpha_cfg = json.load(f)
    alpha_cfg["fill_share_cap"] = fill_share_cap
    with open(ALPHA_PROD, "w") as f:
        json.dump(alpha_cfg, f, indent=2)

    with open(REGIME) as f:
        regime_cfg = json.load(f)
    advisory = regime_cfg.get("advisory", {})
    advisory["crisis_max_positions"] = crisis_max
    advisory["stressed_max_positions"] = stressed_max
    regime_cfg["advisory"] = advisory
    with open(REGIME, "w") as f:
        json.dump(regime_cfg, f, indent=2)

    print(f"[SWEEP] Patched fill_share_cap={fill_share_cap}, "
          f"crisis_max_positions={crisis_max}, "
          f"stressed_max_positions={stressed_max}")
    try:
        yield
    finally:
        shutil.copy(alpha_bak, ALPHA_PROD)
        shutil.copy(regime_bak, REGIME)
        alpha_bak.unlink(missing_ok=True)
        regime_bak.unlink(missing_ok=True)
        print("[SWEEP] Restored alpha_settings.prod.json and regime_settings.json")


def find_run_id(before: set[str]) -> str | None:
    after = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}
    new = after - before
    if not new:
        return None
    if len(new) == 1:
        return next(iter(new))
    candidates = [(p, p.stat().st_mtime) for p in TRADES_DIR.iterdir() if p.name in new]
    candidates.sort(key=lambda x: x[1], reverse=True)
    return candidates[0][0].name


def run_one(label: str, preset: dict, restore_anchor: bool = True,
             post_restore: bool = True) -> dict:
    """Run a single 2025 Q1 OOS under the given preset.

    If restore_anchor=True (default), restore the lifecycle state from
    _cap_recal_anchor/ before the run so each run starts from the same
    edges.yml + governor state. Set False on the very first run if you
    just took the snapshot from current state.

    If post_restore=True (default, since 2026-05-01), ALSO restore from
    the anchor AFTER the run so the next sweep call starts from the
    same state. This makes the sweep harness equivalent to
    `run_isolated.isolated()`. Pass `post_restore=False` for legacy
    behavior where end-of-run lifecycle mutations are kept.
    """
    from orchestration.mode_controller import ModeController
    from core.benchmark import compute_multi_benchmark_metrics

    print(f"[SWEEP-{label.upper()}] {preset['label']}")
    print(f"[SWEEP-{label.upper()}] fill_share_cap={preset['fill_share_cap']}, "
          f"crisis={preset['crisis_max_positions']}, "
          f"stressed={preset['stressed_max_positions']}")

    if restore_anchor:
        restore_lifecycle_state()

    before = {p.name for p in TRADES_DIR.iterdir() if p.is_dir() and p.name != "backup"}

    start = preset.get("start", "2025-01-01")
    end = preset.get("end", "2025-12-31")

    with patched_configs(
        fill_share_cap=preset["fill_share_cap"],
        crisis_max=preset["crisis_max_positions"],
        stressed_max=preset["stressed_max_positions"],
    ):
        mc = ModeController(ROOT, env="prod")
        summary = mc.run_backtest(
            mode="prod",
            fresh=False,
            no_governor=False,
            reset_governor=True,
            alpha_debug=False,
            override_start=start,
            override_end=end,
        )

    if post_restore:
        # 2026-05-01: restore-on-exit makes the sweep idempotent across
        # invocations. Without this, the next sweep --run sees the prior
        # run's mutated edges.yml/lifecycle_history and produces drifted
        # numbers (the round-2 vs round-3 ±1.4 Sharpe variance).
        restore_lifecycle_state()

    run_id = find_run_id(before)
    summary["run_id"] = run_id
    summary["window"] = f"{start} to {end}"
    summary["universe"] = "prod (109 tickers)"
    summary["sweep_label"] = label
    summary["preset"] = preset
    summary["timestamp"] = datetime.utcnow().isoformat() + "Z"

    multi = compute_multi_benchmark_metrics(start=start, end=end)
    summary["benchmarks"] = {
        name: {
            "sharpe": round(bm.sharpe, 3),
            "cagr_pct": round(bm.cagr * 100, 2),
            "mdd_pct": round(bm.mdd * 100, 2),
            "vol_pct": round(bm.vol * 100, 2),
            "n_obs": bm.n_obs,
        }
        for name, bm in multi.items()
    }

    out_path = RESEARCH_DIR / f"cap_recalibration_{label}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(summary, f, indent=2)

    print(f"[SWEEP-{label.upper()}] Saved to {out_path}")
    print(f"  run_id: {run_id}")
    print(f"  Sharpe: {summary.get('Sharpe Ratio')}")
    print(f"  CAGR%:  {summary.get('CAGR (%)')}")
    print(f"  MDD%:   {summary.get('Max Drawdown (%)')}")
    print(f"  Vol%:   {summary.get('Volatility (%)')}")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", choices=list(PRESETS.keys()), default=None,
                        help="Run a single preset (a0/a1/a2/a3).")
    parser.add_argument("--snapshot", action="store_true",
                        help="Snapshot current lifecycle state to "
                             "_cap_recal_anchor/. Run once before sweeping.")
    parser.add_argument("--no-restore", action="store_true",
                        help="Skip restoring the anchor before --run "
                             "(useful for the very first run after --snapshot).")
    parser.add_argument("--no-isolation", action="store_true",
                        help="Disable post-run restore (legacy behavior). "
                             "Default-on means the sweep is idempotent across "
                             "invocations; opt out only when you specifically "
                             "want end-of-run lifecycle mutations to persist.")
    args = parser.parse_args()

    if args.snapshot:
        snapshot_lifecycle_state()
        if not args.run:
            return 0
    if args.run:
        run_one(args.run, PRESETS[args.run],
                restore_anchor=not args.no_restore,
                post_restore=not args.no_isolation)
    return 0


if __name__ == "__main__":
    sys.exit(main())
