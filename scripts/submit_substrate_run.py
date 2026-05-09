"""scripts/submit_substrate_run.py

Director-side launcher: submit N parallel substrate-measurement cells
to AWS Batch, poll until all complete, fetch results from S3, summarize.

Phase 6 of the cloud-prep spike. Replaces the local-sequential
`python -m scripts.run_isolated --runs N` path with N parallel Fargate
workers running the same archondex-backtest image.

Why this exists:
    Local: 6 cells × ~1.5 hr each = 9-10 hr wall clock.
    Cloud: 6 cells in parallel = ~1.5 hr wall clock.

Usage:
    python scripts/submit_substrate_run.py --reps 3 --arms 1,2

Outputs:
    Per-cell trade logs land in `s3://archondex-results-<acct>/<cell_id>/<run_id>/`
    Per-cell manifest summary at `<prefix>/manifest.json`
    Local: a CSV summary table printed to stdout + written to
           `data/cloud_runs/substrate_<launch_ts>.csv`
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

ACCOUNT_ID = "407539788432"
REGION = "us-east-1"
RESULTS_BUCKET = f"archondex-results-{ACCOUNT_ID}"
JOB_QUEUE = "archondex-backtest-queue"
JOB_DEFINITION = "archondex-backtest"  # picks the latest revision
TERMINAL_STATES = {"SUCCEEDED", "FAILED"}


def aws(*args: str) -> str:
    """Run an AWS CLI command via the `archondex` profile in `us-east-1`.
    Returns stdout. Raises on non-zero exit."""
    cmd = ["aws", *args, "--region", REGION, "--profile", "archondex",
           "--output", "json"]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return result.stdout


@dataclass
class Cell:
    cell_id: str
    rep: int
    arm: int
    job_id: Optional[str] = None
    status: Optional[str] = None
    canon_md5: Optional[str] = None
    sharpe: Optional[str] = None
    s3_prefix: Optional[str] = None
    log_stream: Optional[str] = None
    started_at: Optional[int] = None
    stopped_at: Optional[int] = None


def submit(cell: Cell, job_definition: str) -> Cell:
    """Submit one Batch job for this cell."""
    payload = {
        "jobName": f"substrate-{cell.cell_id}",
        "jobQueue": JOB_QUEUE,
        "jobDefinition": job_definition,
        "containerOverrides": {
            "command": ["bash", "scripts/cloud_entrypoint.sh"],
            "environment": [
                {"name": "ARCHONDEX_RESULTS_BUCKET", "value": RESULTS_BUCKET},
                {"name": "ARCHONDEX_CELL_ID", "value": cell.cell_id},
                {"name": "ARCHONDEX_REP", "value": str(cell.rep)},
                {"name": "ARCHONDEX_ARM", "value": str(cell.arm)},
            ],
        },
    }
    out = aws("batch", "submit-job", "--cli-input-json", json.dumps(payload))
    cell.job_id = json.loads(out)["jobId"]
    return cell


def poll_once(cells: list[Cell]) -> None:
    """Update status on every non-terminal cell with one describe-jobs call."""
    pending = [c for c in cells if c.status not in TERMINAL_STATES]
    if not pending:
        return
    job_ids = [c.job_id for c in pending if c.job_id]
    if not job_ids:
        return
    out = aws("batch", "describe-jobs", "--jobs", *job_ids)
    by_id = {j["jobId"]: j for j in json.loads(out)["jobs"]}
    for c in pending:
        j = by_id.get(c.job_id)
        if not j:
            continue
        c.status = j.get("status")
        c.started_at = j.get("startedAt")
        c.stopped_at = j.get("stoppedAt")
        c.log_stream = (j.get("container") or {}).get("logStreamName")


def fetch_manifest(cell: Cell) -> None:
    """Pull the entrypoint-written manifest from S3 to populate canon_md5 etc."""
    if cell.status != "SUCCEEDED":
        return
    s3_path = f"s3://{RESULTS_BUCKET}/{cell.cell_id}/"
    # Find the run_id subdir (entrypoint writes <bucket>/<cell_id>/<run_id>/manifest.json)
    out = aws("s3api", "list-objects-v2",
              "--bucket", RESULTS_BUCKET,
              "--prefix", f"{cell.cell_id}/",
              "--query", "Contents[?ends_with(Key, `manifest.json`)].Key",
              "--output", "json")
    keys = json.loads(out) or []
    if not keys:
        print(f"  [{cell.cell_id}] WARN: no manifest.json under {s3_path}")
        return
    key = keys[0]
    raw = subprocess.run(
        ["aws", "s3", "cp", f"s3://{RESULTS_BUCKET}/{key}", "-",
         "--region", REGION, "--profile", "archondex"],
        check=True, capture_output=True, text=True
    ).stdout
    m = json.loads(raw)
    cell.canon_md5 = m.get("canon_md5")
    cell.sharpe = m.get("sharpe")
    cell.s3_prefix = m.get("s3_prefix")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reps", type=int, default=3,
                    help="Number of reps per arm (default 3).")
    ap.add_argument("--arms", type=str, default="1,2",
                    help="Comma-separated arm IDs (default 1,2).")
    ap.add_argument("--job-def", type=str, default=JOB_DEFINITION,
                    help="Batch job definition name (default archondex-backtest, "
                         "uses latest revision).")
    ap.add_argument("--poll-interval", type=int, default=20,
                    help="Seconds between describe-jobs polls (default 20).")
    ap.add_argument("--out-dir", type=Path,
                    default=Path("data/cloud_runs"),
                    help="Local dir for the summary CSV.")
    args = ap.parse_args()

    arms = [int(a) for a in args.arms.split(",")]
    launch_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    cells: list[Cell] = []
    for rep in range(1, args.reps + 1):
        for arm in arms:
            cells.append(Cell(cell_id=f"{launch_ts}-rep{rep}-arm{arm}",
                              rep=rep, arm=arm))

    print(f"Launching {len(cells)} parallel cells "
          f"(reps={args.reps}, arms={arms})")
    print(f"Job definition: {args.job_def}")
    print(f"Results bucket: s3://{RESULTS_BUCKET}/")

    # Parallel submit (small thread pool for low-latency boto/CLI calls)
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda c: submit(c, args.job_def), cells))

    for c in cells:
        print(f"  submitted {c.cell_id} -> jobId {c.job_id}")

    # Poll loop
    print(f"\nPolling every {args.poll_interval}s until all reach a terminal state...")
    while True:
        poll_once(cells)
        n_done = sum(1 for c in cells if c.status in TERMINAL_STATES)
        n_running = sum(1 for c in cells if c.status == "RUNNING")
        n_pending = len(cells) - n_done - n_running
        print(f"  status: {n_done}/{len(cells)} done | "
              f"{n_running} running | {n_pending} pending/starting")
        if n_done == len(cells):
            break
        time.sleep(args.poll_interval)

    # Fetch manifests (parallel — small per-cell cost)
    print("\nFetching per-cell manifests from S3...")
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch_manifest, cells))

    # Summary
    print("\n========== SUMMARY ==========")
    print(f"{'cell_id':<35} {'status':<10} {'sharpe':<8} {'canon_md5':<33}")
    print("-" * 90)
    for c in cells:
        print(f"{c.cell_id:<35} {c.status or '?':<10} "
              f"{c.sharpe or '?':<8} {c.canon_md5 or '?':<33}")

    args.out_dir.mkdir(parents=True, exist_ok=True)
    out_path = args.out_dir / f"substrate_{launch_ts}.csv"
    with out_path.open("w") as f:
        f.write("cell_id,rep,arm,status,sharpe,canon_md5,s3_prefix,log_stream\n")
        for c in cells:
            f.write(f"{c.cell_id},{c.rep},{c.arm},{c.status},"
                    f"{c.sharpe or ''},{c.canon_md5 or ''},"
                    f"{c.s3_prefix or ''},{c.log_stream or ''}\n")
    print(f"\nSummary CSV: {out_path}")

    n_failed = sum(1 for c in cells if c.status != "SUCCEEDED")
    if n_failed:
        print(f"WARN: {n_failed} cell(s) did not succeed", file=sys.stderr)
        return 1

    # Determinism sanity: across reps within the same arm, canon_md5 should match
    arm_md5s: dict[int, set[str]] = {}
    for c in cells:
        if c.canon_md5:
            arm_md5s.setdefault(c.arm, set()).add(c.canon_md5)
    print("\nDeterminism check (within-arm canon md5 unique counts):")
    for arm, md5s in sorted(arm_md5s.items()):
        marker = "OK" if len(md5s) == 1 else "DRIFT"
        print(f"  arm {arm}: {len(md5s)} unique md5s across reps  [{marker}]")

    return 0


if __name__ == "__main__":
    sys.exit(main())
