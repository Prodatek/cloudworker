module "networking" {
  source = "../../modules/networking"

  project_name = var.project_name
  environment  = var.environment
  vpc_cidr     = var.vpc_cidr
  az_count     = var.az_count
}

module "storage" {
  source = "../../modules/storage"

  project_name             = var.project_name
  environment              = var.environment
  logs_retention_days      = var.logs_retention_days
  artifacts_retention_days = var.artifacts_retention_days
}

module "iam" {
  source = "../../modules/iam"

  project_name         = var.project_name
  environment          = var.environment
  logs_bucket_arn      = module.storage.logs_bucket_arn
  artifacts_bucket_arn = module.storage.artifacts_bucket_arn
}

module "compute" {
  source = "../../modules/compute"

  project_name                 = var.project_name
  environment                  = var.environment
  instance_type                = var.instance_type
  worker_security_group_id     = module.networking.worker_security_group_id
  worker_instance_profile_name = module.iam.worker_instance_profile_name
  custom_ami_id                = var.custom_ami_id
}
