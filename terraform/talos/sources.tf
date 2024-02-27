terraform {
  required_providers {
    talos = {
      source = "siderolabs/talos"
    }
    vault = {
      source = "hashicorp/vault"
    }
  }
}

provider "talos" {}
provider "vault" {}
