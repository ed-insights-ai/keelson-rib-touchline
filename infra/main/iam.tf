# ---------------------------------------------------------------------------
# The publish role: collect and publish jobs in the rib's `production`
# environment, on main only. Writes data, signs snapshots, deletes nothing.
# Capped by the touchline-publish-boundary policy from infra/bootstrap.
# ---------------------------------------------------------------------------

locals {
  # Needs the repo's OIDC subject template (repo, context, ref). See RUNBOOK.md.
  publish_subject = "repo:${local.repo}:environment:${var.publish_environment}:ref:refs/heads/main"

  writable_prefixes = concat(
    ["raw/*", "news/*", "bundles/*", "latest.json"],
    [for s in local.scopes : "snapshots/base/${s}/*"],
    [for s in local.scopes : "snapshots/delta/${s}/*"],
  )
}

data "aws_iam_policy_document" "publish_trust" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.oidc_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:aud"
      values   = ["sts.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.oidc_host}:sub"
      values   = [local.publish_subject]
    }
  }
}

resource "aws_iam_role" "publish" {
  name                 = "touchline-publish"
  description          = "Collect and publish, from ${local.repo} environment ${var.publish_environment} on main"
  assume_role_policy   = data.aws_iam_policy_document.publish_trust.json
  permissions_boundary = "arn:aws:iam::${local.account_id}:policy/touchline-publish-boundary"
  max_session_duration = 3600
}

data "aws_iam_policy_document" "publish" {
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }

  statement {
    sid       = "Read"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }

  statement {
    sid       = "Write"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = [for p in local.writable_prefixes : "${aws_s3_bucket.data.arn}/${p}"]
  }

  statement {
    sid       = "Sign"
    actions   = ["kms:Sign", "kms:GetPublicKey", "kms:DescribeKey"]
    resources = [aws_kms_key.signing.arn]
  }
}

resource "aws_iam_role_policy" "publish" {
  name   = "touchline-publish"
  role   = aws_iam_role.publish.id
  policy = data.aws_iam_policy_document.publish.json
}
