variable "packages" {
    type = map(any)
}

variable "supports_compatible_architectures" {
    description = "Whether this region supports the `compatible_architectures` variable."
    type = bool
    default = true
}

variable "lambda_shell" {
    description = "The Lambda Shell module to be used for setting layer permissions."
    type = any
}
