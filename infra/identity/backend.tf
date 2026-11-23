# Partial backend: pass -backend-config="bucket=touchline-tfstate-<account id>".
terraform {
  backend "s3" {
    key          = "identity/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
