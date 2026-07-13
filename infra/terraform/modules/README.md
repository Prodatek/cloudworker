# Terraform Modules (planned)

No modules exist yet — `environments/dev` currently only declares the AWS provider. Modules are
added incrementally, one per phase, as the corresponding AWS resources are needed:

| Module      | Introduced | Purpose                                                        |
|-------------|-----------|-----------------------------------------------------------------|
| `networking`| Phase 3   | VPC, subnets, security groups for worker instances               |
| `storage`   | Phase 3   | S3 buckets for logs, screenshots, videos, artifacts               |
| `iam`       | Phase 3   | IAM role/instance profile granting SSM (no SSH) + S3 access       |
| `compute`   | Phase 3/4 | EC2 launch template referencing the prebuilt AMI                  |

Each module gets its own `variables.tf`/`outputs.tf` and is composed from
`environments/<env>/main.tf`, keeping environments thin and modules reusable.
