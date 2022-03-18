provider "aws" {
  alias   = "us_east_1"
  region  = "us-east-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "us_east_2"
  region  = "us-east-2"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "us_west_1"
  region  = "us-west-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "us_west_2"
  region  = "us-west-2"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "af_south_1"
  region  = "af-south-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "ap_east_1"
  region  = "ap-east-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "ap_southeast_3"
  region  = "ap-southeast-3"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "ap_south_1"
  region  = "ap-south-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "ap_northeast_3"
  region  = "ap-northeast-3"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "ap_northeast_2"
  region  = "ap-northeast-2"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "ap_southeast_1"
  region  = "ap-southeast-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "ap_southeast_2"
  region  = "ap-southeast-2"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "ap_northeast_1"
  region  = "ap-northeast-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "ca_central_1"
  region  = "ca-central-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "eu_central_1"
  region  = "eu-central-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "eu_west_1"
  region  = "eu-west-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "eu_west_2"
  region  = "eu-west-2"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "eu_south_1"
  region  = "eu-south-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "eu_west_3"
  region  = "eu-west-3"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "eu_north_1"
  region  = "eu-north-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "me_south_1"
  region  = "me-south-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}

provider "aws" {
  alias   = "sa_east_1"
  region  = "sa-east-1"
  profile = lookup(module.backend.backend.config, "profile", null)
}
