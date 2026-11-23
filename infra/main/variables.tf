variable "region" {
  description = "AWS region. Must match the bootstrap stack."
  type        = string
  default     = "us-east-1"
}

variable "github_owner" {
  type    = string
  default = "ed-insights-ai"
}

variable "github_repo" {
  type    = string
  default = "keelson-rib-touchline"
}

variable "publish_environment" {
  description = "GitHub Actions environment whose jobs (collect and publish) may assume the publish role."
  type        = string
  default     = "production"
}

# One list drives every per-scope prefix and the publish role's write paths.
# Adding a division (d3) is a one-line change here.
variable "divisions" {
  description = "NCAA divisions with a dataset. Each gets a snapshot scope per gender."
  type        = list(string)
  default     = ["d1", "d2", "d3"]

  validation {
    condition     = alltrue([for d in var.divisions : can(regex("^d[0-9]$", d))])
    error_message = "Divisions look like d1, d2, d3."
  }
}

variable "genders" {
  type    = list(string)
  default = ["men", "women"]
}

variable "signing_key_spec" {
  description = "KMS key spec for snapshot signing. Must match the algorithm the desk's sign.ts verifies."
  type        = string
  default     = "ECC_NIST_P256"
}

variable "delta_retention_days" {
  type    = number
  default = 45
}

variable "site_bundle_retention_days" {
  type    = number
  default = 30
}

variable "noncurrent_retention_days" {
  description = "Days an overwritten object version stays readable. Also the history kept for snapshot bases, which live at a stable key per scope."
  type        = number
  default     = 7
}
