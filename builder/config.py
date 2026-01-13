class Constants:
    # The region where metadata, CloudFront, etc. are managed
    PRIMARY_REGION = "ca-central-1"

    # Mapping of AWS Lambda architecture to Docker architecture
    ARCHITECTURE_LOOKUP = {
        'x86_64': 'linux/amd64',
        'arm64': 'linux/arm64',
    }

    # The prefix of the S3 bucket name for deployment artifacts
    ARTIFACT_BUCKET_PREFIX = 'invicton-labs-public-lambda-layers-'

    # The S3 bucket where metadata is kept
    METADATA_BUCKET = "invicton-labs-public-lambda-layers"

    # The metadata JSON file object name
    METADATA_OBJECT = 'layers.json'

    # The ID of the CloudFront distribution that serves the metadata
    CLOUDFRONT_DISTRIBUTION_ID = 'E1GH306YC7UXCZ'

    # The ID of the Lambda signing platform in AWS Signer
    LAMBDA_SIGNING_PLATFORM_ID = "AWSLambda-SHA384-ECDSA"

    # The URL of the layer license
    LICENCE_URL = 'https://github.com/Invicton-Labs/public-lambda-layers/blob/main/LAYER-LICENSE.md'

    # The URL of the project on GitHub
    PROJECT_URL = 'https://github.com/Invicton-Labs/public-lambda-layers'

    # The name of the AWS Signer signing profile to use for signing the layers
    SIGNING_PROFILE_NAME = 'InvictonLabs_PublicLambdaLayers'

    # This is the ID we use for the Lambda layer permission statement
    PERMISSION_STATEMENT_ID = 'public-access'

    # The action on the Lambda Layer permission statement
    PERMISSION_ACTION = 'lambda:GetLayerVersion'

    # The principal for the Lambda Layer permission statement
    PERMISSION_PRINCIPAL = '*'
