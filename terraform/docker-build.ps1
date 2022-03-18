$ErrorActionPreference = "Stop"

# Get a write lock on the lock file
$lock = $null
while ($true) {
    try {
        $lock = [System.IO.File]::Open("./build-lock", "OpenOrCreate", "Write")
        break
    }
    catch {
        Start-Sleep -Milliseconds 1000
        continue
    }
}

try {
    docker buildx build --builder "$env:IL_BUILDER_NAME" --platform "$env:IL_BUILD_ARCHITECTURE" --load -t "$env:IL_IMAGE_TAG" -f "./${env:IL_DOCKERFILE_NAME}" .
    if ($LASTEXITCODE -ne 0) { Exit $LASTEXITCODE }
    docker rm -f "$env:IL_CONTAINER_NAME"
    if ($LASTEXITCODE -ne 0) { Exit $LASTEXITCODE }
    docker create -ti --name "$env:IL_CONTAINER_NAME" --platform "$env:IL_BUILD_ARCHITECTURE" "$env:IL_IMAGE_TAG"
    if ($LASTEXITCODE -ne 0) { Exit $LASTEXITCODE }
    docker cp "${env:IL_CONTAINER_NAME}:/package.zip" "${env:IL_CONTAINER_NAME}.zip"
    if ($LASTEXITCODE -ne 0) { Exit $LASTEXITCODE }
    docker rm -f "$env:IL_CONTAINER_NAME" 
    if ($LASTEXITCODE -ne 0) { Exit $LASTEXITCODE }
    docker image rm "$env:IL_IMAGE_TAG"
}
finally {
    # Always unlock the lock file
    $lock.close()
}
