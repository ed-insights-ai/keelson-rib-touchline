# Applied only as root. Neither identity here can read this stack's state or
# change its own permissions.

data "aws_caller_identity" "current" {}

data "aws_kms_key" "signing" {
  key_id = "alias/touchline-snapshot-signing"
}

locals {
  account_id         = data.aws_caller_identity.current.account_id
  iam                = "arn:aws:iam::${local.account_id}"
  ec2                = "arn:aws:ec2:${var.region}:${local.account_id}"
  state_bucket_arn   = "arn:aws:s3:::touchline-tfstate-${local.account_id}"
  budget_arn         = "arn:aws:budgets::${local.account_id}:budget/touchline-monthly"
  boundary_arn       = "${local.iam}:policy/touchline-publish-boundary"
  infra_role_arn     = "${local.iam}:role/touchline-infra-deploy"
  runner_role_arn    = "${local.iam}:role/touchline-presto-runner"
  runner_profile_arn = "${local.iam}:instance-profile/touchline-presto-runner"
  oidc_arn           = "${local.iam}:oidc-provider/token.actions.githubusercontent.com"
  ssm_core_arn       = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"

  stack_role_arns = [
    local.infra_role_arn,
    local.runner_role_arn,
    "${local.iam}:role/touchline-publish",
    "${local.iam}:role/touchline-publish-site",
  ]
}

resource "aws_iam_user" "operator" {
  name = var.operator_user_name
}

resource "aws_iam_user_policy_attachment" "operator_signin" {
  user       = aws_iam_user.operator.name
  policy_arn = "arn:aws:iam::aws:policy/SignInLocalDevelopmentAccess"
}

resource "aws_iam_user_policy_attachment" "operator_read" {
  user       = aws_iam_user.operator.name
  policy_arn = aws_iam_policy.read.arn
}

resource "aws_iam_user_policy_attachment" "operator" {
  user       = aws_iam_user.operator.name
  policy_arn = aws_iam_policy.operator.arn
}

data "aws_iam_policy_document" "read" {
  statement {
    sid       = "StateList"
    actions   = ["s3:ListBucket"]
    resources = [local.state_bucket_arn]
  }

  statement {
    sid       = "StateRead"
    actions   = ["s3:GetObject"]
    resources = ["${local.state_bucket_arn}/bootstrap/*"]
  }

  statement {
    sid       = "StateLock"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.state_bucket_arn}/bootstrap/terraform.tfstate.tflock"]
  }

  statement {
    sid = "StateBucketRead"
    actions = [
      "s3:GetAccelerateConfiguration",
      "s3:GetBucketAcl",
      "s3:GetBucketCORS",
      "s3:GetBucketLogging",
      "s3:GetBucketObjectLockConfiguration",
      "s3:GetBucketOwnershipControls",
      "s3:GetBucketPolicy",
      "s3:GetBucketPublicAccessBlock",
      "s3:GetBucketRequestPayment",
      "s3:GetBucketTagging",
      "s3:GetBucketVersioning",
      "s3:GetBucketWebsite",
      "s3:GetEncryptionConfiguration",
      "s3:GetLifecycleConfiguration",
      "s3:GetReplicationConfiguration",
      "s3:ListTagsForResource",
    ]
    resources = [local.state_bucket_arn]
  }

  statement {
    sid = "AccountWideRead"
    actions = [
      "ec2:Describe*",
      "kms:ListAliases",
      "s3:GetAccountPublicAccessBlock",
    ]
    resources = ["*"]
  }

  statement {
    sid = "IamRoleRead"
    actions = [
      "iam:GetRole",
      "iam:GetRolePolicy",
      "iam:ListAttachedRolePolicies",
      "iam:ListInstanceProfilesForRole",
      "iam:ListRolePolicies",
      "iam:ListRoleTags",
    ]
    resources = local.stack_role_arns
  }

  statement {
    sid = "IamOtherRead"
    actions = [
      "iam:GetInstanceProfile",
      "iam:GetOpenIDConnectProvider",
      "iam:GetPolicy",
      "iam:GetPolicyVersion",
      "iam:ListInstanceProfileTags",
      "iam:ListOpenIDConnectProviderTags",
      "iam:ListPolicyTags",
      "iam:ListPolicyVersions",
    ]
    resources = [local.boundary_arn, local.runner_profile_arn, local.oidc_arn]
  }

  statement {
    sid = "SigningKeyRead"
    actions = [
      "kms:DescribeKey",
      "kms:GetKeyPolicy",
      "kms:GetKeyRotationStatus",
      "kms:GetPublicKey",
      "kms:ListResourceTags",
    ]
    resources = [data.aws_kms_key.signing.arn]
  }

  statement {
    sid       = "BudgetRead"
    actions   = ["budgets:ListTagsForResource", "budgets:ViewBudget"]
    resources = [local.budget_arn]
  }

  statement {
    sid       = "RunnerImageLookup"
    actions   = ["ssm:GetParameter"]
    resources = ["arn:aws:ssm:${var.region}::parameter/aws/service/canonical/ubuntu/server/24.04/*"]
  }
}

