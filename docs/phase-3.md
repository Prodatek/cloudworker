# Phase 3 Report: AWS Infrastructure via Terraform

## What was built

- **`infra/terraform/bootstrap`**: a standalone root module (its own local state) creating the
  S3 bucket + DynamoDB table that every environment's remote state backend depends on. Must be
  applied once, manually, before `environments/dev` can `terraform init` against its S3 backend.
- **`infra/terraform/modules/networking`**: a VPC with 2 private subnets across 2 AZs, **no
  Internet Gateway, no NAT Gateway, no public subnets at all**. Workers reach AWS Systems Manager
  through 3 VPC interface endpoints (`ssm`, `ssmmessages`, `ec2messages`) and reach S3 through a
  gateway endpoint. Two security groups: `worker` (egress-only, no inbound rules at all) and
  `vpc_endpoints` (inbound 443 from the worker SG only).
- **`infra/terraform/modules/iam`**: an EC2 role + instance profile with the AWS-managed
  `AmazonSSMManagedInstanceCore` policy plus one inline policy scoped to exactly the two storage
  bucket ARNs (`s3:ListBucket`/`GetObject`/`PutObject` — no wildcard resources).
- **`infra/terraform/modules/storage`**: `logs` and `artifacts` S3 buckets — versioned, SSE-S3
  encrypted, public access fully blocked, with configurable lifecycle expiration (30/90 days by
  default).
- **`infra/terraform/modules/compute`**: an EC2 launch template referencing the stock Amazon
  Linux 2023 AMI (resolved via AWS's official SSM parameter, not a data-source AMI query),
  IMDSv2 enforced, no public IP. It creates **no EC2 instances** — Phase 4's Worker Manager will
  call `RunInstances` against this template and pick the subnet at launch time.
- **`environments/dev`**: composes all four modules, and the `backend "s3" {}` block stubbed out
  (commented) in Phase 1 is now filled in and active, pointing at the bootstrap module's bucket/
  table names.
- CI: the `terraform` job now runs `fmt -check`/`init -backend=false`/`validate` across
  `bootstrap`, all four modules, and `environments/dev` (previously only checked
  `environments/dev`).
- Docs: `infra/terraform/modules/README.md` rewritten with the shipped module table and bootstrap
  instructions; `docs/architecture.md`/`README.md` roadmaps updated.

## Why it was designed this way

- **No NAT Gateway, no Internet Gateway** — VPC interface endpoints for SSM plus an S3 gateway
  endpoint mean workers never have a route to the public internet at all, not even an outbound
  one. This is strictly more secure than "private subnet + NAT" (there's no egress path to
  exfiltrate to, even if a job's shell script tried) and cheaper (a NAT Gateway is ~$32+/mo plus
  data processing charges; interface endpoints are billed per-hour/per-GB but only for the three
  actually needed, and the S3 gateway endpoint is free).
- **Stock AL2023 AMI, not a custom Packer build** — nothing executes real jobs until Phase 5
  (shell) / Phase 6 (Playwright), so there's nothing to bake into a custom image yet. AL2023 ships
  with the SSM Agent preinstalled, which is all Phase 3's launch template needs. Introducing
  Packer now would be tooling with no functional payoff this phase.
  See "Technical debt" below for when this needs to change.
- **IAM policy scoped to exact bucket ARNs, not `s3:*`/`Resource: "*"`** — the whole point of the
  SSM-only, NAT-less design is minimizing what a compromised worker could do; a wildcard S3
  policy would undermine that even though workers still couldn't reach anything outside the VPC.
- **Bootstrap as its own root module with local state** — this is the standard resolution to
  Terraform's chicken-and-egg problem (you can't store state in a bucket that doesn't exist yet).
  It's applied once per AWS account, manually, and essentially never touched again.
- **Launch template doesn't pin a subnet** — keeps the "what" (instance shape: AMI, IAM role,
  security group, IMDSv2) separate from the "where/when" (which subnet, which job) that Phase 4's
  Worker Manager decides at launch time. Matches the Clean Architecture layering used elsewhere
  in this project: infrastructure describes capabilities, the (future) application layer decides
  how to use them.

## Trade-offs

- **VPC interface endpoints cost more per-hour than a NAT Gateway would at very low, bursty
  traffic** (each interface endpoint bills hourly regardless of usage) but cost less than NAT at
  any realistic worker-fleet data volume, and the security property (zero internet route) isn't
  achievable with NAT at any price. Right trade for this product's threat model.
- **Two S3 buckets (logs, artifacts) instead of one with prefixes** — clearer IAM/lifecycle
  separation (logs might reasonably expire faster than customer-facing artifacts), at the cost of
  two of everything (two versioning configs, two encryption configs, etc.) instead of one.
