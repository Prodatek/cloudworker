variable "project_name" {
  description = "Short name used to prefix/tag compute resources."
  type        = string
}

variable "environment" {
  description = "Deployment environment name (dev, staging, prod)."
  type        = string
}

variable "instance_type" {
  description = "EC2 instance type for CloudWorker workers."
  type        = string
  default     = "t3.micro"
}

variable "worker_security_group_id" {
  description = "Security group (from the networking module) to attach to worker instances."
  type        = string
}

variable "worker_instance_profile_name" {
  description = "IAM instance profile (from the iam module) to attach to worker instances."
  type        = string
}

variable "custom_ami_id" {
  description = "Custom AMI id built by infra/packer (Playwright preinstalled). Falls back to the stock AL2023 SSM-parameter AMI when empty, so shell-only deployments aren't forced to build it first."
  type        = string
  default     = ""
}
