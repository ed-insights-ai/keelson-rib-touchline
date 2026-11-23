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

variable "bundle_retention_days" {
  type    = number
  default = 30
}

variable "noncurrent_retention_days" {
  description = "Days an overwritten object version stays readable. Also the history kept for snapshot bases, which live at a stable key per scope."
  type        = number
  default     = 7
}

# ---------------------------------------------------------------------------
# Site hosting (S3 + CloudFront)
# ---------------------------------------------------------------------------

variable "site_root_division" {
  description = "Division whose men's build sits at the site root. Other builds live under /<division>/ and /women/."
  type        = string
  default     = "d2"
}

variable "site_noncurrent_retention_days" {
  description = "Days a replaced site file stays in the bucket. Short, because every deploy replaces many files."
  type        = number
  default     = 3
}

variable "site_html_ttl_seconds" {
  description = "Default CloudFront TTL for pages, so a daily deploy shows up quickly."
  type        = number
  default     = 300
}

variable "site_domain_names" {
  description = "Optional custom domains (CNAMEs) for the site. Leave empty to use the cloudfront.net name."
  type        = list(string)
  default     = []
}

variable "site_acm_certificate_arn" {
  description = "ACM certificate ARN in us-east-1 covering site_domain_names. Required when site_domain_names is set."
  type        = string
  default     = null

  validation {
    condition     = var.site_acm_certificate_arn == null || can(regex("^arn:aws:acm:us-east-1:", var.site_acm_certificate_arn))
    error_message = "CloudFront only accepts ACM certificates from us-east-1."
  }
}
