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
  value = data.aws_kms_key.signing.arn
}

output "signing_key_alias" {
  value = "alias/touchline-snapshot-signing"
}

output "signing_public_key_pem" {
  description = "Commit this to the desk so sign.ts can verify snapshots."
  value       = data.aws_kms_public_key.signing.public_key_pem
}

output "signing_algorithms" {
  value = data.aws_kms_public_key.signing.signing_algorithms
}

output "site_bucket" {
  value = aws_s3_bucket.site.bucket
}

output "site_distribution_id" {
  value = aws_cloudfront_distribution.site.id
}

output "site_distribution_domain" {
  value = aws_cloudfront_distribution.site.domain_name
}

output "site_url" {
  value = local.use_custom_domain ? "https://${var.site_domain_names[0]}" : "https://${aws_cloudfront_distribution.site.domain_name}"
}

output "site_deploy_role_arn" {
  value = aws_iam_role.site_deploy.arn
}

output "site_build_prefixes" {
  description = "Where each scope's site build goes in the site bucket, from the divisions list."
  value       = local.site_build_prefixes
}
