# Cloud Runbook — AWS Batch backtest parallelism

**Status:** SPIKE-1 done (Dockerfile + lockfile + local determinism verify). Awaiting AWS account creation + Docker Desktop install before SPIKE-2.

This doc is the canonical sequence for setting up AWS-side infrastructure for parallel substrate measurements. Treat as a checklist; don't skip steps; if something doesn't work, update this doc rather than hold the knowledge in chat history.

---

## Why this exists

Substrate measurements (e.g., T-2026-05-08-002) take 9-11 hr wall-clock locally because the harness runs 6 individual backtests sequentially (3 reps × 2 arms). Each individual backtest is single-threaded Python.

**The cloud thesis:** containerize the harness, push to AWS Batch, run all 6 in parallel on Fargate. Wall time drops from ~10 hr → ~2 hr. Cost target: $1-3 per substrate measurement.

This is HORIZONTAL parallelism (run more in parallel), not VERTICAL (faster per run). The single-threaded Python won't get faster on a bigger box; we're using cloud to run more boxes at once.

---

## Architecture (one-paragraph)

Local director writes a brief specifying (universe, edges, window, n_reps). A Python launcher invokes `aws batch submit-job` once per (rep, arm) cell. Each Batch job pulls the `archondex-backtest:dev` image from ECR, runs `python -m scripts.run_isolated --runs 1` inside the container, writes its trade log + performance summary to S3 under `s3://archondex-results-<account>/<run_id>/`. The director polls `aws batch describe-jobs` until all complete, then pulls the per-cell trade logs back, runs aggregation locally, writes the audit doc.

---

## Sequence

### Phase 0 — Local prerequisites (one-time, you-actions)

1. **Install Docker Desktop** (or Colima). Verify with `docker info`.
2. **Sign up for AWS** at aws.amazon.com (Personal account; credit card required; phone verification).
3. **Enable MFA on the AWS root account** before doing anything else. Use your phone authenticator. Root + no-MFA is the #1 source of compromised AWS accounts.
4. **Set a billing alarm** at $20/month: AWS Console → Billing → Budgets → Create → "Monthly budget" → notification at 100%. Circuit breaker; flips fast on misconfiguration.
5. **Install AWS CLI v2** locally: `brew install awscli`. Verify with `aws --version`.

### Phase 1 — Create the IAM user (once you've done Phase 0)

The director (Claude) wrote the policy at `docs/Cloud/iam_policy_claude_code_cli.json`. You attach it to a new IAM user.

1. AWS Console → IAM → Users → Create user
   - Username: `claude-code-cli`
   - **Programmatic access only** (no console password)
2. Permissions step → Attach policies directly → "Create policy"
   - Paste the contents of `docs/Cloud/iam_policy_claude_code_cli.json`
   - Replace every `REPLACE_ACCOUNT_ID` with your 12-digit AWS account number (find it: top-right dropdown in console)
   - Name: `ClaudeCodeCLI-Backtest`
   - Save and attach to the user
3. After user creation, AWS shows the access-key-ID and secret-access-key **exactly once**. Don't paste either into chat. Save them in a password manager and configure your local CLI:
   ```bash
   aws configure --profile archondex
   # AWS Access Key ID: <paste>
   # AWS Secret Access Key: <paste>
   # Default region: us-east-1   (cheapest for Batch + closest free-tier)
   # Default output format: json
   ```
4. Verify: `aws sts get-caller-identity --profile archondex` should return your account ID + the user ARN.

### Phase 2 — Create S3 buckets (one-time, scriptable)

Replace `<ACCT>` with your account ID throughout.

```bash
export AWS_PROFILE=archondex
export ACCT=$(aws sts get-caller-identity --query Account --output text)

aws s3 mb s3://archondex-data-$ACCT      --region us-east-1
aws s3 mb s3://archondex-results-$ACCT   --region us-east-1
aws s3 mb s3://archondex-archives-$ACCT  --region us-east-1

# Block all public access on each (default-deny posture)
for b in data results archives; do
  aws s3api put-public-access-block \
    --bucket archondex-$b-$ACCT \
    --public-access-block-configuration \
      "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"
done

# Server-side encryption (AES256, no KMS cost)
for b in data results archives; do
  aws s3api put-bucket-encryption \
    --bucket archondex-$b-$ACCT \
    --server-side-encryption-configuration \
      '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
done

# Lifecycle: archives bucket auto-transitions to Glacier after 30 days
aws s3api put-bucket-lifecycle-configuration \
  --bucket archondex-archives-$ACCT \
  --lifecycle-configuration '{"Rules":[{"ID":"archive-to-glacier","Status":"Enabled","Filter":{"Prefix":""},"Transitions":[{"Days":30,"StorageClass":"GLACIER"}]}]}'
```

### Phase 3 — Push the container image to ECR