resource "aws_iam_policy" "read" {
  name        = "touchline-read"
  description = "Read what infra/bootstrap manages, enough for terraform plan"
  policy      = data.aws_iam_policy_document.read.json
}

data "aws_iam_policy_document" "operator" {
  statement {
    sid       = "StepUpToApply"
    actions   = ["sts:AssumeRole"]
    resources = [aws_iam_role.apply.arn]
  }

  statement {
    sid       = "RunnerPower"
    actions   = ["ec2:StartInstances", "ec2:StopInstances"]
    resources = ["${local.ec2}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/touchline-role"
      values   = ["presto-runner"]
    }
  }

  statement {
    sid       = "RunnerCommand"
    actions   = ["ssm:SendCommand"]
    resources = ["${local.ec2}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "ssm:resourceTag/touchline-role"
      values   = ["presto-runner"]
    }
  }

  statement {
    sid       = "RunnerCommandDocument"
    actions   = ["ssm:SendCommand"]
    resources = ["arn:aws:ssm:${var.region}::document/AWS-RunShellScript"]
  }

  statement {
    sid = "RunnerCommandStatus"
    actions = [
      "ce:GetCostAndUsage",
      "ssm:DescribeInstanceInformation",
      "ssm:GetCommandInvocation",
      "ssm:ListCommandInvocations",
      "ssm:ListCommands",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "OwnPassword"
    actions   = ["iam:ChangePassword"]
    resources = [aws_iam_user.operator.arn]
  }

  statement {
    sid       = "PasswordPolicyRead"
    actions   = ["iam:GetAccountPasswordPolicy"]
    resources = ["*"]
  }

  statement {
    sid    = "DenyWithoutMfa"
    effect = "Deny"
    not_actions = [
      "iam:ChangePassword",
      "iam:GetAccountPasswordPolicy",
      "sts:GetCallerIdentity",
    ]
    resources = ["*"]

    condition {
      test     = "Bool"
      variable = "aws:MultiFactorAuthPresent"
      values   = ["false"]
    }
  }
}

resource "aws_iam_policy" "operator" {
  name        = "touchline-operator"
  description = "Operate the PrestoSports runner and step up for bootstrap applies"
  policy      = data.aws_iam_policy_document.operator.json
}

data "aws_iam_policy_document" "apply_trust" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = [aws_iam_user.operator.arn]
    }
  }
}

resource "aws_iam_role" "apply" {
  name                 = var.apply_role_name
  description          = "Terraform applies of infra/bootstrap, assumed by ${var.operator_user_name}"
  assume_role_policy   = data.aws_iam_policy_document.apply_trust.json
  max_session_duration = 3600
}

resource "aws_iam_role_policy_attachment" "apply_read" {
  role       = aws_iam_role.apply.name
  policy_arn = aws_iam_policy.read.arn
}

