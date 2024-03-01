terraform {
  required_providers {
    talos = {
      source = "siderolabs/talos"
      version = "~> 0.4"
    }
    vault = {
      source = "hashicorp/vault"
      version = "~> 3.25"
    }
  }
  required_version = "1.7.4"
}

provider "talos" {}
provider "vault" {}
