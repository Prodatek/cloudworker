variable "aws_region" {
  description = "AWS region CloudWorker infrastructure is deployed into."
  type        = string
  default     = "us-east-1"
}

variable "project_name" {
  description = "Short name used to prefix/tag all CloudWorker resources."
  type        = string
  default     = "cloudworker"
}

variable "environment" {
  description = "Deployment environment name (dev, staging, prod)."
  type        = string
  default     = "dev"
}
