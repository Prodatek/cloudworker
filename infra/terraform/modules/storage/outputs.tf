output "logs_bucket_name" {
  description = "S3 bucket name for job execution logs."
  value       = aws_s3_bucket.logs.bucket
}

output "logs_bucket_arn" {
  value = aws_s3_bucket.logs.arn
}

output "artifacts_bucket_name" {
  description = "S3 bucket name for job artifacts (screenshots, videos, generic output files)."
  value       = aws_s3_bucket.artifacts.bucket
}

output "artifacts_bucket_arn" {
  value = aws_s3_bucket.artifacts.arn
}
