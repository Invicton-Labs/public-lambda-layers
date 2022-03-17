resource "aws_s3_bucket" "lambda_layers" {
  bucket = "invicton-labs-shared-lambda-layers-${data.aws_region.current.name}"
}

resource "aws_s3_bucket_versioning" "lambda_layers" {
  bucket = aws_s3_bucket.lambda_layers.id
  versioning_configuration {
    status     = "Enabled"
    mfa_delete = "Disabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "lambda_layers" {
  bucket = aws_s3_bucket_versioning.lambda_layers.bucket
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "lambda_layers" {
  bucket                  = aws_s3_bucket_server_side_encryption_configuration.lambda_layers.bucket
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "lambda_layers" {
  bucket = aws_s3_bucket_public_access_block.lambda_layers.bucket
  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

// Expire objects quickly so we don't pay for long-term storage
resource "aws_s3_bucket_lifecycle_configuration" "lambda_layers" {
  bucket = aws_s3_bucket_ownership_controls.lambda_layers.bucket

  rule {
    id = "all"

    abort_incomplete_multipart_upload {
      days_after_initiation = 1
    }

    expiration {
      days = 1
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }

    status = "Enabled"
  }
}

// Create a bucket policy that requires all uploaded objects to be encrypted
data "aws_iam_policy_document" "lambda_layers" {

  statement {
    sid    = "DenyIncorrectEncryptionHeader"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = [
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.lambda_layers.arn}/*",
    ]
    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["AES256"]
    }
  }

  statement {
    sid    = "DenyUnencryptedObjectUploads"
    effect = "Deny"
    principals {
      type        = "*"
      identifiers = ["*"]
    }
    actions = [
      "s3:PutObject",
    ]
    resources = [
      "${aws_s3_bucket.lambda_layers.arn}/*",
    ]
    condition {
      test     = "Null"
      variable = "s3:x-amz-server-side-encryption"
      values   = [true]
    }
  }
}

// Set the policy on the bucket
resource "aws_s3_bucket_policy" "lambda_layers" {
  bucket = aws_s3_bucket_lifecycle_configuration.lambda_layers.bucket
  policy = data.aws_iam_policy_document.lambda_layers.json
}
