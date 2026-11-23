# ---------------------------------------------------------------------------
# The publish roles, and who may assume them, live in bootstrap: only
# Daniel's CLI can create them or change their trust. infra/main (through the
# infra role) manages only their inline permissions, which the boundary caps.
#
#   touchline-publish       collect and publish: data bucket and signing
#   touchline-publish-site  site deploy: site bucket and invalidation
#
# Both are assumable only from the rib's `production` environment on main.
# ---------------------------------------------------------------------------

locals {
  # Needs the repo's OIDC subject template (repo, context, ref). See RUNBOOK.md.
  publish_subject = "repo:${local.oidc_repo}:environment:${var.publish_environment}:ref:refs/heads/main"
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
  permissions_boundary = aws_iam_policy.publish_boundary.arn
  max_session_duration = 3600

  depends_on = [aws_iam_openid_connect_provider.github]
}

resource "aws_iam_role" "publish_site" {
  name                 = "touchline-publish-site"
  description          = "Site deploy, from ${local.repo} environment ${var.publish_environment} on main"
  assume_role_policy   = data.aws_iam_policy_document.publish_trust.json
  permissions_boundary = aws_iam_policy.publish_boundary.arn
  max_session_duration = 3600

  depends_on = [aws_iam_openid_connect_provider.github]
}
