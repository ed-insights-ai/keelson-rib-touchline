# ---------------------------------------------------------------------------
# The infra deploy role: GitHub Actions in the rib's `infra` environment, on
# main only, runs Terraform for infra/main with it.
#
# It can manage the data and site buckets' configuration (never their
# objects), the site's CloudFront distribution and its policies, and the
# inline permissions of the touchline-publish* roles (never their trust or
# boundary). It can read the signing
# key's metadata and public key, nothing more. It cannot change itself, the
# OIDC provider, the signing key, the budget or the bootstrap state, so a
# change to any of those needs Daniel's signed-in CLI again.
#
# The daily publish job does not use this role. It uses touchline-publish
# (roles.tf), which can only write data and sign.
# ---------------------------------------------------------------------------

locals {
  data_bucket     = "touchline-data-${local.account_id}"
  data_bucket_arn = "arn:aws:s3:::${local.data_bucket}"
  site_bucket_arn = "arn:aws:s3:::touchline-site-${local.account_id}"
  publish_role    = "arn:aws:iam::${local.account_id}:role/touchline-publish*"

  # Requires the repo's OIDC subject template to include repo, context and ref
  # (RUNBOOK.md step 6). The default template has no ref for environment jobs,
  # so without that step this match fails closed.
  infra_subject = "repo:${local.repo}:environment:${var.infra_environment}:ref:refs/heads/main"
}

data "aws_iam_policy_document" "infra_trust" {
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
      values   = [local.infra_subject]
    }
  }
}

resource "aws_iam_role" "infra_deploy" {
  name                 = "touchline-infra-deploy"
  description          = "Terraform for infra/main, from ${local.repo} environment ${var.infra_environment} on main"
  assume_role_policy   = data.aws_iam_policy_document.infra_trust.json
  max_session_duration = 3600

  depends_on = [aws_iam_openid_connect_provider.github]
}

data "aws_iam_policy_document" "infra_deploy" {
  # Remote state: list the bucket, read and write only main/. The bootstrap
  # state stays out of reach.
  statement {
    sid       = "StateList"
    actions   = ["s3:ListBucket"]
    resources = [aws_s3_bucket.state.arn]
  }

  statement {
    sid       = "StateReadWrite"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.state.arn}/main/*"]
  }

  # Bucket-level configuration of the data bucket only. No object actions, so
  # this role cannot read or delete the archive.
  statement {
    sid       = "DataBucketConfig"
    actions   = ["s3:*"]
    resources = [local.data_bucket_arn, local.site_bucket_arn]
  }

  # The site's distribution, origin access control, function and cache and
  # header policies. Most CloudFront policy types take no resource ARN, so
  # this is account-wide; the account holds nothing else on CloudFront.
  statement {
    sid       = "CloudFront"
    actions   = ["cloudfront:*"]
    resources = ["*"]
  }

  # Read-only, for the optional custom-domain certificate.
  statement {
    sid       = "AcmRead"
    actions   = ["acm:DescribeCertificate", "acm:ListCertificates"]
    resources = ["*"]
  }

  # Look up the signing key and export its public key. No admin, grant,
  # policy or signing actions.
  statement {
    sid       = "KmsRead"
    actions   = ["kms:DescribeKey", "kms:GetPublicKey"]
    resources = [aws_kms_key.signing.arn]
  }

  # Publish roles: inline permissions only. The roles, their trust and their
  # boundary are bootstrap's (roles.tf), so this role cannot point a publish
  # role's trust at its own OIDC subject.
  statement {
    sid = "PublishRoleInlinePolicies"
    actions = [
      "iam:GetRole",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:GetRolePolicy",
      "iam:PutRolePolicy",
      "iam:DeleteRolePolicy",
    ]
    resources = [local.publish_role]
  }

  # s3:* above includes PutBucketPolicy, so without this the role could write
  # a bucket policy granting itself the archive. An explicit deny here wins
  # over any bucket-policy allow.
  statement {
    sid       = "DenyBucketObjects"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = ["${local.data_bucket_arn}/*", "${local.site_bucket_arn}/*"]
  }

  # The infra role may not sign, grant or re-policy KMS keys, drop the
  # boundary, or attach managed policies (AdministratorAccess) to anything.
  statement {
    sid    = "DenyEscalation"
    effect = "Deny"
    actions = [
      "kms:Sign",
      "kms:CreateGrant",
      "kms:PutKeyPolicy",
      "kms:CreateKey",
      "s3:PutAccountPublicAccessBlock",
      "iam:CreateRole",
      "iam:DeleteRole",
      "iam:UpdateAssumeRolePolicy",
      "iam:PutRolePermissionsBoundary",
      "iam:DeleteRolePermissionsBoundary",
      "iam:AttachRolePolicy",
      "iam:CreatePolicy",
      "iam:CreatePolicyVersion",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "infra_deploy" {
  name   = "touchline-infra-deploy"
  role   = aws_iam_role.infra_deploy.id
  policy = data.aws_iam_policy_document.infra_deploy.json
}

# ---------------------------------------------------------------------------
# The ceiling for every touchline-publish* role: read and write data objects
# (no deletes), sync the site bucket and invalidate its distribution, sign
# with the snapshot key. Inline policies infra/main writes on those roles can
# only narrow this, never widen it; each role gets only its own part.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "publish_boundary" {
  statement {
    sid       = "DataList"
    actions   = ["s3:ListBucket"]
    resources = [local.data_bucket_arn]
  }

  statement {
    sid       = "DataObjects"
    actions   = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${local.data_bucket_arn}/*"]
  }

  statement {
    sid       = "SiteList"
    actions   = ["s3:ListBucket"]
    resources = [local.site_bucket_arn]
  }

  statement {
    sid       = "SiteObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:AbortMultipartUpload"]
    resources = ["${local.site_bucket_arn}/*"]
  }

  statement {
    sid       = "SiteInvalidate"
    actions   = ["cloudfront:CreateInvalidation", "cloudfront:GetInvalidation"]
    resources = ["arn:aws:cloudfront::${local.account_id}:distribution/*"]
  }

  statement {
    sid       = "Sign"
    actions   = ["kms:Sign", "kms:GetPublicKey", "kms:DescribeKey"]
    resources = [aws_kms_key.signing.arn]
  }
}

resource "aws_iam_policy" "publish_boundary" {
  name        = "touchline-publish-boundary"
  description = "Permissions boundary for touchline-publish* roles"
  policy      = data.aws_iam_policy_document.publish_boundary.json
}
