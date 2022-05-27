# Public Lambda Layers

This project generates and hosts Lambda Layers for various packages and makes them public to the world.

If there's a package that you would like to request be added to this system, create a pull request with a `.json` file that follows the format of the files in the `layers` directory.


## Layers

For a complete listing of layers that are currently maintained, check this file. Since this is a JSON file, you can load it with infrastructure-as-code (e.g. Terraform) to select the desired layer ARNs.

### [Layers List](pll.invictonlabs.com/layers.json)


## Testing

The contents of these layers have not been thoroughly tested. If any of the packages fail to load for your Lambdas, please create an issue and, preferrably, a pull request if you know of the solution.


## Legal

Invicton Labs makes no claim to ownership or copyright of any layer contents that were pulled from an external source (e.g. PyPI). All layer content is licensed under the license of the original external content.

Similarly, Invicton Labs provides no warranty for the contents of the layers.
