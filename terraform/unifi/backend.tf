terraform {
  backend "s3" {
    bucket = "terraform"
    key    = "unifi/terraform.tfstate"
    region = "us-east"
    endpoints = {
      s3 = "https://us-east.object.fastlystorage.app"
    }
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    use_path_style              = true
    skip_s3_checksum            = true
  }
  required_providers {
    unifi = {
      source  = "paultyng/unifi"
      version = "~> 0.41"
    }
    # paultyng/unifi has no zone-based firewall support; this fork manages only
    # the zones and policies in firewall.tf. Everything else stays on paultyng.
    unifizbf = {
      source  = "ubiquiti-community/unifi"
      version = "~> 0.65"
    }
  }
  required_version = "1.17.1"
}

provider "unifi" {
  api_url        = "https://192.168.1.1"
  allow_insecure = true
}

provider "unifizbf" {
  api_url        = "https://192.168.1.1"
  allow_insecure = true
}

provider "aws" {
  endpoints {
  }
}
