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
cloudfront_distribution_id = 'E1D65MH18Z0S5M'

# The URL of the license to include in the layer
license_url = 'https://github.com/Invicton-Labs/public-lambda-layers/blob/main/LAYER-LICENSE.md'

# The URL of the project on GitHub
project_url = 'https://github.com/Invicton-Labs/public-lambda-layers'

# This is the ID we use for the Lambda layer permission statement
permission_statement_id = 'public-access'

# This is the name we use for the Docker
builder_name = "multiarch"

# A temporary directory where we'll be putting our files
tmpdir = tempfile.TemporaryDirectory()

regions = None
s3_clients = None
lambda_clients = None
cloudfront = None
artifact_bucket_names = None


def prepare_aws():
    global regions, s3_clients, lambda_clients, cloudfront, artifact_bucket_names
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
    artifact_bucket_names = {
        region: '{}{}'.format(artifact_bucket_prefix, region)
        for region in regions
    }


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


def layer_has_existing_public_policy(region, layer_name, version):
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
            if statement['Sid'] == permission_statement_id and statement['Principal'] == '*' and statement['Action'] == 'lambda:GetLayerVersion':
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
    return has_public_policy, statements_to_remove


def create_public_policy(region, layer_name, version):
    return lambda_clients[region].add_layer_version_permission(
        LayerName=layer_name,
        VersionNumber=version,
        StatementId=permission_statement_id,
        Action='lambda:GetLayerVersion',
        Principal='*',
    )


def remove_policy_statement(region, layer_name, version, statement_id):
    return lambda_clients[region].remove_layer_version_permission(
        LayerName=layer_name,
        VersionNumber=version,
        StatementId=statement_id
    )


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


def process_existing_layer_data(layer_configs, existing_layers_by_region):
    # This is for tracking all existing layers that match a desired layer, but
    # are missing a public permission policy.
    existing_layers_needing_policy_check = {}

    for layer_config in layer_configs.values():
        layer_regionals = {}
        layer_config['regional'] = layer_regionals

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

                existing_layers_needing_policy_check[uuid.uuid4()] = {
                    'region': region,
                    'layer_name': existing_layer['LayerName'],
                    'version': existing_layer['Version']
                }

                layer_regionals[region] = existing_layer

    print('Checking policies for existing layers...')
    # Check each layer to see if it has an existing public policy
    existing_policy_data = concurrent_func(
        100, layer_has_existing_public_policy, existing_layers_needing_policy_check, expand_input=True)

    all_statements_to_remove = []
    create_policy_inputs = []
    for input_key, existing_policy_datum in existing_policy_data.items():
        has_policy, statements_to_remove = existing_policy_datum
        for stmt in statements_to_remove:
            all_statements_to_remove[uuid.uuid4()] = stmt
        if not has_policy:
            create_policy_inputs[input_key] = existing_layers_needing_policy_check[input_key]

    print('{} existing layer policy statements must be removed'.format(
        len(all_statements_to_remove)))
    print('{} existing layers need public policies'.format(
        len(create_policy_inputs)))

    if len(all_statements_to_remove) > 0:
        print('Removing incorrect statements...')
        concurrent_func(100, remove_policy_statement,
                        all_statements_to_remove, expand_input=True)
        print('Done!')

    if len(create_policy_inputs) > 0:
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


def create_layer(region, layer_config):
    s3_object = '{}-{}.zip'.format(layer_config['name'], uuid.uuid4())

    # Upload the layer to the regional bucket
    print('Uploading deployment artifact for {} in {}'.format(
        layer_config['name'], region))
    s3_clients[region].upload_file(
        layer_config['archive_path'], artifact_bucket_names[region], s3_object)
    print('Publishing layer for {} in {}'.format(layer_config['name'], region))
    publish_response = lambda_clients[region].publish_layer_version(
        LayerName=layer_config['name'],
        Description=json.dumps(
            layer_config['description'], separators=(',', ':')),
        Content={
            'S3Bucket': artifact_bucket_names[region],
            'S3Key': s3_object,
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
        Action='lambda:GetLayerVersion',
        Principal='*',
    )
    print('All operations complete for {} in {}'.format(
        layer_config['name'], region))

    layer_config['regional'][region] = publish_response


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
        r = subprocess.run(['docker', 'buildx', 'build', '--builder', builder_name, '--platform', layer_config['platform'],
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

    # Determine which regions need the layer to be published
    publications = {
        region: {
            'region': region,
            'layer_config': layer_config,
        }
        for region in regions_to_publish
    }
    # Concurrently publish to each region
    concurrent_func(None, create_layer, publications, expand_input=True)
    return None


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
                'arn': regional['LayerArn'],
                'latest_version_arn': regional['LayerVersionArn'],
                'version': regional['Version'],
                'created_date': regional['CreatedDate'],
                'name': regional['LayerName'],
            }
    document_contents = json.dumps(metadata, separators=(',', ':'))
    s3_clients['ca-central-1'].upload_fileobj(
        io.BytesIO(document_contents.encode()),
        metadata_bucket,
        metadata_object,
        ExtraArgs={
            'ContentType': 'application/json',
        }
    )
    cloudfront.create_invalidation(
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


if __name__ == "__main__":
    docker_workers = 4

    layer_definitions = get_layer_definitions()
    layer_configs = generate_layer_configs(layer_definitions)

    # If we're only validating, exit here
    if len(sys.argv) > 1 and sys.argv[1] != 'true':
        exit(0)

    prepare_aws()

    existing_layers_by_region = concurrent_func(
        None, get_existing_layers_in_region, {region: region for region in regions})

    # This evaluates all of the existing layers against the desired layers to
    # find differences (existing layers that must be changed, new layers that must be created)
    process_existing_layer_data(layer_configs, existing_layers_by_region)

    # This finds all layer configs where a deployment is missing in one or more regions
    build_configs = {
        k: {
            'layer_config': layer_config,
            'stream_output': docker_workers == 1,
            'regions_to_publish': [
                region
                for region, existing_layer in layer_config['regional'].items()
                if existing_layer is None
            ]
        }
        for k, layer_config in layer_configs.items()
        if len([True for existing_layer in layer_config['regional'].values() if existing_layer is None])
    }

    num_publications = 0
    for build_config in build_configs.values():
        num_publications += len(build_config['regions_to_publish'])

    print('{} layer images must be built'.format(len(build_configs)))
    print('{} regional layers must be published'.format(num_publications))
    print('Building and publishing...')
    concurrent_func(docker_workers, build_layer,
                    build_configs, expand_input=True)
    print('Uploading metadata document...')
    upload_metadata(layer_configs)
    print('All builds and publications complete!')
