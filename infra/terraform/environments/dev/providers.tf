terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state (S3 + DynamoDB lock table) is bootstrapped in Phase 3, once
  # there are real resources whose state is worth protecting. Local state is
  # fine for an empty scaffold.
  # backend "s3" {
  #   bucket         = "cloudworker-terraform-state-dev"
  #   key            = "cloudworker/dev/terraform.tfstate"
  #   region         = "us-east-1"
  #   dynamodb_table = "cloudworker-terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region
}
