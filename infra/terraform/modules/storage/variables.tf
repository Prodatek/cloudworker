variable "project_name" {
  description = "Short name used to prefix/tag storage resources."
  type        = string
}

variable "environment" {
  description = "Deployment environment name (dev, staging, prod)."
  type        = string
}

variable "logs_retention_days" {
  description = "Days after which job logs are expired from S3."
  type        = number
  default     = 30
}

variable "artifacts_retention_days" {
  description = "Days after which job artifacts (screenshots/videos) are expired from S3."
  type        = number
  default     = 90
}
