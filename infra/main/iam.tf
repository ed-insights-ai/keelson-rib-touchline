# ---------------------------------------------------------------------------
# Permissions for touchline-publish: collect and publish. Writes data, signs
# snapshots, deletes nothing. The role itself, its trust (production on main)
# and its boundary are in infra/bootstrap/roles.tf; this stack only sets its
# inline policy, which the boundary caps.
# ---------------------------------------------------------------------------

data "aws_iam_role" "publish" {
  name = "touchline-publish"
}

locals {
  writable_prefixes = concat(
    ["raw/*", "news/*", "bundles/*"],
    [for f in local.snapshot_folders : "${f}/*"],
  )
}

data "aws_iam_policy_document" "publish" {
  statement {
    sid       = "List"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.data.arn]
  }

  statement {
    sid       = "Read"
    actions   = ["s3:GetObject", "s3:GetObjectVersion"]
    resources = ["${aws_s3_bucket.data.arn}/*"]
  }

  statement {
    sid       = "Write"
    actions   = ["s3:PutObject", "s3:AbortMultipartUpload"]
    resources = [for p in local.writable_prefixes : "${aws_s3_bucket.data.arn}/${p}"]
  }

  # Snapshot bases carry a touchline-base tag (pending, current, superseded)
  # that the lifecycle prunes by; build.sh sets it on upload and release.sh
  # moves it.
  statement {
    sid       = "TagBases"
    actions   = ["s3:PutObjectTagging", "s3:GetObjectTagging"]
    resources = [for f in local.snapshot_folders : "${aws_s3_bucket.data.arn}/${f}/base/*"]
  }

  statement {
    sid       = "Sign"
    actions   = ["kms:Sign", "kms:GetPublicKey", "kms:DescribeKey"]
    resources = [data.aws_kms_key.signing.arn]
  }

  # The Collect workflow starts the PrestoSports runner before it queues the
  # presto job (infra/bootstrap/runner.tf). Start only, and only the instance
  # carrying the runner's tag; the boundary holds the same line.
  statement {
    sid       = "StartPrestoRunner"
    actions   = ["ec2:StartInstances"]
    resources = ["arn:aws:ec2:*:${local.account_id}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/touchline-role"
      values   = ["presto-runner"]
    }
  }
}

resource "aws_iam_role_policy" "publish" {
  name   = "touchline-publish"
  role   = data.aws_iam_role.publish.name
  policy = data.aws_iam_policy_document.publish.json
}
