terraform {
  required_providers {
    coder = {
      source  = "coder/coder"
      version = "~> 2.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 3.0"
    }
  }
}

# coderd already runs in-cluster (k8s/prod/coder), so the default in-cluster
# kubeconfig is enough - no separate credentials needed.
provider "kubernetes" {
  config_path = null
}

data "coder_workspace" "me" {}
data "coder_workspace_owner" "me" {}

variable "namespace" {
  description = "Namespace workspace pods land in - must match the Role/RoleBinding granted to the coder namespace's default ServiceAccount in k8s/prod/coder/coder.yaml."
  type        = string
  default     = "coder"
}

# Every node in this cluster except gpu1 is arm64 (Pi 4 / Rock Pi X); common
# devcontainer images (including the one below) are amd64-only, so this will
# always land on gpu1 regardless of nodeSelector - making it explicit here
# rather than relying on that being implicit. gpu1 has 30GB RAM and Ollama
# only reserves 3Gi + the GPU itself, so a modest workspace fits alongside
# it fine, but keep an eye on this if you add several concurrent workspaces.
variable "node_arch" {
  type    = string
  default = "amd64"
}

data "coder_parameter" "cpu" {
  name         = "cpu"
  display_name = "CPU cores"
  type         = "number"
  default      = "2"
  mutable      = true
}

data "coder_parameter" "memory" {
  name         = "memory"
  display_name = "Memory (GB)"
  type         = "number"
  default      = "4"
  mutable      = true
}

data "coder_parameter" "home_disk_size" {
  name         = "home_disk_size"
  display_name = "Home directory size (GB)"
  type         = "number"
  default      = "10"
  mutable      = false
}

resource "coder_agent" "main" {
  os             = "linux"
  arch           = var.node_arch
  startup_script = <<-EOT
    set -e
    echo "workspace for ${data.coder_workspace_owner.me.name} starting up"
  EOT
}

resource "kubernetes_persistent_volume_claim" "home" {
  metadata {
    name      = "coder-${data.coder_workspace.me.id}-home"
    namespace = var.namespace
  }
  wait_until_bound = false
  spec {
    # Verify with `kubectl get storageclass` - this assumes the Longhorn
    # Helm chart's default dynamic-provisioning class, distinct from the
    # "longhorn-static" pattern the rest of this repo uses for pre-existing
    # pinned volumes (that pattern doesn't fit per-workspace PVCs created
    # on demand).
    storage_class_name = "longhorn"
    access_modes       = ["ReadWriteOnce"]
    resources {
      requests = {
        storage = "${data.coder_parameter.home_disk_size.value}Gi"
      }
    }
  }
}

resource "kubernetes_pod" "main" {
  count = data.coder_workspace.me.start_count
  metadata {
    name      = "coder-${lower(data.coder_workspace_owner.me.name)}-${lower(data.coder_workspace.me.name)}"
    namespace = var.namespace
  }
  spec {
    # See node_arch note above - this is here to make the constraint
    # explicit rather than relying on image-arch mismatches to enforce it.
    node_selector = {
      "kubernetes.io/arch" = var.node_arch
    }
    service_account_name = "default"
    container {
      name    = "dev"
      image   = "codercom/enterprise-base:ubuntu"
      command = ["sh", "-c", coder_agent.main.init_script]
      security_context {
        run_as_user = "1000"
      }
      env {
        name  = "CODER_AGENT_TOKEN"
        value = coder_agent.main.token
      }
      resources {
        requests = {
          cpu    = "${data.coder_parameter.cpu.value}"
          memory = "${data.coder_parameter.memory.value}Gi"
        }
        limits = {
          cpu    = "${data.coder_parameter.cpu.value}"
          memory = "${data.coder_parameter.memory.value}Gi"
        }
      }
      volume_mount {
        mount_path = "/home/coder"
        name       = "home"
      }
    }
    volume {
      name = "home"
      persistent_volume_claim {
        claim_name = kubernetes_persistent_volume_claim.home.metadata[0].name
      }
    }
  }
}
