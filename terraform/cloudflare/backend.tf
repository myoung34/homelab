terraform {
  backend "s3" {
    bucket  = "terraform-847713735871-us-east-1"
    key     = "cloudflare/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
  required_providers {
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 5.0"
    }
  }
  required_version = "1.10.5"
}
