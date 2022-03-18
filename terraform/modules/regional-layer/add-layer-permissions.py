import boto3
from botocore.config import Config

client_config = Config(
    region_name='${region}'
)

client = boto3.client('lambda', config=client_config)

try:
    client.add_layer_version_permission(
        LayerName='${layer_name}',
        VersionNumber=${layer_version},
        StatementId='public-access',
        Action='lambda:GetLayerVersion',
        Principal='*'
    )
except client.exceptions.ResourceConflictException:
    # Handle the case where the permission already exists
    pass
