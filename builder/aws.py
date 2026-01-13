import json
import io
import time
import uuid
import boto3
import botocore
from config import Constants
from concurrency import concurrent_func

class Aws:
    s3_clients = None
    lambda_clients = None
    cloudfront_client = None
    signer_client = None
    ssm_client = None
    artifact_bucket_names = None
    regions = None
    signer_regions = None

    def __init__(self):
        # Create an EC2 client for getting a list of regions
        ec2 = boto3.client('ec2', region_name=Constants.PRIMARY_REGION)
        # Get a list of all supported AWS regions
        self.regions = [r['RegionName'] for r in ec2.describe_regions(
            Filters=[
                {
                    'Name': 'opt-in-status',
                    'Values': [
                        'opt-in-not-required',
                        'opted-in'
                    ]
                },
            ],
            AllRegions=False
        )['Regions']]
        # Increase the number of retries beyond the default
        client_config = botocore.config.Config(
            retries=dict(
                max_attempts=10
            )
        )
        # S3 and Lambda Boto clients for each region
        self.s3_clients = {
            region: boto3.client('s3', region_name=region, config=client_config) for region in self.regions
        }
        self.lambda_clients = {
            region: boto3.client('lambda', region_name=region, config=client_config) for region in self.regions
        }
        self.cloudfront_client = boto3.client('cloudfront', region_name=Constants.PRIMARY_REGION)
        self.signer_client = boto3.client('signer', region_name=Constants.PRIMARY_REGION)
        self.ssm_client = boto3.client('ssm', region_name=Constants.PRIMARY_REGION)
        self.artifact_bucket_names = {
            region: f'{Constants.ARTIFACT_BUCKET_PREFIX}{region}'
            for region in self.regions
        }
        
        self.signer_regions = self.list_service_regions("signer")


    def list_service_regions(self, service_id: str) -> list[str]:
        """
        Returns regions where an AWS service is available, using the AWS-managed
        public SSM parameters dataset.
        """

        path = f"/aws/service/global-infrastructure/services/{service_id}/regions"

        paginator = self.ssm_client.get_paginator("get_parameters_by_path")
        regions = set()

        for page in paginator.paginate(Path=path, Recursive=False):
            for p in page.get("Parameters", []):
                # AWS docs show the region code is in Parameter.Value for this path.
                regions.add(p["Value"])

        return sorted(regions)
    

    # Returns a dict of all layers in a region, formatted in a cleaner way
    def get_existing_layers_in_region(self, region):
        client = self.lambda_clients[region]
        paginator = client.get_paginator('list_layers').paginate()
        layers = {}
        for page in paginator:
            for layer in page['Layers']:
                layers[layer['LayerName']] = layer['LatestMatchingVersion']
                layers[layer['LayerName']]['LayerArn'] = layer['LayerArn']
                layers[layer['LayerName']]['LayerName'] = layer['LayerName']
                layers[layer['LayerName']]['region'] = region

        return layers
        

    # Gets all existing layers in all enabled regions
    def get_existing_layers_by_region(self):
        return concurrent_func(
            None, self.get_existing_layers_in_region, {region: region for region in self.regions})
        

    # Gets an existing Lambda Layer and associated policy
    def get_layer(self, region, layer_name, version):
        client = self.lambda_clients[region]
        statements_to_remove = []
        has_public_policy = False
        try:
            policy_resp = client.get_layer_version_policy(
                LayerName=layer_name,
                VersionNumber=version
            )
            policy = json.loads(policy_resp['Policy'])
            for statement in policy['Statement']:
                # If we haven't already found a public statement, and this one is public, mark it as the public one
                if statement['Sid'] == Constants.PERMISSION_STATEMENT_ID and statement['Principal'] == Constants.PERMISSION_PRINCIPAL and statement['Action'] == Constants.PERMISSION_ACTION:
                    has_public_policy = True
                    continue
                # If it's not the statement we're looking for, mark it for removal
                statements_to_remove.append({
                    'region': region,
                    'layer_name': layer_name,
                    'version': version,
                    'statement_id': statement['Sid'],
                })
        except client.exceptions.ResourceNotFoundException:
            pass

        existing_layer = client.get_layer_version(
            LayerName=layer_name,
            VersionNumber=version
        )
        return has_public_policy, statements_to_remove, existing_layer['Content']


    # Adds a public policy to a Lambda Layer
    def create_public_policy(self, region, layer_name, version):
        return self.lambda_clients[region].add_layer_version_permission(
            LayerName=layer_name,
            VersionNumber=version,
            StatementId=Constants.PERMISSION_STATEMENT_ID,
            Action=Constants.PERMISSION_ACTION,
            Principal=Constants.PERMISSION_PRINCIPAL,
        )
    

    # Removes a given permission from a Lambda Layer
    def remove_policy_statement(self, region, layer_name, version, statement_id):
        return self.lambda_clients[region].remove_layer_version_permission(
            LayerName=layer_name,
            VersionNumber=version,
            StatementId=statement_id
        )
    

    # Creates a Lambda layer, signs it, and deploys it to all supported regions
    def deploy_layer(self, layer_config, regions_to_publish):
        # If there are no publications to be done, exit
        if len(regions_to_publish) == 0:
            return

        s3_object = f'unsigned/{layer_config['name']}/{str(uuid.uuid4())}.zip'

        primary_region_bucket_name = self.artifact_bucket_names[Constants.PRIMARY_REGION]

        # Upload the layer to the regional bucket
        print(f'Uploading unsigned deployment artifact for {layer_config['name']}')
        self.s3_clients[Constants.PRIMARY_REGION].upload_file(
            layer_config['archive_path'], primary_region_bucket_name, s3_object)

        print('Unsigned artifact uploaded. Starting signing job...')
        request_token = str(uuid.uuid4())
        resp = self.signer_client.start_signing_job(
            source={
                's3': {
                    'bucketName': primary_region_bucket_name,
                    'key': s3_object,
                    'version': 'null',
                }
            },
            destination={
                's3': {
                    'bucketName': primary_region_bucket_name,
                    'prefix': 'signed/'
                }
            },
            profileName=Constants.SIGNING_PROFILE_NAME,
            clientRequestToken=request_token,
        )
        signing_job_id = resp['jobId']
        print(f'Signing job created ({signing_job_id}). Waiting for it to complete...')

        signed_object_key = None
        while True:
            resp = self.signer_client.describe_signing_job(
                jobId=signing_job_id
            )
            status = resp['status']
            if status == 'Succeeded':
                signed_object_key = resp['signedObject']['s3']['key']
                break
            elif status == 'InProgress':
                time.sleep(1)
                continue
            else:
                raise RuntimeError(
                    f'Signing job failed: {resp['statusReason']}')
        print(f'Signing job {signing_job_id} complete')

        # Determine which regions need the layer to be published
        publications = {
            region: {
                'region': region,
                'layer_config': layer_config,
                'signed_s3_bucket': primary_region_bucket_name,
                'signed_s3_key': signed_object_key,
            }
            for region in regions_to_publish
        }
        # Concurrently publish to each region
        concurrent_func(None, self._deploy_layer_to_region, publications, expand_input=True)
        return
    

    # This deploys a signed layer zip file from S3 to a Lambda Layer in a given region
    def _deploy_layer_to_region(self, region, layer_config, signed_s3_bucket, signed_s3_key):
        # Copy the signed artifact to the regional bucket
        print(f'Copying signed deployment artifact for {layer_config['name']} to {region}')
        self.s3_clients[region].copy(
            CopySource={
                'Bucket': signed_s3_bucket,
                'Key': signed_s3_key,
            },
            Bucket=self.artifact_bucket_names[region],
            Key=signed_s3_key,
            SourceClient=self.s3_clients[Constants.PRIMARY_REGION]
        )

        print(f'Publishing layer for {layer_config['name']} in {region}')
        publish_response = self.lambda_clients[region].publish_layer_version(
            LayerName=layer_config['name'],
            Description=json.dumps(
                layer_config['description'], separators=(',', ':')),
            Content={
                'S3Bucket': self.artifact_bucket_names[region],
                'S3Key': signed_s3_key,
            },
            CompatibleRuntimes=[
                layer_config['runtime']
            ],
            LicenseInfo=Constants.LICENCE_URL
        )
        publish_response['LayerName'] = layer_config['name']
        publish_response['region'] = region
        print(f'Adding public permission to {layer_config['name']} in {region}')
        self.lambda_clients[region].add_layer_version_permission(
            LayerName=layer_config['name'],
            VersionNumber=publish_response['Version'],
            StatementId=Constants.PERMISSION_STATEMENT_ID,
            Action=Constants.PERMISSION_ACTION,
            Principal=Constants.PERMISSION_PRINCIPAL,
        )
        print(f'All operations complete for {layer_config['name']} in {region}')

        layer_config['regional'][region] = publish_response
    

    # This uploads the metadata file for a Layer to the S3 metadata bucket
    def upload_s3_metadata_file(self, path, metadata):
        self.s3_clients[Constants.PRIMARY_REGION].upload_fileobj(
            io.BytesIO(json.dumps(metadata, separators=(',', ':')).encode()),
            Constants.METADATA_BUCKET,
            path,
            ExtraArgs={
                'ContentType': 'application/json',
            }
        )
        return None


    # Invalidates the metadata CloudFront distribution
    def invalidate_metadata_cloudfront(self):
        r = self.cloudfront_client.create_invalidation(
            DistributionId=Constants.CLOUDFRONT_DISTRIBUTION_ID,
            InvalidationBatch={
                'Paths': {
                    'Quantity': 1,
                    'Items': [
                        '/*',
                    ]
                },
                'CallerReference': str(int(time.time()))
            }
        )
        invalidation_id = r['Invalidation']['Id']

        while True:
            response = self.cloudfront_client.get_invalidation(
                DistributionId=Constants.CLOUDFRONT_DISTRIBUTION_ID,
                Id=invalidation_id
            )
            status = response['Invalidation']['Status']
            if status == 'Completed':
                break
            elif status == 'InProgress':
                time.sleep(2)
                continue
            else:
                raise RuntimeError(f'Invalidation failed: {status}')
