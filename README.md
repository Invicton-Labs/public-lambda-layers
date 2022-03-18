# Public Lambda Layers

This module generates Lambda Layers for various packages and makes them public to the world.

If there's a package that you would like to request be added to this system, create a pull request with a `.json` file that follows the format of the files in the `layers` directory.


## Layers

For a complete listing of layers that are currently maintained, check this file. Since this is a JSON file, you can load it with infrastructure-as-code (e.g. Terraform) to select the desired layer ARNs.

### [Layers List](https://gist.githubusercontent.com/KyleKotowick/173707592654d5a9e37b2f4f7cd51481/raw/6f59d30320261f8114ea56ef729f6c8bc3af750d/layers.json)


## Legal

Invicton Labs makes no claim to ownership or copyright of any layer contents that were pulled from an external source (e.g. PyPI). All layer content is licensed under the license of the original external content.

Similarly, Invicton Labs provides no warranty for the contents of the layers.
