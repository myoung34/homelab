# testing atlantis
terraform {
  required_providers {
    talos = {
      source = "siderolabs/talos"
      version = "~> 0.5"
    }
    vault = {
      source = "hashicorp/vault"
      version = "~> 4.0"
    }
  }
  required_version = "1.8.4"
}

provider "talos" {}
provider "vault" {}
