# testing atlantis
terraform {
  required_providers {
    talos = {
      source  = "siderolabs/talos"
      version = "~> 0.8"
    }
    vault = {
      source  = "hashicorp/vault"
      version = "~> 4.0"
    }
  }
  required_version = "1.11.4"
}

provider "talos" {}
provider "vault" {}
