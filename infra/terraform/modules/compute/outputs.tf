output "launch_template_id" {
  description = "Launch template Phase 4's Worker Manager launches worker instances from."
  value       = aws_launch_template.worker.id
}

output "launch_template_latest_version" {
  value = aws_launch_template.worker.latest_version
}
