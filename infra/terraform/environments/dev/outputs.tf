output "vpc_id" {
  value = module.networking.vpc_id
}

output "private_subnet_ids" {
  value = module.networking.private_subnet_ids
}

output "worker_security_group_id" {
  value = module.networking.worker_security_group_id
}

output "logs_bucket_name" {
  value = module.storage.logs_bucket_name
}

output "artifacts_bucket_name" {
  value = module.storage.artifacts_bucket_name
}

output "worker_instance_profile_name" {
  value = module.iam.worker_instance_profile_name
}

output "launch_template_id" {
  description = "Referenced by Phase 4's Worker Manager when launching worker instances."
  value       = module.compute.launch_template_id
}