```bash
export AWS_PROFILE=archondex
export ACCT=$(aws sts get-caller-identity --query Account --output text)
export REGION=us-east-1

aws ecr create-repository \
  --repository-name archondex-backtest \
  --region $REGION \
  --image-scanning-configuration scanOnPush=true

# Authenticate Docker to ECR (token good for 12 hr)
aws ecr get-login-password --region $REGION | \
  docker login --username AWS --password-stdin $ACCT.dkr.ecr.$REGION.amazonaws.com

# Build (already verified locally via scripts/verify_container_determinism.sh)
docker build -f Dockerfile.backtest -t archondex-backtest:dev .

# Tag + push
docker tag archondex-backtest:dev \
  $ACCT.dkr.ecr.$REGION.amazonaws.com/archondex-backtest:dev
docker push $ACCT.dkr.ecr.$REGION.amazonaws.com/archondex-backtest:dev
```

Image size budget: ~2-2.5 GB. Push time: ~2-5 min on a residential connection.

### Phase 4 — Create the Batch compute environment, queue, and job definition

(To be drafted in SPIKE-2 — needs Phase 0-3 done first. Will live at `docs/Cloud/batch_*.json`.)

### Phase 5 — Submit a single test job

(SPIKE-2 deliverable. Goal: one Batch job runs `--runs 1`, writes results to S3, exits clean.)

### Phase 6 — Submit the substrate measurement (6 parallel jobs)

(SPIKE-3 deliverable, after SPIKE-2 verified end-to-end.)

---

## Cost model (rough)

| Component | Per substrate run (6 reps × 2 hr ea) | Monthly (~10 substrate runs) |
|---|---:|---:|
| Fargate on-demand (1 vCPU, 4 GB) | ~$0.60 | ~$6 |
| Fargate Spot (same) | ~$0.18 | ~$1.80 |
| ECR storage (3 GB image) | $0 (free tier) | ~$0.30 |
| S3 storage (per-run trade log ~700 MB × 60 runs) | n/a | ~$1 |
| S3 PUT/GET requests | negligible | <$0.10 |
| Data transfer (in is free; out only on local pulls) | <$0.10 | ~$1 |

Total estimate: **~$2-7/month at this volume.** Billing alarm at $20 catches anything 3-5× the expected.

---

## Determinism guarantees

The Dockerfile sets:
- `PYTHONHASHSEED=0` — locks dict iteration order
- `LC_ALL=C.UTF-8` / `LANG=C.UTF-8` — locale-stable string formatting
- `TZ=UTC` — wall-clock-independent date math
- All 90 deps pinned exactly via `requirements.lock.txt`
- Same Python version baseline (3.14-slim) as local `.venv`

**Determinism gate:** `bash scripts/verify_container_determinism.sh` must exit 0. The gate is *container-internal* determinism — 3 container reps producing bitwise-identical canon md5s. That's the invariant cloud parallelism actually depends on (6 Fargate workers running the same image must agree).

**Cross-platform NOT guaranteed.** macOS host (Apple Accelerate BLAS) and Linux container (OpenBLAS) produce slightly different floating-point ordering in numpy/scipy matrix ops, which compounds through a backtest into different trade lists. Verified 2026-05-09: same Python (3.14.4), same numpy (2.4.3), but BLAS divergence drives a different canon md5 between host and container. There is no fix — Linux containers cannot use Apple Accelerate.

**Project policy from 2026-05-09:** the **container is the canonical substrate**. All new substrate measurements should run via the image (locally or in cloud Batch), not bare-metal. Bare-metal Python becomes a debugging tool only. Audit docs from past bare-metal runs remain valid as historical records but are not directly comparable to future container-based measurements at the canon-md5 level.

If `verify_container_determinism.sh` Step 2 (container internal) ever fails, **do not push to ECR**. Diagnose first. Common causes of a Step-2 failure:
- A dep in `.venv` with a different version than the image's `requirements.lock.txt` (regenerate the lockfile)
- Governor-state files in the image baked at a different state than the harness expects
- The harness's `_reexec_if_hashseed_unset` not firing in the container
- A library's behavior depending on number of threads (set `OMP_NUM_THREADS=1` in the image if so)

---

## Hard constraints

- Engine B and `live_trader/` are **not** allowed to be exercised from cloud workers without explicit user approval (CLAUDE.md non-negotiable). Substrate measurements are Engine A/C/D/E/F only.
- API keys (`.env`, `config/alpaca_keys*.json`) are **never** baked into the image. Pass at runtime via `--env-file` (locally) or AWS Secrets Manager (in Batch).
- Cloud workers have `--network none` for substrate runs by default. Backtests don't need internet; allowing it is an unnecessary attack surface.
- The IAM policy is least-privilege. If a future task needs broader scope, the policy gets a new statement reviewed before attachment, not a blanket `*`.

---

## Open questions

1. **Where do per-run config bundles (universe, edges, window) get assembled?** Probably the director uploads a JSON to S3, the Batch job reads that JSON at startup, and the run is parameterized off it. Spec'd in SPIKE-2.
2. **Does the determinism harness run unmodified inside Batch?** It expects to read `data/governor/` from the local FS. The image bakes templates; the harness's snapshot/restore should still work but needs verification on a no-mount Batch run.
3. **Do we need Reserved Instances or Compute Savings Plans?** Not at this volume. Revisit if monthly Batch spend exceeds $50.
