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

variable "instance_type" {
  description = "EC2 instance type for CloudWorker workers."
  type        = string
  default     = "t3.micro"
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

variable "custom_ami_id" {
  description = "Custom AMI id built by infra/packer (Playwright preinstalled). Empty falls back to the stock AL2023 SSM-parameter AMI."
  type        = string
  default     = ""
}
