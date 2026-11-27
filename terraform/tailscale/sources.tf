terraform {
  backend "s3" {
    bucket  = "terraform"
    key     = "tailscale/terraform.tfstate"
    region  = "us-east"
    endpoints = {
      s3 = "https://us-east.object.fastlystorage.app"
    }
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    use_path_style              = true
    # Fastly object storage rejects the AWS SDK's default request checksums
    # (PutObject -> 400 InvalidRequest); see the AWS_*_CHECKSUM_* vars in .envrc.
    skip_s3_checksum = true
  }
  required_providers {
    tailscale = {
      source  = "tailscale/tailscale"
      version = "~> 0.30"
    }
  }
  required_version = "1.17.2"
}

provider "tailscale" {}
