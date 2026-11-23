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

output "publish_role_arn" {
  value = aws_iam_role.publish.arn
}

output "publish_site_role_arn" {
  value = aws_iam_role.publish_site.arn
}

output "publish_boundary_arn" {
  value = aws_iam_policy.publish_boundary.arn
}

output "presto_runner_instance_id" {
  description = "Set as the repository variable TOUCHLINE_PRESTO_RUNNER_INSTANCE."
  value       = one(aws_instance.runner[*].id)
}

output "presto_runner_address" {
  description = "The address the schools' sites see. Null without a fixed address."
  value       = one(aws_eip.runner[*].public_ip)
}
