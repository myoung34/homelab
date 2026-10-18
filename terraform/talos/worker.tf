data "talos_machine_configuration" "worker" {
  cluster_name     = local.cluster_name
  cluster_endpoint = local.cluster_endpoint
  machine_type     = "worker"
  machine_secrets  = local.machine_secrets
  # Must be pinned. Left unset, the provider defaults this to the version of
  # pkg/machinery it was built against, so a provider bump silently changes the
  # generated config's feature level. 0.11 (machinery v1.13) -> 0.12 (machinery
  # v1.14) started emitting a v1alpha1/DiscoveryServiceConfig document, which a
  # v1.14 node rejects outright:
  #   error decoding document v1alpha1/DiscoveryServiceConfig/default:
  #   "DiscoveryServiceConfig" "v1alpha1": not registered
  # Generate for the version the nodes actually run, not the provider's.
  talos_version = local.talos_version
}

# Per-node patches, keyed by node IP. A local rather than inline in the
# resource so validate.sh can render exactly what terraform applies.
locals {
  worker_patches = { for ip, node in local.node_data.workers : ip => flatten([
    templatefile("${path.module}/templates/install-disk-and-hostname.yaml.tmpl", {
      hostname           = node.hostname
      install_disk       = node.install_disk
      image              = node.image
      machine_token      = local.machine_secrets.secrets.machine_token
      kubernetes_version = length(node.kubernetes_version) == 0 ? local.kubernetes_version : node.kubernetes_version
    }),
    templatefile("${path.module}/templates/extensionserviceconfig.yaml.tmpl", {
      name = "tailscale"
      env  = local.extensions.tailscale.env
    }),
    templatefile("${path.module}/templates/extensionserviceconfig.yaml.tmpl", {
      name = "docker"
      env  = local.extensions.docker.env
    }),
    templatefile("${path.module}/templates/extensionserviceconfig.yaml.tmpl", {
      name = "nvidia"
      env  = local.extensions.nvidia.env
    }),
    # Longhorn requires dedicated disk partitions and the nvidia runtime.
    length(node.extra_disk) == 0 ? null : templatefile("${path.module}/templates/longhorn.yaml.tmpl", {
      hostname              = node.hostname
      install_disk          = node.install_disk
      extra_disk            = node.extra_disk
      machine_token         = local.machine_secrets.secrets.machine_token
      kubernetes_version    = length(node.kubernetes_version) == 0 ? local.kubernetes_version : node.kubernetes_version
      nvidia_runtime        = local.extensions.nvidia.env.NVIDIA_RUNTIME
    }),
  ])}
}

resource "talos_machine_configuration" "worker" {
  cluster_name     = local.cluster_name
  cluster_endpoint = local.cluster_endpoint
  machine_type     = "worker"
  machine_secrets  = local.machine_secrets

  for_each = local.node_data.workers

  dynamic "apply_patches" {
    iterator = patch
    for_each = local.worker_patches[each.value.ip]
    content {
      document = patch.value
    }
  }
}
