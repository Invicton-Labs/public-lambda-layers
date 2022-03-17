module "regional_layer_us_east_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.us_east_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_us_east_2" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.us_east_2
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_us_west_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.us_west_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_us_west_2" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.us_west_2
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_af_south_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.af_south_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_ap_east_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.ap_east_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_ap_southeast_3" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.ap_southeast_3
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_ap_south_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.ap_south_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_ap_northeast_3" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.ap_northeast_3
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_ap_northeast_2" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.ap_northeast_2
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_ap_southeast_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.ap_southeast_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_ap_southeast_2" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.ap_southeast_2
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_ap_northeast_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.ap_northeast_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_ca_central_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.ca_central_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_eu_central_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.eu_central_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_eu_west_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.eu_west_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_eu_west_2" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.eu_west_2
    aws.lambda_shell = aws.ca_central_1
  }
  packages     = local.packages
  lambda_shell = module.lambda_shell_layer_permission_granter
}

module "regional_layer_eu_south_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.eu_south_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_eu_west_3" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.eu_west_3
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_eu_north_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.eu_north_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_me_south_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.me_south_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}

module "regional_layer_sa_east_1" {
  source = "./modules/regional-layer"
  providers = {
    aws              = aws.sa_east_1
    aws.lambda_shell = aws.ca_central_1
  }
  packages                          = local.packages
  supports_compatible_architectures = false
  lambda_shell                      = module.lambda_shell_layer_permission_granter
}
