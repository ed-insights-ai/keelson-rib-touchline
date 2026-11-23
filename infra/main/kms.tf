# The snapshot signing key is created in infra/bootstrap (Daniel's CLI only).
# This stack only looks it up, to scope the publish role and export the
# public key.

data "aws_kms_key" "signing" {
  key_id = "alias/touchline-snapshot-signing"
}

data "aws_kms_public_key" "signing" {
  key_id = data.aws_kms_key.signing.arn
}
