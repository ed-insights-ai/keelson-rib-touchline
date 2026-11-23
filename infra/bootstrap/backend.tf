# Partial backend: the bucket name holds the AWS account id, so it is passed at
# init time (-backend-config="bucket=touchline-tfstate-<account id>").
#
# The very first apply runs with a local backend, because this stack creates
# the bucket. See infra/RUNBOOK.md for the one-time override and the state
# migration that follows it.
terraform {
  backend "s3" {
    key          = "bootstrap/terraform.tfstate"
    region       = "us-east-1"
    encrypt      = true
    use_lockfile = true
  }
}
