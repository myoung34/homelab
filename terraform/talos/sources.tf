# testing atlantis
terraform {
  required_providers {
    talos = {
      source  = "siderolabs/talos"
      version = "~> 0.9"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "~> 5.0"
    }
  }
  required_version = "1.13.2"
}

provider "talos" {}
provider "vault" {}
