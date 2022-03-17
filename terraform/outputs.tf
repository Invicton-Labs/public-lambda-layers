locals {
  region_modules = [
    module.regional_layer_us_east_1,
    module.regional_layer_us_east_2,
    module.regional_layer_us_west_1,
    module.regional_layer_us_west_2,
    module.regional_layer_af_south_1,
    module.regional_layer_ap_east_1,
    module.regional_layer_ap_southeast_3,
    module.regional_layer_ap_south_1,
    module.regional_layer_ap_northeast_3,
    module.regional_layer_ap_northeast_2,
    module.regional_layer_ap_southeast_1,
    module.regional_layer_ap_southeast_2,
    module.regional_layer_ap_northeast_1,
    module.regional_layer_ca_central_1,
    module.regional_layer_eu_central_1,
    module.regional_layer_eu_west_1,
    module.regional_layer_eu_west_2,
    module.regional_layer_eu_south_1,
    module.regional_layer_eu_west_3,
    module.regional_layer_eu_north_1,
    module.regional_layer_me_south_1,
    module.regional_layer_sa_east_1,
  ]

  all_layers = merge([
    for region_module in local.region_modules :
    region_module.layers
  ]...)

  package_layers = {
    for package in distinct([for layer in local.all_layers : layer.layer_name]) :
    package => [
      for layer in local.all_layers :
      layer
      if layer.layer_name == package
    ]
  }
  package_version_layers = {
    for package, layers in local.package_layers :
    package => {
      for version in distinct([for layer in layers : layer.version]) :
      version => [
        for layer in layers :
        layer
        if layer.version == version
      ]
    }
  }

  package_version_runtime_layers = {
    for package, version_layers in local.package_version_layers :
    package => {
      for version, layers in version_layers :
      version => {
        for runtime in distinct([for layer in layers : layer.runtime]) :
        runtime => [
          for layer in layers :
          layer
          if layer.runtime == runtime
        ]
      }
  }
  package_version_runtime_architecture_layers = {
    for package, version_runtime_layers in local.package_version_runtime_layers :
    package => {
      for version, runtime_layers in version_runtime_layers :
      version => {
        for runtime, layers in runtime_layers :
        runtime => {
          for layer in layers :
          (layer.architecture) => {
            arn                  = layer.lambda_layer_version_resource.arn
            size                 = layer.lambda_layer_version_resource.source_code_size
            last_updated_unix    = layer.last_updated_unix
            last_updated_rfc3339 = layer.last_updated_rfc3339
          }
        }
      }
  }
}

module "layer_json" {
  source  = "Invicton-Labs/jsonencode-no-replacements/null"
  version = "~>0.1.1"
  object  = local.package_version_runtime_architecture_layers
}

module "layer_file" {
  source   = "Invicton-Labs/file-data/local"
  version  = "~>0.1.0"
  content  = module.layer_json.encoded
  filename = "${path.module}/tmpfiles/layers.json"
}
