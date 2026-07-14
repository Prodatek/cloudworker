# Deployment Guide

End-to-end instructions for standing CloudWorker up in your own AWS account. This repo provides
the API/worker container images and the worker-fleet infrastructure (VPC, IAM, S3, EC2 launch
template) — it deliberately does **not** prescribe how you host the API/worker containers
themselves (ECS, Fargate, EC2, App Runner, Kubernetes are all reasonable choices); pick whatever
fits your existing operational stack. Building a specific hosting module (e.g. an ECS/Fargate
Terraform module) is new infrastructure scope, not hardening of what exists, so it's intentionally
out of scope here.

None of the AWS-touching steps below have been run in this project's development sandbox (no AWS
credentials were available) — they're authored and, where possible, syntax-validated
(`terraform validate`, `packer validate`), not proven end-to-end. Budget time for troubleshooting
on your first real run.

## Prerequisites

- An AWS account and credentials with permission to create the resources below (VPC, IAM roles,
  S3 buckets, EC2 launch templates, DynamoDB table for Terraform locking).
- Terraform >= 1.9.
- [Packer](https://developer.hashicorp.com/packer) >= 1.10, if you want Playwright/browser job
  support (shell-only deployments can skip this — see Step 4).
- A place to run the `api` and `worker` containers with a reachable Postgres database (your own
  ECS/EC2/Kubernetes/etc. — not provided by this repo).
- Docker, to build the `api`/`worker`/`frontend` images (or use `.github/workflows/deploy.yml`,
  which builds and pushes them to GHCR on a version tag push — see that file's comments for the
  secrets it needs).

## 1. Bootstrap Terraform remote state

One-time, per AWS account: creates the S3 bucket + DynamoDB table Terraform's remote state and
locking use for every other module.

```bash
cd infra/terraform/bootstrap
terraform init
terraform apply
```

Note the bucket/table names from the output — reference them in
`infra/terraform/environments/dev/providers.tf`'s backend block (or your own environment's, if
you copy `environments/dev` to make one).

## 2. Apply the core infrastructure

```bash
cd infra/terraform/environments/dev
terraform init
terraform plan
terraform apply
```

This creates (see `docs/architecture.md`'s Security model section for the reasoning behind the
IAM/networking choices):

- A private-only VPC with VPC interface endpoints for SSM and S3 (workers never need a public IP
  or NAT gateway).
- An IAM role/instance profile for workers, scoped to `AmazonSSMManagedInstanceCore` plus
  read/write on exactly the two S3 buckets below — no wildcard resources.
- `logs` and `artifacts` S3 buckets (retention configurable via `logs_retention_days`/
  `artifacts_retention_days`).
- An EC2 launch template `WorkerManager` uses to provision workers, defaulting to the stock
  Amazon Linux 2023 AMI (shell jobs work immediately; browser jobs need Step 4 first).

Take note of the `terraform output` values — `launch_template_id`, `private_subnet_ids`,
`logs_bucket_name`, `artifacts_bucket_name` all map directly to `backend/.env.example` settings
in Step 5.

## 3. Run database migrations

Point `DATABASE_URL` at your Postgres instance (this repo doesn't provision one — bring your own,
or run `docker compose up db` for local/dev use) and run:

```bash
cd backend
pip install -r requirements.txt
alembic upgrade head
```

## 4. (Optional) Build the Playwright worker AMI

Skip this if you only need shell jobs. See `infra/packer/README.md` for full detail; summary:

```bash
cd infra/packer
packer init .
packer build worker-ami.pkr.hcl
```

Take the resulting AMI id and set it as `custom_ami_id` in
`infra/terraform/environments/dev/variables.tf` (or `TF_VAR_custom_ami_id`), then re-run
`terraform apply` from Step 2 so the launch template picks it up.

## 5. Configure and run the API/worker containers

Copy `backend/.env.example` to `backend/.env` (or set the equivalent environment variables in
your hosting platform) and fill in, from Step 2's Terraform outputs:

| Setting | Source |
| --- | --- |
| `DATABASE_URL` | Your Postgres instance |
| `LAUNCH_TEMPLATE_ID` | `terraform output launch_template_id` |
| `WORKER_SUBNET_IDS` | `terraform output private_subnet_ids` (comma-separated) |
| `LOGS_BUCKET_NAME` | `terraform output logs_bucket_name` |
| `ARTIFACTS_BUCKET_NAME` | `terraform output artifacts_bucket_name` |
| `JWT_SECRET_KEY` | A real random secret — **do not** ship the insecure dev default |
| `CORS_ALLOWED_ORIGINS` | Your dashboard's real origin(s) |

Build and run the images (or let `.github/workflows/deploy.yml` build/push them on a tag push):

```bash
docker build -t cloudworker-backend ./backend
docker build -t cloudworker-frontend ./frontend
```

Run one container as the API (`uvicorn app.main:app --host 0.0.0.0 --port 8000`, the backend
image's default `CMD`) and a second from the *same image* as the worker
(`python -m app.worker_entrypoint`) — see `docker-compose.yml` for the exact commands, which is
the reference for "what does a working deployment actually run."

The worker process needs AWS credentials with permission to call `ec2:RunInstances`/
`ec2:TerminateInstances`/`ssm:SendCommand`/`ssm:GetCommandInvocation` against the resources Step 2
created — an IAM role attached to whatever compute runs the worker container (not the worker
*instances* themselves, which use their own instance profile from Step 2) is the standard
approach; avoid long-lived access keys where your hosting platform supports role-based auth.

## 6. Verify

- `GET /healthz` on your API returns 200.
- `GET /readyz` returns 200 (confirms Postgres connectivity).
- `POST /api/v1/auth/register`, then `POST /api/v1/jobs` with a trivial shell command, then poll
  `GET /api/v1/jobs/{id}` until it reaches `succeeded` — this exercises the full worker
  provisioning → SSM dispatch → S3 log write → termination path end to end. See
  `docs/api-examples.md` for exact `curl` calls.
- `GET /metrics` returns Prometheus exposition text — point your monitoring stack at it (see
  `docs/observability.md`).

## What this repo does not provide

- A production hosting stack for the API/worker containers themselves (see the intro above).
- Prometheus/Grafana/alerting infrastructure — `docs/observability.md` documents what to scrape
  and example queries, not a shipped monitoring deployment.
- TLS termination / a load balancer in front of the API — put your platform's standard one in
  front of it; the API itself speaks plain HTTP.
- Multi-region or multi-account support — one Terraform environment maps to one region/account.
