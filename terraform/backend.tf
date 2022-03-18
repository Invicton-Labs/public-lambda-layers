// Use a remote S3 backend, hosted on the main Clip Money account
terraform {
  backend "s3" {
    encrypt        = true
    region         = "ca-central-1"
    dynamodb_table = "org-terraform-lock"
  }
}

module "backend" {
  source  = "Invicton-Labs/backend-config/null"
  version = "~> 0.2.1"
}
