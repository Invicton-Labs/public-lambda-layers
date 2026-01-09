import glob
import os
import pathlib
import json
import tempfile
import subprocess
import hashlib
import concurrent.futures
import re
import uuid
import base64
from collections.abc import Mapping
import io
import time
import sys
import boto3
import botocore.config
from botocore.exceptions import ClientError, EndpointConnectionError
import jsonschema
import jsonref

os.environ['AWS_DEFAULT_REGION'] = "ca-central-1"

# A mapping of AWS Lambda architecture names to buildx platform names
arch_lookup = {
    'x86_64': 'linux/amd64',
    'arm64': 'linux/arm64',
}

# The prefix of the S3 bucket name for deployment artifacts
artifact_bucket_prefix = 'invicton-labs-public-lambda-layers-'

metadata_bucket = "invicton-labs-public-lambda-layers"
metadata_object = 'layers.json'
cloudfront_distribution_id = 'E1GH306YC7UXCZ'
lambda_signing_platform_id = "AWSLambda-SHA384-ECDSA"

# The URL of the license to include in the layer
license_url = 'https://github.com/Invicton-Labs/public-lambda-layers/blob/main/LAYER-LICENSE.md'

# The URL of the project on GitHub
project_url = 'https://github.com/Invicton-Labs/public-lambda-layers'

signing_profile_name = 'InvictonLabs_PublicLambdaLayers'

# This is the ID we use for the Lambda layer permission statement
permission_statement_id = 'public-access'
permission_action = 'lambda:GetLayerVersion'
permission_principal = '*'

# These regions don't support Lambda layer code signing
unsupported_code_signing_regions = [
    # "ap-northeast-3",
    # "ap-southeast-3",
]

# A temporary directory where we'll be putting our files
tmpdir = tempfile.TemporaryDirectory()

regions = None
s3_clients = None
lambda_clients = None
cloudfront = None
signer = None
artifact_bucket_names = None


