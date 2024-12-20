terraform {
  backend "s3" {
    bucket  = "terraform-847713735871-us-east-1"
    key     = "unifi/terraform.tfstate"
    region  = "us-east-1"
    encrypt = true
  }
  required_providers {
    unifi = {
      source  = "paultyng/unifi"
      version = "~> 0.41"
    }
  }
  required_version = "1.10.3"
}

provider "unifi" {
  api_url        = "https://192.168.1.1"
  allow_insecure = true
}
