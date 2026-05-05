"""90-day archive enforcement for the Feature Foundry.

Scans every model card on disk, examines its `ablation_history`
window for the last `archive_window_days` (default 90), and flips
`status` to `review_pending` for any feature whose lift trends
negative over that window.

Per CLAUDE.md ("archive don't delete") this script NEVER deletes a
feature. The action is informational: a flagged card surfaces in the
"Review Pending" section of the dashboard's Feature Foundry tab. A
human triages whether the feature stays, gets archived (status set to
`archived` manually), or stays active despite the trend (e.g. the
feature is regime-conditional and the window crossed an off regime).

Trend rule
----------
Within the look-back window, we require:

  * at least `archive_min_observations` ablation observations (default 3
    — below this we're flagging on noise, not trend),
  * mean(contribution_sharpe) over those observations is < 0,
  * AND the most recent observation is < 0 (a single positive late
    print is enough to keep the feature active; this avoids flagging
    on a stale negative streak that's already turned).

We DO NOT flag on a single negative observation; the test must show
sustained underperformance.

Usage
-----

    # Manual run (dry: prints what would change without writing):
    python -m scripts.audit_feature_archive --dry-run

    # Real run — flips status in-place and rewrites the YAML:
    python -m scripts.audit_feature_archive

    # Custom window:
    python -m scripts.audit_feature_archive --window-days 60

    # Re-clear `review_pending` flags before the run (idempotent):
    python -m scripts.audit_feature_archive --reset-pending

Cron sketch (system crontab, weekly Monday 06:00 UTC)
-----------------------------------------------------

    0 6 * * 1 cd /path/to/trading_machine-2 && \\
        .venv/bin/python -m scripts.audit_feature_archive >> \\
        data/feature_foundry/archive_audit.log 2>&1

Or as a GitHub Actions scheduled workflow — see
`.github/workflows/feature_archive_audit.yml` (separate file, not
shipped in this round; the manual + cron paths cover the closeout
acceptance criteria).
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from core.feature_foundry.model_card import (
    CARD_ROOT, ModelCard, load_model_card, VALID_STATUSES,
)


GATE_CONFIG_PATH = REPO_ROOT / "core" / "feature_foundry" / "gate_config.yml"
DEFAULT_WINDOW_DAYS = 90
DEFAULT_MIN_OBSERVATIONS = 3


@dataclass
class AuditDecision:
    feature_id: str
    action: str                       # "flag" | "no_change" | "skipped"
    reason: str
    observations_in_window: int
    mean_lift: Optional[float]
    most_recent_lift: Optional[float]


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def _load_window_days() -> int:
    if not GATE_CONFIG_PATH.exists():
        return DEFAULT_WINDOW_DAYS
    try:
        cfg = yaml.safe_load(GATE_CONFIG_PATH.read_text()) or {}
        return int(cfg.get("archive_window_days", DEFAULT_WINDOW_DAYS))
    except Exception:
        return DEFAULT_WINDOW_DAYS


def _load_min_obs() -> int:
    if not GATE_CONFIG_PATH.exists():
        return DEFAULT_MIN_OBSERVATIONS
    try:
        cfg = yaml.safe_load(GATE_CONFIG_PATH.read_text()) or {}
        return int(cfg.get("archive_min_observations",
                           DEFAULT_MIN_OBSERVATIONS))
    except Exception:
        return DEFAULT_MIN_OBSERVATIONS


# ---------------------------------------------------------------------------
# Trend evaluation
# ---------------------------------------------------------------------------

def _parse_iso_date(value: str) -> Optional[date]:
    """Best-effort parse of an ISO date or full ISO timestamp."""
    if not value:
        return None
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def evaluate_card(
    card: ModelCard,
    window_days: int,
    min_observations: int,
    today: Optional[date] = None,
) -> AuditDecision:
    """Decide whether `card` should be flagged review_pending.

    Pure function — no side effects. The caller is responsible for
    writing the updated card back to disk.
    """
    today = today or date.today()
    cutoff = today - timedelta(days=window_days)

    # Gather lifts within window
    in_window: List[tuple[date, float]] = []
    for row in card.ablation_history:
        d = _parse_iso_date(str(row.get("measured_at", "")))
        if d is None:
            continue
        lift = row.get("contribution_sharpe")
        if lift is None:
            continue
        try:
            lift_f = float(lift)
        except (TypeError, ValueError):
            continue
        if d >= cutoff:
            in_window.append((d, lift_f))

    in_window.sort(key=lambda x: x[0])

    if len(in_window) < min_observations:
        return AuditDecision(
            feature_id=card.feature_id,
            action="skipped",
            reason=(
                f"only {len(in_window)} ablation obs in last "
                f"{window_days}d (need ≥ {min_observations})"
            ),
            observations_in_window=len(in_window),
            mean_lift=None,
            most_recent_lift=None,
        )

    lifts = [v for _, v in in_window]
    mean_lift = sum(lifts) / len(lifts)
    most_recent = lifts[-1]

    # Already flagged? Note it but don't re-flag (idempotent).
    if card.status == "review_pending":
        return AuditDecision(
            feature_id=card.feature_id,
            action="no_change",
            reason="already review_pending",
            observations_in_window=len(in_window),
            mean_lift=mean_lift,
            most_recent_lift=most_recent,
        )

    if card.status == "archived":
        return AuditDecision(
            feature_id=card.feature_id,
            action="no_change",
            reason="already archived (human-triage decision)",
            observations_in_window=len(in_window),
            mean_lift=mean_lift,
            most_recent_lift=most_recent,
        )

    if mean_lift < 0 and most_recent < 0:
        return AuditDecision(
            feature_id=card.feature_id,
            action="flag",
            reason=(
                f"mean lift {mean_lift:+.4f} over last {len(in_window)} "
                f"obs in {window_days}d AND most-recent {most_recent:+.4f} "
                f"both negative"
            ),
            observations_in_window=len(in_window),
            mean_lift=mean_lift,
            most_recent_lift=most_recent,
        )

    return AuditDecision(
        feature_id=card.feature_id,
        action="no_change",
        reason=(
            f"mean lift {mean_lift:+.4f} over last {len(in_window)} obs; "
            f"most-recent {most_recent:+.4f}"
        ),
        observations_in_window=len(in_window),
        mean_lift=mean_lift,
        most_recent_lift=most_recent,
    )


# ---------------------------------------------------------------------------
# Side-effecting orchestration
# ---------------------------------------------------------------------------

def apply_decision(card: ModelCard, decision: AuditDecision,
                   root: Path) -> None:
    """Mutate the card in-place and write it back when the action is
    `flag`. No-op for other actions. Updates `last_ablation_date` /
    `last_ablation_lift` to mirror the most-recent observation."""
    if decision.action != "flag":
        return
    card.status = "review_pending"
    card.flagged_reason = decision.reason
    if decision.most_recent_lift is not None:
        card.last_ablation_lift = float(decision.most_recent_lift)
    # Record the audit timestamp on the card for traceability.
    card.last_ablation_date = date.today().isoformat()
    card.write(root=root)


def reset_pending(root: Path = CARD_ROOT) -> int:
    """Optional: clear all `review_pending` flags before re-running.
    Use when iterating on the trend rule. Returns count cleared."""
    count = 0
    for path in sorted(root.glob("*.yml")):
        try:
            data = yaml.safe_load(path.read_text()) or {}
            card = ModelCard.from_dict(data)
        except Exception:
            continue
        if card.status == "review_pending":
            card.status = "active"
            card.flagged_reason = None
            card.write(root=root)
            count += 1
    return count


def run_audit(
    root: Path = CARD_ROOT,
    window_days: Optional[int] = None,
    min_observations: Optional[int] = None,
    dry_run: bool = False,
    today: Optional[date] = None,
) -> List[AuditDecision]:
    """Iterate over every card in `root`, evaluate, and (unless
    `dry_run`) write back. Returns the per-card decisions."""
    window_days = window_days if window_days is not None else _load_window_days()
    min_observations = (
        min_observations
        if min_observations is not None else _load_min_obs()
    )

    decisions: List[AuditDecision] = []
    if not root.exists():
        print(f"[audit] no cards directory at {root}; nothing to do.")
        return decisions

    for path in sorted(root.glob("*.yml")):
        try:
            data = yaml.safe_load(path.read_text()) or {}
            card = ModelCard.from_dict(data)
        except Exception as exc:
            print(f"[audit][SKIP] {path.name}: parse error — {exc}")
            continue
        decision = evaluate_card(
            card, window_days, min_observations, today=today,
        )
        decisions.append(decision)
        flag = {
            "flag": "FLAG",
            "no_change": "ok",
            "skipped": "skip",
        }.get(decision.action, decision.action)
        print(f"[audit][{flag}] {decision.feature_id}: {decision.reason}")
        if not dry_run:
            apply_decision(card, decision, root=root)

    flagged = [d for d in decisions if d.action == "flag"]
    print(
        f"[audit] {len(decisions)} card(s) evaluated; "
        f"{len(flagged)} newly flagged review_pending"
    )
    return decisions


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would change without writing.",
    )
    parser.add_argument(
        "--window-days", type=int, default=None,
        help="Look-back window (default from gate_config.yml or 90).",
    )
    parser.add_argument(
        "--min-observations", type=int, default=None,
        help="Min ablation obs required to flag (default 3).",
    )
    parser.add_argument(
        "--reset-pending", action="store_true",
        help="Clear all review_pending flags before evaluating.",
    )
    parser.add_argument(
        "--cards-dir", type=Path, default=CARD_ROOT,
        help="Override the cards directory (default core/feature_foundry/model_cards).",
    )
    args = parser.parse_args()

    if args.reset_pending and not args.dry_run:
        cleared = reset_pending(root=args.cards_dir)
        print(f"[audit] reset {cleared} review_pending flag(s)")

    run_audit(
        root=args.cards_dir,
        window_days=args.window_days,
        min_observations=args.min_observations,
        dry_run=args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
