output "account_id" {
  value = local.account_id
}

output "state_bucket" {
  value = aws_s3_bucket.state.bucket
}

output "infra_deploy_role_arn" {
  value = aws_iam_role.infra_deploy.arn
}

output "oidc_provider_arn" {
  value = local.oidc_arn
}

output "signing_key_arn" {
  value = aws_kms_key.signing.arn
}

output "publish_boundary_arn" {
  value = aws_iam_policy.publish_boundary.arn
}
