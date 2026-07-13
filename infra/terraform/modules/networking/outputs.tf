output "vpc_id" {
  description = "The CloudWorker VPC id."
  value       = aws_vpc.this.id
}

output "private_subnet_ids" {
  description = "Private subnet ids workers can be launched into."
  value       = aws_subnet.private[*].id
}

output "worker_security_group_id" {
  description = "Security group to attach to worker EC2 instances."
  value       = aws_security_group.worker.id
}
