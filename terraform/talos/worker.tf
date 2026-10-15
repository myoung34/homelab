data "talos_machine_configuration" "worker" {
  cluster_name     = local.cluster_name
  cluster_endpoint = local.cluster_endpoint
  machine_type     = "worker"
  machine_secrets  = local.machine_secrets
  talos_version = local.talos_version
}

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
    length(node.longhorn_disk_selector) == 0 ? [templatefile("${path.module}/templates/longhorn.yaml.tmpl", {})] : [templatefile("${path.module}/templates/longhorn-dedicated-volume.yaml.tmpl", {
      disk_selector      = node.longhorn_disk_selector
      ephemeral_max_size = node.ephemeral_max_size
      longhorn_min_size  = node.longhorn_min_size
    })],
    node.image == local.bare_metal_image ? [templatefile("${path.module}/templates/nvidia.yaml.tmpl", {})] : [],
    node.image == local.rpi_overlay_image ? [templatefile("${path.module}/templates/pi4-cpufreq.yaml.tmpl", {})] : [],
    length(node.mount_point) == 0 ? [] : [templatefile("${path.module}/templates/worker-with-extra-disk.yaml.tmpl", {
      mount_point  = node.mount_point
      extra_device = node.extra_device
    })]
  ]) }
}

resource "talos_machine_configuration_apply" "worker" {
  client_configuration        = local.client_configuration
  machine_configuration_input = data.talos_machine_configuration.worker.machine_configuration
  for_each                    = local.node_data.workers
  node                        = each.key
  config_patches              = local.worker_patches[each.key]
}