# Trust policies, the OIDC provider and the signing key stay root-only: a role
# that could rewrite both a role's trust and its policy could make itself admin.
data "aws_iam_policy_document" "apply" {
  statement {
    sid       = "StateWrite"
    actions   = ["s3:PutObject", "s3:DeleteObject"]
    resources = ["${local.state_bucket_arn}/bootstrap/*"]
  }

  statement {
    sid       = "BudgetWrite"
    actions   = ["budgets:ModifyBudget"]
    resources = [local.budget_arn]
  }

  statement {
    sid       = "RoleSettings"
    actions   = ["iam:TagRole", "iam:UntagRole", "iam:UpdateRole", "iam:UpdateRoleDescription"]
    resources = local.stack_role_arns
  }

  statement {
    sid       = "InfraRoleInlinePolicy"
    actions   = ["iam:DeleteRolePolicy", "iam:PutRolePolicy"]
    resources = [local.infra_role_arn]
  }

  statement {
    sid = "PublishBoundary"
    actions = [
      "iam:CreatePolicyVersion",
      "iam:DeletePolicyVersion",
      "iam:SetDefaultPolicyVersion",
      "iam:TagPolicy",
      "iam:UntagPolicy",
    ]
    resources = [local.boundary_arn]
  }

  statement {
    sid       = "RunnerRoleLifecycle"
    actions   = ["iam:CreateRole", "iam:DeleteRole", "iam:PassRole"]
    resources = [local.runner_role_arn]
  }

  statement {
    sid       = "RunnerRolePolicy"
    actions   = ["iam:AttachRolePolicy", "iam:DetachRolePolicy"]
    resources = [local.runner_role_arn]

    condition {
      test     = "ArnEquals"
      variable = "iam:PolicyARN"
      values   = [local.ssm_core_arn]
    }
  }

  statement {
    sid = "RunnerInstanceProfile"
    actions = [
      "iam:AddRoleToInstanceProfile",
      "iam:CreateInstanceProfile",
      "iam:DeleteInstanceProfile",
      "iam:RemoveRoleFromInstanceProfile",
      "iam:TagInstanceProfile",
      "iam:UntagInstanceProfile",
    ]
    resources = [local.runner_profile_arn]
  }

  statement {
    sid = "RunnerNetworkCreate"
    actions = [
      "ec2:AllocateAddress",
      "ec2:CreateInternetGateway",
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSubnet",
    ]
    resources = [
      "${local.ec2}:elastic-ip/*",
      "${local.ec2}:internet-gateway/*",
      "${local.ec2}:route-table/*",
      "${local.ec2}:security-group/*",
      "${local.ec2}:subnet/*",
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/project"
      values   = ["touchline"]
    }
  }

  statement {
    sid       = "RunnerVpcCreate"
    actions   = ["ec2:CreateVpc"]
    resources = ["${local.ec2}:vpc/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/project"
      values   = ["touchline"]
    }
  }

  statement {
    sid = "RunnerTaggedChanges"
    actions = [
      "ec2:AssociateAddress",
      "ec2:AssociateRouteTable",
      "ec2:AttachInternetGateway",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:CreateRoute",
      "ec2:CreateRouteTable",
      "ec2:CreateSecurityGroup",
      "ec2:CreateSubnet",
      "ec2:CreateTags",
      "ec2:DeleteInternetGateway",
      "ec2:DeleteRoute",
      "ec2:DeleteRouteTable",
      "ec2:DeleteSecurityGroup",
      "ec2:DeleteSubnet",
      "ec2:DeleteTags",
      "ec2:DeleteVpc",
      "ec2:DetachInternetGateway",
      "ec2:DisassociateAddress",
      "ec2:DisassociateRouteTable",
      "ec2:ModifyInstanceAttribute",
      "ec2:ModifySubnetAttribute",
      "ec2:ModifyVpcAttribute",
      "ec2:ReleaseAddress",
      "ec2:ReplaceRoute",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
      "ec2:StartInstances",
      "ec2:StopInstances",
      "ec2:TerminateInstances",
    ]
    resources = ["${local.ec2}:*"]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = ["touchline"]
    }
  }

  statement {
    sid       = "TagOnCreate"
    actions   = ["ec2:CreateTags"]
    resources = ["${local.ec2}:*"]

    condition {
      test     = "StringEquals"
      variable = "ec2:CreateAction"
      values = [
        "AllocateAddress",
        "CreateInternetGateway",
        "CreateRouteTable",
        "CreateSecurityGroup",
        "CreateSubnet",
        "CreateVpc",
        "RunInstances",
      ]
    }
  }

  statement {
    sid = "UntaggedSubResources"
    actions = [
      "ec2:AssociateAddress",
      "ec2:AuthorizeSecurityGroupEgress",
      "ec2:AuthorizeSecurityGroupIngress",
      "ec2:DisassociateAddress",
      "ec2:RevokeSecurityGroupEgress",
      "ec2:RevokeSecurityGroupIngress",
    ]
    resources = [
      "${local.ec2}:network-interface/*",
      "${local.ec2}:security-group-rule/*",
    ]
  }

  statement {
    sid       = "RunnerLaunchInstance"
    actions   = ["ec2:RunInstances"]
    resources = ["${local.ec2}:instance/*"]

    condition {
      test     = "StringEquals"
      variable = "aws:RequestTag/touchline-role"
      values   = ["presto-runner"]
    }
  }

  statement {
    sid     = "RunnerLaunchAttachments"
    actions = ["ec2:RunInstances"]
    resources = [
      "${local.ec2}:network-interface/*",
      "${local.ec2}:volume/*",
    ]
  }

  statement {
    sid     = "RunnerLaunchNetwork"
    actions = ["ec2:RunInstances"]
    resources = [
      "${local.ec2}:security-group/*",
      "${local.ec2}:subnet/*",
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:ResourceTag/project"
      values   = ["touchline"]
    }
  }

  statement {
    sid       = "RunnerLaunchImage"
    actions   = ["ec2:RunInstances"]
    resources = ["arn:aws:ec2:${var.region}::image/*"]

    # Canonical's images in the SSM catalog report the owner alias "amazon".
    condition {
      test     = "StringEquals"
      variable = "ec2:Owner"
      values   = ["amazon"]
    }
  }
}

resource "aws_iam_role_policy" "apply" {
  name   = "touchline-bootstrap-apply"
  role   = aws_iam_role.apply.id
  policy = data.aws_iam_policy_document.apply.json
}
