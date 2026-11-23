# ---------------------------------------------------------------------------
# The infra deploy role: GitHub Actions in the rib's `infra` environment, on
# main only, runs Terraform for infra/main with it.
#
# It can manage the Touchline data bucket's configuration, KMS keys tagged
# project=touchline, and roles named touchline-publish*, and every role it
# creates must carry the touchline-publish-boundary permissions boundary. It
# cannot change itself, the OIDC provider, the budget or the bootstrap state,
# so a change to this file needs Daniel's signed-in CLI again.
#
# The daily publish job does not use this role. It uses touchline-publish,
# made by infra/main, which can only write data and sign.
# ---------------------------------------------------------------------------

locals {
  data_bucket     = "touchline-data-${local.account_id}"
  data_bucket_arn = "arn:aws:s3:::${local.data_bucket}"
  kms_key_arns    = "arn:aws:kms:${var.region}:${local.account_id}:key/*"
  publish_role    = "arn:aws:iam::${local.account_id}:role/touchline-publish*"
  boundary_arn    = "arn:aws:iam::${local.account_id}:policy/touchline-publish-boundary"

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
    resources = [local.data_bucket_arn]
  }

  statement {
    sid       = "KmsCreateTagged"
    actions   = ["kms:CreateKey", "kms:TagResource"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/project"
      values   = ["touchline"]
    }
  }

  statement {
    sid       = "KmsManageTagged"
    actions   = ["kms:*"]
    resources = [local.kms_key_arns]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = ["touchline"]
    }
  }

  statement {
    sid       = "KmsAliases"
    actions   = ["kms:CreateAlias", "kms:DeleteAlias", "kms:UpdateAlias"]
    resources = ["arn:aws:kms:${var.region}:${local.account_id}:alias/touchline-*"]
  }

  statement {
    sid       = "KmsList"
    actions   = ["kms:ListAliases", "kms:ListKeys"]
    resources = ["*"]
  }

  # Publish roles: created only with the boundary attached.
  statement {
    sid       = "PublishRoleCreate"
    actions   = ["iam:CreateRole", "iam:PutRolePermissionsBoundary"]
    resources = [local.publish_role]
    condition {
      test     = "StringEquals"
      variable = "iam:PermissionsBoundary"
      values   = [local.boundary_arn]
    }
  }

  statement {
    sid = "PublishRoleManage"
    actions = [
      "iam:GetRole",
      "iam:UpdateRole",
      "iam:UpdateRoleDescription",
      "iam:UpdateAssumeRolePolicy",
      "iam:DeleteRole",
      "iam:TagRole",
      "iam:UntagRole",
      "iam:ListRoleTags",
      "iam:PutRolePolicy",
      "iam:GetRolePolicy",
      "iam:DeleteRolePolicy",
      "iam:ListRolePolicies",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
    ]
    resources = [local.publish_role]
  }

  # The infra role may not sign snapshots, drop the boundary, or attach
  # managed policies (AdministratorAccess) to anything.
  statement {
    sid    = "DenyEscalation"
    effect = "Deny"
    actions = [
      "kms:Sign",
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
# The ceiling for every touchline-publish* role: read and write data objects,
# sign with Touchline keys. No deletes. Inline policies infra/main writes on
# those roles can only narrow this, never widen it.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "publish_boundary" {
  statement {
    sid       = "DataList"
    actions   = ["s3:ListBucket"]
    resources = [local.data_bucket_arn]
  }

  statement {
    sid       = "DataObjects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:AbortMultipartUpload"]
    resources = ["${local.data_bucket_arn}/*"]
  }

  statement {
    sid       = "Sign"
    actions   = ["kms:Sign", "kms:GetPublicKey", "kms:DescribeKey"]
    resources = [local.kms_key_arns]
    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = ["touchline"]
    }
  }
}

resource "aws_iam_policy" "publish_boundary" {
  name        = "touchline-publish-boundary"
  description = "Permissions boundary for touchline-publish* roles"
  policy      = data.aws_iam_policy_document.publish_boundary.json
}
