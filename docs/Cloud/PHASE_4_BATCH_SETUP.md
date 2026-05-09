# Phase 4 — AWS Batch infrastructure setup

After Phase 3 (image pushed to ECR), Phase 4 wires the AWS-side infrastructure that makes `aws batch submit-job` actually run our backtests.

There's one user-action step (creating two IAM roles via console), then the rest is CLI-driven.

---

## Why two IAM roles

AWS Batch with Fargate compute uses three role-shaped concepts:

| Role | Who assumes it | What it does |
|---|---|---|
| Task Execution Role | Fargate agent (the wrapper that pulls your image and writes logs) | `ecr:Pull*`, `logs:CreateLogStream`, `logs:PutLogEvents` |
| Task Role | The actual container running your code | `s3:GetObject` on data bucket, `s3:PutObject` on results bucket |
| Service Role for Batch | AWS Batch service itself | Manages the compute environment lifecycle |

The third (Service Role) is auto-created the first time you create a Compute Environment — no action needed. The first two need to exist before the Job Definition can reference them.

---

## Step 1 — Create the Task Execution Role (you, console clickthrough, ~2 min)

1. AWS Console → IAM → **Roles** → "Create role"
2. Trusted entity type: **AWS service**
3. Use case: scroll to **Elastic Container Service** → pick "**Elastic Container Service Task**"
4. Click Next
5. Permissions: search `AmazonECSTaskExecutionRolePolicy` — check it. (This grants ECR pull + CloudWatch logs.)
6. Click Next
7. Role name: `archondex-batch-task-execution-role`
8. Description: `Fargate execution role for archondex-backtest jobs — ECR pull + CloudWatch logs`
9. Create role

When done, copy the role's ARN (top of the role detail page) and paste it back to the director chat. Format will be:
```
arn:aws:iam::407539788432:role/archondex-batch-task-execution-role
```

## Step 2 — Create the Task Role (you, console, ~3 min)

This is what the running container itself can do (S3 read/write to our buckets).

1. IAM → Roles → "Create role"
2. Trusted entity: **AWS service**
3. Use case: **Elastic Container Service Task** (same as before)
4. Click Next
5. **Skip the AWS-managed policies** for now — click Next without selecting anything
6. Role name: `archondex-batch-task-role`
7. Description: `Container-runtime role for archondex-backtest — S3 read on data, write on results`
8. Create role

Now attach an inline policy:
1. Click into the new role → **Permissions** tab → "Add permissions" → "Create inline policy"
2. Click **JSON** tab
3. Paste:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "S3DataRead",
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::archondex-data-407539788432",
        "arn:aws:s3:::archondex-data-407539788432/*"
      ]
    },
    {
      "Sid": "S3ResultsWrite",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::archondex-results-407539788432",
        "arn:aws:s3:::archondex-results-407539788432/*"
      ]
    }
  ]
}
```

4. Click Next
5. Policy name: `archondex-batch-task-s3-access`
6. Create policy

Paste this role's ARN back to the director:
```
arn:aws:iam::407539788432:role/archondex-batch-task-role
```

---

## Step 3 — I extend `claude-code-cli` policy with `iam:PassRole` (director, after you give me both ARNs)

The CLI user needs `iam:PassRole` to "pass" the two role ARNs above into Batch service when registering the job definition. Without it, `aws batch register-job-definition` fails.

Director will add this scoped statement to the policy and have you re-paste it:

```json
{
  "Sid": "PassBatchRolesToFargate",
  "Effect": "Allow",
  "Action": "iam:PassRole",
  "Resource": [
    "arn:aws:iam::407539788432:role/archondex-batch-task-execution-role",
    "arn:aws:iam::407539788432:role/archondex-batch-task-role"
  ],
  "Condition": {
    "StringEquals": {
      "iam:PassedToService": [
        "ecs-tasks.amazonaws.com"
      ]
    }
  }
}
```

The condition pin ensures these roles can only be passed to ECS/Fargate (not anywhere else, like Lambda or CodeBuild).

---

## Step 4 — Director creates compute env + queue + job definition (CLI)

After both roles exist and the policy is updated, the director runs (no action needed from you):

```bash
# Compute environment — Fargate, on-demand, max 6 vCPU
aws batch create-compute-environment ...

# Job queue — feeds the compute env
aws batch create-job-queue ...

# Job definition — pins image URI, command, vCPU/memory
aws batch register-job-definition ...
```

Each command is ~5 seconds; the whole step is under a minute.

---

## Step 5 — Submit a test job (director)

```bash
aws batch submit-job --job-name test-q1-cell-01 \
  --job-queue archondex-backtest-queue \
  --job-definition archondex-backtest:1 \
  --parameters arm=1,task=q1,run_id=$(uuidgen)
```

Expected: Fargate spins up a worker (~30 sec to provision), pulls the image, runs one backtest, writes results to `s3://archondex-results-407539788432/<run-id>/`, exits. Total wall time ~2-4 min.

If the test job exits clean and a trade log appears in S3, Phase 4 is done. We're ready for Phase 6 (parallel substrate launcher).

---

## Total time estimate

| Step | Who | Time |
|---|---|---|
| 1. Task Execution Role | you (console) | 2 min |
| 2. Task Role + inline S3 policy | you (console) | 3 min |
| 3. Update `claude-code-cli` policy with PassRole | director + you | 2 min |
| 4. Compute env + queue + job def | director (CLI) | 1 min |
| 5. Test job submission + wait | director (CLI) | 5 min |
| **Phase 4 total** | | **~13 min** after ECR push lands |
