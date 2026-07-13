# Terraform Modules

| Module      | Shipped | Purpose                                                                 |
|-------------|---------|--------------------------------------------------------------------------|
| `networking`| Phase 3 | VPC, 2 private subnets (no IGW/NAT), SSM interface + S3 gateway endpoints, security groups |
| `storage`   | Phase 3 | S3 buckets for logs and artifacts (screenshots/videos/generic output)     |
| `iam`       | Phase 3 | IAM role/instance profile granting SSM (no SSH) + scoped S3 access        |
| `compute`   | Phase 3 | EC2 launch template referencing the stock AL2023 AMI                     |

Each module has its own `variables.tf`/`outputs.tf` and is composed from
`environments/<env>/main.tf`, keeping environments thin and modules reusable.

Workers are deliberately private-only: there's no Internet Gateway or NAT Gateway anywhere in
`networking`. Workers reach AWS Systems Manager exclusively through VPC interface endpoints
(`ssm`, `ssmmessages`, `ec2messages`) and reach S3 through a gateway endpoint — so there is no
route to the public internet from a worker instance at all, and no SSH is ever needed or possible.

## Remote state bootstrap (`../bootstrap`)

`bootstrap/` is a separate root module with its own **local** state — it creates the S3 bucket and
DynamoDB table that `environments/*/providers.tf` then use as their own S3 backend. It has to be
its own thing because `environments/dev` can't depend on a backend that doesn't exist yet.

Run once per AWS account, with real AWS credentials configured:

```bash
cd infra/terraform/bootstrap
terraform init
terraform plan   # review what will be created
terraform apply  # creates the state bucket + lock table — confirm before running
```

After that, `environments/dev`'s `backend "s3" {}` block (in `providers.tf`) can `terraform init`
successfully, since the bucket/table it references now exist.
