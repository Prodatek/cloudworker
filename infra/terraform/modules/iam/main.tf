locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
  name_prefix = "${var.project_name}-${var.environment}"
}

data "aws_iam_policy_document" "ec2_assume_role" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "worker" {
  name               = "${local.name_prefix}-worker"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume_role.json
  tags               = local.common_tags
}

# AWS-managed policy granting the SSM Agent what it needs to register/be sent commands.
# This, plus the S3 policy below, is the entire permission set a worker gets — no wildcard
# resources, no permissions beyond "talk to SSM" and "read/write its own buckets".
resource "aws_iam_role_policy_attachment" "ssm_managed_instance_core" {
  role       = aws_iam_role.worker.name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

data "aws_iam_policy_document" "worker_storage_access" {
  statement {
    sid     = "ListJobBuckets"
    actions = ["s3:ListBucket"]
    resources = [
      var.logs_bucket_arn,
      var.artifacts_bucket_arn,
    ]
  }

  statement {
    sid     = "ReadWriteJobObjects"
    actions = ["s3:PutObject", "s3:GetObject"]
    resources = [
      "${var.logs_bucket_arn}/*",
      "${var.artifacts_bucket_arn}/*",
    ]
  }
}

resource "aws_iam_role_policy" "worker_storage_access" {
  name   = "${local.name_prefix}-worker-storage-access"
  role   = aws_iam_role.worker.id
  policy = data.aws_iam_policy_document.worker_storage_access.json
}

resource "aws_iam_instance_profile" "worker" {
  name = "${local.name_prefix}-worker"
  role = aws_iam_role.worker.name
  tags = local.common_tags
}
