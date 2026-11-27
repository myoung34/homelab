terraform {
  backend "s3" {
    bucket = "terraform"
    key    = "datadog/terraform.tfstate"
    region = "us-east"
    endpoints = {
      s3 = "https://us-east.object.fastlystorage.app"
    }
    skip_credentials_validation = true
    skip_requesting_account_id  = true
    skip_metadata_api_check     = true
    skip_region_validation      = true
    use_path_style              = true
  }
  required_providers {
    datadog = {
      source  = "DataDog/datadog"
      version = "~> 4.32"
    }
  }
  required_version = "1.17.2"
}

# DD_API_KEY / DD_APP_KEY from the environment; see README.md.
provider "datadog" {}
