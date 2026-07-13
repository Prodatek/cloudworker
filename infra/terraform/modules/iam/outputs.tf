output "worker_instance_profile_name" {
  description = "Instance profile to attach to worker EC2 instances / the launch template."
  value       = aws_iam_instance_profile.worker.name
}

output "worker_role_arn" {
  value = aws_iam_role.worker.arn
}
