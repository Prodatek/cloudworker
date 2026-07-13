variable "project_name" {
  description = "Short name used to prefix/tag networking resources."
  type        = string
}

variable "environment" {
  description = "Deployment environment name (dev, staging, prod)."
  type        = string
}

variable "vpc_cidr" {
  description = "CIDR block for the CloudWorker VPC."
  type        = string
  default     = "10.42.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to spread private subnets across."
  type        = number
  default     = 2
}
