// Use a remote S3 backend, hosted on the main Clip Money account
terraform {
  required_version = ">= 1.1.6"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~>4.3"
    }
    time = {
      source = "hashicorp/time"
      version = "~>0.7"
    }
  }
}
