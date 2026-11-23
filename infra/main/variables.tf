variable "region" {
  description = "AWS region. Must match the bootstrap stack."
  type        = string
  default     = "us-east-1"
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

variable "delta_retention_days" {
  type    = number
  default = 45
}

variable "base_retention_days" {
  description = "Days a snapshot base is kept. Must stay well over an off-season (about eight months), since the current base is the newest one written."
  type        = number
  default     = 400

  validation {
    condition     = var.base_retention_days >= 300
    error_message = "A base must outlive the off-season, when no new base is written."
  }
}

variable "bundle_retention_days" {
  type    = number
  default = 30
}

variable "noncurrent_retention_days" {
  description = "Days an overwritten object version stays readable (latest.json and other replaced files)."
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
