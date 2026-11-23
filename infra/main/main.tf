data "aws_caller_identity" "current" {}

locals {
  account_id = data.aws_caller_identity.current.account_id

  # Snapshot scopes: `all` (every division and gender in one file, what the
  # desk reads in the pilot) and d1-men, d1-women, d2-men, ... from the two lists.
  scopes = concat(["all"], [for pair in setproduct(var.divisions, var.genders) : "${pair[0]}-${pair[1]}"])

  # One published folder per source and scope: snapshots/<source>/<scope>/.
  # `data` is built from the private data homes, `samples` from samples/ in
  # the rib, so a sample run never mixes into the real dataset's history.
  snapshot_sources = ["data", "samples"]
  snapshot_folders = [for pair in setproduct(local.snapshot_sources, local.scopes) : "snapshots/${pair[0]}/${pair[1]}"]
}

# ---------------------------------------------------------------------------
# The private data bucket. Layout (kind first, so lifecycle rules are one
# prefix each, whatever the scope):
#
#   raw/<school>/...                 raw HTML cache, kept (re-parse, never re-scrape)
#   snapshots/<source>/<scope>/      one touchline-desk publish folder, exactly as
#                                    packages/data writes it: latest.json (moved
#                                    last, by conditional write, only after the
#                                    site smoke check), manifests/<id>.json and
#                                    .sig, base/<id>.duckdb.zst, deltas/<a>__<b>.
#                                    Deltas expire after delta_retention_days.
#                                    Bases and manifests are kept: an age rule
#                                    could take the base a latest.json still
#                                    names (a folder not published for a long
#                                    time), so old bases are only pruned once a
#                                    rule can tell the current one apart
#   bundles/<build id>/...           current-season data bundles the site build reads,
#                                    expire after 30 days (the built site itself is
#                                    in the separate site bucket, site.tf)
#   news/...                         journals, kept
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

# Versioning, with old versions gone after a week. Snapshot files are written
# once under their id (the publish job refuses to overwrite one), so only
# latest.json gets replaced versions; the publish role has no delete
# permission, so a bad run's overwrite is recoverable for a week.
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

  # Lifecycle prefixes take no wildcard, so one rule per published folder.
  dynamic "rule" {
    for_each = local.snapshot_folders
    content {
      id     = "expire-deltas-${replace(rule.value, "/", "-")}"
      status = "Enabled"
      filter {
        prefix = "${rule.value}/deltas/"
      }
      expiration {
        days = var.delta_retention_days
      }
    }
  }

  rule {
    id     = "expire-data-bundles"
    status = "Enabled"
    filter {
      prefix = "bundles/"
    }
    expiration {
      days = var.bundle_retention_days
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
