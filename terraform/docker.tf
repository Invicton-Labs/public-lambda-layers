locals {
  // The name will will give our Docker buildx builder
  builder_name = "invicton-labs-public-lambda-layers-multiarch"

  image_prefix = "il-pll-"

  tmp_dir = "${path.module}/tmpfiles"

  // A mapping of AWS Lambda architecture names to buildx platform names
  arch_lookup = {
    x86_64 = "linux/amd64"
    arm64  = "linux/arm64"
  }

  // Load all of the layer configs from files
  layer_configs = {
    for layer_config_file in fileset("${path.module}/../layers/", "**.json") :
    substr(layer_config_file, 0, length(layer_config_file) - 5) => jsondecode(file("${path.module}/../layers/${layer_config_file}"))
  }

  docker_configs = merge(flatten([
    for layer_name, layer_config in local.layer_configs :
    [
      for version, version_config in layer_config.versions :
      {
        for runtime, runtime_config in version_config.runtimes :
        "${layer_name}.${version}.${runtime}" => {
          layer_name      = layer_name
          version         = version
          runtime         = runtime
          architectures   = try(runtime_config.architectures, version_config.default_architectures, layer_config.default_architectures)
          license_info    = "https://github.com/Invicton-Labs/public-lambda-layers/blob/main/LAYER-LICENSE.md"
          dockerfile_name = "${layer_name}.${version}.${runtime}.Dockerfile"
          dockerfile = replace(replace(join("\n", concat(
            [
              "FROM ${runtime_config.image} AS build_image",
            ],
            layer_config.common_instructions,
            version_config.common_instructions,
            runtime_config.instructions,
            [
              "FROM alpine:latest",
              "RUN apk add --no-cache zip",
              "COPY --from=build_image \"${layer_config.source_directory}\" \"/layer/${trimprefix(runtime_config.destination_directory, "/")}\"",
              // This command will ignore extra attributes such as file times
              // This is so that the output file has the same hash as long as the contents
              // of the contained files remain the same
              "WORKDIR /layer",
              "RUN TZ=UTC zip -r -o -X /package.zip ./*"
            ]
          )), "\r", ""), "\r\n", "")
        }
      }
    ]
  ])...)

  docker_images = merge([
    for docker_config_key, docker_config in local.docker_configs :
    {
      for architecture in docker_config.architectures :
      "${docker_config_key}.${architecture}" => merge(docker_config, {
        architecture    = architecture
        layer_full_name = replace("${docker_config.layer_name}-${docker_config.version}-${docker_config.runtime}-${architecture}", ".", "_")
        package_file    = "${local.tmp_dir}/${docker_config_key}.${architecture}.zip"
        image_tag       = "${local.image_prefix}${docker_config.layer_name}-${docker_config.version}:${docker_config.runtime}-${architecture}"
      })
    }
  ]...)
}

module "naming_validation" {
  source        = "Invicton-Labs/assertion/null"
  version       = "~>0.2.1"
  for_each      = local.docker_images
  condition     = length(regexall("^[a-zA-Z0-9_\\.-]+$", "${each.value.layer_name}${each.value.version}${each.value.runtime}")) == 1 && contains(["arm64", "x86_64"], each.value.architecture)
  error_message = "Layer ${each.value.layer_name} v${each.value.version} ${each.value.runtime} for ${each.value.architecture} is invalid. Layer names, versions, and runtimes must consist solely of letters, numbers, underscores, hyphens, and periods. Architectures must be `arm64` or `x86_64`."
}

// Create the buildx builders
module "create_builder" {
  source  = "Invicton-Labs/shell-data/external"
  version = "~>0.3.1"
  depends_on = [
    module.naming_validation
  ]
  command_unix              = <<EOF
set +e
docker buildx inspect --bootstrap "$BUILDER_NAME" > /dev/null 2>&1
if ! [ $? -eq 0 ]; then
    set -e
    docker buildx create --name "$BUILDER_NAME"
fi
EOF
  command_windows           = <<EOF
$ErrorActionPreference = "Continue"
docker buildx inspect --bootstrap "$Env:BUILDER_NAME" | Out-Null
if (!$?) {
    $ErrorActionPreference = "Stop"
    docker buildx create --name "$Env:BUILDER_NAME"
}
EOF
  working_dir               = path.module
  fail_on_nonzero_exit_code = true
  environment = {
    BUILDER_NAME = local.builder_name
  }
}

// Create the Dockerfiles
module "create_dockerfiles" {
  source   = "Invicton-Labs/file-data/local"
  version  = "~>0.1.0"
  for_each = local.docker_configs
  filename = "${local.tmp_dir}/${each.value.dockerfile_name}"
  content  = each.value.dockerfile
}

// Build the Docker containers that we will pull the layer files from
module "docker_build" {
  source   = "Invicton-Labs/shell-resource/external"
  version  = "~>0.3.0"
  for_each = local.docker_images
  depends_on = [
    module.create_builder,
    module.create_dockerfiles
  ]
  dynamic_depends_on = [
    local.arch_lookup
  ]
  // Trigger a rebuild if any of the parameters change
  triggers       = each.value
  timeout_create = 900
  environment = {
    IL_BUILDER_NAME       = local.builder_name
    IL_BUILD_ARCHITECTURE = local.arch_lookup[each.value.architecture]
    IL_IMAGE_TAG          = each.value.image_tag
    IL_DOCKERFILE_NAME    = each.value.dockerfile_name
    IL_CONTAINER_NAME     = each.key
  }
  command_unix    = "bash ../docker-build.sh"
  command_windows = "powershell.exe -file ..\\docker-build.ps1"
  working_dir     = module.create_builder.exit_code == 0 ? local.tmp_dir : null
}

module "package_hash_keeper" {
  source   = "Invicton-Labs/state-keeper/null"
  version  = "~>0.1.2"
  for_each = module.docker_build
  depends_on = [
    module.docker_build
  ]
  triggers = each.value
  input = {
    md5          = fileexists(each.value.exit_code == 0 ? local.docker_images[each.key].package_file : null) ? filemd5(each.value.exit_code == 0 ? local.docker_images[each.key].package_file : null) : null
    base64sha256 = fileexists(each.value.exit_code == 0 ? local.docker_images[each.key].package_file : null) ? filebase64sha256(each.value.exit_code == 0 ? local.docker_images[each.key].package_file : null) : null
  }
}

resource "time_static" "last_updated" {
  for_each = module.docker_build
  triggers = {
    package_hash_keeper = jsonencode(each.value)
  }
}

locals {
  packages = {
    for k, v in local.docker_images :
    k => merge(v, {
      package_md5          = module.package_hash_keeper[k].output.md5
      package_base64sha256 = module.package_hash_keeper[k].output.base64sha256
      last_updated_unix    = time_static.last_updated[k].unix
      last_updated_rfc3339 = time_static.last_updated[k].rfc3339
    })
  }
}
