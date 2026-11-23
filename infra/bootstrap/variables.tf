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

variable "github_owner_id" {
  description = "Numeric GitHub ID of the owner, part of the immutable OIDC subject."
  type        = number
  default     = 210274923
}

variable "github_repo_id" {
  description = "Numeric GitHub ID of the repository, part of the immutable OIDC subject."
  type        = number
  default     = 1328075011
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

variable "publish_environment" {
  description = "GitHub Actions environment whose jobs (collect, publish, site deploy) may assume the publish roles."
  type        = string
  default     = "production"
}

variable "presto_runner" {
  description = "Keep the PrestoSports runner (runner.tf). Set false out of season: the instance, its network and its address are destroyed and cost nothing."
  type        = bool
  default     = true
}

variable "runner_instance_type" {
  description = "Instance type of the PrestoSports runner. 2 GB of memory is enough for the runner and one collect."
  type        = string
  default     = "t3a.small"
}

variable "runner_fixed_address" {
  description = "Give the PrestoSports runner one fixed public address (about $3.65 a month). False saves that, and the runner then gets a different AWS address every time it starts."
  type        = bool
  default     = true
}

variable "runner_idle_minutes" {
  description = "Minutes with no job running before the PrestoSports runner stops itself."
  type        = number
  default     = 15
}
