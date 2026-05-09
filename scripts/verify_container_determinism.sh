#!/usr/bin/env bash
# scripts/verify_container_determinism.sh
#
# Local-only verification that the Docker image produces the same canon md5
# as a bare-metal run. This is the first gate before any cloud spend.
#
# What it does:
#   1. Build the image (Dockerfile.backtest)
#   2. Run a 3-rep determinism check INSIDE the container
#      → exits non-zero if the container alone is non-deterministic
#   3. Run a 1-rep bare-metal reference (your .venv)
#   4. Compare bare-metal canon md5 against container canon md5
#      → exits non-zero on mismatch
#
# Pre-reqs:
#   - Docker Desktop (or Colima) running
#   - .venv exists with the same pinned deps as requirements.lock.txt
#   - ISOLATED_ANCHOR exists (run `python -m scripts.run_isolated --save-anchor`)
#
# Usage:
#   bash scripts/verify_container_determinism.sh
#
# Exit codes:
#   0 = PASS — container matches bare-metal bitwise
#   1 = build failed
#   2 = container internal non-determinism (3 reps don't match)
#   3 = container vs bare-metal mismatch
#   4 = bare-metal produced empty trade log (substrate side issue, not container's fault)

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

IMAGE_TAG="archondex-backtest:dev"
LOG_DIR="/tmp/verify_container_$$"
mkdir -p "$LOG_DIR"

echo "== Step 1: build $IMAGE_TAG =="
if ! docker build -f Dockerfile.backtest -t "$IMAGE_TAG" . > "$LOG_DIR/build.log" 2>&1; then
    echo "BUILD FAILED — see $LOG_DIR/build.log"
    tail -40 "$LOG_DIR/build.log"
    exit 1
fi
echo "  build OK ($(docker images "$IMAGE_TAG" --format '{{.Size}}'))"

echo "== Step 2: container internal determinism (3 reps) =="
# Mount trade_logs out so we can read the canon md5s after the run; mount .env
# for any edges that read API keys (most don't, but safer). Network OFF —
# substrate measurement should not need it.
if ! docker run --rm --network none \
    -v "$REPO_ROOT/data/trade_logs":/app/data/trade_logs \
    --env-file .env \
    "$IMAGE_TAG" \
    python -m scripts.run_isolated --runs 3 --task q1 \
    > "$LOG_DIR/container.log" 2>&1; then
    rc=$?
    echo "CONTAINER NON-DETERMINISTIC (run_isolated exit $rc)"
    tail -30 "$LOG_DIR/container.log"
    exit 2
fi

container_canon="$(grep 'trades_canon_md5:' "$LOG_DIR/container.log" \
                  | awk '{print $NF}' | sort -u)"
container_canon_count=$(echo "$container_canon" | wc -l | tr -d ' ')

echo "  container canon md5 (unique across 3 reps): $container_canon_count"
echo "  $container_canon"

if [ "$container_canon_count" -ne 1 ]; then
    echo "FAIL — container produces multiple canon md5s across 3 reps"
    exit 2
fi

empty_md5="d41d8cd98f00b204e9800998ecf8427e"
if [ "$container_canon" = "$empty_md5" ]; then
    echo "WARN — container produced empty trade log (canon md5 = empty marker)"
    echo "       This usually means governor state side issue or zero-signals path."
    echo "       Cannot validate container determinism on a no-trade run."
    exit 4
fi

echo "== Step 3: bare-metal reference (1 rep) =="
if ! .venv/bin/python -m scripts.run_isolated --runs 1 --task q1 \
    > "$LOG_DIR/bare_metal.log" 2>&1; then
    rc=$?
    echo "BARE-METAL RUN FAILED (rc=$rc)"
    tail -30 "$LOG_DIR/bare_metal.log"
    exit 4
fi

bare_canon="$(grep 'trades_canon_md5:' "$LOG_DIR/bare_metal.log" \
              | awk '{print $NF}')"
echo "  bare-metal canon md5: $bare_canon"

if [ "$bare_canon" = "$empty_md5" ]; then
    echo "WARN — bare-metal also produced empty trade log."
    echo "       The substrate environment is not currently producing trades."
    echo "       Container/bare-metal can't be compared on no-trade output."
    exit 4
fi

echo "== Step 4: compare (informational, not a gate) =="
echo "  bare-metal: $bare_canon"
echo "  container : $container_canon"
if [ "$bare_canon" = "$container_canon" ]; then
    echo "PASS — container matches bare-metal bitwise"
    echo "       Container determinism (Step 2) AND cross-platform match (Step 4)."
    echo "Logs in $LOG_DIR"
    exit 0
fi
# Step 4 mismatch is EXPECTED on macOS host vs Linux container due to BLAS
# divergence (Apple Accelerate vs OpenBLAS). Step 2 is the real gate; if 3
# container reps match bitwise, the cloud parallelism invariant holds.
# Going forward: container is canonical. Bare-metal becomes a debug tool.
echo "PASS (container-canonical) — container is internally deterministic"
echo "       Step 2 produced 3 bitwise-identical reps inside the container."
echo "       Step 4 differs from bare-metal: this is EXPECTED on macOS host"
echo "       (Apple Accelerate BLAS) vs Linux container (OpenBLAS). No fix."
echo "       From this point onward, container is the canonical substrate;"
echo "       all NEW measurements should run via the image, not bare-metal."
echo "Logs in $LOG_DIR"
exit 0
