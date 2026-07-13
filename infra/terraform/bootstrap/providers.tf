terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Deliberately local state: this config creates the S3 bucket + DynamoDB table that
  # every other Terraform root (environments/*) stores ITS state in, so it can't depend
  # on that same backend existing yet. Run this once, manually, per AWS account.
}

provider "aws" {
  region = var.aws_region
}
