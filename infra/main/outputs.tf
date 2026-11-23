output "data_bucket" {
  value = aws_s3_bucket.data.bucket
}

output "publish_role_arn" {
  value = aws_iam_role.publish.arn
}

output "snapshot_scopes" {
  description = "Scopes the publish role may write under snapshots/base/ and snapshots/delta/."
  value       = local.scopes
}

output "signing_key_arn" {
  value = aws_kms_key.signing.arn
}

output "signing_key_alias" {
  value = aws_kms_alias.signing.name
}

output "signing_public_key_pem" {
  description = "Commit this to the desk so sign.ts can verify snapshots."
  value       = data.aws_kms_public_key.signing.public_key_pem
}

output "signing_algorithms" {
  value = data.aws_kms_public_key.signing.signing_algorithms
}
