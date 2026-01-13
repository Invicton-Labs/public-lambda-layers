import json
import glob
import pathlib
import re
import hashlib
import base64
import subprocess
import jsonschema
import jsonref
from config import Constants

# Parses the filesystem to load the layer files with their names
def get_layer_definitions():
    build_dir = pathlib.Path(__file__).parent.resolve()
    layers_dir = f"{build_dir}/../layers"
    layer_filenames = glob.glob(f'{layers_dir}/*.json')

    with open(f'{build_dir}/layer-definition-jsonschema.json', mode='r') as file:
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
                    f'Failed to JSON-decode {pretty_filename}: {e}') from e
        try:
            # Dereference references
            definition = jsonref.JsonRef.replace_refs(definition)
            # Validate that the definition is valid
            validator.validate(definition)
        except jsonschema.ValidationError as e:
            raise ValueError(
                f'Definition for {pretty_filename} is invalid: {e.message} (at {'->'.join(e.schema_path)})') from e
        except jsonref.JsonRefError as e:
            raise ValueError(
                f'Definition for {pretty_filename} is invalid: {e.message}') from e
        layer_definitions[layer_name] = {
            'pretty_filename': pretty_filename,
            'package_config': definition,
        }

    return layer_definitions


# Parses the layer JSON files and generates Dockerfiles for each
def generate_layer_configs(layer_definitions, directory):
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
            raise AssertionError(f'Definition for {filename} is invalid: package names (filenames) must match the regex "{package_pattern}"')

        for runtime, runtime_config in package_config['runtimes'].items():
            if not runtime_regex.match(runtime):
                raise AssertionError(f'Definition for {filename} is invalid: runtime names must match the regex "{package_pattern}"')

            for version, version_config in runtime_config['versions'].items():
                if not version_regex.match(version):
                    raise AssertionError(f'Definition for {filename} is invalid: versions must match the regex "{package_pattern}"')

                for architecture, architecture_config in version_config['architectures'].items():

                    layer_name = f"{package_name}_{version.replace('.', '-')}_{runtime.replace('.', '-')}_{architecture}"

                    layer_source_directory = architecture_config.get('layer_source_directory', version_config.get(
                        'default_layer_source_directory', runtime_config.get('default_layer_source_directory', package_config.get('default_layer_source_directory'))))
                    if layer_source_directory is None:
                        raise ValueError(
                            f'{layer_name} has no "layer_source_directory" property, and there are no "default_layer_source_directory" properties at the version, runtime, or package level')

                    layer_target_directory = architecture_config.get('layer_target_directory', version_config.get(
                        'default_layer_target_directory', runtime_config.get('default_layer_target_directory', package_config.get('default_layer_target_directory'))))
                    if layer_target_directory is None:
                        raise ValueError(
                            f'{layer_name} has no "layer_target_directory" property, and there are no "default_layer_target_directory" properties at the rversion, runtime, or package level')

                    image = architecture_config.get('image', version_config.get(
                        'default_image', runtime_config.get('default_image', package_config.get('default_image'))))
                    if image is None:
                        raise ValueError(
                            f'{layer_name} has no "image" property, and there are no "default_image" property at the version, runtime, or package level')

                    dockerfile_lines = [
                        f'FROM {image} AS build_image'
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
                        f'COPY --from=build_image "{layer_source_directory}" "/layer/{layer_target_directory.lstrip('/')}"',
                        'WORKDIR /layer',
                        # This command will ignore extra attributes such as file times
                        # This is so that the output file has the same hash as long as the contents
                        # of the contained files remain the same
                        f'RUN TZ=UTC zip -r -X "{package_path}" ./*'
                    ])

                    dockerfile_content = '\n'.join(dockerfile_lines)

                    # Calculate the hash of the Dockerfile so we can track if it changes
                    h = hashlib.sha256()
                    h.update(dockerfile_content.encode())

                    dockerfile_sha256 = base64.b64encode(h.digest()).decode()

                    layer_configs[layer_name] = {
                        'dockerfile_content': dockerfile_content,
                        'dockerfile_sha256': dockerfile_sha256,
                        'dockerfile_path': f"{directory}/{layer_name}.Dockerfile",
                        'package_name': package_name,
                        'package_path': package_path,
                        'runtime': runtime,
                        'version': version,
                        'architecture': architecture,
                        'archive_path': f"{directory}/{layer_name}.zip",
                        'image_tag': f"{layer_name}:local",
                        'platform': Constants.ARCHITECTURE_LOOKUP[architecture],
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


# This builds the Docker image, extracts the built layer from it, pushes it to S3, signs it, then publishes it to each region
def build_layer(layer_config, stream_output, regions_to_publish, is_deploy, aws):
    with open(layer_config['dockerfile_path'], "w", newline='\n') as f:
        # Writing data to a file
        f.write(layer_config['dockerfile_content'])

    stderr = None
    stdout = None
    if not stream_output:
        stderr = subprocess.STDOUT
        stdout = subprocess.PIPE

    # Build the image and load it into the local registry
    print(f'Building layer {layer_config['name']}...')
    try:
        subprocess.run(['docker', 'buildx', 'build', '--progress', 'plain', '--platform',
                        layer_config['platform'], '--load', '-t', layer_config['image_tag'],
                        '-f', layer_config['dockerfile_path'], '.'], check=True, stderr=stderr, 
                        stdout=stdout
                    )
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Remove any existing containers of the same name
    try:
        subprocess.run(
            ['docker', 'rm', '-f', layer_config['name']], check=True, stderr=subprocess.STDOUT,
            stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Create a new container with this image
    try:
        subprocess.run(['docker', 'create', '-ti', '--name', layer_config['name'],
                            '--platform', layer_config['platform'], layer_config['image_tag']], 
                            check=True, stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Copy the layer files from it
    try:
        subprocess.run(['docker', 'cp', f'{layer_config['name']}:{layer_config['package_path']}', 
                        layer_config['archive_path']], check=True, 
                        stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Remove the container we just created
    try:
        subprocess.run(
            ['docker', 'rm', '-f', layer_config['name']], check=True, 
            stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    # Remove the image we just created
    try:
        subprocess.run(
            ['docker', 'image', 'rm', layer_config['image_tag']], check=True, 
            stderr=subprocess.STDOUT, stdout=subprocess.PIPE)
    except subprocess.CalledProcessError as e:
        if e.stdout is not None:
            print(e.stdout.decode())
        raise e

    if not is_deploy:
        return
    
    # Now deploy it!
    aws.deploy_layer(layer_config, regions_to_publish)
