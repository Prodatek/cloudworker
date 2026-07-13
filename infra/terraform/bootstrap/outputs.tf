output "state_bucket_name" {
  description = "S3 bucket name to reference from environments/*/providers.tf's backend block."
  value       = aws_s3_bucket.terraform_state.bucket
}

output "lock_table_name" {
  description = "DynamoDB table name to reference from environments/*/providers.tf's backend block."
  value       = aws_dynamodb_table.terraform_locks.name
}
