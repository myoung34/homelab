terraform {
  required_providers {
    coder = {
      source  = "coder/coder"
      version = "~> 2.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.30"
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

# The agent's init script is generated from CODER_ACCESS_URL
# (https://coder.king-gila.ts.net), which no workspace pod can reach:
#   - CoreDNS rewrites that name to the coder ClusterIP (the "rewrite name"
#     line in kube-system/coredns), but that Service only listens on 8080/http
#     while the access URL implies 443/https - so curl gets ECONNREFUSED.
#   - The only thing serving 443 for that name is the Tailscale Ingress proxy
#     (tailscale/ts-coder-*), and it binds the tailnet interface, not its pod
#     IP. Tailscale's fix for that is the experimental
#     `tailscale.com/experimental-forward-cluster-traffic-via-ingress`
#     annotation, which is a known crash-loop on Talos - see
#     https://github.com/tailscale/tailscale/issues/19538.
# So substitute the access URL out of the init script and send the agent
# straight at the Service. This leg is cluster-internal but unencrypted, and
# the agent token rides on it; acceptable here, revisit if the cluster ever
# hosts anything untrusted.
variable "coder_internal_url" {
  description = "In-cluster URL the workspace agent uses instead of the public access URL."
  type        = string
  default     = "http://coder.coder.svc.cluster.local:8080"
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
      name  = "dev"
      image = "codercom/enterprise-base:ubuntu"
      # See coder_internal_url above - access_url is the bare base URL with no
      # trailing slash, so this catches both the binary download and the
      # exported CODER_AGENT_URL.
      command = ["sh", "-c", replace(coder_agent.main.init_script, data.coder_workspace.me.access_url, var.coder_internal_url)]
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
