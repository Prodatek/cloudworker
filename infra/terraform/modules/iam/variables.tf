variable "project_name" {
  description = "Short name used to prefix/tag IAM resources."
  type        = string
}

variable "environment" {
  description = "Deployment environment name (dev, staging, prod)."
  type        = string
}

variable "logs_bucket_arn" {
  description = "ARN of the S3 bucket workers write job logs to (from the storage module)."
  type        = string
}

variable "artifacts_bucket_arn" {
  description = "ARN of the S3 bucket workers write job artifacts to (from the storage module)."
  type        = string
}
