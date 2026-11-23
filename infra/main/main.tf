data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id
  repo       = "${var.github_owner}/${var.github_repo}"
  oidc_host  = "token.actions.githubusercontent.com"
  oidc_arn   = "arn:aws:iam::${local.account_id}:oidc-provider/${local.oidc_host}"

  # Snapshot scopes: d1-men, d1-women, d2-men, ... from the two lists.
  scopes = [for pair in setproduct(var.divisions, var.genders) : "${pair[0]}-${pair[1]}"]
}

# ---------------------------------------------------------------------------
# The private data bucket. Layout (kind first, so lifecycle rules are one
# prefix each, whatever the scope):
#
#   raw/<school>/...                 raw HTML cache, kept (re-parse, never re-scrape)
#   snapshots/base/<scope>/<id>...   signed DuckDB bases, expire after base_retention_days
#   snapshots/delta/<scope>/<id>...  signed daily deltas, expire after delta_retention_days
#   site/<build id>/...              current-season site bundles, expire after 30 days
#   news/...                         journals, kept
#   latest.json                      pointer the desk reads; moved by conditional write
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "data" {
  bucket = "touchline-data-${local.account_id}"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_ownership_controls" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "data" {
  bucket                  = aws_s3_bucket.data.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Versioning, with old versions gone after a week: the publish role has no
# delete permission, so an overwrite by a bad run is recoverable for a week.
resource "aws_s3_bucket_versioning" "data" {
  bucket = aws_s3_bucket.data.id
  versioning_configuration {
    status = "Enabled"
  }
}

# SSE-S3 is free. SSE-KMS with our own key would bill every request.
resource "aws_s3_bucket_server_side_encryption_configuration" "data" {
  bucket = aws_s3_bucket.data.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "data" {
  bucket     = aws_s3_bucket.data.id
  depends_on = [aws_s3_bucket_versioning.data]

  rule {
    id     = "housekeeping"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.noncurrent_retention_days
    }

    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 3
    }
  }

  rule {
    id     = "expire-snapshot-bases"
    status = "Enabled"
    filter {
      prefix = "snapshots/base/"
    }
    expiration {
      days = var.base_retention_days
    }
  }

  rule {
    id     = "expire-snapshot-deltas"
    status = "Enabled"
    filter {
      prefix = "snapshots/delta/"
    }
    expiration {
      days = var.delta_retention_days
    }
  }

  rule {
    id     = "expire-site-bundles"
    status = "Enabled"
    filter {
      prefix = "site/"
    }
    expiration {
      days = var.site_bundle_retention_days
    }
  }
}

resource "aws_s3_bucket_policy" "data" {
  bucket     = aws_s3_bucket.data.id
  depends_on = [aws_s3_bucket_public_access_block.data]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.data.arn, "${aws_s3_bucket.data.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}
