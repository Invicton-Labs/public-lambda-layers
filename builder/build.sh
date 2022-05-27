# !bin/bash

set +e
docker buildx inspect --bootstrap "multiarch" > /dev/null 2>&1
if ! [ $? -eq 0 ]; then
    set -e
    docker buildx create --name "multiarch"
fi

python ./build.py "$@"
