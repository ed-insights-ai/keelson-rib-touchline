# ---------------------------------------------------------------------------
# The public site: a private S3 bucket that only CloudFront can read.
#
# The site outgrew GitHub Pages' 1 GB limit (about 2.7 GB today, about 4.9 GB
# with D3). CloudFront's always-free tier (1 TB out and 10 million requests a
# month) covers pilot traffic, so this adds no standing charge: only S3
# storage, a few cents a month.
#
# Build folders follow the same division list as the snapshots:
#   /              root division, men      /women/            root division, women
#   /<div>/        other divisions, men    /<div>/women/      other divisions, women
# ---------------------------------------------------------------------------

locals {
  site_bucket = "touchline-site-${local.account_id}"

  site_build_prefixes = {
    for pair in setproduct(var.divisions, var.genders) :
    "${pair[0]}-${pair[1]}" => join("", [
      pair[0] == var.site_root_division ? "/" : "/${pair[0]}/",
      pair[1] == "men" ? "" : "${pair[1]}/",
    ])
  }

  use_custom_domain = length(var.site_domain_names) > 0
}

resource "aws_s3_bucket" "site" {
  bucket = local.site_bucket

  # Unlike the data bucket, everything here is rebuilt by each deploy, so the
  # bucket may be replaced.
}

resource "aws_s3_bucket_ownership_controls" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "site" {
  bucket = aws_s3_bucket.site.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "site" {
  bucket     = aws_s3_bucket.site.id
  depends_on = [aws_s3_bucket_versioning.site]

  rule {
    id     = "expire-replaced-files"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = var.site_noncurrent_retention_days
    }

    expiration {
      expired_object_delete_marker = true
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }
  }
}

# Only this distribution may read, through origin access control. Block
# Public Access stays on: a policy naming a service principal with a SourceArn
# condition is not public.
resource "aws_s3_bucket_policy" "site" {
  bucket     = aws_s3_bucket.site.id
  depends_on = [aws_s3_bucket_public_access_block.site]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "CloudFrontRead"
        Effect    = "Allow"
        Principal = { Service = "cloudfront.amazonaws.com" }
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.site.arn}/*"
        Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
      },
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource  = [aws_s3_bucket.site.arn, "${aws_s3_bucket.site.arn}/*"]
        Condition = { Bool = { "aws:SecureTransport" = "false" } }
      },
    ]
  })
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "touchline-site"
  description                       = "CloudFront reads the Touchline site bucket"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# /x/ -> /x/index.html and /x -> /x/index.html, for Astro's directory output.
# CloudFront Functions: 2 million invocations a month free.
resource "aws_cloudfront_function" "index_rewrite" {
  name    = "touchline-site-index-rewrite"
  runtime = "cloudfront-js-2.0"
  comment = "Directory URLs to index.html"
  publish = true
  code    = <<-JS
    function handler(event) {
      var request = event.request;
      var uri = request.uri;
      if (uri.endsWith('/')) {
        request.uri = uri + 'index.html';
      } else if (uri.lastIndexOf('.') <= uri.lastIndexOf('/')) {
        request.uri = uri + '/index.html';
      }
      return request;
    }
  JS
}

# Pages: short TTL, so a deploy shows within minutes even before invalidation.
resource "aws_cloudfront_cache_policy" "pages" {
  name        = "touchline-site-pages"
  comment     = "Short TTL for HTML and other unhashed files"
  min_ttl     = 0
  default_ttl = var.site_html_ttl_seconds
  max_ttl     = 3600

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

# Astro's hashed assets (/_astro/, /women/_astro/, ...) never change.
resource "aws_cloudfront_cache_policy" "assets" {
  name        = "touchline-site-assets"
  comment     = "Long TTL for content-hashed build assets"
  min_ttl     = 86400
  default_ttl = 31536000
  max_ttl     = 31536000

  parameters_in_cache_key_and_forwarded_to_origin {
    enable_accept_encoding_brotli = true
    enable_accept_encoding_gzip   = true
    cookies_config {
      cookie_behavior = "none"
    }
    headers_config {
      header_behavior = "none"
    }
    query_strings_config {
      query_string_behavior = "none"
    }
  }
}

# No Content-Security-Policy yet: Astro islands use inline scripts, and a
# wrong CSP breaks the site silently. Add one once the site is measured.
resource "aws_cloudfront_response_headers_policy" "security" {
  name    = "touchline-site-security"
  comment = "Security headers for the Touchline site"

  security_headers_config {
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      preload                    = false
      override                   = true
    }
    content_type_options {
      override = true
    }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "Touchline site"
  price_class         = "PriceClass_100"
  http_version        = "http2and3"
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = var.site_domain_names

  origin {
    origin_id                = "site-bucket"
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id           = "site-bucket"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.pages.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id

    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.index_rewrite.arn
    }
  }

  ordered_cache_behavior {
    path_pattern               = "*_astro/*"
    target_origin_id           = "site-bucket"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    compress                   = true
    cache_policy_id            = aws_cloudfront_cache_policy.assets.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
  }

  # Without s3:ListBucket, S3 answers a missing key with 403, so both map to
  # the site's 404 page (the root build's /404.html).
  custom_error_response {
    error_code            = 403
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 60
  }

  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/404.html"
    error_caching_min_ttl = 60
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = local.use_custom_domain ? null : true
    acm_certificate_arn            = local.use_custom_domain ? var.site_acm_certificate_arn : null
    ssl_support_method             = local.use_custom_domain ? "sni-only" : null
    minimum_protocol_version       = local.use_custom_domain ? "TLSv1.2_2021" : "TLSv1"
  }

  lifecycle {
    precondition {
      condition     = !local.use_custom_domain || var.site_acm_certificate_arn != null
      error_message = "site_domain_names needs site_acm_certificate_arn (us-east-1)."
    }
  }
}

# ---------------------------------------------------------------------------
# Site deploy role: the publish workflow's site job, in `production` on main.
# Syncs the site bucket and invalidates this one distribution. No access to
# the data bucket or the signing key.
# ---------------------------------------------------------------------------

resource "aws_iam_role" "site_deploy" {
  name                 = "touchline-publish-site"
  description          = "Site deploy, from ${local.repo} environment ${var.publish_environment} on main"
  assume_role_policy   = data.aws_iam_policy_document.publish_trust.json
  permissions_boundary = "arn:aws:iam::${local.account_id}:policy/touchline-publish-boundary"
  max_session_duration = 3600
}

data "aws_iam_policy_document" "site_deploy" {
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.site.arn]
  }

  statement {
    sid       = "Sync"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${aws_s3_bucket.site.arn}/*"]
  }

  statement {
    sid       = "Invalidate"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = [aws_cloudfront_distribution.site.arn]
  }
}

resource "aws_iam_role_policy" "site_deploy" {
  name   = "touchline-publish-site"
  role   = aws_iam_role.site_deploy.id
  policy = data.aws_iam_policy_document.site_deploy.json
}
