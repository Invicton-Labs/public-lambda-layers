data "aws_iam_policy_document" "layer_permission_granter" {
  provider = aws.ca_central_1
  statement {
    actions = [
      "lambda:AddLayerVersionPermission"
    ]
    resources = [
      "*"
    ]
  }
}

module "lambda_shell_layer_permission_granter" {
  source  = "Invicton-Labs/lambda-shell/aws"
  version = "~>0.2.0"
  providers = {
    aws = aws.ca_central_1
  }
  lambda_memory_size = 128
  lambda_timeouts    = 30
  lambda_role_policies_json = [
    data.aws_iam_policy_document.layer_permission_granter.json
  ]
}
