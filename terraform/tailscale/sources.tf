terraform {
  backend "s3" {
    bucket  = "terraform-847713735871-us-east-1"
    key     = "tailscale/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
  required_providers {
    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.17"
    }
  }
  required_version = "1.10.5"
}

provider "tailscale" {}
