# Partial backend: pass -backend-config="bucket=touchline-tfstate-<account id>"
# at init (the infra workflow does this from vars.AWS_ACCOUNT_ID).
terraform {
  backend "s3" {
    key          = "main/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
