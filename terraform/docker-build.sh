#!/bin/bash

set -eu

(
    flock -x 200

    docker buildx build --builder "$IL_BUILDER_NAME" --platform "$IL_BUILD_ARCHITECTURE" --load -t "$IL_IMAGE_TAG" -f "./${IL_DOCKERFILE_NAME}" .
    docker rm -f "$IL_CONTAINER_NAME"
    docker create -ti --name "$IL_CONTAINER_NAME" --platform "$IL_BUILD_ARCHITECTURE" "$IL_IMAGE_TAG"
    docker cp "${IL_CONTAINER_NAME}:/package.zip" "${IL_CONTAINER_NAME}.zip"
    docker rm -f "$IL_CONTAINER_NAME" 
    docker image rm "$IL_IMAGE_TAG"

) 200>"./build-lock"
