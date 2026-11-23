terraform {
  # 1.10+ for S3-native state locking (use_lockfile), so no DynamoDB table.
  required_version = ">= 1.10.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      project    = "touchline"
      managed-by = "terraform"
      stack      = "main"
    }
  }
}