- **`t3.micro` default instance type** is cheap but may be too small once Phase 5/6 workloads
  (real shell scripts, headless Chromium for Playwright) are running on it — easy to bump via the
  `instance_type` variable, no structural change needed.
- **This phase is authored and statically validated, not proven against real AWS.** See below.

## Tests run

```
terraform fmt -check -recursive                          -> clean (entire infra/terraform tree)
terraform init -backend=false && terraform validate       -> Success, in every one of:
  bootstrap/, modules/networking/, modules/iam/,
  modules/storage/, modules/compute/, environments/dev/
```

While fixing this up, `terraform validate` caught a real cross-provider-version issue: an
unconstrained ad-hoc `init` on a module directory picked up AWS provider v6, whose `aws_region`
data source exposes `.region` (with `.name` deprecated) — but the project's actual pinned
constraint everywhere else is `~> 5.0` (resolving to 5.100.0), where `.region` **doesn't exist at
all** and `.name` is the only valid attribute. Every module now has its own `versions.tf` pinning
`~> 5.0` so standalone module validation always uses the same provider version the real
environments do, instead of silently drifting to whatever's newest.

**This phase was NOT verified against a real AWS account.** As flagged going into this phase, this
environment has no working AWS credentials (`aws sts get-caller-identity` returns
`InvalidClientTokenId`), so:
- `terraform plan` has never been run for either `bootstrap` or `environments/dev` — data sources
  (AMI lookup, availability zones, caller identity) need live API calls that couldn't happen here.
- `terraform apply` has not been run — no AWS resources described in this phase actually exist
  yet.

**Action for the user, before treating Phase 3 as fully proven**:
```bash
cd infra/terraform/bootstrap
terraform init && terraform plan   # review, then:
terraform apply                    # creates the state bucket + lock table

cd ../environments/dev
terraform init                     # now succeeds against the real S3 backend
terraform plan                     # review the full VPC/IAM/S3/launch-template plan
terraform apply                    # only when you're ready to actually create these in AWS
```
I did not run any of these `apply` commands and will always ask before doing so against a real
account, per the project's standing rule on actions with real blast radius.

## Technical debt

1. **Entirely unverified against real AWS** (see above) — the single highest-priority item before
   trusting this phase; static validation catches syntax/type errors, not e.g. IAM policy typos
   that AWS would reject, or CIDR overlaps, or endpoint DNS resolution issues.
2. No custom AMI/Packer pipeline yet — needed by Phase 6 at the latest (Playwright needs specific
   browser/dependency versions baked in rather than installed at boot).
3. `t3.micro` is an untested default for real workloads — revisit once Phase 5 shell execution
   gives real CPU/memory numbers to size against.
4. No CloudWatch alarms/dashboards on the VPC endpoints, IAM role usage, or S3 buckets yet —
   reasonable to defer to Phase 8 (hardening) but worth tracking.
5. Single AWS region, no multi-region/DR story — fine for a beta, would need revisiting before a
   production SLA.
6. The `environments/dev` provider block hardcodes `us-east-1` as a default; a `staging`/`prod`
   environment directory doesn't exist yet — will be needed before this goes past a single dev/
   beta deployment.

## Proposed Phase 4: Worker Manager

Scope proposal (not yet implemented):
- A `WorkerManager` domain/application service (Clean Architecture: depends on the `JobRepository`
  protocol from Phase 2 and a new `WorkerProvisioner` protocol, not directly on boto3) that:
  - Polls `claim_next_job()` in a loop.
  - On claiming a job, calls EC2 `RunInstances` referencing Phase 3's launch template + a chosen
    private subnet + a per-job tag (so a worker can be traced back to its job).
  - Waits for the instance to register with SSM (polls `DescribeInstanceInformation`), then marks
    the job as ready for command dispatch.
  - On job completion (Phase 5/6 will report this), terminates the instance — this phase's
    "automatically destroy workers after completion" guarantee starts here.
  - Handles the failure path too: if provisioning fails or SSM registration times out, the job is
    marked `failed` and any partially-created instance is terminated (no orphaned workers).
- A worker lifecycle state machine (`pending` → `provisioning` → `ready` → `running` →
  `terminating` → `terminated`, plus a `failed` terminal state) persisted alongside the job (new
  `workers` table, or a few new columns on `jobs` — will decide during planning).
- This phase needs a runnable AWS account to do anything meaningful (it's the first phase that
  actually launches EC2 instances), so real end-to-end testing depends on Phase 3's `bootstrap`/
  `apply` having been run for real first.

Will present this as a full plan for approval before writing any Phase 4 code, same as Phases 1–3.
