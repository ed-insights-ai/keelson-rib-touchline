variable "region" {
  description = "AWS region for the state bucket and every Touchline resource."
  type        = string
  default     = "us-east-1"
}

variable "github_owner" {
  description = "GitHub organization that owns the rib."
  type        = string
  default     = "ed-insights-ai"
}

variable "github_repo" {
  description = "The private rib repository allowed to assume the deploy role."
  type        = string
  default     = "keelson-rib-touchline"
}

variable "infra_environment" {
  description = "GitHub Actions environment whose jobs may run Terraform for the main stack."
  type        = string
  default     = "infra"
}

variable "create_oidc_provider" {
  description = "Create GitHub's OIDC provider. Set false if the account already has one for token.actions.githubusercontent.com (an account can hold only one)."
  type        = bool
  default     = true
}

variable "budget_email" {
  description = "Address that gets the monthly budget alerts. Passed on the command line, never committed."
  type        = string
}

variable "budget_limit_usd" {
  description = "Monthly AWS cost budget, in US dollars."
  type        = number
  default     = 5
}

variable "budget_second_alert_usd" {
  description = "Absolute monthly spend, in US dollars, for the second alert."
  type        = number
  default     = 10
}

variable "signing_key_spec" {
  description = "KMS key spec for snapshot signing. Must match the algorithm the desk's sign.ts verifies. Changing it replaces the key."
  type        = string
  default     = "ECC_NIST_P256"
}

variable "block_account_public_access" {
  description = "Turn on S3 Block Public Access for the whole account. Set false only if this account already serves something public straight from S3."
  type        = bool
  default     = true
}
