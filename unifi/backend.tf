terraform {
  #backend "s3" {
  #  bucket  = "terraform-847713735871-us-east-1"
  #  key     = "unifi/terraform.tfstate"
  #  region  = "us-east-1"
  #  encrypt = true
  #}
  required_providers {
    unifi = {
      source = "paultyng/unifi"

    }
  }
}

provider "unifi" {
  api_url        = "https://192.168.1.1"
  allow_insecure = true
}
