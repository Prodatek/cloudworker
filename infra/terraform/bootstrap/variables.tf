variable "aws_region" {
  description = "AWS region the state bucket/lock table are created in."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used to prefix/tag the bootstrap resources."
  type        = string
  default     = "cloudworker"
}

variable "environment" {
  description = "Deployment environment this state backend serves (dev, staging, prod)."
  type        = string
  default     = "dev"
}
