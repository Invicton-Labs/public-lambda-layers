# Public Lambda Layers

This project generates and hosts Lambda Layers for various packages and makes them public to the world.

If there's a package that you would like to request be added to this system, create a pull request with a `.json` file that follows the format of the files in the `layers` directory.


## Layers

For a complete listing of layers that are currently maintained, check this file. Since this is a JSON file, you can load it with infrastructure-as-code (e.g. Terraform) to select the desired layer ARNs.

### [https://pll.invictonlabs.com/layers.json](https://pll.invictonlabs.com/layers.json)

Metadata for layers can also be sub-indexed, which can be helpful if you want to load a smaller amount of data (the main `layers.json` file is quite large):

- `https://pll.invictonlabs.com/packages/{PACKAGE_NAME}.json`
- `https://pll.invictonlabs.com/packages/{PACKAGE_NAME}/{PACKAGE_VERSION}.json`
- `https://pll.invictonlabs.com/packages/{PACKAGE_NAME}/{PACKAGE_VERSION}/{RUNTIME}.json`
- `https://pll.invictonlabs.com/packages/{PACKAGE_NAME}/{PACKAGE_VERSION}/{RUNTIME}/{ARCHITECTURE}.json`
- `https://pll.invictonlabs.com/packages/{PACKAGE_NAME}/{PACKAGE_VERSION}/{RUNTIME}/{ARCHITECTURE}/{REGION}.json`


## Signing

All layers (except those in regions where layer signing isn't supported) are signed by an AWS Signer Signing Profile with ARN `arn:aws:signer:ca-central-1:216976011668:/signing-profiles/InvictonLabs_PublicLambdaLayers`. As of the time of writing, the current version of the signing profile is `4QhjJy9LL7` (`arn:aws:signer:ca-central-1:216976011668:/signing-profiles/InvictonLabs_PublicLambdaLayers/4QhjJy9LL7`), although this version may change in the future.

## Terraform

To use these layers with Terraform, consider using the [Invicton-Labs/public-lambda-layer/aws](https://registry.terraform.io/modules/Invicton-Labs/public-lambda-layer/aws/latest) module.


## Testing

The contents of these layers have **not** been thoroughly tested. If any of the packages fail to load for your Lambdas, please create an issue and, preferrably, a pull request if you know of the solution.


## Legal

Invicton Labs makes no claim to ownership or copyright of any layer contents that were pulled from an external source (e.g. PyPI). All layer content is licensed under the license of the original external content.

Invicton Labs provides no warranty for the contents of the layers.
