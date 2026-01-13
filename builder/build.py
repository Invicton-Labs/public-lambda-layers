import os
import shutil
from pathlib import Path
import json
import uuid
import sys
from aws import Aws
from concurrency import concurrent_func
from config import Constants
import layers


def process_existing_layer_data(aws, is_deploy: bool, layer_configs: dict, existing_layers_by_region: dict):
    # This is for tracking all existing layers that match a desired layer, but
    # are missing a public permission policy.
    existing_layers_needing_policy_check = {}

    # Check each unique layer config
    for layer_config in layer_configs.values():
        layer_regionals = {}
        layer_config['regional'] = layer_regionals

        # Check all regions
        for region in existing_layers_by_region.keys():
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
        100, aws.get_layer, existing_layers_needing_policy_check, expand_input=True)

    # We do this as a dict with unique random keys because the concurrent_func function expects a dict
    all_statements_to_remove = {}
    create_policy_inputs = {}
    for input_key, existing_layer_datum in existing_layer_data.items():
        has_policy, statements_to_remove, content = existing_layer_datum
        inpt = existing_layers_needing_policy_check[input_key]

        if 'SigningJobArn' not in content and inpt['region'] in aws.signer_regions:
            # If the existing layer isn't signed, and it isn't in a region that doesn't
            # support signing, don't include it as an existing region layer.
            # That way, it will be regenerated with a signature.
            print(f'Found layer for {inpt['layer_name']} in region {inpt['region']} with no SigningJobArn')
            layer_configs[inpt['layer_name']
                          ]['regional'][inpt['region']] = None
        else:
            layer_configs[inpt['layer_name']
                          ]['regional'][inpt['region']]['Content'] = content

        for stmt in statements_to_remove:
            all_statements_to_remove[str(uuid.uuid4())] = stmt
        if not has_policy:
            create_policy_inputs[input_key] = inpt

    print(f'{len(all_statements_to_remove)} existing layer policy statements are incorrect and must be removed')
    print(f'{len(create_policy_inputs)} existing layers need public policies')

    if is_deploy and len(all_statements_to_remove) > 0:
        print('Removing incorrect statements...')
        concurrent_func(100, aws.remove_policy_statement,
                        all_statements_to_remove, expand_input=True)
        print('Done!')

    if is_deploy and len(create_policy_inputs) > 0:
        print('Creating public policies for existing layers...')
        concurrent_func(100, aws.create_public_policy,
                        create_policy_inputs, expand_input=True)
        print('Done!')

    untracked_layers = []
    for region, existing_layers in existing_layers_by_region.items():
        for layer_name, layer in existing_layers.items():
            if layer_name not in layer_configs:
                untracked_layers.append(layer)

    print(f'There are {len(untracked_layers)} untracked layers')


# Once everything is built and deployed, this uploads the metadata files to the S3 metadata bucket,
# then invalidates the CloudFront distribution to ensure the cache is cleared.
def upload_metadata(aws, layer_configs):
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
            'path': f'{package_base_path}/{package_name}.json',
            'metadata': package_config | {
                'package': package_name,
            }
        }
        for version, version_config in package_config.items():
            metadata_files[str(uuid.uuid4())] = {
                'path': f'{package_base_path}/{package_name}/{version}.json',
                'metadata': version_config | {
                    'package': package_name,
                    'package_version': version,
                }
            }
            for runtime, runtime_config in version_config.items():
                metadata_files[str(uuid.uuid4())] = {
                    'path': f'{package_base_path}/{package_name}/{version}/{runtime}.json',
                    'metadata': runtime_config | {
                        'package': package_name,
                        'package_version': version,
                        'runtime': runtime,
                    }
                }
                for architecture, architecture_config in runtime_config.items():
                    metadata_files[str(uuid.uuid4())] = {
                        'path': f'{package_base_path}/{package_name}/{version}/{runtime}/{architecture}.json',
                        'metadata': architecture_config | {
                            'package': package_name,
                            'package_version': version,
                            'runtime': runtime,
                            'architecture': architecture,
                        }
                    }
                    for region, region_config in architecture_config.items():
                        metadata_files[str(uuid.uuid4())] = {
                            'path': f'{package_base_path}/{package_name}/{version}/{runtime}/{architecture}/{region}.json',
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
        'path': Constants.METADATA_OBJECT,
        'metadata': metadata
    }

    print(f'Uploading {len(metadata_files)} metadata documents...')

    # Upload all metadata files
    concurrent_func(
        100, aws.upload_s3_metadata_file, metadata_files, expand_input=True)

    print('Invalidating CloudFront paths...')
    aws.invalidate_metadata_cloudfront()
    print('CloudFront invalidation complete')


if __name__ == "__main__":
    docker_workers = 4
    is_deploy = len(sys.argv) > 1 and sys.argv[1] == 'true'
    dockerfile_dir = os.path.join(Path.cwd().resolve(), "dockerfiles")

    if os.path.exists(dockerfile_dir):
        shutil.rmtree(dockerfile_dir)

    os.makedirs(dockerfile_dir)
    aws = Aws()

    layer_definitions = layers.get_layer_definitions()
    layer_configs = layers.generate_layer_configs(layer_definitions, dockerfile_dir)

    existing_layers_by_region = aws.get_existing_layers_by_region()

    # This evaluates all of the existing layers against the desired layers to
    # find differences (existing layers that must be changed, new layers that must be created)
    process_existing_layer_data(aws, is_deploy, layer_configs, existing_layers_by_region)
    
    # This finds all layer configs where a deployment is missing in one or more regions
    build_configs = {
        k: {
            'layer_config': layer_config,
            'stream_output': docker_workers == 1,
            'regions_to_publish': [
                region
                for region, existing_layer in layer_config['regional'].items()
                if existing_layer is None
            ],
            'is_deploy': is_deploy,
            'aws': aws
        }
        for k, layer_config in layer_configs.items()
        if len([True for existing_layer in layer_config['regional'].values() if existing_layer is None]) > 0
    }

    num_publications = 0
    for build_config in build_configs.values():
        num_publications += len(build_config['regions_to_publish'])

    print(f'{len(build_configs)} layer images must be built')
    print(f'{num_publications} regional layers must be published')
    
    if is_deploy:
        print('Building and publishing...')
    else:
        print('Building...')
    concurrent_func(docker_workers, layers.build_layer,
                    build_configs, expand_input=True)
    
    print('All builds successful!')

    # If we're only validating, exit here
    if is_deploy:
        upload_metadata(aws, layer_configs)
        print('All builds and publications complete!')
