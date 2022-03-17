// Upload the packages to S3
resource "aws_s3_object" "packages" {
  for_each               = var.packages
  bucket                 = aws_s3_bucket_policy.lambda_layers.id
  key                    = "${each.key}.zip"
  source                 = each.value.package_file
  source_hash            = each.value.package_md5
  server_side_encryption = "AES256"
  metadata = {}
  tags = {}
}

resource "aws_lambda_layer_version" "lambda_layers" {
  for_each                 = var.packages
  layer_name               = each.value.layer_full_name
  compatible_architectures = var.supports_compatible_architectures ? [each.value.architecture] : null
  compatible_runtimes      = [each.value.runtime]
  description              = "${each.value.layer_name} v${each.value.version} for ${each.value.architecture}"
  license_info             = each.value.license_info
  s3_bucket                = aws_s3_object.packages[each.key].bucket
  s3_key                   = aws_s3_object.packages[each.key].key
  s3_object_version        = aws_s3_object.packages[each.key].version_id
  source_code_hash         = each.value.package_base64sha256
  // Keep old versions so redeploys don't break a bunch of users' code
  skip_destroy = true
}

// This module runs a command in AWS via a Lambda.
// It is used to grant public access permissions on the Lambda Layers.
// We use this instead of the aws_lambda_layer_version_permission resource because that resource
// would delete the permissions on an old version when a new version is created, which we
// absolutely do not want to do (all historical versions are also public).
module "apply_layer_permissions" {
  source   = "Invicton-Labs/lambda-shell-resource/aws"
  version  = "~>0.2.0"
  for_each = aws_lambda_layer_version.lambda_layers

  providers = {
    aws = aws.lambda_shell
  }

  // Pass in the Lambda Shell module
  lambda_shell_module = var.lambda_shell

  // Run the command using the Python interpreter
  interpreter = ["python3"]

  // Load the command/script from a file
  command = templatefile("${path.module}/add-layer-permissions.py", {
    region        = data.aws_region.current.name
    layer_name    = each.value.layer_arn
    layer_version = each.value.version
  })

  // Cause Terraform to fail if the function throws an error when creating the resource
  fail_on_nonzero_exit_code = true
  fail_on_stderr = true
}
