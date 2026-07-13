terraform {
  required_version = ">= 1.7"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Bucket/table names must match infra/terraform/bootstrap's output exactly (backend
  # blocks can't reference variables/outputs, so these are hardcoded literals). Bootstrap
  # must be applied once, manually, before `terraform init` here can succeed.
  backend "s3" {
    bucket         = "cloudworker-terraform-state-dev"
    key            = "cloudworker/dev/terraform.tfstate"
    region         = "us-east-1"
    dynamodb_table = "cloudworker-terraform-locks-dev"
    encrypt        = true
  }
}

provider "aws" {
  region = var.aws_region
}
