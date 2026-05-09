#!/usr/bin/env bash
# scripts/cloud_entrypoint.sh
#
# Container entrypoint for AWS Batch / Fargate runs.
#
# Wraps `python -m scripts.run_isolated --runs 1` so trade logs +
# performance_summary land in S3 instead of ephemeral container disk.
#
# Why a wrapper script: Fargate task disk is gone the moment the container
# exits, so the harness's local `data/trade_logs/<run_id>/` files are lost
# unless we explicitly upload them. This script does the upload.
#
# Required environment (set by the Batch job definition or submit-time):
#   ARCHONDEX_RESULTS_BUCKET — e.g., archondex-results-407539788432
#   ARCHONDEX_CELL_ID        — director-supplied cell identifier (rep × arm)
#                              used as the S3 prefix; falls back to the
#                              run-uuid if unset.
#
# Stdout pattern (so the parent launcher can parse):
#   CANON_MD5=<hex32>
#   CELL_ID=<id>
#   S3_PREFIX=<s3://...>

set -euo pipefail

if [ -z "${ARCHONDEX_RESULTS_BUCKET:-}" ]; then
    echo "ERROR: ARCHONDEX_RESULTS_BUCKET not set" >&2
    exit 64
fi

# Run the harness and capture its stdout (canon md5 lives there).
# `tee` so the same lines also stream to CloudWatch.
HARNESS_LOG=/tmp/harness.log
python -m scripts.run_isolated --runs 1 --task q1 2>&1 | tee "$HARNESS_LOG"

CANON_MD5=$(grep -E "trades_canon_md5:" "$HARNESS_LOG" | awk '{print $NF}' | tr -d '[:space:]')
RUN_ID=$(grep -E "^\s+run_id:" "$HARNESS_LOG" | awk '{print $NF}' | tr -d '[:space:]')
SHARPE=$(grep -E "^\s+Sharpe:" "$HARNESS_LOG" | awk '{print $NF}' | tr -d '[:space:]')
CELL_ID="${ARCHONDEX_CELL_ID:-$RUN_ID}"

if [ -z "$RUN_ID" ] || [ "$RUN_ID" = "?" ]; then
    echo "ERROR: harness did not produce a run_id; nothing to upload" >&2
    exit 65
fi

S3_PREFIX="s3://${ARCHONDEX_RESULTS_BUCKET}/${CELL_ID}/${RUN_ID}"

# Upload everything in the run dir
RUN_DIR="/app/data/trade_logs/${RUN_ID}"
if [ ! -d "$RUN_DIR" ]; then
    echo "ERROR: run dir $RUN_DIR not found" >&2
    exit 66
fi

aws s3 cp --recursive --no-progress "$RUN_DIR" "$S3_PREFIX/" \
    --metadata "canon-md5=${CANON_MD5},sharpe=${SHARPE},cell-id=${CELL_ID}"

# Also upload a small manifest summarizing the run for the launcher
MANIFEST=/tmp/manifest.json
cat > "$MANIFEST" <<EOF
{
  "run_id":         "$RUN_ID",
  "cell_id":        "$CELL_ID",
  "canon_md5":      "$CANON_MD5",
  "sharpe":         "$SHARPE",
  "s3_prefix":      "$S3_PREFIX",
  "completed_at":   "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF
aws s3 cp --no-progress "$MANIFEST" "$S3_PREFIX/manifest.json"

# Stdout markers the parent launcher parses
echo "CANON_MD5=$CANON_MD5"
echo "CELL_ID=$CELL_ID"
echo "S3_PREFIX=$S3_PREFIX"
echo "SHARPE=$SHARPE"
