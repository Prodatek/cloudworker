locals {
  common_tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
  name_prefix = "${var.project_name}-${var.environment}"
}

# Stock Amazon Linux 2023, resolved via AWS's official SSM parameter rather than an AMI
# data source query — ships with the SSM Agent preinstalled. Nothing executes real jobs
# until Phase 5/6, so a custom Packer-built AMI (e.g. with Playwright baked in) is deferred
# until it's actually needed.
data "aws_ssm_parameter" "al2023_ami" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

# Describes how a worker instance is launched; Phase 4's Worker Manager launches actual
# instances from this template and picks the subnet at launch time, so no subnet_id is
# baked in here.
resource "aws_launch_template" "worker" {
  name          = "${local.name_prefix}-worker"
  image_id      = data.aws_ssm_parameter.al2023_ami.value
  instance_type = var.instance_type

  iam_instance_profile {
    name = var.worker_instance_profile_name
  }

  network_interfaces {
    associate_public_ip_address = false
    security_groups             = [var.worker_security_group_id]
  }

  metadata_options {
    http_tokens   = "required" # enforce IMDSv2
    http_endpoint = "enabled"
  }

  monitoring {
    enabled = true
  }

  tag_specifications {
    resource_type = "instance"
    tags          = merge(local.common_tags, { Name = "${local.name_prefix}-worker" })
  }

  tag_specifications {
    resource_type = "volume"
    tags          = merge(local.common_tags, { Name = "${local.name_prefix}-worker-volume" })
  }

  tags = local.common_tags
}
