# Intentionally empty in Phase 1: no AWS resources are created yet.
#
# Phase 3 populates this with module calls for:
#   - networking (VPC, subnets, security groups)
#   - iam (SSM instance profile/role for ephemeral workers)
#   - storage (S3 buckets for logs/artifacts)
#   - compute (EC2 launch template using the prebuilt AMI)
#
# See ../../modules/README.md for the planned module layout.

locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}
