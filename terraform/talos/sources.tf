# testing atlantis
terraform {
  required_providers {
    talos = {
      source = "siderolabs/talos"
      version = "~> 0.6"
    }
    vault = {
      source = "hashicorp/vault"
      version = "~> 4.0"
    }
  }
  required_version = "1.9.8"
}

provider "talos" {}
provider "vault" {}
