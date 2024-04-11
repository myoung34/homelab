# testing atlantis
terraform {
  required_providers {
    talos = {
      source = "siderolabs/talos"
      version = "~> 0.4"
    }
    vault = {
      source = "hashicorp/vault"
      version = "~> 4.0"
    }
  }
  required_version = "1.8.0"
}

provider "talos" {}
provider "vault" {}
