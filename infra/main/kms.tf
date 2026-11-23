# ---------------------------------------------------------------------------
# Snapshot signing key. Asymmetric, so the private half never leaves KMS and
# never touches a runner. This is the one standing AWS charge: $1 a month,
# plus $0.15 per 10,000 Sign calls (a few a day).
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "signing_key" {
  # Account root, so IAM policies (the infra and publish roles) take effect.
  statement {
    sid       = "AccountAdmin"
    actions   = ["kms:*"]
    resources = ["*"]
    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${local.account_id}:root"]
    }
  }
}

resource "aws_kms_key" "signing" {
  description              = "Touchline snapshot signing"
  key_usage                = "SIGN_VERIFY"
  customer_master_key_spec = var.signing_key_spec
  deletion_window_in_days  = 30
  policy                   = data.aws_iam_policy_document.signing_key.json

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_kms_alias" "signing" {
  name          = "alias/touchline-snapshot-signing"
  target_key_id = aws_kms_key.signing.key_id
}

data "aws_kms_public_key" "signing" {
  key_id = aws_kms_key.signing.arn
}