# Setts up clients for each region
def prepare_aws():
    global regions, s3_clients, lambda_clients, cloudfront, signer, artifact_bucket_names, unsupported_code_signing_regions
    # Create an EC2 client for getting a list of regions
    ec2 = boto3.client('ec2')
    # Get a list of all supported AWS regions
    regions = [r['RegionName'] for r in ec2.describe_regions(
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
    s3_clients = {
        region: boto3.client('s3', region_name=region, config=client_config) for region in regions
    }
    lambda_clients = {
        region: boto3.client('lambda', region_name=region, config=client_config) for region in regions
    }
    cloudfront = boto3.client('cloudfront')
    signer = boto3.client('signer')
    artifact_bucket_names = {
        region: f'{artifact_bucket_prefix}{region}'
        for region in regions
    }

    no_signing_regions = []
    no_lambda_signing_regions = []
    for region in regions:
        try:
            regional_signer = boto3.client("signer", region_name=region)
            paginator = regional_signer.get_paginator("list_signing_platforms")

            platform_ids = set()
            for page in paginator.paginate():
                for p in page.get("platforms", []):
                    if "platformId" in p:
                        platform_ids.add(p["platformId"])

            if lambda_signing_platform_id not in platform_ids:
                no_lambda_signing_regions.append(region)

        except EndpointConnectionError:
            no_signing_regions.append(region)

    print(f"Non-signing regions: {json.dumps(no_signing_regions)}")
    print(f"Non-Lambda-signing regions: {json.dumps(no_lambda_signing_regions)}")


# Runs a function many times concurrently on a set of inputs
def concurrent_func(num_workers, worker_func, inputs: dict, expand_input=False):
    err = None
    results = {}
    max_workers = len(inputs)
    if num_workers is not None:
        max_workers = num_workers
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_input_key = {}
        for k, inpt in inputs.items():
            if expand_input:
                if isinstance(inpt, Mapping):
                    future = executor.submit(worker_func, **inpt)
                else:
                    future = executor.submit(worker_func, *inpt)
            else:
                future = executor.submit(worker_func, inpt)
            future_to_input_key[future] = k

        for future in concurrent.futures.as_completed(future_to_input_key):
            try:
                res = future.result()
                results[future_to_input_key[future]] = res
            except Exception as e:
                err = e
                # If one job failed, exit all of them
                executor.shutdown(wait=True, cancel_futures=True)
                break
    if err is not None:
        raise err
    return results


# Returns a dict of all layers in a region, formatted in a cleaner way
def get_existing_layers_in_region(region):
    client = lambda_clients[region]
    paginator = client.get_paginator('list_layers').paginate()
    layers = {}
    for page in paginator:
        for layer in page['Layers']:
            layers[layer['LayerName']] = layer['LatestMatchingVersion']
            layers[layer['LayerName']]['LayerArn'] = layer['LayerArn']
            layers[layer['LayerName']]['LayerName'] = layer['LayerName']
            layers[layer['LayerName']]['region'] = region

    return layers


# Gets an existing Lambda Layer and associated policy
def get_layer(region, layer_name, version):
    client = lambda_clients[region]
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
            if statement['Sid'] == permission_statement_id and statement['Principal'] == permission_principal and statement['Action'] == permission_action:
                has_public_policy = True
                continue
            # If it's not what we're looking for, mark it for removal
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
def create_public_policy(region, layer_name, version):
    return lambda_clients[region].add_layer_version_permission(
        LayerName=layer_name,
        VersionNumber=version,
        StatementId=permission_statement_id,
        Action=permission_action,
        Principal=permission_principal,
    )


# Removes a given permission from a Lambda Layer
def remove_policy_statement(region, layer_name, version, statement_id):
    return lambda_clients[region].remove_layer_version_permission(
        LayerName=layer_name,
        VersionNumber=version,
        StatementId=statement_id
    )


# Parses the filesystem to load the layer files with their names
def get_layer_definitions():
    build_dir = pathlib.Path(__file__).parent.resolve()
    layers_dir = "{}/../layers".format(build_dir)
    layer_filenames = glob.glob('{}/*.json'.format(layers_dir))

    with open('{}/layer-definition-jsonschema.json'.format(build_dir), mode='r') as file:
        schema = json.loads(file.read())

    vclass = jsonschema.validators.validator_for(schema)
    vclass.check_schema(schema)
    validator = vclass(schema)

    layer_definitions = {}

    for layer_filename in layer_filenames:
        layer_name = layer_filename.replace("\\", "/").split("/")[-1][0:-5]
        pretty_filename = layer_filename[len(layers_dir)+1:]
        with open(layer_filename, mode='r') as file:
            raw = file.read()
            try:
                definition = json.loads(raw)
            except json.JSONDecodeError as e:
                raise ValueError(
                    'Failed to JSON-decode {}: {}'.format(pretty_filename, e))
        try:
            # Dereference references
            definition = jsonref.JsonRef.replace_refs(definition)
            # Validate that the definition is valid
            validator.validate(definition)
        except jsonschema.ValidationError as e:
            raise ValueError(
                'Definition for {} is invalid: {} (at {})'.format(pretty_filename, e.message, '->'.join(e.schema_path)))
        except jsonref.JsonRefError as e:
            raise ValueError(
                'Definition for {} is invalid: {}'.format(pretty_filename, e.message))
        layer_definitions[layer_name] = {
            'pretty_filename': pretty_filename,
            'package_config': definition,
        }

    return layer_definitions


# Parses the layer JSON files to determine all the build configurations that need to be run
def generate_layer_configs(layer_definitions):
    package_path = '/package.zip'
    layer_configs = {}
    package_pattern = '^[a-z0-9-]+$'
    runtime_pattern = '^[a-z0-9.]+$'
    version_pattern = '^[a-z0-9.]+$'
    package_regex = re.compile(package_pattern)
    runtime_regex = re.compile(runtime_pattern)
    version_regex = re.compile(version_pattern)
    for package_name, definition in layer_definitions.items():
        filename = definition['pretty_filename']
        package_config = definition['package_config']

        if not package_regex.match(package_name):
            raise Exception('Definition for {} is invalid: package names (filenames) must match the regex "{}"'.format(
                filename, package_pattern))

        for runtime, runtime_config in package_config['runtimes'].items():
            if not runtime_regex.match(runtime):
                raise Exception('Definition for {} is invalid: runtime names must match the regex "{}"'.format(
                    filename, runtime_pattern))

            for version, version_config in runtime_config['versions'].items():
                if not version_regex.match(version):
                    raise Exception('Definition for {} is invalid: versions must match the regex "{}"'.format(
                        filename, version_pattern))

                for architecture, architecture_config in version_config['architectures'].items():

                    layer_name = "{}_{}_{}_{}".format(
                        package_name, version.replace('.', '-'), runtime.replace('.', '-'), architecture)

                    layer_source_directory = architecture_config.get('layer_source_directory', version_config.get(
                        'default_layer_source_directory', runtime_config.get('default_layer_source_directory', package_config.get('default_layer_source_directory'))))
                    if layer_source_directory is None:
                        raise ValueError(
                            '{} has no "layer_source_directory" property, and there are no "default_layer_source_directory" properties at the version, runtime, or package level'.format(layer_name))

                    layer_target_directory = architecture_config.get('layer_target_directory', version_config.get(
                        'default_layer_target_directory', runtime_config.get('default_layer_target_directory', package_config.get('default_layer_target_directory'))))
                    if layer_target_directory is None:
                        raise ValueError(
                            '{} has no "layer_target_directory" property, and there are no "default_layer_target_directory" properties at the rversion, runtime, or package level'.format(layer_name))

                    image = architecture_config.get('image', version_config.get(
                        'default_image', runtime_config.get('default_image', package_config.get('default_image'))))
                    if image is None:
                        raise ValueError(
                            '{} has no "image" property, and there are no "default_image" property at the version, runtime, or package level'.format(layer_name))

                    dockerfile_lines = [
                        'FROM {} AS build_image'.format(image)
                    ]
                    dockerfile_lines.extend(package_config.get(
                        'common_instructions_pre', []))
                    dockerfile_lines.extend(runtime_config.get(
                        'common_instructions_pre', []))
                    dockerfile_lines.extend(version_config.get(
                        'common_instructions_pre', []))
                    dockerfile_lines.extend(
                        architecture_config.get('instructions', []))
                    dockerfile_lines.extend(version_config.get(
                        'common_instructions_post', []))
                    dockerfile_lines.extend(runtime_config.get(
                        'common_instructions_post', []))
                    dockerfile_lines.extend(package_config.get(
                        'common_instructions_post', []))

                    dockerfile_lines.extend([
                        'FROM alpine:latest',
                        'RUN apk add --no-cache zip',
                        'COPY --from=build_image "{}" "/layer/{}"'.format(
                            layer_source_directory, layer_target_directory.lstrip('/')),
                        # This command will ignore extra attributes such as file times
                        # This is so that the output file has the same hash as long as the contents
                        # of the contained files remain the same
                        'WORKDIR /layer',
                        'RUN TZ=UTC zip -r -X "{}" ./*'.format(package_path)
                    ])

                    dockerfile_content = '\n'.join(dockerfile_lines)

                    # Calculate the hash of the Dockerfile so we can track if it changes
                    h = hashlib.sha256()
                    h.update(dockerfile_content.encode())

                    dockerfile_sha256 = base64.b64encode(h.digest()).decode()

                    layer_configs[layer_name] = {
                        'dockerfile_content': dockerfile_content,
                        'dockerfile_sha256': dockerfile_sha256,
                        'dockerfile_path': "{}/{}.Dockerfile".format(tmpdir.name, layer_name),
                        'package_name': package_name,
                        'package_path': package_path,
                        'runtime': runtime,
                        'version': version,
                        'architecture': architecture,
                        'archive_path': "{}/{}.zip".format(tmpdir.name, layer_name),
                        'image_tag': "{}:local".format(layer_name),
                        'platform': arch_lookup[architecture],
                        'name': layer_name,
                        'description': {
                            'df_sha256': dockerfile_sha256,
                            'package': package_name,
                            'runtime': runtime,
                            'version': version,
                            'architecture': architecture,
                        }
                    }

    return layer_configs


def process_existing_layer_data(is_deploy, layer_configs, existing_layers_by_region):
    # This is for tracking all existing layers that match a desired layer, but
    # are missing a public permission policy.
    existing_layers_needing_policy_check = {}

    # Check each unique layer config
    for layer_config in layer_configs.values():
        layer_regionals = {}
        layer_config['regional'] = layer_regionals

        # Check all regions
        for region in regions:
            layer_regionals[region] = None

            existing_layer = existing_layers_by_region[region].get(
                layer_config['name'])
            if existing_layer is not None:
                try:
                    metadata = json.loads(existing_layer['Description'])
                except json.JSONDecodeError:
                    # If we couldn't decode the description, then it's an old version that doesn't
                    # match the format, so replace it.
                    continue
                # If any of the description fields have changed, publish a new version.
                if metadata != layer_config['description']:
                    continue

                existing_layers_needing_policy_check[str(uuid.uuid4())] = {
                    'region': region,
                    'layer_name': existing_layer['LayerName'],
                    'version': existing_layer['Version']
                }

                layer_regionals[region] = existing_layer

    print('Checking policies for existing layers...')
    # Check each layer to see if it has an existing public policy. This
    # also populates data about the Content (including signing)
    existing_layer_data = concurrent_func(
        100, get_layer, existing_layers_needing_policy_check, expand_input=True)

    all_statements_to_remove = []
    create_policy_inputs = {}
    for input_key, existing_layer_datum in existing_layer_data.items():
        has_policy, statements_to_remove, content = existing_layer_datum
        inpt = existing_layers_needing_policy_check[input_key]

        if 'SigningJobArn' not in content and inpt['region'] not in unsupported_code_signing_regions:
            # If the existing layer isn't signed, and it isn't in a region that doesn't
            # support signing, don't include it as an existing region layer.
            # That way, it will be regenerated with a signature.
            layer_configs[inpt['layer_name']
                          ]['regional'][inpt['region']] = None
        else:
            layer_configs[inpt['layer_name']
                          ]['regional'][inpt['region']]['Content'] = content

        for stmt in statements_to_remove:
            all_statements_to_remove[str(uuid.uuid4())] = stmt
        if not has_policy:
            create_policy_inputs[input_key] = inpt

    print(f'{len(all_statements_to_remove)} existing layer policy statements must be removed')
    print(f'{len(create_policy_inputs)} existing layers need public policies')

    if is_deploy and len(all_statements_to_remove) > 0:
        print('Removing incorrect statements...')
        concurrent_func(100, remove_policy_statement,
                        all_statements_to_remove, expand_input=True)
        print('Done!')

    if is_deploy and len(create_policy_inputs) > 0:
        print('Creating public policies for existing layers...')
        concurrent_func(100, create_public_policy,
                        create_policy_inputs, expand_input=True)
        print('Done!')

    untracked_layers = []
    for region, existing_layers in existing_layers_by_region.items():
        for layer_name, layer in existing_layers.items():
            if layer_name not in layer_configs:
                untracked_layers.append(layer)

    print('There are {} untracked layers'.format(len(untracked_layers)))


# This deploys a signed layer zip file from S3 to a Lambda Layer in a given region
def create_layer(region, layer_config, signed_s3_bucket, signed_s3_key):
    # Copy the signed artifact to the regional bucket
    print('Copying signed deployment artifact for {} to {}'.format(
        layer_config['name'], region))
    s3_clients[region].copy(
        CopySource={
            'Bucket': signed_s3_bucket,
            'Key': signed_s3_key,
        },
        Bucket=artifact_bucket_names[region],
        Key=signed_s3_key,
        SourceClient=s3_clients[os.environ['AWS_DEFAULT_REGION']]
    )

    print('Publishing layer for {} in {}'.format(layer_config['name'], region))
    publish_response = lambda_clients[region].publish_layer_version(
        LayerName=layer_config['name'],
        Description=json.dumps(
            layer_config['description'], separators=(',', ':')),
        Content={
            'S3Bucket': artifact_bucket_names[region],
            'S3Key': signed_s3_key,
        },
        CompatibleRuntimes=[
            layer_config['runtime']
        ],
        LicenseInfo=license_url
    )
    publish_response['LayerName'] = layer_config['name']
    publish_response['region'] = region
    print('Adding public permission to {} in {}'.format(
        layer_config['name'], region))
    lambda_clients[region].add_layer_version_permission(
        LayerName=layer_config['name'],
        VersionNumber=publish_response['Version'],
        StatementId=permission_statement_id,
        Action=permission_action,
        Principal=permission_principal,
    )
    print('All operations complete for {} in {}'.format(
        layer_config['name'], region))

    layer_config['regional'][region] = publish_response


# This builds the Docker image, extracts the built layer from it, pushes it to S3, signs it, then publishes it to each region
def build_layer(layer_config, stream_output, regions_to_publish):
    with open(layer_config['dockerfile_path'], "w", newline='\n') as f:
        # Writing data to a file
        f.write(layer_config['dockerfile_content'])

    stderr = None
    stdout = None
    if not stream_output:
        stderr = subprocess.STDOUT
        stdout = subprocess.PIPE

    # Build the image and load it into the local registry
    print('Building layer {}...'.format(layer_config['name']))
    try:
        r = subprocess.run(['docker', 'buildx', 'build', '--platform', layer_config['platform'],
                            '--load', '-t', layer_config['image_tag'], '-f', layer_config['dockerfile_path'], '.'], check=True, stderr=stderr, stdout=stdout)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Remove any existing containers of the same name
    try:
        r = subprocess.run(
            ['docker', 'rm', '-f', layer_config['name']], check=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Create a new container with this image
    try:
        r = subprocess.run(['docker', 'create', '-ti', '--name', layer_config['name'],
                            '--platform', layer_config['platform'], layer_config['image_tag']], check=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Copy the layer files from it
    try:
        r = subprocess.run(['docker', 'cp', '{}:{}'.format(
            layer_config['name'], layer_config['package_path']), layer_config['archive_path']], check=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Remove the container we just created
    try:
        r = subprocess.run(
            ['docker', 'rm', '-f', layer_config['name']], check=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Remove the image we just created
    try:
        r = subprocess.run(
            ['docker', 'image', 'rm', layer_config['image_tag']], check=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # If there are no publications to be done, exit
    if len(regions_to_publish) == 0:
        return None

    s3_object = 'unsigned/{}/{}.zip'.format(
        layer_config['name'], str(uuid.uuid4()))

    primary_region_bucket_name = artifact_bucket_names[os.environ['AWS_DEFAULT_REGION']]

    # Upload the layer to the regional bucket
    print('Uploading unsigned deployment artifact for {}'.format(
        layer_config['name']))
    r = s3_clients[os.environ['AWS_DEFAULT_REGION']].upload_file(
        layer_config['archive_path'], primary_region_bucket_name, s3_object)

    print('Unsigned artifact uploaded. Starting signing job...')
    requestToken = str(uuid.uuid4())
    resp = signer.start_signing_job(
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
        profileName=signing_profile_name,
        clientRequestToken=requestToken,
    )
    signing_job_id = resp['jobId']
    print('Signing job created ({}). Waiting for it to complete...'.format(
        signing_job_id))

    signed_object_key = None
    while True:
        resp = signer.describe_signing_job(
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
            raise Exception(
                'Signing job failed: {}'.format(resp['statusReason']))
    print('Signing job {} complete'.format(signing_job_id))

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
    concurrent_func(None, create_layer, publications, expand_input=True)
    return None


# This uploads the metadata file for a Layer to the S3 metadata bucket
def upload_s3_metadata_file(path, metadata):
    s3_clients[os.environ['AWS_DEFAULT_REGION']].upload_fileobj(
        io.BytesIO(json.dumps(metadata, separators=(',', ':')).encode()),
        metadata_bucket,
        path,
        ExtraArgs={
            'ContentType': 'application/json',
        }
    )
    return None


# Once everything is built and deployed, this uploads the metadata files to the S3 metadata bucket,
# then invalidates the CloudFront distribution to ensure the cache is cleared.
def upload_metadata(layer_configs):
    metadata = {}
    for layer_config in layer_configs.values():
        if layer_config['package_name'] not in metadata:
            metadata[layer_config['package_name']] = {}
        if layer_config['version'] not in metadata[layer_config['package_name']]:
            metadata[layer_config['package_name']
                     ][layer_config['version']] = {}
        if layer_config['runtime'] not in metadata[layer_config['package_name']][layer_config['version']]:
            metadata[layer_config['package_name']][layer_config['version']
                                                   ][layer_config['runtime']] = {}
        if layer_config['architecture'] not in metadata[layer_config['package_name']][layer_config['version']][layer_config['runtime']]:
            metadata[layer_config['package_name']][layer_config['version']
                                                   ][layer_config['runtime']][layer_config['architecture']] = {}
        for region, regional in layer_config['regional'].items():
            metadata[layer_config['package_name']][layer_config['version']][layer_config['runtime']][layer_config['architecture']][region] = {
                'description': regional['Description'],
                'license_info': regional['LicenseInfo'],
                'layer_arn': regional['LayerArn'],
                'layer_version_arn': regional['LayerVersionArn'],
                'layer_version': regional['Version'],
                'created_date': regional['CreatedDate'],
                'layer_name': regional['LayerName'],
                'signing_job_arn': regional['Content'].get('SigningJobArn'),
                'signing_profile_version_arn': regional['Content'].get('SigningProfileVersionArn'),
                'source_code_hash': regional['Content']['CodeSha256'],
                'source_code_size': regional['Content']['CodeSize']
            }

    metadata_files = {}
    package_base_path = "packages"
    for package_name, package_config in metadata.items():
        metadata_files[str(uuid.uuid4())] = {
            'path': '{}/{}.json'.format(package_base_path, package_name),
            'metadata': package_config | {
                'package': package_name,
            }
        }
        for version, version_config in package_config.items():
            metadata_files[str(uuid.uuid4())] = {
                'path': '{}/{}/{}.json'.format(package_base_path, package_name, version),
                'metadata': version_config | {
                    'package': package_name,
                    'package_version': version,
                }
            }
            for runtime, runtime_config in version_config.items():
                metadata_files[str(uuid.uuid4())] = {
                    'path': '{}/{}/{}/{}.json'.format(package_base_path, package_name, version, runtime),
                    'metadata': runtime_config | {
                        'package': package_name,
                        'package_version': version,
                        'runtime': runtime,
                    }
                }
                for architecture, architecture_config in runtime_config.items():
                    metadata_files[str(uuid.uuid4())] = {
                        'path': '{}/{}/{}/{}/{}.json'.format(package_base_path, package_name, version, runtime, architecture),
                        'metadata': architecture_config | {
                            'package': package_name,
                            'package_version': version,
                            'runtime': runtime,
                            'architecture': architecture,
                        }
                    }
                    for region, region_config in architecture_config.items():
                        metadata_files[str(uuid.uuid4())] = {
                            'path': '{}/{}/{}/{}/{}/{}.json'.format(package_base_path, package_name, version, runtime, architecture, region),
                            'metadata': region_config | {
                                'package': package_name,
                                'package_version': version,
                                'runtime': runtime,
                                'architecture': architecture,
                                'region': region,
                            }
                        }

    # Upload the master layers file with all data
    metadata_files[str(uuid.uuid4())] = {
        'path': metadata_object,
        'metadata': metadata
    }

    concurrent_func(
        100, upload_s3_metadata_file, metadata_files, expand_input=True)

    print('Invalidating CloudFront paths...')
    r = cloudfront.create_invalidation(
        DistributionId=cloudfront_distribution_id,
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
        response = cloudfront.get_invalidation(
            DistributionId=cloudfront_distribution_id,
            Id=invalidation_id
        )
        status = response['Invalidation']['Status']
        if status == 'Completed':
            break
        elif status == 'InProgress':
            time.sleep(2)
            continue
        else:
            raise Exception('Invalidation failed: {}'.format(status))

    print('CloudFront invalidation complete')


if __name__ == "__main__":
    docker_workers = 4
    is_deploy = len(sys.argv) > 1 and sys.argv[1] == 'true'

    layer_definitions = get_layer_definitions()
    layer_configs = generate_layer_configs(layer_definitions)

    prepare_aws()

    existing_layers_by_region = concurrent_func(
        None, get_existing_layers_in_region, {region: region for region in regions})

    # This evaluates all of the existing layers against the desired layers to
    # find differences (existing layers that must be changed, new layers that must be created)
    process_existing_layer_data(is_deploy, layer_configs, existing_layers_by_region)
    
    # This finds all layer configs where a deployment is missing in one or more regions
    build_configs = {
        k: {
            'layer_config': layer_config,
            'stream_output': docker_workers == 1,
            'regions_to_publish': [
                region
                for region, existing_layer in layer_config['regional'].items()
                if existing_layer is None
            ] if is_deploy else []
        }
        for k, layer_config in layer_configs.items()
        if len([True for existing_layer in layer_config['regional'].values() if existing_layer is None]) > 0
    }

    num_publications = 0
    for build_config in build_configs.values():
        num_publications += len(build_config['regions_to_publish'])

    print('{} layer images must be built'.format(len(build_configs)))
    print('{} regional layers must be published'.format(num_publications))
    
    if is_deploy:
        print('Building and publishing...')
    else:
        print('Building...')
    concurrent_func(docker_workers, build_layer,
                    build_configs, expand_input=True)
    
    # If we're only validating, exit here
    if not is_deploy:
        print('All builds successful!')
        exit(0)

    print('Uploading metadata document...')
    upload_metadata(layer_configs)
    print('All builds and publications complete!')
