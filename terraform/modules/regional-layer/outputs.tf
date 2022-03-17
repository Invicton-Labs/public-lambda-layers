output "bucket_id" {
  depends_on = [
    aws_s3_bucket_policy.lambda_layers
  ]
  value = aws_s3_bucket.lambda_layers.id
}

output "bucket_arn" {
  depends_on = [
    aws_s3_bucket_policy.lambda_layers
  ]
  value = aws_s3_bucket.lambda_layers.arn
}

output "layers" {
  value = {
    for k, v in aws_lambda_layer_version.lambda_layers :
    k => merge(var.packages[k], {
      lambda_layer_version_resource = v
      region = data.aws_region.current.name
    })
  }
}
